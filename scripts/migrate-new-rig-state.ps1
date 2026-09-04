# ModelRig/Kaliv old-rig -> new-rig state migration operator.
# Windows PowerShell 5.1 compatible. Safe by default: no secret export, no
# overwrite on restore, and no backup/restore while ModelRig processes are live.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Export", "Import", "Verify")]
    [string]$Action,

    [string]$RuntimeRoot = "C:\Rig\ModelRig",
    [string]$RepoRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$EnvPath = "",
    [string]$OutDir = (Join-Path $env:USERPROFILE "ModelRigMigration"),
    [string]$Archive = "",
    [string]$PythonExe = "python.exe",
    [string]$BootstrapTaskName = "KalivBootstrap",
    [string]$SupervisorTaskName = "KalivSupervisor",
    [int]$MinimumGpuCount = 1,

    [switch]$ForceRestore,
    [switch]$SkipRestart,
    [switch]$SkipValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$script:TaskState = @{}
$script:EnvOriginal = @{}
$script:LoadedEnvKeys = @()

function Write-Step {
    param([string]$Text)
    Write-Host ("== {0} ==" -f $Text) -ForegroundColor Cyan
}

function Resolve-RuntimeRoot {
    param([string]$Requested)
    if (Test-Path -LiteralPath $Requested -PathType Container) {
        return (Resolve-Path -LiteralPath $Requested).Path
    }

    try {
        $task = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop
        $working = [string]$task.Actions[0].WorkingDirectory
        if (-not [string]::IsNullOrWhiteSpace($working) -and
            (Test-Path -LiteralPath $working -PathType Container)) {
            Write-Host "Runtime root auto-detected from '$SupervisorTaskName': $working"
            return (Resolve-Path -LiteralPath $working).Path
        }
    } catch {
        # No registered appliance task: caller must provide the root explicitly.
    }

    throw "Runtime root not found at '$Requested' and could not be inferred from '$SupervisorTaskName'."
}

function Import-ModelRigEnv {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        Write-Host "No modelrig.env found at $Path; using process/default paths."
        return
    }

    $keys = New-Object System.Collections.Generic.List[string]
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if ($line.Length -eq 0 -or $line.StartsWith("#")) { continue }
        $parts = $line.Split(@("="), 2, [StringSplitOptions]::None)
        if ($parts.Count -ne 2) { continue }
        $key = $parts[0].Trim()
        if ($key -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
        $value = $parts[1].Trim()
        if ($value.Length -ge 2 -and
            (($value.StartsWith('"') -and $value.EndsWith('"')) -or
             ($value.StartsWith("'") -and $value.EndsWith("'")))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        if (-not $script:EnvOriginal.ContainsKey($key)) {
            $script:EnvOriginal[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        }
        [Environment]::SetEnvironmentVariable($key, $value, "Process")
        $keys.Add($key)
    }
    $script:LoadedEnvKeys = @($keys)
    Write-Host ("Loaded {0} environment keys from modelrig.env (values are not printed)." -f $keys.Count)
}

function Restore-ProcessEnv {
    foreach ($key in $script:EnvOriginal.Keys) {
        [Environment]::SetEnvironmentVariable($key, $script:EnvOriginal[$key], "Process")
    }
}

function Save-TaskStatesAndStop {
    Write-Step "Stopping appliance for a consistent migration boundary"
    foreach ($name in @($BootstrapTaskName, $SupervisorTaskName)) {
        try {
            $task = Get-ScheduledTask -TaskName $name -ErrorAction Stop
            $script:TaskState[$name] = [string]$task.State
            if ($task.State -eq "Running") {
                Stop-ScheduledTask -TaskName $name
                Write-Host "Stopped scheduled task '$name'."
            }
        } catch {
            $script:TaskState[$name] = "Missing"
        }
    }

    $deadline = (Get-Date).AddSeconds(20)
    do {
        $running = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
            $_.ProcessName -like "modelrig-*"
        })
        if ($running.Count -eq 0) { return }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    $names = @($running | ForEach-Object { $_.ProcessName + "(" + $_.Id + ")" }) -join ", "
    throw "ModelRig processes are still running after scheduled tasks were stopped: $names. Refusing migration."
}

function Resume-Appliance {
    param([switch]$Always)
    if ($SkipRestart) {
        Write-Host "Restart skipped by operator."
        return
    }

    $shouldStart = $Always.IsPresent -or
        $script:TaskState[$BootstrapTaskName] -eq "Running" -or
        $script:TaskState[$SupervisorTaskName] -eq "Running"
    if (-not $shouldStart) {
        Write-Host "Appliance was not running before export; leaving it stopped."
        return
    }

    try {
        Get-ScheduledTask -TaskName $BootstrapTaskName -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $BootstrapTaskName
        Write-Host "Started '$BootstrapTaskName' (recovery-first startup)."
    } catch {
        throw "Migration completed but '$BootstrapTaskName' could not be started: $($_.Exception.Message)"
    }
}

function Invoke-BackupModule {
    param([object[]]$Arguments)
    $worker = Join-Path $RepoRoot "worker"
    $backupPy = Join-Path $worker "app\backup.py"
    if (-not (Test-Path -LiteralPath $backupPy -PathType Leaf)) {
        throw "Backup module not found at $backupPy"
    }
    if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
        throw "Python executable '$PythonExe' not found."
    }

    $previous = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $worker, "Process")
        Push-Location $RepoRoot
        try {
            & $PythonExe -m app.backup @Arguments
            if ($LASTEXITCODE -ne 0) {
                throw "backup module failed with exit code $LASTEXITCODE"
            }
        } finally {
            Pop-Location
        }
    } finally {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $previous, "Process")
    }
}

function Get-RepoHead {
    if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) { return $null }
    try {
        $head = (& git.exe -C $RepoRoot rev-parse HEAD 2>$null).Trim()
        if ($LASTEXITCODE -eq 0) { return $head }
    } catch { }
    return $null
}

function Write-MigrationSidecar {
    param([string]$ArchivePath, [string]$Runtime, [string]$EnvironmentFile)
    $hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash.ToLowerInvariant()
    $nonSecret = [ordered]@{}
    $sensitiveKeys = New-Object System.Collections.Generic.List[string]
    foreach ($key in $script:LoadedEnvKeys | Sort-Object -Unique) {
        if ($key -match '(?i)(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)') {
            $sensitiveKeys.Add($key)
        } else {
            $nonSecret[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        }
    }

    $gpu = @()
    if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) {
        try {
            $gpu = @(& nvidia-smi.exe --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>$null)
        } catch { }
    }

    $meta = [ordered]@{
        schema = "modelrig-rig-migration/v1"
        created_utc = [DateTime]::UtcNow.ToString("o")
        source_computer = $env:COMPUTERNAME
        runtime_root = $Runtime
        repo_root = $RepoRoot
        repo_head = Get-RepoHead
        archive = (Split-Path -Leaf $ArchivePath)
        archive_sha256 = $hash
        env_file_present = (Test-Path -LiteralPath $EnvironmentFile -PathType Leaf)
        non_secret_config = $nonSecret
        sensitive_config_keys_not_exported = @($sensitiveKeys)
        nvidia = $gpu
    }
    $sidecar = $ArchivePath + ".migration.json"
    $meta | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $sidecar -Encoding UTF8
    Write-Host "Migration metadata: $sidecar"
}

function Resolve-Archive {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "-Archive is required for $Action."
    }
    if (-not (Test-Path -LiteralPath $Value -PathType Leaf)) {
        throw "Archive not found: $Value"
    }
    return (Resolve-Path -LiteralPath $Value).Path
}

$resolvedRuntime = $null
$resolvedEnv = $null
$stopped = $false

try {
    if ($Action -eq "Verify") {
        $archivePath = Resolve-Archive -Value $Archive
        Write-Step "Verifying migration archive"
        Invoke-BackupModule -Arguments @("verify", $archivePath)
        Write-Host "Archive verified: $archivePath" -ForegroundColor Green
        exit 0
    }

    $resolvedRuntime = Resolve-RuntimeRoot -Requested $RuntimeRoot
    $resolvedEnv = if ([string]::IsNullOrWhiteSpace($EnvPath)) {
        Join-Path $resolvedRuntime "modelrig.env"
    } else {
        $EnvPath
    }
    Import-ModelRigEnv -Path $resolvedEnv
    Save-TaskStatesAndStop
    $stopped = $true

    if ($Action -eq "Export") {
        Write-Step "Creating verified migration archive"
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
        $before = @(Get-ChildItem -LiteralPath $OutDir -Filter "kaliv-backup-*.tar.gz" -File -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName)
        Invoke-BackupModule -Arguments @("create", "--out", $OutDir)
        $after = @(Get-ChildItem -LiteralPath $OutDir -Filter "kaliv-backup-*.tar.gz" -File -ErrorAction Stop |
            Sort-Object LastWriteTimeUtc -Descending)
        $created = $after | Where-Object { $before -notcontains $_.FullName } | Select-Object -First 1
        if ($null -eq $created) {
            $created = $after | Select-Object -First 1
        }
        if ($null -eq $created) {
            throw "Backup module returned success but no migration archive was found in $OutDir"
        }
        Invoke-BackupModule -Arguments @("verify", $created.FullName)
        Write-MigrationSidecar -ArchivePath $created.FullName -Runtime $resolvedRuntime -EnvironmentFile $resolvedEnv
        Write-Host "EXPORT READY: $($created.FullName)" -ForegroundColor Green
    } else {
        $archivePath = Resolve-Archive -Value $Archive
        Write-Step "Verifying archive before restore"
        Invoke-BackupModule -Arguments @("verify", $archivePath)
        Write-Step "Restoring portable rig state"
        $args = @("restore", $archivePath)
        if ($ForceRestore) { $args += "--force" }
        Invoke-BackupModule -Arguments $args
        Write-Host "RESTORE COMPLETE: $archivePath" -ForegroundColor Green
    }
} finally {
    try {
        if ($stopped) {
            Resume-Appliance -Always:($Action -eq "Import")
        }
    } finally {
        Restore-ProcessEnv
    }
}

if ($Action -eq "Import" -and -not $SkipValidation -and -not $SkipRestart) {
    Write-Step "Running post-restore new-rig validation"
    $bootstrap = Join-Path $RepoRoot "scripts\bootstrap-new-rig.ps1"
    if (-not (Test-Path -LiteralPath $bootstrap -PathType Leaf)) {
        throw "Restore succeeded, but bootstrap validation script was not found at $bootstrap"
    }
    $installRoot = Split-Path -Parent $resolvedRuntime
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $bootstrap `
        -Phase Validate `
        -InstallRoot $installRoot `
        -MinimumGpuCount $MinimumGpuCount
    if ($LASTEXITCODE -ne 0) {
        throw "State restore completed, but new-rig validation failed with exit code $LASTEXITCODE"
    }
}

Write-Host "Migration action '$Action' completed." -ForegroundColor Green

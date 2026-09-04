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

    # Do not grow another dotenv parser here. This helper is already CI-gated
    # against trailing comments, quotes and literal '#' values because a naive
    # parser previously broke the appliance for days.
    $parser = Join-Path $RepoRoot "scripts\Read-KalivEnvFile.ps1"
    if (-not (Test-Path -LiteralPath $parser -PathType Leaf)) {
        throw "Authoritative env parser not found at $parser"
    }
    . $parser
    $parsed = Read-KalivEnvFile -Path $Path
    $keys = New-Object System.Collections.Generic.List[string]
    foreach ($key in ($parsed.Keys | Sort-Object)) {
        if (-not $script:EnvOriginal.ContainsKey($key)) {
            $script:EnvOriginal[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        }
        [Environment]::SetEnvironmentVariable($key, [string]$parsed[$key], "Process")
        $keys.Add([string]$key)
    }
    $script:LoadedEnvKeys = @($keys)
    Write-Host ("Loaded {0} environment keys from modelrig.env (values are not printed)." -f $keys.Count)
}

function Restore-ProcessEnv {
    foreach ($key in $script:EnvOriginal.Keys) {
        [Environment]::SetEnvironmentVariable($key, $script:EnvOriginal[$key], "Process")
    }
}

function Resolve-LivePath {
    param(
        [string]$ExplicitValue,
        [string]$DefaultName,
        [string]$Runtime
    )
    if (-not [string]::IsNullOrWhiteSpace($ExplicitValue)) {
        if ([IO.Path]::IsPathRooted($ExplicitValue)) { return $ExplicitValue }
        return [IO.Path]::GetFullPath((Join-Path $Runtime $ExplicitValue))
    }

    $dataRoot = [Environment]::GetEnvironmentVariable("KALIV_DATA_DIR", "Process")
    if ([string]::IsNullOrWhiteSpace($dataRoot)) {
        $base = $env:LOCALAPPDATA
        if ([string]::IsNullOrWhiteSpace($base)) {
            $base = Join-Path $env:USERPROFILE "AppData\Local"
        }
        $dataRoot = Join-Path $base "Kaliv"
    } elseif (-not [IO.Path]::IsPathRooted($dataRoot)) {
        $dataRoot = [IO.Path]::GetFullPath((Join-Path $Runtime $dataRoot))
    }
    return Join-Path $dataRoot $DefaultName
}

function Assert-PortableSourceState {
    param([string]$Runtime)
    $mode = [Environment]::GetEnvironmentVariable("KALIV_AGENT3_MEMORY_STORE", "Process")
    if ([string]::IsNullOrWhiteSpace($mode) -or $mode.Trim().ToLowerInvariant() -ne "protected") {
        return
    }

    $configured = [Environment]::GetEnvironmentVariable("KALIV_AGENT3_MEMORY_DB", "Process")
    $memoryPath = Resolve-LivePath -ExplicitValue $configured -DefaultName "kaliv-agent3-memory.db" -Runtime $Runtime
    if (Test-Path -LiteralPath $memoryPath -PathType Leaf) {
        throw ("KALIV_AGENT3_MEMORY_STORE=protected and a protected memory database exists at '{0}'. " +
            "That store is bound to Windows DPAPI current-user key material and has no proven cross-machine restore contract. " +
            "Refusing to label it portable. Complete the dedicated T-033 physical migration/restore proof before moving this state.") -f $memoryPath
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

    $bootstrapWasRunning = $script:TaskState.ContainsKey($BootstrapTaskName) -and
        $script:TaskState[$BootstrapTaskName] -eq "Running"
    $supervisorWasRunning = $script:TaskState.ContainsKey($SupervisorTaskName) -and
        $script:TaskState[$SupervisorTaskName] -eq "Running"
    $shouldStart = $Always.IsPresent -or $bootstrapWasRunning -or $supervisorWasRunning
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
    param(
        [object[]]$Arguments,
        [string]$WorkingDirectory = $RepoRoot
    )
    $worker = Join-Path $RepoRoot "worker"
    $backupPy = Join-Path $worker "app\backup.py"
    if (-not (Test-Path -LiteralPath $backupPy -PathType Leaf)) {
        throw "Backup module not found at $backupPy"
    }
    if (-not (Test-Path -LiteralPath $WorkingDirectory -PathType Container)) {
        throw "Backup working directory not found: $WorkingDirectory"
    }
    if (-not (Get-Command $PythonExe -ErrorAction SilentlyContinue)) {
        throw "Python executable '$PythonExe' not found."
    }

    $previous = [Environment]::GetEnvironmentVariable("PYTHONPATH", "Process")
    try {
        [Environment]::SetEnvironmentVariable("PYTHONPATH", $worker, "Process")
        # Relative path overrides in modelrig.env are relative to the appliance
        # working directory. Running from RepoRoot would silently back up a
        # different ./modelrig-data.json or ./modelrig-rag.db.
        Push-Location $WorkingDirectory
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

    # Export values only for an explicit non-secret allowlist. Unknown future
    # variables are safer left out than guessed non-secret from their names.
    $safeValueKeys = @(
        "MODELRIG_HOST", "MODELRIG_PORT", "MODELRIG_WORKER_URL",
        "MODELRIG_DATA", "MODELRIG_PAIRING_TTL", "MODELRIG_CLAIM_MAX",
        "KALIV_AGENT3_ENABLED", "KALIV_AGENT3_MEMORY_STORE",
        "KALIV_SCHEDULER_API", "KALIV_SCHEDULER", "KALIV_SCHEDULER_POLL_S",
        "MODELRIG_EMBED_MODEL", "MODELRIG_GEN_MODEL", "MODELRIG_OLLAMA_TIMEOUT",
        "MODELRIG_DB", "MODELRIG_JOBS_DB", "KALIV_DATA_DIR", "KALIV_AUDIT_DB",
        "KALIV_TOOLS_STATE", "KALIV_TOOLS_DIR", "KALIV_SCHEDULES_DB",
        "KALIV_AGENT3_DB", "KALIV_AGENT3_REVIEW_DB", "KALIV_AGENT3_REPLAN_DB",
        "KALIV_AGENT3_REPLAN_PREVIEW_DB", "KALIV_AGENT3_MEMORY_DB",
        "KALIV_AGENT3_MEMORY_GRANT_DB", "KALIV_AGENT3_PLAN_DB",
        "KALIV_AGENT3_TASK_PLAN_DB", "KALIV_AGENT3_APPROVAL_DB",
        "KALIV_HOME_RIG_GRANTS_DB", "KALIV_HOME_RIG_AUDIT_DB",
        "KALIV_DATA_SHARING_DB", "KALIV_TOOLS_ENABLED"
    )
    $safe = [ordered]@{}
    $sensitiveKeys = New-Object System.Collections.Generic.List[string]
    $unclassifiedKeys = New-Object System.Collections.Generic.List[string]
    foreach ($key in $script:LoadedEnvKeys | Sort-Object -Unique) {
        if ($key -match '(?i)(KEY|SECRET|TOKEN|PASSWORD|CREDENTIAL)') {
            $sensitiveKeys.Add($key)
        } elseif ($safeValueKeys -contains $key) {
            $safe[$key] = [Environment]::GetEnvironmentVariable($key, "Process")
        } else {
            $unclassifiedKeys.Add($key)
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
        safe_config = $safe
        sensitive_config_keys_not_exported = @($sensitiveKeys)
        unclassified_config_keys_not_exported = @($unclassifiedKeys)
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

function Assert-MigrationSidecar {
    param([string]$ArchivePath)
    $sidecar = $ArchivePath + ".migration.json"
    if (-not (Test-Path -LiteralPath $sidecar -PathType Leaf)) {
        throw "Migration sidecar not found at $sidecar. Copy the archive and its .migration.json sidecar together."
    }
    try {
        $meta = Get-Content -LiteralPath $sidecar -Raw | ConvertFrom-Json
    } catch {
        throw "Migration sidecar is not valid JSON: $($_.Exception.Message)"
    }
    if ([string]$meta.schema -ne "modelrig-rig-migration/v1") {
        throw "Unsupported migration sidecar schema: $($meta.schema)"
    }
    if ([string]$meta.archive -ne (Split-Path -Leaf $ArchivePath)) {
        throw "Migration sidecar names archive '$($meta.archive)', not '$(Split-Path -Leaf $ArchivePath)'."
    }
    $got = (Get-FileHash -Algorithm SHA256 -LiteralPath $ArchivePath).Hash.ToLowerInvariant()
    $want = ([string]$meta.archive_sha256).Trim().ToLowerInvariant()
    if ([string]::IsNullOrWhiteSpace($want) -or $got -ne $want) {
        throw "Migration archive SHA-256 does not match its sidecar."
    }
    Write-Host "Migration sidecar matches archive SHA-256."
}

$resolvedRuntime = $null
$resolvedEnv = $null
$boundaryEstablished = $false
$restoreSucceeded = $false

try {
    if ($Action -eq "Verify") {
        $archivePath = Resolve-Archive -Value $Archive
        Write-Step "Verifying migration archive"
        Invoke-BackupModule -Arguments @("verify", $archivePath)
        $sidecar = $archivePath + ".migration.json"
        if (Test-Path -LiteralPath $sidecar -PathType Leaf) {
            Assert-MigrationSidecar -ArchivePath $archivePath
        }
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

    if ($Action -eq "Export") {
        Assert-PortableSourceState -Runtime $resolvedRuntime
    } else {
        $archivePath = Resolve-Archive -Value $Archive
        Assert-MigrationSidecar -ArchivePath $archivePath
    }

    Save-TaskStatesAndStop
    $boundaryEstablished = $true

    if ($Action -eq "Export") {
        Write-Step "Creating verified migration archive"
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
        $before = @(Get-ChildItem -LiteralPath $OutDir -Filter "kaliv-backup-*.tar.gz" -File -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName)
        Invoke-BackupModule -Arguments @("create", "--out", $OutDir) -WorkingDirectory $resolvedRuntime
        $after = @(Get-ChildItem -LiteralPath $OutDir -Filter "kaliv-backup-*.tar.gz" -File -ErrorAction Stop |
            Sort-Object LastWriteTimeUtc -Descending)
        $created = $after | Where-Object { $before -notcontains $_.FullName } | Select-Object -First 1
        if ($null -eq $created) {
            $created = $after | Select-Object -First 1
        }
        if ($null -eq $created) {
            throw "Backup module returned success but no migration archive was found in $OutDir"
        }
        Invoke-BackupModule -Arguments @("verify", $created.FullName) -WorkingDirectory $resolvedRuntime
        Write-MigrationSidecar -ArchivePath $created.FullName -Runtime $resolvedRuntime -EnvironmentFile $resolvedEnv
        Write-Host "EXPORT READY: $($created.FullName)" -ForegroundColor Green
    } else {
        Write-Step "Verifying archive before restore"
        Invoke-BackupModule -Arguments @("verify", $archivePath) -WorkingDirectory $resolvedRuntime
        Write-Step "Restoring portable rig state"
        $args = @("restore", $archivePath)
        if ($ForceRestore) { $args += "--force" }
        Invoke-BackupModule -Arguments $args -WorkingDirectory $resolvedRuntime
        $restoreSucceeded = $true
        Write-Host "RESTORE COMPLETE: $archivePath" -ForegroundColor Green
    }
} finally {
    try {
        if ($boundaryEstablished) {
            if ($Action -eq "Export") {
                # Export does not modify live state, so restore the old rig's
                # previous running/stopped state even if archive creation failed.
                Resume-Appliance
            } elseif ($Action -eq "Import" -and $restoreSucceeded) {
                # A completed restore always starts through recovery-first
                # bootstrap. A failed/partial restore deliberately stays down.
                Resume-Appliance -Always
            } elseif ($Action -eq "Import") {
                Write-Host "Import did not complete; appliance remains stopped for diagnosis." -ForegroundColor Yellow
            }
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

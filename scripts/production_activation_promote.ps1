[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$BodyRigEvidenceDir,

    [string]$Agent3ReportPath = "",

    [string]$ApplianceDir = "",

    [string]$BaseUrl = "http://127.0.0.1:8080",

    [string]$WorkerUrl = "http://127.0.0.1:8099",

    [string]$TokenEnv = "MODELRIG_TOKEN",

    [string]$OutputDir = "",

    [int]$ReadyTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$CandidateBranch = "feat/unity-frame-source"
$PromotionBranch = "feat/production-activation-promotion"
$SupervisorTaskName = "KalivSupervisor"
$BootstrapTaskName = "KalivBootstrap"

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $lines = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($lines -join [Environment]::NewLine)"
    }
    return (($lines -join "`n").Trim())
}

function Assert-Administrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Production activation must run in an elevated PowerShell because it restarts the recovery-first appliance tasks."
    }
}

function Assert-SupervisorAuthority {
    param([Parameter(Mandatory = $true)][string]$Root)

    $supervisor = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop
    if (@($supervisor.Triggers).Count -ne 0) {
        throw "KalivSupervisor has a direct trigger; recovery-first authority is not installed. Rerun scripts\kaliv-autostart.ps1 elevated."
    }
    $actions = @($supervisor.Actions)
    if ($actions.Count -ne 1) { throw "KalivSupervisor must have exactly one action." }
    $expectedExe = [IO.Path]::GetFullPath((Join-Path $Root "modelrig-supervisor-windows-x64.exe"))
    $actualExe = [IO.Path]::GetFullPath(([string]$actions[0].Execute).Trim('"'))
    if (-not [string]::Equals($expectedExe, $actualExe, [StringComparison]::OrdinalIgnoreCase)) {
        throw "KalivSupervisor points at a different appliance root. Expected $expectedExe, got $actualExe"
    }
    $actualWorking = [string]$actions[0].WorkingDirectory
    if ([string]::IsNullOrWhiteSpace($actualWorking)) {
        throw "KalivSupervisor has no WorkingDirectory; modelrig.env authority cannot be proven."
    }
    $actualWorking = [IO.Path]::GetFullPath($actualWorking)
    if (-not [string]::Equals([IO.Path]::GetFullPath($Root), $actualWorking, [StringComparison]::OrdinalIgnoreCase)) {
        throw "KalivSupervisor WorkingDirectory does not match the selected appliance root."
    }
    [void](Get-ScheduledTask -TaskName $BootstrapTaskName -ErrorAction Stop)
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Uri,
        [Parameter(Mandatory = $true)][int]$TimeoutSeconds
    )
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Method Get -Uri $Uri -TimeoutSec 5
            if ([int]$response.StatusCode -eq 200) { return }
        }
        catch {
            # Startup is asynchronous; retry until the bounded deadline.
        }
        Start-Sleep -Milliseconds 750
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Timed out waiting for $Uri"
}

function Restart-RecoveryFirstAppliance {
    param([Parameter(Mandatory = $true)][int]$TimeoutSeconds)

    $supervisor = Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop
    if ($supervisor.State -eq "Running") {
        Stop-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop
    }
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(30)
    do {
        $state = (Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop).State
        if ($state -ne "Running") { break }
        Start-Sleep -Milliseconds 500
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    if ((Get-ScheduledTask -TaskName $SupervisorTaskName -ErrorAction Stop).State -eq "Running") {
        throw "KalivSupervisor did not stop before recovery-first restart."
    }

    Start-ScheduledTask -TaskName $BootstrapTaskName -ErrorAction Stop
    Wait-HttpOk -Uri ($BaseUrl.TrimEnd("/") + "/healthz") -TimeoutSeconds $TimeoutSeconds
    Wait-HttpOk -Uri ($WorkerUrl.TrimEnd("/") + "/healthz") -TimeoutSeconds $TimeoutSeconds
}

function Write-AtomicUtf8Replacing {
    param(
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Content,
        [string]$BackupPath = ""
    )
    $directory = Split-Path -Parent $Destination
    $temporary = Join-Path $directory ("." + [IO.Path]::GetFileName($Destination) + ".tmp-" + [Guid]::NewGuid().ToString("N"))
    $encoding = [Text.UTF8Encoding]::new($false)
    $bytes = $encoding.GetBytes($Content)
    $stream = [IO.FileStream]::new(
        $temporary,
        [IO.FileMode]::CreateNew,
        [IO.FileAccess]::Write,
        [IO.FileShare]::None,
        4096,
        [IO.FileOptions]::WriteThrough
    )
    try {
        $stream.Write($bytes, 0, $bytes.Length)
        $stream.Flush($true)
    }
    finally {
        $stream.Dispose()
    }
    try {
        if ([string]::IsNullOrWhiteSpace($BackupPath)) {
            [IO.File]::Replace($temporary, $Destination, $null, $true)
        }
        else {
            if (Test-Path -LiteralPath $BackupPath) { throw "Backup destination already exists: $BackupPath" }
            [IO.File]::Replace($temporary, $Destination, $BackupPath, $true)
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function Restore-EnvironmentBackup {
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "Cannot roll back: environment backup is missing."
    }
    $raw = [IO.File]::ReadAllBytes($BackupPath)
    $directory = Split-Path -Parent $Destination
    $temporary = Join-Path $directory (".modelrig.env.rollback-" + [Guid]::NewGuid().ToString("N"))
    [IO.File]::WriteAllBytes($temporary, $raw)
    try {
        [IO.File]::Replace($temporary, $Destination, $null, $true)
    }
    finally {
        if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
    }
}

function New-SchedulerApprovalSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
}

function Build-PromotedEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$EnvironmentFile,
        [Parameter(Mandatory = $true)][string]$ValidationReport,
        [Parameter(Mandatory = $true)][string]$ApprovalSecret
    )

    $target = [Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($name in @(
        "KALIV_AGENT3_ENABLED",
        "KALIV_TOOLS_ENABLED",
        "KALIV_SCHEDULER",
        "KALIV_SCHEDULER_API",
        "KALIV_AGENT3_VALIDATION_REPORT",
        "KALIV_SCHEDULER_APPROVAL_SECRET"
    )) { [void]$target.Add($name) }

    $out = [Collections.Generic.List[string]]::new()
    foreach ($line in [IO.File]::ReadAllLines($EnvironmentFile)) {
        $eq = $line.IndexOf('=')
        if ($eq -gt 0) {
            $key = $line.Substring(0, $eq).Trim()
            if ($target.Contains($key)) { continue }
        }
        $out.Add($line)
    }
    if ($out.Count -gt 0 -and -not [string]::IsNullOrWhiteSpace($out[$out.Count - 1])) {
        $out.Add("")
    }
    $out.Add("# Machine-promoted production runtime. Evidence receipts remain production_activation=false.")
    $out.Add("KALIV_AGENT3_ENABLED=1")
    $out.Add("KALIV_TOOLS_ENABLED=1")
    $out.Add("KALIV_SCHEDULER=1")
    $out.Add("KALIV_SCHEDULER_API=1")
    $out.Add("KALIV_AGENT3_VALIDATION_REPORT=$ValidationReport")
    $out.Add("KALIV_SCHEDULER_APPROVAL_SECRET=$ApprovalSecret")
    return (($out -join "`r`n") + "`r`n")
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "Production activation promotion must run on the physical Windows appliance."
}
if ($ReadyTimeoutSeconds -lt 30 -or $ReadyTimeoutSeconds -gt 600) {
    throw "ReadyTimeoutSeconds must be between 30 and 600."
}
Assert-Administrator

if ([string]::IsNullOrWhiteSpace([Environment]::GetEnvironmentVariable($TokenEnv, "Process"))) {
    throw "$TokenEnv is not set in the process environment. Never pass the paired-device token on the command line."
}
if ([string]::IsNullOrWhiteSpace($ApplianceDir)) { $ApplianceDir = $RepoRoot }
$ApplianceDir = [IO.Path]::GetFullPath($ApplianceDir)
$EnvFile = [IO.Path]::GetFullPath((Join-Path $ApplianceDir "modelrig.env"))
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
    throw "Permanent appliance environment is missing: $EnvFile"
}
if ([string]::IsNullOrWhiteSpace($Agent3ReportPath)) {
    $Agent3ReportPath = Join-Path $RepoRoot "validation\agent3-rig-validation-latest.json"
}
$Agent3ReportPath = [IO.Path]::GetFullPath($Agent3ReportPath)
$BodyRigEvidenceDir = [IO.Path]::GetFullPath($BodyRigEvidenceDir)
if ($Agent3ReportPath.Contains("#")) {
    throw "Agent3 report path contains '#', which is ambiguous in modelrig.env. Move the report before promotion."
}
if (-not (Test-Path -LiteralPath $Agent3ReportPath -PathType Leaf)) {
    throw "Agent3 rig-validation report is missing: $Agent3ReportPath"
}
if (-not (Test-Path -LiteralPath $BodyRigEvidenceDir -PathType Container)) {
    throw "BodyRig evidence directory is missing: $BodyRigEvidenceDir"
}
Assert-SupervisorAuthority -Root $ApplianceDir

Push-Location $RepoRoot
$environmentMutated = $false
$backupPath = ""
try {
    Invoke-Git @("fetch", "--quiet", "origin", "main", $CandidateBranch, $PromotionBranch) | Out-Null
    $candidateSha = Invoke-Git @("rev-parse", ("origin/" + $CandidateBranch))
    $promotionSha = Invoke-Git @("rev-parse", "HEAD")

    if ([string]::IsNullOrWhiteSpace($OutputDir)) {
        $base = $env:LOCALAPPDATA
        if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:TEMP }
        if ([string]::IsNullOrWhiteSpace($base)) { throw "LOCALAPPDATA/TEMP is unavailable; pass -OutputDir." }
        $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
        $OutputDir = Join-Path $base ("ModelRig\ProductionActivation\" + $candidateSha + "-" + $stamp)
    }
    $OutputDir = [IO.Path]::GetFullPath($OutputDir)
    if (Test-Path -LiteralPath $OutputDir) {
        if (@(Get-ChildItem -LiteralPath $OutputDir -Force).Count -ne 0) {
            throw "OutputDir is not empty; preserve it and choose a new one."
        }
    }
    else {
        New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    }

    $preflight = Join-Path $OutputDir "production-activation-preflight.json"
    $finalReceipt = Join-Path $OutputDir "production-activation.json"

    Write-Host "[1/4] Validating candidate-bound BodyRig + Agent3 promotion evidence"
    & python -m scripts.production_activation_gate preflight `
        --candidate-sha $candidateSha `
        --bodyrig-evidence-dir $BodyRigEvidenceDir `
        --agent3-report $Agent3ReportPath `
        --env-file $EnvFile `
        --output $preflight
    if ($LASTEXITCODE -ne 0) { throw "Production activation preflight failed." }

    . (Join-Path $RepoRoot "scripts\Read-KalivEnvFile.ps1")
    $current = Read-KalivEnvFile -Path $EnvFile
    $secret = [string]$current["KALIV_SCHEDULER_APPROVAL_SECRET"]
    if ([string]::IsNullOrWhiteSpace($secret) -or $secret.Length -lt 32 -or $secret -match '[\s#]') {
        $secret = New-SchedulerApprovalSecret
    }

    Write-Host "[2/4] Atomically promoting permanent appliance environment (secret value is never printed)"
    $promoted = Build-PromotedEnvironment -EnvironmentFile $EnvFile -ValidationReport $Agent3ReportPath -ApprovalSecret $secret
    $backupPath = Join-Path $ApplianceDir ("modelrig.env.pre-production-activation-" + [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff") + ".bak")
    Write-AtomicUtf8Replacing -Destination $EnvFile -Content $promoted -BackupPath $backupPath
    $environmentMutated = $true
    $secret = $null

    $after = Read-KalivEnvFile -Path $EnvFile
    foreach ($key in @("KALIV_AGENT3_ENABLED", "KALIV_TOOLS_ENABLED", "KALIV_SCHEDULER", "KALIV_SCHEDULER_API")) {
        if ([string]$after[$key] -ne "1") { throw "Environment writer failed to set $key=1" }
    }
    if ([string]::IsNullOrWhiteSpace([string]$after["KALIV_SCHEDULER_APPROVAL_SECRET"])) {
        throw "Environment writer failed to configure scheduler approval secret."
    }

    Write-Host "[3/4] Restarting through KalivBootstrap recovery authority"
    Restart-RecoveryFirstAppliance -TimeoutSeconds $ReadyTimeoutSeconds

    Write-Host "[4/4] Revalidating evidence + live Agent3/tools/scheduler before activation receipt"
    & python -m scripts.production_activation_gate finalize `
        --candidate-sha $candidateSha `
        --bodyrig-evidence-dir $BodyRigEvidenceDir `
        --agent3-report $Agent3ReportPath `
        --env-file $EnvFile `
        --preflight $preflight `
        --base-url $BaseUrl `
        --worker-url $WorkerUrl `
        --token-env $TokenEnv `
        --output $finalReceipt
    if ($LASTEXITCODE -ne 0) { throw "Final production activation gate failed." }

    $environmentMutated = $false
    Write-Host "PRODUCTION ACTIVATION PROMOTION: PASS"
    Write-Host "  candidate: $candidateSha"
    Write-Host "  promotion: $promotionSha"
    Write-Host "  receipt:   $finalReceipt"
    Write-Host "  rollback backup retained locally: $backupPath"
    Write-Host "production_activation=true"
    Write-Output $finalReceipt
}
catch {
    $failure = $_
    if ($environmentMutated -and -not [string]::IsNullOrWhiteSpace($backupPath)) {
        Write-Warning "Promotion failed after env mutation. Restoring the exact pre-activation environment and recovery-first restarting the appliance."
        try {
            Restore-EnvironmentBackup -BackupPath $backupPath -Destination $EnvFile
            Restart-RecoveryFirstAppliance -TimeoutSeconds $ReadyTimeoutSeconds
            Write-Warning "Pre-activation environment restored; production_activation remains false."
        }
        catch {
            Write-Error "ROLLBACK FAILURE: $($_.Exception.Message)"
        }
    }
    throw $failure
}
finally {
    Pop-Location
}

param(
    [Parameter(Mandatory = $true)]
    [string]$Store,

    [string]$RigUrl = "http://127.0.0.1:8080",

    [string]$WorkerUrl = "http://127.0.0.1:8099",

    [string]$TokenEnv = "BODYRIG_RIG_TOKEN",

    [string]$EvidenceDir = "",

    [string]$UnityExe = "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe",

    [string]$Model = "",

    [int]$RuntimeReceiptTimeoutSeconds = 90,

    [int]$LiveReceiptTimeoutSeconds = 30,

    [int]$QualityReceiptTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GitShaPattern = '^[0-9a-f]{40}$'
$CandidateBranch = "feat/unity-frame-source"

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $lines = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($lines -join [Environment]::NewLine)"
    }
    return (($lines -join "`n").Trim())
}

function Assert-FullyClean {
    param([Parameter(Mandatory = $true)][string]$Stage)
    $status = Invoke-Git @("status", "--porcelain=v1", "--untracked-files=all")
    if (-not [string]::IsNullOrWhiteSpace($status)) {
        throw "repository is not fully clean at $Stage; automatic live evidence is invalid:`n$status"
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig automatic live proof must run on the physical Windows rig"
}
if ($QualityReceiptTimeoutSeconds -lt 5 -or $QualityReceiptTimeoutSeconds -gt 300) {
    throw "QualityReceiptTimeoutSeconds must be between 5 and 300"
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $RepoRoot
try {
    Assert-FullyClean "automatic proof start"
    $head = Invoke-Git @("rev-parse", "HEAD")
    if ($head -notmatch $GitShaPattern) { throw "current HEAD is not a canonical git SHA" }

    Invoke-Git @("fetch", "--quiet", "origin", "main", $CandidateBranch) | Out-Null
    $remoteHead = Invoke-Git @("rev-parse", ("origin/" + $CandidateBranch))
    if ($head -ne $remoteHead) {
        throw "local HEAD is not current remote #846 head; fetch/pull before collecting evidence"
    }
    $behind = [int](Invoke-Git @("rev-list", "--count", ($head + "..origin/main")))
    if ($behind -ne 0) {
        throw "#846 head is behind current origin/main; re-anchor before collecting evidence"
    }

    $token = [Environment]::GetEnvironmentVariable($TokenEnv, "Process")
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "$TokenEnv is not set in process environment; never pass the device token on the command line"
    }

    if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
        $base = $env:LOCALAPPDATA
        if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:TEMP }
        if ([string]::IsNullOrWhiteSpace($base)) {
            throw "LOCALAPPDATA/TEMP is unavailable; pass -EvidenceDir explicitly"
        }
        $stamp = [DateTimeOffset]::UtcNow.ToString("yyyyMMdd-HHmmssfff")
        $EvidenceDir = Join-Path $base ("ModelRig\BodyRigLiveAutomaticEvidence\" + $head + "-" + $stamp)
    }
    $EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
    if (Test-Path -LiteralPath $EvidenceDir) {
        if (@(Get-ChildItem -LiteralPath $EvidenceDir -Force).Count -ne 0) {
            throw "evidence directory is not empty; preserve it and choose a new -EvidenceDir"
        }
    }

    $qualityReceipt = Join-Path $EvidenceDir "live-quality-receipt.json"
    $savedQualityReceipt = [Environment]::GetEnvironmentVariable("BODYRIG_LIVE_QUALITY_RECEIPT", "Process")
    try {
        $env:BODYRIG_LIVE_QUALITY_RECEIPT = $qualityReceipt

        $machineProof = Join-Path $RepoRoot "scripts\bodyrig_unity_live_physical_proof.ps1"
        & $machineProof `
            -Store $Store `
            -RigUrl $RigUrl `
            -TokenEnv $TokenEnv `
            -EvidenceDir $EvidenceDir `
            -UnityExe $UnityExe `
            -RuntimeReceiptTimeoutSeconds $RuntimeReceiptTimeoutSeconds `
            -LiveReceiptTimeoutSeconds $LiveReceiptTimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw "base #846 Unity live machine proof failed"
        }

        $exercise = Join-Path $RepoRoot "scripts\bodyrig_live_automatic_exercise.py"
        $exerciseArgs = @(
            $exercise,
            "--evidence-dir", $EvidenceDir,
            "--rig-url", $RigUrl,
            "--worker-url", $WorkerUrl,
            "--token-env", $TokenEnv,
            "--quality-timeout-seconds", [string]$QualityReceiptTimeoutSeconds
        )
        if (-not [string]::IsNullOrWhiteSpace($Model)) {
            $exerciseArgs += @("--model", $Model)
        }
        & python @exerciseArgs
        if ($LASTEXITCODE -ne 0) {
            throw "automatic live product exercise failed"
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable("BODYRIG_LIVE_QUALITY_RECEIPT", $savedQualityReceipt, "Process")
    }

    Assert-FullyClean "before automatic final gate"
    $headAfter = Invoke-Git @("rev-parse", "HEAD")
    if ($headAfter -ne $head) { throw "local HEAD moved during automatic proof; discard this evidence" }

    & python -m scripts.bodyrig_unity_live_automatic_final_gate --expected-sha $head --evidence-dir $EvidenceDir
    if ($LASTEXITCODE -ne 0) {
        throw "automatic #846 final gate failed"
    }

    $finalReceipt = Join-Path $EvidenceDir "live-automatic-final-receipt.json"
    if (-not (Test-Path -LiteralPath $finalReceipt -PathType Leaf)) {
        throw "automatic final gate returned success without its final receipt"
    }
    try {
        $final = Get-Content -LiteralPath $finalReceipt -Raw | ConvertFrom-Json
    }
    catch {
        throw "automatic final receipt is not valid JSON"
    }
    if ([string]$final.schema -ne "bodyrig.unity_live_automatic_final/v0.1") {
        throw "automatic final receipt schema mismatch"
    }
    if ([string]$final.candidate_git_sha -ne $head) {
        throw "automatic final receipt candidate SHA mismatch"
    }
    if (-not [bool]$final.machine_live_proof -or -not [bool]$final.machine_quality -or -not [bool]$final.product_exercise) {
        throw "automatic final receipt does not prove the complete machine path"
    }
    if ([bool]$final.production_activation -ne $false) {
        throw "#846 renderer proof must not independently activate production"
    }

    Write-Host "BODYRIG UNITY LIVE AUTOMATIC PROOF: PASS"
    Write-Host "  candidate: $head"
    Write-Host "  evidence:  $EvidenceDir"
    Write-Host "  final:     $finalReceipt"
    Write-Host "production_activation=false"
    Write-Output $EvidenceDir
}
finally {
    Pop-Location
}

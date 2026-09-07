param(
    [Parameter(Mandatory = $true)]
    [string]$Store,

    [string]$RigUrl = "http://127.0.0.1:8080",

    [string]$TokenEnv = "BODYRIG_RIG_TOKEN",

    [string]$EvidenceDir = "",

    [string]$UnityExe = "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe",

    [int]$FrameCount = 5,

    [int]$RuntimeReceiptTimeoutSeconds = 90,

    [int]$LiveReceiptTimeoutSeconds = 30
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GitShaPattern = '^[0-9a-f]{40}$'
$BodyIdPattern = '^bodyid-[0-9a-f]{24}$'
$Sha256Pattern = '^[0-9a-f]{64}$'
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
        throw "repository is not fully clean at $Stage; live evidence is invalid:`n$status"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant())
}

function Get-DefaultEvidenceDir {
    param([Parameter(Mandatory = $true)][string]$HeadSha)
    $base = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) { $base = $env:TEMP }
    if ([string]::IsNullOrWhiteSpace($base)) {
        throw "LOCALAPPDATA/TEMP is unavailable; pass -EvidenceDir explicitly"
    }
    return (Join-Path $base ("ModelRig\BodyRigLiveEvidence\" + $HeadSha))
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig live Unity proof must run on the physical Windows rig"
}
if ($FrameCount -lt 2 -or $FrameCount -gt 100) {
    throw "FrameCount must be between 2 and 100"
}
if ($LiveReceiptTimeoutSeconds -lt 5 -or $LiveReceiptTimeoutSeconds -gt 300) {
    throw "LiveReceiptTimeoutSeconds must be between 5 and 300"
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $RepoRoot
try {
    Assert-FullyClean "live proof start"
    $head = Invoke-Git @("rev-parse", "HEAD")
    if ($head -notmatch $GitShaPattern) { throw "current HEAD is not a canonical git SHA" }

    Invoke-Git @("fetch", "--quiet", "origin", "main", $CandidateBranch) | Out-Null
    $remoteHead = Invoke-Git @("rev-parse", ("origin/" + $CandidateBranch))
    $mainBefore = Invoke-Git @("rev-parse", "origin/main")
    if ($remoteHead -notmatch $GitShaPattern -or $mainBefore -notmatch $GitShaPattern) {
        throw "remote authority is not a canonical git SHA"
    }
    if ($head -ne $remoteHead) {
        throw "local HEAD is not the current remote #846 head; fetch/pull before collecting evidence"
    }
    $behind = [int](Invoke-Git @("rev-list", "--count", ($head + "..origin/main")))
    if ($behind -ne 0) {
        throw "#846 head is behind current origin/main; rebase before collecting physical evidence"
    }

    $token = [Environment]::GetEnvironmentVariable($TokenEnv, "Process")
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "$TokenEnv is not set in the process environment; the device token is never accepted on the command line"
    }

    if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
        $EvidenceDir = Get-DefaultEvidenceDir $head
    }
    $EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
    if (Test-Path -LiteralPath $EvidenceDir) {
        if (@(Get-ChildItem -LiteralPath $EvidenceDir -Force).Count -ne 0) {
            throw "evidence directory is not empty; preserve it and choose a new -EvidenceDir"
        }
    }
    else {
        New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
    }

    $prepareScript = Join-Path $RepoRoot "scripts\bodyrig_prepare_renderer_profile.py"
    $handoffRaw = & python $prepareScript $Store 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig renderer profile preparation failed: $($handoffRaw -join [Environment]::NewLine)"
    }
    try {
        $handoff = (($handoffRaw -join "`n").Trim()) | ConvertFrom-Json
    }
    catch {
        throw "renderer profile preparation did not return valid JSON"
    }
    $bodyId = [string]$handoff.body_id
    $packageSha = [string]$handoff.package_sha256
    if ($bodyId -notmatch $BodyIdPattern) { throw "prepared body_id is invalid" }
    if ($packageSha -notmatch $Sha256Pattern) { throw "prepared package SHA-256 is invalid" }

    $preflightReceipt = Join-Path $EvidenceDir "live-preflight-receipt.json"
    $probe = Join-Path $RepoRoot "scripts\bodyrig_live_stream_probe.py"
    & python $probe `
        --base-url $RigUrl `
        --token-env $TokenEnv `
        --expected-body-id $bodyId `
        --expected-package-sha256 $packageSha `
        --frame-count $FrameCount `
        --output $preflightReceipt
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig live stream preflight failed"
    }
    if (-not (Test-Path -LiteralPath $preflightReceipt -PathType Leaf)) {
        throw "live stream preflight returned success without a receipt"
    }

    $liveReceipt = Join-Path $EvidenceDir "unity-live-receipt.json"
    $rendererEvidence = Join-Path $EvidenceDir "renderer"
    $physicalProof = Join-Path $RepoRoot "scripts\bodyrig_unity_physical_proof.ps1"

    $savedRigUrl = [Environment]::GetEnvironmentVariable("BODYRIG_RIG_URL", "Process")
    $savedRigToken = [Environment]::GetEnvironmentVariable("BODYRIG_RIG_TOKEN", "Process")
    $savedLiveReceipt = [Environment]::GetEnvironmentVariable("BODYRIG_LIVE_RECEIPT", "Process")
    try {
        $env:BODYRIG_RIG_URL = $RigUrl.TrimEnd('/')
        $env:BODYRIG_RIG_TOKEN = $token
        $env:BODYRIG_LIVE_RECEIPT = $liveReceipt
        & $physicalProof `
            -Store $Store `
            -EvidenceDir $rendererEvidence `
            -UnityExe $UnityExe `
            -RuntimeReceiptTimeoutSeconds $RuntimeReceiptTimeoutSeconds
        if ($LASTEXITCODE -ne 0) {
            throw "base Unity physical proof failed"
        }

        $deadline = [DateTimeOffset]::UtcNow.AddSeconds($LiveReceiptTimeoutSeconds)
        while (-not (Test-Path -LiteralPath $liveReceipt -PathType Leaf)) {
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                throw "Unity loaded the renderer but did not attest an applied live frame within $LiveReceiptTimeoutSeconds seconds"
            }
            Start-Sleep -Milliseconds 250
        }
    }
    finally {
        [Environment]::SetEnvironmentVariable("BODYRIG_RIG_URL", $savedRigUrl, "Process")
        [Environment]::SetEnvironmentVariable("BODYRIG_RIG_TOKEN", $savedRigToken, "Process")
        [Environment]::SetEnvironmentVariable("BODYRIG_LIVE_RECEIPT", $savedLiveReceipt, "Process")
    }

    $preflight = Get-Content -LiteralPath $preflightReceipt -Raw | ConvertFrom-Json
    $live = Get-Content -LiteralPath $liveReceipt -Raw | ConvertFrom-Json
    $buildReceipt = Join-Path $rendererEvidence "build-receipt.json"
    $runtimeReceipt = Join-Path $rendererEvidence "runtime-receipt.json"
    if (-not (Test-Path -LiteralPath $buildReceipt -PathType Leaf)) { throw "renderer build receipt is missing" }
    if (-not (Test-Path -LiteralPath $runtimeReceipt -PathType Leaf)) { throw "renderer runtime receipt is missing" }

    if ([string]$preflight.schema -ne "bodyrig.live_stream_probe/v0.1") { throw "preflight schema mismatch" }
    if ([string]$preflight.candidate_git_sha -ne $head) { throw "preflight candidate SHA mismatch" }
    if ([string]$preflight.active_body_id -ne $bodyId) { throw "preflight body mismatch" }
    if ([string]$preflight.active_package_sha256 -ne $packageSha) { throw "preflight package mismatch" }
    if (-not [bool]$preflight.canonical_frame_validation) { throw "preflight did not validate canonical frames" }
    if ([bool]$preflight.production_activation -ne $false) { throw "preflight unexpectedly activated production" }

    if ([string]$live.schema -ne "bodyrig.unity_live_stream/v0.1") { throw "Unity live receipt schema mismatch" }
    if ([string]$live.candidate_git_sha -ne $head) { throw "Unity live receipt candidate SHA mismatch" }
    if ([string]$live.body_id -ne $bodyId) { throw "Unity live receipt body mismatch" }
    if ([string]$live.package_sha256 -ne $packageSha) { throw "Unity live receipt package mismatch" }
    if (-not [bool]$live.bearer_auth_used -or -not [bool]$live.renderer_bound -or -not [bool]$live.frame_applied) {
        throw "Unity live receipt does not prove authenticated frame application to a bound renderer"
    }
    if ([bool]$live.production_activation -ne $false) { throw "Unity live receipt unexpectedly activated production" }
    if ([string]$live.source_url -ne $RigUrl.TrimEnd('/')) { throw "Unity live source URL differs from the probed rig URL" }

    Assert-FullyClean "after Unity live machine proof"
    $headAfter = Invoke-Git @("rev-parse", "HEAD")
    if ($headAfter -ne $head) { throw "local HEAD moved during live proof; discard this run" }
    Invoke-Git @("fetch", "--quiet", "origin", "main", $CandidateBranch) | Out-Null
    $remoteHeadAfter = Invoke-Git @("rev-parse", ("origin/" + $CandidateBranch))
    $mainAfter = Invoke-Git @("rev-parse", "origin/main")
    if ($remoteHeadAfter -ne $remoteHead) {
        throw "remote #846 head moved during live proof; discard this run"
    }
    if ($mainAfter -ne $mainBefore) {
        throw "origin/main moved during live proof; discard this run and rebase #846"
    }

    $runReceipt = [ordered]@{
        schema = "bodyrig.unity_live_run/v0.1"
        created_at = [DateTimeOffset]::UtcNow.ToString("o")
        production_activation = $false
        visual_acceptance = $false
        pr_number = 846
        candidate_git_sha = $head
        authority = [ordered]@{
            remote_branch = $CandidateBranch
            remote_pr_head_sha = $remoteHead
            origin_main_sha = $mainBefore
            remote_pr_head_verified = $true
            origin_main_stable_during_run = $true
            clean_checkout = $true
        }
        rig_url = $RigUrl.TrimEnd('/')
        profile = [ordered]@{
            body_id = $bodyId
            package_sha256 = $packageSha
        }
        receipts = [ordered]@{
            preflight = [ordered]@{
                path = [IO.Path]::GetFullPath($preflightReceipt)
                sha256 = Get-Sha256 $preflightReceipt
            }
            renderer_build = [ordered]@{
                path = [IO.Path]::GetFullPath($buildReceipt)
                sha256 = Get-Sha256 $buildReceipt
            }
            renderer_runtime = [ordered]@{
                path = [IO.Path]::GetFullPath($runtimeReceipt)
                sha256 = Get-Sha256 $runtimeReceipt
            }
            unity_live = [ordered]@{
                path = [IO.Path]::GetFullPath($liveReceipt)
                sha256 = Get-Sha256 $liveReceipt
            }
        }
    }
    $runReceiptPath = Join-Path $EvidenceDir "live-run-receipt.json"
    $runReceipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $runReceiptPath -Encoding UTF8

    Write-Host "BODYRIG UNITY LIVE MACHINE GATE: PASS"
    Write-Host "  candidate: $head"
    Write-Host "  remote:    origin/$CandidateBranch"
    Write-Host "  body:      $bodyId"
    Write-Host "  rig:       $($RigUrl.TrimEnd('/'))"
    Write-Host "  evidence:  $EvidenceDir"
    Write-Host ""
    Write-Host "Renderer remains open. Observe a real conversation, then record the separate visual acceptance."
    Write-Output $EvidenceDir
}
finally {
    Pop-Location
}

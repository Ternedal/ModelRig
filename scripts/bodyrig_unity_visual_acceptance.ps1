param(
    [string]$EvidenceDir = "",

    [switch]$StatesDistinct,
    [switch]$GazeBlinkBreathVisible,
    [switch]$ExplainGestureVisible,
    [switch]$SpeechModesDiffer,
    [switch]$InterruptionImmediateNeutral
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$GitShaPattern = '^[0-9a-f]{40}$'
$Sha256Pattern = '^[0-9a-f]{64}$'

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $lines = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($lines -join [Environment]::NewLine)"
    }
    return (($lines -join "`n").Trim())
}

function Assert-TrackedClean {
    & git diff --quiet --
    if ($LASTEXITCODE -ne 0) { throw "tracked files differ from the accepted candidate" }
    & git diff --cached --quiet --
    if ($LASTEXITCODE -ne 0) { throw "index differs from the accepted candidate" }
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
    return (Join-Path $base ("ModelRig\BodyRigEvidence\" + $HeadSha))
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig Unity visual acceptance must be recorded on the physical Windows rig"
}

if (-not ($StatesDistinct -and $GazeBlinkBreathVisible -and $ExplainGestureVisible -and $SpeechModesDiffer -and $InterruptionImmediateNeutral)) {
    throw "all five visual acceptance switches must be supplied after direct observation; no partial acceptance is recorded"
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $RepoRoot
try {
    $head = Invoke-Git @("rev-parse", "HEAD")
    if ($head -notmatch $GitShaPattern) { throw "current HEAD is not a canonical git SHA" }
    Assert-TrackedClean

    if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
        $EvidenceDir = Get-DefaultEvidenceDir $head
    }
    $EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
    $buildReceiptPath = Join-Path $EvidenceDir "build-receipt.json"
    if (-not (Test-Path -LiteralPath $buildReceiptPath -PathType Leaf)) {
        throw "build-receipt.json is missing; run bodyrig_unity_physical_proof.ps1 first"
    }
    $visualReceiptPath = Join-Path $EvidenceDir "visual-receipt.json"
    if (Test-Path -LiteralPath $visualReceiptPath) {
        throw "visual-receipt.json already exists; preserve it and use a new evidence directory for another observation"
    }

    $buildRaw = [IO.File]::ReadAllBytes($buildReceiptPath)
    $buildReceiptSha = [BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($buildRaw)).Replace("-", "").ToLowerInvariant()
    $build = Get-Content -LiteralPath $buildReceiptPath -Raw | ConvertFrom-Json

    if ([string]$build.schema -ne "bodyrig.unity_physical_build/v0.2") { throw "build receipt schema mismatch" }
    if ([bool]$build.production_activation -ne $false) { throw "build receipt unexpectedly activated production" }
    if ([bool]$build.visual_acceptance -ne $false) { throw "build receipt must not self-assert visual acceptance" }
    if ([string]$build.candidate.git_sha -ne $head) { throw "current HEAD differs from the physical build candidate" }
    if (-not [bool]$build.build.success -or [int]$build.build.exit_code -ne 0) { throw "build receipt does not represent a successful Unity build" }
    if (-not [bool]$build.build.launched) { throw "renderer was not launched by the physical proof run; visual acceptance cannot be bound to it" }
    if (-not [bool]$build.build.runtime_load_verified) { throw "runtime VRM load/bind was not verified; visual acceptance cannot proceed" }

    $exePath = [string]$build.artifacts.executable.path
    $exeSha = [string]$build.artifacts.executable.sha256
    if ($exeSha -notmatch $Sha256Pattern -or -not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "built renderer artifact is missing or has an invalid digest"
    }
    if ((Get-Sha256 $exePath) -ne $exeSha) { throw "built renderer executable changed after the physical build" }

    $runtimeReceiptPath = [string]$build.artifacts.runtime_receipt.path
    $runtimeReceiptSha = [string]$build.artifacts.runtime_receipt.sha256
    if ($runtimeReceiptSha -notmatch $Sha256Pattern -or -not (Test-Path -LiteralPath $runtimeReceiptPath -PathType Leaf)) {
        throw "runtime VRM-load receipt is missing or has an invalid digest"
    }
    if ((Get-Sha256 $runtimeReceiptPath) -ne $runtimeReceiptSha) { throw "runtime VRM-load receipt changed after the physical build" }
    $runtime = Get-Content -LiteralPath $runtimeReceiptPath -Raw | ConvertFrom-Json
    if ([string]$runtime.schema -ne "bodyrig.unity_runtime_load/v0.1") { throw "runtime receipt schema mismatch" }
    if (-not [bool]$runtime.vrm_loaded -or -not [bool]$runtime.renderer_bound) { throw "runtime receipt no longer proves VRM load + renderer bind" }
    if ([string]$runtime.candidate_git_sha -ne $head) { throw "runtime receipt candidate mismatch" }

    $vrmPath = [string]$build.profile.vrm_path
    $avatarSha = [string]$build.profile.avatar_sha256
    if ($avatarSha -notmatch $Sha256Pattern -or -not (Test-Path -LiteralPath $vrmPath -PathType Leaf)) {
        throw "digest-bound renderer avatar is missing or has an invalid digest"
    }
    if ((Get-Sha256 $vrmPath) -ne $avatarSha) { throw "renderer avatar changed after the physical build" }

    $receipt = [ordered]@{
        schema = "bodyrig.unity_visual_acceptance/v0.2"
        accepted_at = [DateTimeOffset]::UtcNow.ToString("o")
        production_activation = $false
        visual_acceptance = $true
        pr_number = 720
        candidate_git_sha = $head
        build_receipt_sha256 = $buildReceiptSha
        runtime_receipt_sha256 = $runtimeReceiptSha
        profile = [ordered]@{
            body_id = [string]$build.profile.body_id
            package_sha256 = [string]$build.profile.package_sha256
            avatar_sha256 = $avatarSha
        }
        executable_sha256 = $exeSha
        checks = [ordered]@{
            states_distinct = $true
            gaze_blink_breath_visible = $true
            explain_gesture_visible = $true
            speech_modes_visibly_differ = $true
            interruption_immediately_neutralizes_mouth_and_gesture = $true
        }
        operator = [ordered]@{
            user = [Environment]::UserName
            machine = [Environment]::MachineName
            attestation = "directly observed on the physical Windows renderer rig"
        }
    }

    $receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $visualReceiptPath -Encoding UTF8
    Write-Host "BodyRig Unity visual acceptance recorded: $visualReceiptPath"
    Write-Host "Now run the independent gate against the same exact draft SHA:"
    Write-Host "  python scripts/bodyrig_unity_physical_gate.py --expected-sha $head"
    Write-Output $EvidenceDir
}
finally {
    Pop-Location
}

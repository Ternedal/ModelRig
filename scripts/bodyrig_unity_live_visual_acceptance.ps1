param(
    [Parameter(Mandatory = $true)]
    [string]$EvidenceDir,

    [switch]$StatesDistinct,
    [switch]$GazeBlinkBreathVisible,
    [switch]$SpeechMouthTracksPlayback,
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
    if ($LASTEXITCODE -ne 0) { throw "tracked files differ from the live candidate" }
    & git diff --cached --quiet --
    if ($LASTEXITCODE -ne 0) { throw "index differs from the live candidate" }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant())
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig live visual acceptance must be recorded on the physical Windows rig"
}
if (-not ($StatesDistinct -and $GazeBlinkBreathVisible -and $SpeechMouthTracksPlayback -and $InterruptionImmediateNeutral)) {
    throw "all four live visual acceptance switches must be supplied after direct observation"
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $RepoRoot
try {
    $head = Invoke-Git @("rev-parse", "HEAD")
    if ($head -notmatch $GitShaPattern) { throw "current HEAD is not a canonical git SHA" }
    Assert-TrackedClean

    $EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
    $runPath = Join-Path $EvidenceDir "live-run-receipt.json"
    $preflightPath = Join-Path $EvidenceDir "live-preflight-receipt.json"
    $unityLivePath = Join-Path $EvidenceDir "unity-live-receipt.json"
    $buildPath = Join-Path $EvidenceDir "renderer\build-receipt.json"
    $runtimePath = Join-Path $EvidenceDir "renderer\runtime-receipt.json"
    foreach ($path in @($runPath, $preflightPath, $unityLivePath, $buildPath, $runtimePath)) {
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "required live evidence is missing: $path"
        }
    }

    $run = Get-Content -LiteralPath $runPath -Raw | ConvertFrom-Json
    $preflight = Get-Content -LiteralPath $preflightPath -Raw | ConvertFrom-Json
    $unityLive = Get-Content -LiteralPath $unityLivePath -Raw | ConvertFrom-Json
    $build = Get-Content -LiteralPath $buildPath -Raw | ConvertFrom-Json
    $runtime = Get-Content -LiteralPath $runtimePath -Raw | ConvertFrom-Json

    if ([string]$run.schema -ne "bodyrig.unity_live_run/v0.1" -or [int]$run.pr_number -ne 846) {
        throw "live run receipt schema/PR mismatch"
    }
    if ([string]$run.candidate_git_sha -ne $head) { throw "live run candidate differs from current HEAD" }
    if ([bool]$run.production_activation -ne $false -or [bool]$run.visual_acceptance -ne $false) {
        throw "live run receipt must remain non-production and non-visual"
    }
    if ([string]$preflight.candidate_git_sha -ne $head) { throw "preflight candidate mismatch" }
    if ([string]$unityLive.candidate_git_sha -ne $head) { throw "Unity live candidate mismatch" }
    if ([string]$build.candidate.git_sha -ne $head) { throw "renderer build candidate mismatch" }
    if ([string]$runtime.candidate_git_sha -ne $head) { throw "renderer runtime candidate mismatch" }

    $bodyId = [string]$run.profile.body_id
    $packageSha = [string]$run.profile.package_sha256
    if ([string]$preflight.active_body_id -ne $bodyId -or [string]$unityLive.body_id -ne $bodyId -or [string]$runtime.body_id -ne $bodyId) {
        throw "body identity differs across live evidence"
    }
    if ([string]$preflight.active_package_sha256 -ne $packageSha -or [string]$unityLive.package_sha256 -ne $packageSha -or [string]$runtime.package_sha256 -ne $packageSha) {
        throw "package identity differs across live evidence"
    }
    if (-not [bool]$unityLive.frame_applied -or -not [bool]$unityLive.renderer_bound -or -not [bool]$unityLive.bearer_auth_used) {
        throw "Unity live receipt does not prove authenticated applied frames"
    }

    $visualPath = Join-Path $EvidenceDir "live-visual-receipt.json"
    if (Test-Path -LiteralPath $visualPath) {
        throw "live visual receipt already exists; preserve it and use a new evidence directory for another observation"
    }

    $receipt = [ordered]@{
        schema = "bodyrig.unity_live_visual_acceptance/v0.1"
        accepted_at = [DateTimeOffset]::UtcNow.ToString("o")
        production_activation = $false
        visual_acceptance = $true
        pr_number = 846
        candidate_git_sha = $head
        rig_url = [string]$run.rig_url
        profile = [ordered]@{
            body_id = $bodyId
            package_sha256 = $packageSha
        }
        evidence_sha256 = [ordered]@{
            live_run = Get-Sha256 $runPath
            preflight = Get-Sha256 $preflightPath
            unity_live = Get-Sha256 $unityLivePath
            renderer_build = Get-Sha256 $buildPath
            renderer_runtime = Get-Sha256 $runtimePath
        }
        checks = [ordered]@{
            idle_listening_thinking_speaking_interrupted_are_visibly_distinct = $true
            gaze_blink_breath_are_visible = $true
            mouth_motion_tracks_live_speech_playback = $true
            interruption_immediately_neutralizes_mouth_and_gesture = $true
        }
        operator = [ordered]@{
            user = [Environment]::UserName
            machine = [Environment]::MachineName
            attestation = "directly observed during a real ModelRig conversation on the physical Windows renderer rig"
        }
    }

    $receipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $visualPath -Encoding UTF8
    Write-Host "BodyRig Unity LIVE visual acceptance recorded: $visualPath"
    Write-Host "Now run the independent live gate on the same exact SHA:"
    Write-Host "  python scripts/bodyrig_unity_live_physical_gate.py --expected-sha $head --evidence-dir `"$EvidenceDir`""
    Write-Output $EvidenceDir
}
finally {
    Pop-Location
}

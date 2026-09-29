[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedSha,
    [string]$HostReceipt = "",
    [switch]$AvatarVisibleAndStable,
    [switch]$PlacementMatchesTappedPlane,
    [switch]$CameraBackgroundTracksRoom,
    [switch]$BodyAnimationContinuesAfterPlacement,
    [switch]$NoVisibleCredentialOrDebugLeak
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$validationDir = Join-Path $repoRoot "validation"
if ([string]::IsNullOrWhiteSpace($HostReceipt)) {
    $HostReceipt = Join-Path $validationDir "kaliv-body-android-latest.json"
}
$HostReceipt = [System.IO.Path]::GetFullPath($HostReceipt)
$visualReceiptPath = Join-Path $validationDir "kaliv-body-android-visual-latest.json"

function Invoke-Git([string[]]$Arguments) {
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return @($output)
}

$actualSha = (Invoke-Git @("rev-parse", "HEAD"))[0].Trim().ToLowerInvariant()
$expected = $ExpectedSha.ToLowerInvariant()
if ($actualSha -ne $expected) {
    throw "Exact-head mismatch: expected $expected, checkout is $actualSha."
}
$dirty = @(Invoke-Git @("status", "--porcelain=v1", "--untracked-files=all"))
if ($dirty.Count -gt 0) {
    throw "Visual acceptance requires the exact clean candidate checkout."
}

if (-not (Test-Path -LiteralPath $HostReceipt -PathType Leaf)) {
    throw "Host qualification receipt is missing: $HostReceipt"
}
$hostRaw = [System.IO.File]::ReadAllBytes($HostReceipt)
$hostSha = [BitConverter]::ToString(
    [Security.Cryptography.SHA256]::Create().ComputeHash($hostRaw)
).Replace("-", "").ToLowerInvariant()
$host = Get-Content -LiteralPath $HostReceipt -Raw | ConvertFrom-Json

if ([string]$host.schema -ne "modelrig.kaliv-body.android-host-qualification/v1") {
    throw "Host receipt schema mismatch."
}
if ([string]$host.exact_head -ne $actualSha) {
    throw "Host receipt is not bound to current exact HEAD."
}
if ([bool]$host.production_activation -ne $false) {
    throw "Host receipt unexpectedly activated production."
}
if (-not [bool]$host.installed -or -not [bool]$host.launched) {
    throw "Host receipt does not prove physical install + launch."
}
if ([bool]$host.fatal_package_crash_observed) {
    throw "Host receipt contains a package-scoped fatal crash."
}
if (-not [bool]$host.arcore_runtime_qualified) {
    throw "ARCore runtime was not physically qualified."
}
if (-not [bool]$host.plane_placement_qualified) {
    throw "Detected-plane placement was not physically qualified."
}
if (-not [bool]$host.rig_link_qualified) {
    throw "Intent RigLink was not physically qualified."
}
if ([bool]$host.rig_link_token_leak_observed) {
    throw "Host receipt observed a RigLink token leak."
}
if (-not [bool]$host.avatar_from_rig_qualified) {
    throw "Digest-bound active avatar load was not physically qualified."
}
if (-not [bool]$host.live_frame_qualified) {
    throw "Authenticated live-frame application was not physically qualified."
}
if (-not [bool]$host.live_body_qualified) {
    throw "End-to-end live BodyRig was not physically qualified."
}

if (-not ($AvatarVisibleAndStable -and
          $PlacementMatchesTappedPlane -and
          $CameraBackgroundTracksRoom -and
          $BodyAnimationContinuesAfterPlacement -and
          $NoVisibleCredentialOrDebugLeak)) {
    throw "All five direct-observation switches are required; partial visual acceptance is forbidden."
}

New-Item -ItemType Directory -Force -Path $validationDir | Out-Null
$receipt = [ordered]@{
    schema = "modelrig.kaliv-body.android-visual-acceptance/v1"
    accepted_at = [DateTimeOffset]::UtcNow.ToString("o")
    exact_head = $actualSha
    host_receipt_path = $HostReceipt
    host_receipt_sha256 = $hostSha
    production_activation = $false
    release_gate_satisfied = $false
    visual_acceptance = $true
    prerequisites = [ordered]@{
        installed = [bool]$host.installed
        launched = [bool]$host.launched
        rig_link_qualified = [bool]$host.rig_link_qualified
        rig_link_token_leak_observed = [bool]$host.rig_link_token_leak_observed
        arcore_runtime_qualified = [bool]$host.arcore_runtime_qualified
        plane_placement_qualified = [bool]$host.plane_placement_qualified
        avatar_from_rig_qualified = [bool]$host.avatar_from_rig_qualified
        live_frame_qualified = [bool]$host.live_frame_qualified
        live_body_qualified = [bool]$host.live_body_qualified
    }
    checks = [ordered]@{
        avatar_visible_and_stable = $true
        placement_matches_tapped_plane = $true
        camera_background_tracks_room = $true
        body_animation_continues_after_placement = $true
        no_visible_credential_or_debug_leak = $true
    }
    operator = [ordered]@{
        user = [Environment]::UserName
        machine = [Environment]::MachineName
        attestation = "directly observed on the physical Android Kaliv Body host"
    }
}
$receipt | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $visualReceiptPath -Encoding utf8

Write-Host "Kaliv Body Android visual acceptance recorded: $visualReceiptPath"
Write-Host "Exact head: $actualSha"
Write-Host "Host receipt SHA-256: $hostSha"
Write-Host "Release gate and production activation remain FALSE."

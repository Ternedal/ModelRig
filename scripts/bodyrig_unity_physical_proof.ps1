param(
    [Parameter(Mandatory = $true)]
    [string]$Store,

    [string]$EvidenceDir = "",

    [string]$UnityExe = "C:\Program Files\Unity\Hub\Editor\6000.3.21f1\Editor\Unity.exe",

    [int]$RuntimeReceiptTimeoutSeconds = 90,

    [switch]$NoLaunch
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ExpectedUnity = "6000.3.21f1"
$ExpectedUniGltf = "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#v0.131.2"
$ExpectedUniVrm = "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#v0.131.2"
$RuntimeReceiptSchema = "bodyrig.unity_runtime_load/v0.1"
$BodyIdPattern = '^bodyid-[0-9a-f]{24}$'
$Sha256Pattern = '^[0-9a-f]{64}$'
$GitShaPattern = '^[0-9a-f]{40}$'

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
        throw "repository is not fully clean at $Stage; physical evidence is invalid:`n$status"
    }
}

function Get-Sha256 {
    param([Parameter(Mandatory = $true)][string]$Path)
    return ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant())
}

function Get-DefaultEvidenceDir {
    param([Parameter(Mandatory = $true)][string]$HeadSha)
    $base = $env:LOCALAPPDATA
    if ([string]::IsNullOrWhiteSpace($base)) {
        $base = $env:TEMP
    }
    if ([string]::IsNullOrWhiteSpace($base)) {
        throw "LOCALAPPDATA/TEMP is unavailable; pass -EvidenceDir explicitly"
    }
    return (Join-Path $base ("ModelRig\BodyRigEvidence\" + $HeadSha))
}

function Restore-Environment {
    param([hashtable]$Saved)
    foreach ($name in $Saved.Keys) {
        [Environment]::SetEnvironmentVariable($name, $Saved[$name], "Process")
    }
}

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw "BodyRig Unity physical proof must run on the physical Windows rig"
}
if ($RuntimeReceiptTimeoutSeconds -lt 5 -or $RuntimeReceiptTimeoutSeconds -gt 600) {
    throw "RuntimeReceiptTimeoutSeconds must be between 5 and 600"
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
Push-Location $RepoRoot
try {
    Assert-FullyClean "proof start"

    $head = Invoke-Git @("rev-parse", "HEAD")
    if ($head -notmatch $GitShaPattern) {
        throw "current HEAD is not a canonical git SHA"
    }
    $branch = Invoke-Git @("branch", "--show-current")
    # This once refused to run on main, because the renderer only existed on
    # the #720 draft and evidence had to attest the draft. #720 was merged on
    # 2/9 and the branch is gone, so the refusal now forbids exactly the right
    # thing. The substantive rule -- HEAD must not be behind origin/main --
    # is checked below and is what the evidence actually rests on.
    if ([string]::IsNullOrWhiteSpace($branch)) {
        $branch = "detached"
    }

    Invoke-Git @("fetch", "--quiet", "origin", "main") | Out-Null
    $mainBefore = Invoke-Git @("rev-parse", "origin/main")
    if ($mainBefore -notmatch $GitShaPattern) {
        throw "origin/main is not a canonical git SHA"
    }
    $behind = [int](Invoke-Git @("rev-list", "--count", ($head + "..origin/main")))
    if ($behind -ne 0) {
        throw "HEAD is behind origin/main; pull before collecting physical evidence"
    }

    $prepareScript = Join-Path $RepoRoot "scripts\bodyrig_prepare_renderer_profile.py"
    $handoffRaw = & python $prepareScript $Store 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "BodyRig renderer profile preparation failed: $($handoffRaw -join [Environment]::NewLine)"
    }
    $handoffText = ($handoffRaw -join "`n").Trim()
    try {
        $handoff = $handoffText | ConvertFrom-Json
    }
    catch {
        throw "renderer profile preparation did not return valid JSON"
    }

    $bodyId = [string]$handoff.body_id
    $packageSha = [string]$handoff.package_sha256
    $avatarSha = [string]$handoff.avatar_sha256
    $vrmPath = [IO.Path]::GetFullPath([string]$handoff.BODYRIG_VRM_PATH)
    if ($bodyId -notmatch $BodyIdPattern) { throw "handoff body_id is invalid" }
    if ($packageSha -notmatch $Sha256Pattern) { throw "handoff package SHA-256 is invalid" }
    if ($avatarSha -notmatch $Sha256Pattern) { throw "handoff avatar SHA-256 is invalid" }
    if (-not (Test-Path -LiteralPath $vrmPath -PathType Leaf)) {
        throw "digest-bound BODYRIG_VRM_PATH does not exist"
    }
    if ((Get-Sha256 $vrmPath) -ne $avatarSha) {
        throw "staged avatar SHA-256 no longer matches the validated handoff"
    }

    $projectDir = [IO.Path]::GetFullPath((Join-Path $RepoRoot "renderers\bodyrig-unity"))
    $projectVersionPath = Join-Path $projectDir "ProjectSettings\ProjectVersion.txt"
    # Unity's first import adds m_EditorVersionWithRevision beside the pin.
    # Comparing the whole file to a single line made the editor's own
    # bookkeeping look like a moved pin. #896 taught the gate and the contract
    # this; the proof was left comparing the old way, and it blocked the first
    # physical run right after the tree finally came clean. Same rule as the
    # gate: the version must be named, and no line may name a different one.
    $pinLines = @((Get-Content -LiteralPath $projectVersionPath) |
        ForEach-Object { $_.Trim() } | Where-Object { $_ })
    if ($pinLines -notcontains ("m_EditorVersion: " + $ExpectedUnity)) {
        throw "Unity project version pin is not $ExpectedUnity"
    }
    foreach ($line in $pinLines) {
        if ($line -notlike ("*" + $ExpectedUnity + "*")) {
            throw "Unity project version pin is not $ExpectedUnity"
        }
        if (-not ($line.StartsWith("m_EditorVersion:") -or
                  $line.StartsWith("m_EditorVersionWithRevision:"))) {
            throw "Unity project version file has unexpected content"
        }
    }

    $manifestPath = Join-Path $projectDir "Packages\manifest.json"
    $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
    $gltfPin = [string]$manifest.dependencies.PSObject.Properties["com.vrmc.gltf"].Value
    $vrmPin = [string]$manifest.dependencies.PSObject.Properties["com.vrmc.vrm"].Value
    if ($gltfPin -ne $ExpectedUniGltf -or $vrmPin -ne $ExpectedUniVrm) {
        throw "UniVRM package pins differ from the qualified renderer contract"
    }

    $UnityExe = [IO.Path]::GetFullPath($UnityExe)
    if (-not (Test-Path -LiteralPath $UnityExe -PathType Leaf)) {
        throw "Unity executable not found: $UnityExe"
    }
    $unityProductVersion = [string](Get-Item -LiteralPath $UnityExe).VersionInfo.ProductVersion
    if ([string]::IsNullOrWhiteSpace($unityProductVersion) -or $unityProductVersion -notmatch '^6000\.3\.21') {
        throw "Unity executable product version does not match the pinned 6000.3.21 baseline: $unityProductVersion"
    }

    if ([string]::IsNullOrWhiteSpace($EvidenceDir)) {
        $EvidenceDir = Get-DefaultEvidenceDir $head
    }
    $EvidenceDir = [IO.Path]::GetFullPath($EvidenceDir)
    if (Test-Path -LiteralPath $EvidenceDir) {
        $existing = @(Get-ChildItem -LiteralPath $EvidenceDir -Force)
        if ($existing.Count -ne 0) {
            throw "evidence directory is not empty; choose a new -EvidenceDir or preserve the previous run"
        }
    }
    else {
        New-Item -ItemType Directory -Path $EvidenceDir -Force | Out-Null
    }

    $buildDir = Join-Path $EvidenceDir "build"
    $unityLog = Join-Path $EvidenceDir "unity-build.log"
    $runtimeReceiptPath = Join-Path $EvidenceDir "runtime-receipt.json"
    New-Item -ItemType Directory -Path $buildDir -Force | Out-Null

    $savedBuildEnvironment = @{
        BODYRIG_VRM_PATH = [Environment]::GetEnvironmentVariable("BODYRIG_VRM_PATH", "Process")
        BODYRIG_BUILD_DIR = [Environment]::GetEnvironmentVariable("BODYRIG_BUILD_DIR", "Process")
    }
    try {
        $env:BODYRIG_VRM_PATH = $vrmPath
        $env:BODYRIG_BUILD_DIR = $buildDir
        & $UnityExe `
            -batchmode -quit `
            -projectPath $projectDir `
            -executeMethod ModelRig.BodyRig.UnityRenderer.Editor.BodyRigBuild.BuildWindows `
            -logFile $unityLog
        $unityExit = $LASTEXITCODE
    }
    finally {
        Restore-Environment $savedBuildEnvironment
    }
    if ($unityExit -ne 0) {
        throw "Unity batch build failed with exit code $unityExit; inspect $unityLog"
    }

    $exePath = Join-Path $buildDir "BodyRigRendererProof.exe"
    # Unity exits before Windows makes the player visible. Measured on the rig
    # 6/9: the build log said "Build Finished, Result: Success", Test-Path said
    # missing, and a listing seconds later showed the same 667 KB exe sitting
    # there. Defender scans a fresh unsigned binary and a 36 MB UnityPlayer.dll
    # before releasing them. Judging on the first attempt turned a good build
    # into a failed proof; wait for it, and still fail if it never arrives.
    $exeDeadline = (Get-Date).AddSeconds(90)
    while (-not (Test-Path -LiteralPath $exePath -PathType Leaf) -and (Get-Date) -lt $exeDeadline) {
        Start-Sleep -Milliseconds 500
    }
    if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "Unity reported success but BodyRigRendererProof.exe never appeared in $buildDir"
    }
    $exeInfo = Get-Item -LiteralPath $exePath
    if ($exeInfo.Length -le 0) { throw "built renderer executable is empty" }
    if (-not (Test-Path -LiteralPath $unityLog -PathType Leaf)) { throw "Unity build log is missing" }

    $headAfterBuild = Invoke-Git @("rev-parse", "HEAD")
    if ($headAfterBuild -ne $head) {
        throw "draft HEAD moved during physical build; discard this run"
    }
    Assert-FullyClean "after Unity batch build"

    Invoke-Git @("fetch", "--quiet", "origin", "main") | Out-Null
    $mainAfterBuild = Invoke-Git @("rev-parse", "origin/main")
    if ($mainAfterBuild -ne $mainBefore) {
        throw "origin/main moved during physical build; discard this run and rebind #720"
    }
    $behindAfter = [int](Invoke-Git @("rev-list", "--count", ($head + "..origin/main")))
    if ($behindAfter -ne 0) {
        throw "#720 became behind origin/main during physical build"
    }

    if ((Get-Sha256 $vrmPath) -ne $avatarSha) {
        throw "digest-bound staged avatar changed during physical build"
    }

    $launched = $false
    $runtimeLoadVerified = $false
    $rendererProcess = $null
    if (-not $NoLaunch) {
        $runtimeEnvironmentNames = @(
            "BODYRIG_VRM_PATH",
            "BODYRIG_RUNTIME_RECEIPT",
            "BODYRIG_CANDIDATE_SHA",
            "BODYRIG_BODY_ID",
            "BODYRIG_PACKAGE_SHA256",
            "BODYRIG_AVATAR_SHA256"
        )
        $savedRuntimeEnvironment = @{}
        foreach ($name in $runtimeEnvironmentNames) {
            $savedRuntimeEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
        }
        try {
            $env:BODYRIG_VRM_PATH = $vrmPath
            $env:BODYRIG_RUNTIME_RECEIPT = $runtimeReceiptPath
            $env:BODYRIG_CANDIDATE_SHA = $head
            $env:BODYRIG_BODY_ID = $bodyId
            $env:BODYRIG_PACKAGE_SHA256 = $packageSha
            $env:BODYRIG_AVATAR_SHA256 = $avatarSha
            $rendererProcess = Start-Process -FilePath $exePath -WorkingDirectory $buildDir -PassThru
            $launched = $true
        }
        finally {
            Restore-Environment $savedRuntimeEnvironment
        }

        $deadline = [DateTimeOffset]::UtcNow.AddSeconds($RuntimeReceiptTimeoutSeconds)
        while (-not (Test-Path -LiteralPath $runtimeReceiptPath -PathType Leaf)) {
            if ([DateTimeOffset]::UtcNow -ge $deadline) {
                if ($null -ne $rendererProcess -and -not $rendererProcess.HasExited) {
                    Stop-Process -Id $rendererProcess.Id -Force -ErrorAction SilentlyContinue
                }
                throw "renderer did not produce a runtime VRM-load receipt within $RuntimeReceiptTimeoutSeconds seconds"
            }
            if ($null -ne $rendererProcess) {
                $rendererProcess.Refresh()
                if ($rendererProcess.HasExited) {
                    throw "renderer exited before proving VRM load/bind; exit code $($rendererProcess.ExitCode)"
                }
            }
            Start-Sleep -Milliseconds 250
        }

        try {
            $runtime = Get-Content -LiteralPath $runtimeReceiptPath -Raw | ConvertFrom-Json
        }
        catch {
            throw "runtime receipt is not valid JSON"
        }
        if ([string]$runtime.schema -ne $RuntimeReceiptSchema) { throw "runtime receipt schema mismatch" }
        if ([bool]$runtime.production_activation -ne $false) { throw "runtime receipt unexpectedly activated production" }
        if ([bool]$runtime.visual_acceptance -ne $false) { throw "runtime receipt must not assert visual acceptance" }
        if (-not [bool]$runtime.vrm_loaded -or -not [bool]$runtime.renderer_bound) {
            throw "runtime receipt does not prove both VRM load and renderer bind"
        }
        if ([string]$runtime.candidate_git_sha -ne $head) { throw "runtime receipt candidate SHA mismatch" }
        if ([string]$runtime.body_id -ne $bodyId) { throw "runtime receipt body_id mismatch" }
        if ([string]$runtime.package_sha256 -ne $packageSha) { throw "runtime receipt package SHA mismatch" }
        if ([string]$runtime.avatar_sha256 -ne $avatarSha) { throw "runtime receipt avatar SHA mismatch" }
        if ([string]$runtime.unity_version -notmatch '^6000\.3\.21') { throw "runtime Unity version mismatch" }
        if ([IO.Path]::GetFullPath([string]$runtime.vrm_path) -ne $vrmPath) { throw "runtime receipt VRM path mismatch" }
        $runtimeLoadVerified = $true
    }

    if ((Get-Sha256 $vrmPath) -ne $avatarSha) {
        throw "digest-bound staged avatar changed after runtime load"
    }
    $headAfterRuntime = Invoke-Git @("rev-parse", "HEAD")
    if ($headAfterRuntime -ne $head) {
        throw "draft HEAD moved during runtime proof; discard this run"
    }
    Assert-FullyClean "after renderer runtime proof"

    Invoke-Git @("fetch", "--quiet", "origin", "main") | Out-Null
    $mainAfterRuntime = Invoke-Git @("rev-parse", "origin/main")
    if ($mainAfterRuntime -ne $mainBefore) {
        throw "origin/main moved during runtime proof; discard this run and rebind #720"
    }
    $behindAfterRuntime = [int](Invoke-Git @("rev-list", "--count", ($head + "..origin/main")))
    if ($behindAfterRuntime -ne 0) {
        throw "#720 became behind origin/main during runtime proof"
    }

    $receipt = [ordered]@{
        schema = "bodyrig.unity_physical_build/v0.2"
        created_at = [DateTimeOffset]::UtcNow.ToString("o")
        production_activation = $false
        visual_acceptance = $false
        pr_number = 720
        candidate = [ordered]@{
            git_sha = $head
            branch = $branch
            origin_main_sha = $mainBefore
            origin_main_stable_during_build = $true
            origin_main_stable_through_runtime = $true
            clean_checkout_before_build = $true
            working_tree_clean_after_runtime = $true
        }
        profile = [ordered]@{
            body_id = $bodyId
            package_sha256 = $packageSha
            avatar_sha256 = $avatarSha
            vrm_path = $vrmPath
        }
        renderer = [ordered]@{
            unity_project_version = $ExpectedUnity
            unity_exe = $UnityExe
            unity_product_version = $unityProductVersion
            univrm_gltf = $gltfPin
            univrm_vrm = $vrmPin
        }
        build = [ordered]@{
            success = $true
            exit_code = 0
            launched = $launched
            runtime_load_verified = $runtimeLoadVerified
        }
        artifacts = [ordered]@{
            executable = [ordered]@{
                path = [IO.Path]::GetFullPath($exePath)
                bytes = [int64]$exeInfo.Length
                sha256 = Get-Sha256 $exePath
            }
            unity_log = [ordered]@{
                path = [IO.Path]::GetFullPath($unityLog)
                bytes = [int64](Get-Item -LiteralPath $unityLog).Length
                sha256 = Get-Sha256 $unityLog
            }
            runtime_receipt = if ($runtimeLoadVerified) {
                [ordered]@{
                    path = [IO.Path]::GetFullPath($runtimeReceiptPath)
                    bytes = [int64](Get-Item -LiteralPath $runtimeReceiptPath).Length
                    sha256 = Get-Sha256 $runtimeReceiptPath
                }
            } else { $null }
        }
    }

    $receiptPath = Join-Path $EvidenceDir "build-receipt.json"
    $receipt | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Write-Host "BodyRig Unity physical build receipt: $receiptPath"
    if ($runtimeLoadVerified) {
        Write-Host "Renderer runtime independently confirmed VRM load + renderer bind. Observe the full deterministic sequence before recording visual acceptance."
    }
    else {
        Write-Host "Renderer was not launched (-NoLaunch); runtime load and visual acceptance are intentionally unproven."
    }
    Write-Output $EvidenceDir
}
finally {
    Pop-Location
}

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string]$ExpectedSha,
    [string]$UnityPath = "",
    [switch]$Install,
    [switch]$Launch,
    [ValidateRange(2, 60)]
    [int]$LaunchEvidenceSeconds = 8
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$projectPath = Join-Path $repoRoot "vr"
$validationDir = Join-Path $repoRoot "validation"
$receiptPath = Join-Path $validationDir "kaliv-vr-quest-latest.json"
$logPath = Join-Path $validationDir "kaliv-vr-unity-build.log"
$logcatPath = Join-Path $validationDir "kaliv-vr-quest-logcat.txt"
$apkPath = Join-Path $projectPath "release\output\KalivVR-dev.apk"
$appId = "dk.ternedal.kalivvr"
$requiredUnity = "6000.4.10f1"

function Invoke-Git([string[]]$Arguments) {
    $output = & git -C $repoRoot @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed: $($output -join [Environment]::NewLine)"
    }
    return @($output)
}

function Assert-CleanTree {
    $dirty = @(Invoke-Git @("status", "--porcelain=v1", "--untracked-files=all"))
    if ($dirty.Count -gt 0) {
        throw ("Exact-head qualification requires a clean checkout. Dirty paths:" + [Environment]::NewLine + ($dirty -join [Environment]::NewLine))
    }
}

function Resolve-Unity {
    if (-not [string]::IsNullOrWhiteSpace($UnityPath)) {
        $candidate = [System.IO.Path]::GetFullPath($UnityPath)
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "Unity executable not found: $candidate"
        }
        return $candidate
    }

    $candidates = @(
        "C:\Program Files\Unity\Hub\Editor\$requiredUnity\Editor\Unity.exe",
        "C:\Program Files\Unity Hub\Editor\$requiredUnity\Editor\Unity.exe"
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw ("Unity $requiredUnity was not found in the standard Hub location. " +
           "Install that exact editor with Android Build Support or pass -UnityPath.")
}

function Resolve-Adb([string]$UnityExe) {
    $candidates = [System.Collections.Generic.List[string]]::new()
    foreach ($root in @($env:ANDROID_SDK_ROOT, $env:ANDROID_HOME)) {
        if (-not [string]::IsNullOrWhiteSpace($root)) {
            $candidates.Add((Join-Path $root "platform-tools\adb.exe"))
        }
    }
    $editorRoot = Split-Path -Parent (Split-Path -Parent $UnityExe)
    $candidates.Add((Join-Path $editorRoot "Editor\Data\PlaybackEngines\AndroidPlayer\SDK\platform-tools\adb.exe"))
    $onPath = Get-Command adb -ErrorAction SilentlyContinue
    if ($null -ne $onPath) { $candidates.Add($onPath.Source) }
    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and
            (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return [System.IO.Path]::GetFullPath($candidate)
        }
    }
    throw "ADB was not found (ANDROID_SDK_ROOT / ANDROID_HOME / Unity Android SDK / PATH)."
}

function Get-SingleAdbDevice([string]$Adb) {
    $lines = & $Adb devices
    if ($LASTEXITCODE -ne 0) { throw "adb devices failed." }
    $devices = @(
        $lines | Select-Object -Skip 1 | ForEach-Object { $_.Trim() } |
            Where-Object { $_ -match "\tdevice$" } |
            ForEach-Object { ($_ -split "\t")[0] }
    )
    if ($devices.Count -ne 1) {
        throw "Expected exactly one authorized ADB device; found $($devices.Count)."
    }
    return $devices[0]
}

New-Item -ItemType Directory -Force -Path $validationDir | Out-Null

$actualSha = (Invoke-Git @("rev-parse", "HEAD"))[0].Trim().ToLowerInvariant()
$expected = $ExpectedSha.ToLowerInvariant()
if ($actualSha -ne $expected) {
    throw "Exact-head mismatch: expected $expected, checkout is $actualSha."
}

Write-Host "Exact head: $actualSha"
Assert-CleanTree

$unity = Resolve-Unity
$projectVersion = (Get-Content -LiteralPath (Join-Path $projectPath "ProjectSettings\ProjectVersion.txt") -Raw).Trim()
if ($projectVersion -notmatch [regex]::Escape($requiredUnity)) {
    throw "ProjectVersion.txt does not pin required Unity ${requiredUnity}: $projectVersion"
}

if (Test-Path -LiteralPath $logPath) { Remove-Item -LiteralPath $logPath -Force }
if (Test-Path -LiteralPath $apkPath) { Remove-Item -LiteralPath $apkPath -Force }

Write-Host "[1/4] Unity package restore + C# compile + Android IL2CPP build"
$unityArgs = @(
    "-batchmode",
    "-nographics",
    "-quit",
    "-projectPath", $projectPath,
    "-buildTarget", "Android",
    "-executeMethod", "Kaliv.VR.EditorTools.KalivVrBuild.BuildAndroid",
    "-logFile", $logPath
)
& $unity @unityArgs
$unityExit = $LASTEXITCODE
if ($unityExit -ne 0) {
    throw "Unity build failed with exit code $unityExit. Log: $logPath"
}
if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
    throw "Unity exited successfully but APK is missing: $apkPath"
}

Write-Host "[2/4] Verify exact checkout stayed clean"
Assert-CleanTree

$apk = Get-Item -LiteralPath $apkPath
$apkSha = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
$adb = $null
$device = $null
$installed = $false
$launched = $false
$appPid = $null
$deviceModel = $null
$androidVersion = $null
$passthroughInjectionObserved = $false
$rendererLogObserved = $false

if ($Install -or $Launch) {
    Write-Host "[3/4] ADB device + install"
    $adb = Resolve-Adb $unity
    $device = Get-SingleAdbDevice $adb
    & $adb -s $device install -r $apkPath
    if ($LASTEXITCODE -ne 0) { throw "ADB install failed for device $device." }
    $installed = $true
    if ($Launch) {
        & $adb -s $device logcat -c
        if ($LASTEXITCODE -ne 0) { throw "Failed to clear device logcat before launch." }

        $deviceModel = (& $adb -s $device shell getprop ro.product.model 2>$null | Out-String).Trim()
        $androidVersion = (& $adb -s $device shell getprop ro.build.version.release 2>$null | Out-String).Trim()

        & $adb -s $device shell monkey -p $appId -c android.intent.category.LAUNCHER 1 | Out-Host
        if ($LASTEXITCODE -ne 0) { throw "APK installed but launch failed on device $device." }
        $launched = $true

        Start-Sleep -Seconds $LaunchEvidenceSeconds

        $pidText = (& $adb -s $device shell pidof $appId 2>$null | Out-String).Trim()
        if ([string]::IsNullOrWhiteSpace($pidText)) {
            throw "Kaliv VR launch command returned success, but no running app process was observed."
        }
        $appPid = $pidText

        $logcat = & $adb -s $device logcat -d -v threadtime 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Failed to capture device logcat after launch." }
        $logcatText = ($logcat -join [Environment]::NewLine)
        $logcatText | Set-Content -LiteralPath $logcatPath -Encoding utf8

        $passthroughInjectionObserved =
            $logcatText.Contains("[Passthrough] xrEndFrame underlay injecting OK")
        $rendererLogObserved =
            $logcatText.Contains("[KalivVR.Render]") -or
            $logcatText.Contains("[KalivVR.Perf]") -or
            $logcatText.Contains("[KalivVR.XR]")

        Write-Host "Device: $deviceModel (Android $androidVersion)"
        Write-Host "Kaliv VR PID: $appPid"
        Write-Host "Renderer log observed: $rendererLogObserved"
        Write-Host "Passthrough xrEndFrame injection observed: $passthroughInjectionObserved"
        Write-Host "Logcat: $logcatPath"
    }
} else {
    Write-Host "[3/4] ADB install skipped (use -Install or -Launch)"
}

$receipt = [ordered]@{
    schema = "modelrig.kaliv-vr.quest-qualification/v1"
    timestamp_utc = [DateTime]::UtcNow.ToString("o")
    exact_head = $actualSha
    unity_required = $requiredUnity
    unity_executable = $unity
    project_version = $projectVersion
    build_exit_code = $unityExit
    apk_path = $apk.FullName
    apk_size_bytes = $apk.Length
    apk_sha256 = $apkSha
    checkout_clean_after_build = $true
    adb_device = $device
    adb_device_model = $deviceModel
    android_version = $androidVersion
    installed = $installed
    launched = $launched
    app_pid = $appPid
    logcat_path = if ($launched) { $logcatPath } else { $null }
    renderer_log_observed = $rendererLogObserved
    passthrough_injection_observed = $passthroughInjectionObserved
    physical_acceptance = $false
    physical_acceptance_note = "Set only after in-headset checklist is manually observed."
}
$receipt | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $receiptPath -Encoding utf8

Write-Host "[4/4] BUILD PASS"
Write-Host "APK: $apkPath"
Write-Host "APK SHA-256: $apkSha"
Write-Host "Receipt: $receiptPath"
if ($Install -or $Launch) {
    Write-Host "ADB device: $device (installed=$installed, launched=$launched)"
}
if ($Launch) {
    Write-Host "Launch evidence: pid=$appPid, renderer_log=$rendererLogObserved, passthrough_injection=$passthroughInjectionObserved"
}
Write-Host "Physical headset acceptance remains FALSE until the in-headset checklist is observed."

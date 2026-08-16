[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "validation\stage-a-runtime\physical-candidate-app"
$receiptPath = Join-Path $runtimeDir "receipt.json"
$apkPath = Join-Path $runtimeDir "kaliv-physical-candidate.apk"
$installReceiptPath = Join-Path $runtimeDir "install-receipt.json"
$repo = "Ternedal/ModelRig"
$workflow = "agent4-a4-25f-harness.yml"
$physicalPackage = "dk.ternedal.modelrig.a425f"
$normalPackage = "dk.ternedal.modelrig"

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Executable,
        [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments
    )
    $previousErrorActionPreference = $ErrorActionPreference
    $text = ""
    $code = -1
    try {
        $ErrorActionPreference = "Continue"
        $text = (& $Executable @Arguments 2>&1 | ForEach-Object { "$_" }) -join "`n"
        $code = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($code -ne 0) {
        throw "Kommando fejlede ($code): $Executable $($Arguments -join ' ')`n$text"
    }
    return $text.Trim()
}

function Resolve-CommandPath {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace([string]$command.Source)) {
            return [string]$command.Source
        }
    }
    return $null
}

function Resolve-Adb {
    $fromPath = Resolve-CommandPath -Names @("adb.exe", "adb")
    if ($fromPath) { return $fromPath }

    $roots = @()
    if (-not [string]::IsNullOrWhiteSpace($env:ANDROID_HOME)) { $roots += $env:ANDROID_HOME }
    if (-not [string]::IsNullOrWhiteSpace($env:ANDROID_SDK_ROOT)) { $roots += $env:ANDROID_SDK_ROOT }
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $roots += (Join-Path $env:LOCALAPPDATA "Android\Sdk")
    }
    foreach ($root in $roots | Select-Object -Unique) {
        $candidate = Join-Path $root "platform-tools\adb.exe"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw "ADB blev ikke fundet. Installér Android Platform Tools eller Android Studio, tilslut telefonen med USB-fejlfinding, og kør proof-launcheren igen."
}

function Get-PackageVersion {
    param(
        [string]$Adb,
        [string]$Serial,
        [string]$Package
    )
    $text = Invoke-Native $Adb @("-s", $Serial, "shell", "dumpsys", "package", $Package)
    $match = [regex]::Match($text, "\bversionName=([^\s]+)")
    if (-not $match.Success) { return $null }
    return [string]$match.Groups[1].Value
}

if ($env:OS -ne "Windows_NT") {
    throw "Den fysiske Android-bootstrap må kun køres på Windows-riggen."
}

$version = (Get-Content -LiteralPath (Join-Path $repoRoot "VERSION") -Raw).Trim()
if ([string]::IsNullOrWhiteSpace($version)) { throw "VERSION er tom." }
$expectedAppVersion = "$version-a425f"
$sha = (Invoke-Native "git.exe" @("-C", $repoRoot, "rev-parse", "HEAD")).Trim()
if ($sha -notmatch "^[0-9a-f]{40}$") { throw "Git HEAD er ikke en gyldig SHA." }
$dirty = Invoke-Native "git.exe" @("-C", $repoRoot, "status", "--porcelain")
if (-not [string]::IsNullOrWhiteSpace($dirty)) {
    throw "Working tree er ikke ren; kandidatappen må kun bootstrappe fra exact HEAD."
}

$gh = Resolve-CommandPath -Names @("gh.exe", "gh")
if (-not $gh) { throw "GitHub CLI (gh) blev ikke fundet på PATH." }
$adb = Resolve-Adb
$adbDir = Split-Path -Parent $adb
if (-not (($env:PATH -split ";") -contains $adbDir)) {
    $env:PATH = "$adbDir;$env:PATH"
}

$devicesText = Invoke-Native $adb @("devices")
$authorized = @()
$unauthorized = @()
foreach ($line in ($devicesText -split "`r?`n")) {
    if ($line -match "^([^\s]+)\s+device$") { $authorized += $Matches[1] }
    elseif ($line -match "^([^\s]+)\s+unauthorized$") { $unauthorized += $Matches[1] }
}
if ($authorized.Count -eq 0) {
    if ($unauthorized.Count -gt 0) {
        throw "Telefonen ses af ADB, men er ikke godkendt. Godkend dialogen 'Tillad USB-fejlfinding' på telefonen og kør launcheren igen."
    }
    throw "Ingen ADB-godkendt telefon fundet. Tilslut telefonen med USB, slå USB-fejlfinding til, og kør launcheren igen."
}
if ($authorized.Count -ne 1) {
    throw "Der er $($authorized.Count) ADB-godkendte enheder. Proof-flowet kræver præcis én telefon for entydig fysisk evidens."
}
$serial = [string]$authorized[0]

$normalBefore = Get-PackageVersion -Adb $adb -Serial $serial -Package $normalPackage
$physicalBefore = Get-PackageVersion -Adb $adb -Serial $serial -Package $physicalPackage
if ($physicalBefore -eq $expectedAppVersion) {
    Write-Host "  Exact fysisk kandidatapp er allerede installeret: $expectedAppVersion" -ForegroundColor Green
}
else {
    $runJson = Invoke-Native $gh @(
        "run", "list",
        "--repo", $repo,
        "--workflow", $workflow,
        "--commit", $sha,
        "--status", "success",
        "--json", "databaseId,headSha,conclusion",
        "--limit", "20"
    )
    $runs = @($runJson | ConvertFrom-Json)
    $run = $runs |
        Where-Object { [string]$_.headSha -eq $sha -and [string]$_.conclusion -eq "success" } |
        Select-Object -First 1
    if ($null -eq $run) {
        throw "Der findes endnu ingen grøn exact-SHA $workflow-kørsel for $sha. Android-kandidatappen må ikke bygges eller gættes lokalt."
    }

    $artifactName = "kaliv-physical-candidate-$sha"
    $needsDownload = $true
    if ((Test-Path -LiteralPath $receiptPath -PathType Leaf) -and (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
        try {
            $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
            $actualHash = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
            $needsDownload = -not (
                [string]$receipt.schema -eq "kaliv-physical-candidate-apk/v1" -and
                [string]$receipt.git_sha -eq $sha -and
                [string]$receipt.candidate_version -eq $version -and
                [string]$receipt.app_version -eq $expectedAppVersion -and
                [string]$receipt.package -eq $physicalPackage -and
                [string]$receipt.sha256 -eq $actualHash
            )
        }
        catch {
            $needsDownload = $true
        }
    }

    if ($needsDownload) {
        if (Test-Path -LiteralPath $runtimeDir) {
            Remove-Item -LiteralPath $runtimeDir -Recurse -Force
        }
        New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
        Write-Host "  Henter exact-head fysisk Android-app fra grøn CI..." -ForegroundColor Cyan
        [void](Invoke-Native $gh @(
            "run", "download", ([string]$run.databaseId),
            "--repo", $repo,
            "--name", $artifactName,
            "--dir", $runtimeDir
        ))
    }

    if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf) -or
        -not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
        throw "CI-artifactet mangler receipt.json eller kaliv-physical-candidate.apk."
    }
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
    $actualHash = (Get-FileHash -LiteralPath $apkPath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ([string]$receipt.schema -ne "kaliv-physical-candidate-apk/v1" -or
        [string]$receipt.git_sha -ne $sha -or
        [string]$receipt.candidate_version -ne $version -or
        [string]$receipt.app_version -ne $expectedAppVersion -or
        [string]$receipt.package -ne $physicalPackage -or
        [string]$receipt.sha256 -ne $actualHash) {
        throw "Det downloadede Android-artifact matcher ikke exact kandidat-SHA/version/package/hash."
    }

    Write-Host "  Installerer isoleret $expectedAppVersion ved siden af normal Kaliv..." -ForegroundColor Cyan
    $installOutput = Invoke-Native $adb @("-s", $serial, "install", "-r", $apkPath)
    if ($installOutput -notmatch "(?im)\bSuccess\b") {
        throw "ADB rapporterede ikke Success ved installation: $installOutput"
    }
}

$physicalAfter = Get-PackageVersion -Adb $adb -Serial $serial -Package $physicalPackage
if ($physicalAfter -ne $expectedAppVersion) {
    throw "Fysisk kandidatapp verificerede som '$physicalAfter', forventede '$expectedAppVersion'."
}
$normalAfter = Get-PackageVersion -Adb $adb -Serial $serial -Package $normalPackage
if ($normalBefore -and $normalAfter -ne $normalBefore) {
    throw "Normal Kaliv ændrede version under fysisk bootstrap ($normalBefore -> $normalAfter); stopper fail-closed."
}

$model = Invoke-Native $adb @("-s", $serial, "shell", "getprop", "ro.product.model")
[void](Invoke-Native $adb @(
    "-s", $serial,
    "shell", "monkey",
    "-p", $physicalPackage,
    "-c", "android.intent.category.LAUNCHER",
    "1"
))

$serialHashBytes = [Text.Encoding]::UTF8.GetBytes($serial)
$sha256 = [Security.Cryptography.SHA256]::Create()
try {
    $serialHash = ([BitConverter]::ToString($sha256.ComputeHash($serialHashBytes))).Replace("-", "").ToLowerInvariant()
}
finally {
    $sha256.Dispose()
}
$installReceipt = [ordered]@{
    schema = "kaliv-stage-a-physical-app-install/v1"
    verified_at = (Get-Date).ToUniversalTime().ToString("o")
    git_sha = $sha
    candidate_version = $version
    package = $physicalPackage
    app_version = $physicalAfter
    model = $model
    adb_serial_sha256 = $serialHash
    normal_package = $normalPackage
    normal_version_before = $normalBefore
    normal_version_after = $normalAfter
    production_activation = $false
}
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
$installReceipt | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $installReceiptPath -Encoding UTF8

Write-Host "  OK: fysisk kandidatapp $expectedAppVersion er ADB-verificeret på $model." -ForegroundColor Green
if ($normalAfter) {
    Write-Host "  Normal Kaliv er stadig $normalAfter og blev ikke overskrevet." -ForegroundColor Green
}
Write-Host "  Den isolerede kandidatapp er åbnet; brug DEN til pairing-vinduet." -ForegroundColor Yellow

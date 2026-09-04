# New Windows rig bootstrap for ModelRig + VoiceRig + BodyRig.
# Safe to re-run. This file is intentionally ASCII-only for Windows PowerShell 5.1.

[CmdletBinding()]
param(
    [ValidateSet("Base", "Core", "BodyRig", "Validate", "All")]
    [string]$Phase = "All",

    [string]$InstallRoot = "C:\Rig",
    [string]$ConfigPath = "",
    [string]$BodyRigRef = "76c64a9546238663dedf750a1da4a230cc1e7fa4",
    [string]$WslDistribution = "Ubuntu-22.04",
    [string]$SmplModelPath = "",
    [string]$SmplxSource = "",
    [string]$DiffusionModel = "",
    [string[]]$OllamaModels = @(),
    [int]$MinimumGpuCount = 1,

    [switch]$SkipModelPulls,
    [switch]$SkipVoiceRigWarmup,
    [switch]$SkipAutostart,
    [switch]$SkipBodyRig,
    [switch]$SkipDevTools
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$script:CliBoundParameters = @{}
foreach ($entry in $PSBoundParameters.GetEnumerator()) { $script:CliBoundParameters[$entry.Key] = $entry.Value }
$script:Results = [System.Collections.Generic.List[object]]::new()
$script:RebootRequired = $false
$script:TranscriptStarted = $false

function Add-Result {
    param(
        [Parameter(Mandatory = $true)][string]$Step,
        [Parameter(Mandatory = $true)][ValidateSet("PASS", "WARN", "BLOCKED", "FAIL")][string]$Status,
        [string]$Detail = ""
    )
    $script:Results.Add([pscustomobject]@{
        step = $Step
        status = $Status
        detail = $Detail
    })
    $color = switch ($Status) {
        "PASS" { "Green" }
        "WARN" { "Yellow" }
        "BLOCKED" { "Yellow" }
        "FAIL" { "Red" }
    }
    Write-Host ("[{0}] {1}: {2}" -f $Status, $Step, $Detail) -ForegroundColor $color
}

function Write-Section {
    param([string]$Name)
    Write-Host ""
    Write-Host ("== {0} ==" -f $Name) -ForegroundColor Cyan
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Refresh-ProcessPath {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = @($machine, $user, $env:Path) -join ";"
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [string]$Step = $FilePath,
        [int[]]$AllowedExitCodes = @(0)
    )
    & $FilePath @Arguments
    $code = $LASTEXITCODE
    if ($AllowedExitCodes -notcontains $code) {
        throw "$Step failed with exit code $code"
    }
}

function Invoke-PowerShellScript {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [object[]]$Arguments = @(),
        [string]$Step = $Path
    )
    $hostExe = (Get-Command powershell.exe -ErrorAction Stop).Source
    $args = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $Path) + $Arguments
    Invoke-Native -FilePath $hostExe -Arguments $args -Step $Step
}

function Apply-Config {
    if ([string]::IsNullOrWhiteSpace($script:ConfigPath)) {
        $candidate = Join-Path $PSScriptRoot "bootstrap-new-rig.config.psd1"
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $script:ConfigPath = $candidate
        }
    }

    if ([string]::IsNullOrWhiteSpace($script:ConfigPath)) {
        return
    }
    if (-not (Test-Path -LiteralPath $script:ConfigPath -PathType Leaf)) {
        throw "Config file not found: $script:ConfigPath"
    }

    $cfg = Import-PowerShellDataFile -Path $script:ConfigPath
    $pairs = @(
        @("InstallRoot", "InstallRoot"),
        @("BodyRigRef", "BodyRigRef"),
        @("WslDistribution", "WslDistribution"),
        @("SmplModelPath", "SmplModelPath"),
        @("SmplxSource", "SmplxSource"),
        @("DiffusionModel", "DiffusionModel"),
        @("MinimumGpuCount", "MinimumGpuCount")
    )
    foreach ($pair in $pairs) {
        $key = $pair[0]
        $variableName = $pair[1]
        if ($cfg.ContainsKey($key) -and -not $script:CliBoundParameters.ContainsKey($key)) {
            Set-Variable -Name $variableName -Value $cfg[$key] -Scope Script
        }
    }
    if ($cfg.ContainsKey("OllamaModels") -and -not $script:CliBoundParameters.ContainsKey("OllamaModels")) {
        $script:OllamaModels = @($cfg.OllamaModels)
    }
}

function Ensure-WingetPackage {
    param(
        [Parameter(Mandatory = $true)][string]$Id,
        [Parameter(Mandatory = $true)][string]$Name,
        [switch]$Optional
    )
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw "Windows Package Manager (winget) is missing. Install App Installer and re-run."
    }

    & $winget.Source list --id $Id -e --source winget --accept-source-agreements *> $null
    if ($LASTEXITCODE -eq 0) {
        Add-Result -Step "package:$Name" -Status PASS -Detail "already installed"
        return
    }

    Write-Host "Installing $Name ($Id)..."
    & $winget.Source install --id $Id -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -ne 0) {
        if ($Optional) {
            Add-Result -Step "package:$Name" -Status WARN -Detail "winget install failed; install manually if needed"
            return
        }
        throw "winget could not install $Name ($Id)"
    }
    Refresh-ProcessPath
    Add-Result -Step "package:$Name" -Status PASS -Detail "installed"
}

function Test-GitDirty {
    param([string]$Path)
    $output = & git -C $Path status --porcelain
    return -not [string]::IsNullOrWhiteSpace(($output -join "`n"))
}

function Ensure-GitCheckout {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Url,
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Ref,
        [switch]$Pinned
    )

    if (-not (Test-Path -LiteralPath (Join-Path $Path ".git") -PathType Container)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $Path) -Force | Out-Null
        Invoke-Native -FilePath "git" -Arguments @("clone", $Url, $Path) -Step "clone $Name"
    }

    if (Test-GitDirty -Path $Path) {
        throw "$Name checkout has local changes: $Path. Commit/stash them before bootstrap updates it."
    }

    Invoke-Native -FilePath "git" -Arguments @("-C", $Path, "remote", "set-url", "origin", $Url) -Step "$Name remote"
    Invoke-Native -FilePath "git" -Arguments @("-C", $Path, "fetch", "--prune", "--tags", "origin") -Step "$Name fetch"

    if ($Pinned) {
        Invoke-Native -FilePath "git" -Arguments @("-C", $Path, "checkout", "--detach", $Ref) -Step "$Name checkout $Ref"
        $actual = (& git -C $Path rev-parse HEAD).Trim()
        if ($actual -ne $Ref) {
            throw "$Name pinned checkout mismatch. Expected $Ref, got $actual"
        }
        Add-Result -Step "repo:$Name" -Status PASS -Detail "pinned at $actual"
        return
    }

    Invoke-Native -FilePath "git" -Arguments @("-C", $Path, "checkout", $Ref) -Step "$Name checkout $Ref"
    Invoke-Native -FilePath "git" -Arguments @("-C", $Path, "pull", "--ff-only", "origin", $Ref) -Step "$Name update"
    $actualBranch = (& git -C $Path branch --show-current).Trim()
    $actualSha = (& git -C $Path rev-parse HEAD).Trim()
    Add-Result -Step "repo:$Name" -Status PASS -Detail "$actualBranch @ $actualSha"
}

function Get-ReleaseAsset {
    param(
        [Parameter(Mandatory = $true)]$Release,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $asset = @($Release.assets | Where-Object { $_.name -eq $Name })
    if ($asset.Count -ne 1) {
        throw "Release $($Release.tag_name) does not contain exactly one $Name asset."
    }
    return $asset[0]
}

function Read-Sha256Sums {
    param([Parameter(Mandatory = $true)][string]$Path)
    $map = @{}
    foreach ($line in Get-Content -LiteralPath $Path) {
        if ($line -match '^([0-9A-Fa-f]{64})\s+\*?(.+?)\s*$') {
            $map[$matches[2]] = $matches[1].ToLowerInvariant()
        }
    }
    return $map
}

function Copy-GitHubFileAtRef {
    param(
        [Parameter(Mandatory = $true)][string]$Ref,
        [Parameter(Mandatory = $true)][string]$RepoPath,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    $parent = Split-Path -Parent $Destination
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $url = "https://raw.githubusercontent.com/Ternedal/ModelRig/$Ref/$RepoPath"
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $Destination
}

function Ensure-ModelRigRuntime {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$RuntimePath
    )

    Write-Section "ModelRig appliance"
    New-Item -ItemType Directory -Path $RuntimePath -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $RuntimePath "worker") -Force | Out-Null

    $headers = @{ "User-Agent" = "ModelRig-new-rig-bootstrap" }
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/Ternedal/ModelRig/releases/latest" -Headers $headers
    if ($release.draft -or $release.prerelease) {
        throw "Latest ModelRig release is draft/prerelease; refusing appliance install."
    }
    $tag = [string]$release.tag_name
    if ([string]::IsNullOrWhiteSpace($tag)) {
        throw "Latest ModelRig release has no tag."
    }

    Invoke-Native -FilePath "git" -Arguments @("-C", $SourcePath, "fetch", "--tags", "origin") -Step "ModelRig release tags"

    $sumAsset = Get-ReleaseAsset -Release $release -Name "SHA256SUMS.txt"
    $tempRoot = Join-Path $env:TEMP ("modelrig-bootstrap-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
    try {
        $sumPath = Join-Path $tempRoot "SHA256SUMS.txt"
        Invoke-WebRequest -UseBasicParsing -Uri $sumAsset.browser_download_url -OutFile $sumPath
        $sums = Read-Sha256Sums -Path $sumPath

        $targets = @(
            @{ Name = "modelrig-server-windows-x64.exe"; Dest = (Join-Path $RuntimePath "modelrig-server-windows-x64.exe") },
            @{ Name = "modelrig-supervisor-windows-x64.exe"; Dest = (Join-Path $RuntimePath "modelrig-supervisor-windows-x64.exe") },
            @{ Name = "modelrig-updater-windows-x64.exe"; Dest = (Join-Path $RuntimePath "modelrig-updater-windows-x64.exe") },
            @{ Name = "modelrig-worker-windows-x64.exe"; Dest = (Join-Path $RuntimePath "worker\modelrig-worker-windows-x64.exe") }
        )

        foreach ($target in $targets) {
            $name = [string]$target.Name
            $dest = [string]$target.Dest
            if (-not $sums.ContainsKey($name)) {
                throw "SHA256SUMS.txt has no entry for $name"
            }
            $expected = [string]$sums[$name]
            $valid = $false
            if (Test-Path -LiteralPath $dest -PathType Leaf) {
                $existing = (Get-FileHash -Algorithm SHA256 -LiteralPath $dest).Hash.ToLowerInvariant()
                $valid = ($existing -eq $expected)
            }
            if (-not $valid) {
                $asset = Get-ReleaseAsset -Release $release -Name $name
                $download = Join-Path $tempRoot $name
                Invoke-WebRequest -UseBasicParsing -Uri $asset.browser_download_url -OutFile $download
                $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $download).Hash.ToLowerInvariant()
                if ($actual -ne $expected) {
                    throw "SHA-256 mismatch for $name"
                }
                Copy-Item -LiteralPath $download -Destination $dest -Force
            }
            Add-Result -Step "ModelRig:$name" -Status PASS -Detail "$tag checksum verified"
        }

        Copy-Item -LiteralPath $sumPath -Destination (Join-Path $RuntimePath "SHA256SUMS.txt") -Force
    }
    finally {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }

    Copy-GitHubFileAtRef -Ref $tag -RepoPath "scripts/kaliv-bootstrap.ps1" -Destination (Join-Path $RuntimePath "scripts\kaliv-bootstrap.ps1")
    Copy-GitHubFileAtRef -Ref $tag -RepoPath "scripts/kaliv-autostart.ps1" -Destination (Join-Path $RuntimePath "scripts\kaliv-autostart.ps1")
    Copy-GitHubFileAtRef -Ref $tag -RepoPath "deploy/validate-rig.ps1" -Destination (Join-Path $RuntimePath "deploy\validate-rig.ps1")
    Copy-GitHubFileAtRef -Ref $tag -RepoPath "deploy/modelrig.env.example" -Destination (Join-Path $RuntimePath "deploy\modelrig.env.example")

    $envPath = Join-Path $RuntimePath "modelrig.env"
    if (-not (Test-Path -LiteralPath $envPath -PathType Leaf)) {
        Copy-Item -LiteralPath (Join-Path $RuntimePath "deploy\modelrig.env.example") -Destination $envPath
        Add-Result -Step "ModelRig:modelrig.env" -Status PASS -Detail "created from $tag defaults"
    } else {
        Add-Result -Step "ModelRig:modelrig.env" -Status PASS -Detail "existing config preserved"
    }

    [IO.File]::WriteAllText(
        (Join-Path $RuntimePath ".bootstrap-release-version"),
        $tag + "`n",
        [Text.UTF8Encoding]::new($false)
    )
}

function Test-Http {
    param([string]$Uri, [int]$TimeoutSec = 3)
    try {
        $null = Invoke-RestMethod -Uri $Uri -TimeoutSec $TimeoutSec
        return $true
    } catch {
        return $false
    }
}

function Ensure-OllamaRunning {
    $ollama = Get-Command ollama.exe -ErrorAction SilentlyContinue
    if ($null -eq $ollama) {
        throw "ollama.exe is not available after package installation."
    }
    if (Test-Http -Uri "http://127.0.0.1:11434/api/tags") {
        Add-Result -Step "Ollama" -Status PASS -Detail "API reachable"
        return
    }
    Start-Process -FilePath $ollama.Source -ArgumentList @("serve") -WindowStyle Hidden
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Seconds 2
        if (Test-Http -Uri "http://127.0.0.1:11434/api/tags") {
            Add-Result -Step "Ollama" -Status PASS -Detail "started and API reachable"
            return
        }
    } while ((Get-Date) -lt $deadline)
    throw "Ollama did not become reachable on 127.0.0.1:11434."
}

function Ensure-OllamaModels {
    if ($SkipModelPulls) {
        Add-Result -Step "Ollama models" -Status WARN -Detail "model pulls skipped by operator"
        return
    }
    foreach ($model in $script:OllamaModels) {
        if ([string]::IsNullOrWhiteSpace($model)) { continue }
        & ollama show $model *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "Pulling Ollama model $model..."
            Invoke-Native -FilePath "ollama" -Arguments @("pull", $model) -Step "ollama pull $model"
        }
        Add-Result -Step "Ollama:$model" -Status PASS -Detail "available"
    }
}

function Ensure-WslBase {
    Write-Section "WSL base"
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wsl) {
        Add-Result -Step "WSL" -Status BLOCKED -Detail "wsl.exe missing; enable WSL and re-run"
        return $false
    }

    $distros = @(& $wsl.Source -l -q 2>$null) | ForEach-Object { ([string]$_).Replace([char]0, "").Trim() } | Where-Object { $_ }
    if ($distros -notcontains $script:WslDistribution) {
        Write-Host "Installing WSL distribution $script:WslDistribution..."
        & $wsl.Source --install -d $script:WslDistribution --no-launch
        if ($LASTEXITCODE -ne 0) {
            Add-Result -Step "WSL:$script:WslDistribution" -Status BLOCKED -Detail "automatic distro install failed; run 'wsl --install -d $script:WslDistribution' manually"
            return $false
        }
        $script:RebootRequired = $true
        Add-Result -Step "WSL:$script:WslDistribution" -Status BLOCKED -Detail "installed; reboot/initialize distro, then re-run"
        return $false
    }

    & $wsl.Source -d $script:WslDistribution -- bash -lc "true" *> $null
    if ($LASTEXITCODE -ne 0) {
        Add-Result -Step "WSL:$script:WslDistribution" -Status BLOCKED -Detail "distro exists but is not initialized; launch it once, then re-run"
        return $false
    }

    Add-Result -Step "WSL:$script:WslDistribution" -Status PASS -Detail "available"

    $linuxDeps = "apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y git cmake make build-essential curl wget unzip pkg-config"
    & $wsl.Source -d $script:WslDistribution -u root -- bash -lc $linuxDeps
    if ($LASTEXITCODE -eq 0) {
        Add-Result -Step "WSL build tools" -Status PASS -Detail "git/cmake/make/build-essential present"
    } else {
        Add-Result -Step "WSL build tools" -Status WARN -Detail "apt provisioning failed; BodyRig may need manual packages"
    }
    return $true
}

function Get-NvidiaGpus {
    $nvidia = Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue
    if ($null -eq $nvidia) {
        return @()
    }
    $rows = @(& $nvidia.Source --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits 2>$null)
    if ($LASTEXITCODE -ne 0) {
        return @()
    }
    return @($rows | ForEach-Object { ([string]$_).Trim() } | Where-Object { $_ })
}

function Ensure-VoiceRig {
    param([string]$SourcePath)
    Write-Section "VoiceRig"
    $gpus = @(Get-NvidiaGpus)
    if ($gpus.Count -lt 1) {
        Add-Result -Step "VoiceRig install" -Status BLOCKED -Detail "NVIDIA driver/GPU not visible; install current NVIDIA driver and re-run Core"
        return
    }
    $installer = Join-Path $SourcePath "install-windows.ps1"
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) {
        throw "VoiceRig installer missing: $installer"
    }
    $args = @("-NoBrowser")
    if ($SkipVoiceRigWarmup) {
        $args += "-SkipModelWarmup"
    }
    Invoke-PowerShellScript -Path $installer -Arguments $args -Step "VoiceRig install-windows.ps1"
    Add-Result -Step "VoiceRig install" -Status PASS -Detail "repository installer completed"
}

function Test-WslCuda117 {
    $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
    if ($null -eq $wsl) { return $false }
    & $wsl.Source -d $script:WslDistribution -- bash -lc "test -x /usr/local/cuda-11.7/bin/nvcc" *> $null
    return ($LASTEXITCODE -eq 0)
}

function Find-CondaExe {
    $command = Get-Command conda.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }
    $candidates = @(
        (Join-Path $env:USERPROFILE "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "miniconda3\Scripts\conda.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\miniconda3\Scripts\conda.exe"),
        (Join-Path $env:ProgramData "miniconda3\Scripts\conda.exe")
    )
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    return ""
}

function Ensure-BodyRig {
    param([string]$SourcePath)
    Write-Section "BodyRig"

    if ($SkipBodyRig) {
        Add-Result -Step "BodyRig" -Status WARN -Detail "skipped by operator"
        return
    }

    $gpus = @(Get-NvidiaGpus)
    if ($gpus.Count -lt 1) {
        Add-Result -Step "BodyRig" -Status BLOCKED -Detail "NVIDIA driver/GPU not visible"
        return
    }

    $distros = @(& wsl.exe -l -q 2>$null) | ForEach-Object { ([string]$_).Replace([char]0, "").Trim() } | Where-Object { $_ }
    if ($distros -notcontains $script:WslDistribution) {
        Add-Result -Step "BodyRig" -Status BLOCKED -Detail "$script:WslDistribution is not ready; run Base and re-run after WSL initialization"
        return
    }

    if (-not (Test-WslCuda117)) {
        Add-Result -Step "BodyRig CUDA" -Status BLOCKED -Detail "WSL CUDA 11.7 nvcc missing at /usr/local/cuda-11.7/bin/nvcc"
        return
    }
    Add-Result -Step "BodyRig CUDA" -Status PASS -Detail "CUDA 11.7 compiler present"

    $missing = @()
    if ([string]::IsNullOrWhiteSpace($SmplModelPath) -or -not (Test-Path -LiteralPath $SmplModelPath -PathType Leaf)) {
        $missing += "SmplModelPath"
    }
    if ([string]::IsNullOrWhiteSpace($SmplxSource) -or -not (Test-Path -LiteralPath $SmplxSource)) {
        $missing += "SmplxSource"
    }
    if ([string]::IsNullOrWhiteSpace($DiffusionModel)) {
        $missing += "DiffusionModel (WSL path)"
    }
    if ($missing.Count -gt 0) {
        Add-Result -Step "BodyRig licensed/model assets" -Status BLOCKED -Detail ("set in bootstrap-new-rig.config.psd1: " + ($missing -join ", "))
        return
    }

    $python = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -eq $python) {
        Add-Result -Step "BodyRig Python" -Status BLOCKED -Detail "Python launcher not found"
        return
    }

    $condaExe = Find-CondaExe
    if ([string]::IsNullOrWhiteSpace($condaExe)) {
        Add-Result -Step "BodyRig Conda" -Status BLOCKED -Detail "Miniconda/Conda not found after Base; re-run Base or install Miniconda"
        return
    }
    Add-Result -Step "BodyRig Conda" -Status PASS -Detail $condaExe

    $venvPython = Join-Path $SourcePath ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        Invoke-Native -FilePath $python.Source -Arguments @("-3.11", "-m", "venv", (Join-Path $SourcePath ".venv")) -Step "BodyRig venv"
    }
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip") -Step "BodyRig pip upgrade"
    Invoke-Native -FilePath $venvPython -Arguments @("-m", "pip", "install", "-e", "$SourcePath[dev]") -Step "BodyRig package install"

    $setup = Join-Path $SourcePath "setup-rig-windows.ps1"
    $args = @(
        "-CondaExe", $condaExe,
        "-SmplModelPath", $SmplModelPath,
        "-SmplxSource", $SmplxSource,
        "-DiffusionModel", $DiffusionModel,
        "-Distribution", $script:WslDistribution,
        "-BodyRigPython", $venvPython,
        "-ProvisionOpenPose",
        "-DownloadPublicCheckpoints",
        "-PersistUserEnvironment"
    )
    Invoke-PowerShellScript -Path $setup -Arguments $args -Step "BodyRig setup-rig-windows.ps1"
    Add-Result -Step "BodyRig" -Status PASS -Detail "full rig setup reported READY"
}

function Register-ModelRigAutostart {
    param([string]$RuntimePath)
    if ($SkipAutostart) {
        Add-Result -Step "ModelRig autostart" -Status WARN -Detail "skipped by operator"
        return
    }
    $scriptPath = Join-Path $RuntimePath "scripts\kaliv-autostart.ps1"
    Invoke-PowerShellScript -Path $scriptPath -Step "ModelRig autostart registration"
    Add-Result -Step "ModelRig autostart" -Status PASS -Detail "KalivBootstrap + KalivSupervisor registered"

    Start-ScheduledTask -TaskName "KalivBootstrap"
    $deadline = (Get-Date).AddSeconds(90)
    do {
        Start-Sleep -Seconds 3
        if ((Test-Http "http://127.0.0.1:8080/healthz") -and (Test-Http "http://127.0.0.1:8099/healthz")) {
            Add-Result -Step "ModelRig runtime" -Status PASS -Detail "server :8080 + worker :8099 healthy"
            return
        }
    } while ((Get-Date) -lt $deadline)
    Add-Result -Step "ModelRig runtime" -Status WARN -Detail "autostart registered, but health endpoints were not both ready within 90 seconds"
}

function Validate-Rig {
    param(
        [string]$ModelRigRuntime,
        [string]$VoiceRigSource,
        [string]$BodyRigSource
    )
    Write-Section "Validation"

    $gpus = @(Get-NvidiaGpus)
    if ($gpus.Count -ge $MinimumGpuCount) {
        Add-Result -Step "NVIDIA GPUs" -Status PASS -Detail ("{0} detected: {1}" -f $gpus.Count, ($gpus -join " | "))
    } else {
        Add-Result -Step "NVIDIA GPUs" -Status FAIL -Detail ("expected at least {0}, detected {1}. This is expected before the extra 3060 is moved if MinimumGpuCount is set higher." -f $MinimumGpuCount, $gpus.Count)
    }

    if (Test-Http "http://127.0.0.1:11434/api/tags") {
        Add-Result -Step "Ollama health" -Status PASS -Detail "127.0.0.1:11434 reachable"
    } else {
        Add-Result -Step "Ollama health" -Status FAIL -Detail "127.0.0.1:11434 not reachable"
    }

    if ((Test-Path -LiteralPath (Join-Path $ModelRigRuntime "deploy\validate-rig.ps1")) -and
        (Test-Path -LiteralPath (Join-Path $ModelRigRuntime "modelrig-server-windows-x64.exe"))) {
        $validator = Join-Path $ModelRigRuntime "deploy\validate-rig.ps1"
        $hostExe = (Get-Command powershell.exe -ErrorAction Stop).Source
        & $hostExe -NoProfile -ExecutionPolicy Bypass -File $validator -Root $ModelRigRuntime
        if ($LASTEXITCODE -eq 0) {
            Add-Result -Step "ModelRig validate-rig" -Status PASS -Detail "read-only validation passed"
        } else {
            Add-Result -Step "ModelRig validate-rig" -Status FAIL -Detail "read-only validation returned exit $LASTEXITCODE"
        }
    } else {
        Add-Result -Step "ModelRig validate-rig" -Status WARN -Detail "runtime not installed yet"
    }

    if (Test-Http "http://127.0.0.1:8079/api/readiness") {
        Add-Result -Step "VoiceRig readiness" -Status PASS -Detail "127.0.0.1:8079/api/readiness reachable"
    } else {
        Add-Result -Step "VoiceRig readiness" -Status WARN -Detail "VoiceRig readiness endpoint not reachable; start/check VoiceRig if Core completed"
    }

    $bodyReport = Join-Path $env:LOCALAPPDATA "BodyRig\bodyrig-rig-setup.json"
    if (Test-Path -LiteralPath $bodyReport -PathType Leaf) {
        Add-Result -Step "BodyRig evidence" -Status PASS -Detail $bodyReport
    } elseif (-not $SkipBodyRig) {
        Add-Result -Step "BodyRig evidence" -Status WARN -Detail "full BodyRig setup report not present yet"
    }

    if (Test-Path -LiteralPath (Join-Path $BodyRigSource "reference-renderer\ProjectSettings\ProjectVersion.txt")) {
        $unityVersionLine = Get-Content -LiteralPath (Join-Path $BodyRigSource "reference-renderer\ProjectSettings\ProjectVersion.txt") | Select-Object -First 1
        Add-Result -Step "BodyRig Unity project" -Status PASS -Detail $unityVersionLine
    }
}

function Write-FinalReport {
    param(
        [string]$ReportRoot,
        [string]$ModelRigRuntime,
        [string]$SourceRoot
    )
    New-Item -ItemType Directory -Path $ReportRoot -Force | Out-Null
    $reportPath = Join-Path $ReportRoot "bootstrap-new-rig-latest.json"
    $report = [ordered]@{
        format = "modelrig-new-rig-bootstrap"
        version = 1
        generated_at = (Get-Date).ToString("o")
        computer = $env:COMPUTERNAME
        phase = $Phase
        install_root = $InstallRoot
        source_root = $SourceRoot
        modelrig_runtime = $ModelRigRuntime
        bodyrig_ref = $BodyRigRef
        wsl_distribution = $WslDistribution
        minimum_gpu_count = $MinimumGpuCount
        reboot_required = $script:RebootRequired
        results = @($script:Results)
    }
    $json = $report | ConvertTo-Json -Depth 8
    [IO.File]::WriteAllText($reportPath, $json + "`n", [Text.UTF8Encoding]::new($false))
    Write-Host ""
    Write-Host "Report: $reportPath" -ForegroundColor Cyan
    return $reportPath
}

# Config values are applied before paths are derived.
$script:ConfigPath = $ConfigPath
$script:InstallRoot = $InstallRoot
$script:BodyRigRef = $BodyRigRef
$script:WslDistribution = $WslDistribution
$script:SmplModelPath = $SmplModelPath
$script:SmplxSource = $SmplxSource
$script:DiffusionModel = $DiffusionModel
$script:OllamaModels = $OllamaModels
$script:MinimumGpuCount = $MinimumGpuCount
Apply-Config

$InstallRoot = $script:InstallRoot
$BodyRigRef = $script:BodyRigRef
$WslDistribution = $script:WslDistribution
$SmplModelPath = $script:SmplModelPath
$SmplxSource = $script:SmplxSource
$DiffusionModel = $script:DiffusionModel
$OllamaModels = @($script:OllamaModels)
$MinimumGpuCount = [int]$script:MinimumGpuCount

if ($OllamaModels.Count -eq 0) {
    $OllamaModels = @("nomic-embed-text", "qwen2.5-coder:7b", "gemma3:12b")
    $script:OllamaModels = $OllamaModels
}

if ($MinimumGpuCount -lt 0) {
    throw "MinimumGpuCount cannot be negative."
}

$SourceRoot = Join-Path $InstallRoot "src"
$ModelRigSource = Join-Path $SourceRoot "ModelRig"
$VoiceRigSource = Join-Path $SourceRoot "VoiceRig"
$BodyRigSource = Join-Path $SourceRoot "BodyRig"
$ModelRigRuntime = Join-Path $InstallRoot "ModelRig"
$ReportRoot = Join-Path $InstallRoot "bootstrap"
New-Item -ItemType Directory -Path $ReportRoot -Force | Out-Null

$logPath = Join-Path $ReportRoot ("bootstrap-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
try {
    Start-Transcript -Path $logPath -Force | Out-Null
    $script:TranscriptStarted = $true
} catch {
    Write-Warning "Could not start transcript: $($_.Exception.Message)"
}

Write-Host "ModelRig new-rig bootstrap" -ForegroundColor Cyan
Write-Host "Phase: $Phase"
Write-Host "Install root: $InstallRoot"
Write-Host "BodyRig ref: $BodyRigRef"

$needsAdmin = ($Phase -ne "Validate")
if ($needsAdmin -and -not (Test-IsAdministrator)) {
    Add-Result -Step "Administrator" -Status FAIL -Detail "re-run PowerShell as Administrator"
    Write-FinalReport -ReportRoot $ReportRoot -ModelRigRuntime $ModelRigRuntime -SourceRoot $SourceRoot | Out-Null
    if ($script:TranscriptStarted) { Stop-Transcript | Out-Null }
    exit 1
}
if ($needsAdmin) {
    Add-Result -Step "Administrator" -Status PASS -Detail "elevated"
}

$runBase = ($Phase -eq "Base" -or $Phase -eq "All")
$runCore = ($Phase -eq "Core" -or $Phase -eq "All")
$runBody = ($Phase -eq "BodyRig" -or $Phase -eq "All")
$runValidate = ($Phase -eq "Validate" -or $Phase -eq "All")

try {
    if ($runBase) {
        Write-Section "Windows base"
        Ensure-WingetPackage -Id "Git.Git" -Name "Git"
        Ensure-WingetPackage -Id "Python.Python.3.11" -Name "Python 3.11"
        Ensure-WingetPackage -Id "Ollama.Ollama" -Name "Ollama"
        Ensure-WingetPackage -Id "Tailscale.Tailscale" -Name "Tailscale"
        Ensure-WingetPackage -Id "Anaconda.Miniconda3" -Name "Miniconda"
        Ensure-WingetPackage -Id "Microsoft.PowerShell" -Name "PowerShell 7"

        if (-not $SkipDevTools) {
            Ensure-WingetPackage -Id "GitHub.cli" -Name "GitHub CLI"
            Ensure-WingetPackage -Id "GoLang.Go" -Name "Go"
            Ensure-WingetPackage -Id "EclipseAdoptium.Temurin.21.JDK" -Name "Temurin JDK 21"
            Ensure-WingetPackage -Id "Google.AndroidStudio" -Name "Android Studio" -Optional
            Ensure-WingetPackage -Id "Unity.UnityHub" -Name "Unity Hub" -Optional
        }

        Refresh-ProcessPath
        $gpus = @(Get-NvidiaGpus)
        if ($gpus.Count -eq 0) {
            Add-Result -Step "NVIDIA driver" -Status BLOCKED -Detail "nvidia-smi is unavailable. Install the current NVIDIA driver before VoiceRig/BodyRig."
        } else {
            Add-Result -Step "NVIDIA driver" -Status PASS -Detail ($gpus -join " | ")
        }

        $null = Ensure-WslBase
    }

    if ($runCore) {
        Write-Section "Source checkouts"
        Ensure-GitCheckout -Name "ModelRig" -Url "https://github.com/Ternedal/ModelRig.git" -Path $ModelRigSource -Ref "main"
        Ensure-GitCheckout -Name "VoiceRig" -Url "https://github.com/Ternedal/VoiceRig.git" -Path $VoiceRigSource -Ref "main"
        Ensure-GitCheckout -Name "BodyRig" -Url "https://github.com/Ternedal/BodyRig.git" -Path $BodyRigSource -Ref $BodyRigRef -Pinned

        Ensure-ModelRigRuntime -SourcePath $ModelRigSource -RuntimePath $ModelRigRuntime
        Ensure-OllamaRunning
        Ensure-OllamaModels
        Register-ModelRigAutostart -RuntimePath $ModelRigRuntime
        Ensure-VoiceRig -SourcePath $VoiceRigSource
    }

    if ($runBody) {
        if (-not (Test-Path -LiteralPath (Join-Path $BodyRigSource ".git") -PathType Container)) {
            if (-not (Get-Command git.exe -ErrorAction SilentlyContinue)) {
                throw "Git is missing. Run -Phase Base first."
            }
            Ensure-GitCheckout -Name "BodyRig" -Url "https://github.com/Ternedal/BodyRig.git" -Path $BodyRigSource -Ref $BodyRigRef -Pinned
        }
        Ensure-BodyRig -SourcePath $BodyRigSource
    }

    if ($runValidate) {
        Validate-Rig -ModelRigRuntime $ModelRigRuntime -VoiceRigSource $VoiceRigSource -BodyRigSource $BodyRigSource
    }
}
catch {
    Add-Result -Step "bootstrap exception" -Status FAIL -Detail $_.Exception.Message
}

$reportPath = Write-FinalReport -ReportRoot $ReportRoot -ModelRigRuntime $ModelRigRuntime -SourceRoot $SourceRoot

$pass = @($script:Results | Where-Object status -eq "PASS").Count
$warn = @($script:Results | Where-Object status -eq "WARN").Count
$blocked = @($script:Results | Where-Object status -eq "BLOCKED").Count
$fail = @($script:Results | Where-Object status -eq "FAIL").Count

Write-Host ""
Write-Host ("Summary: {0} PASS / {1} WARN / {2} BLOCKED / {3} FAIL" -f $pass, $warn, $blocked, $fail) -ForegroundColor Cyan
if ($script:RebootRequired) {
    Write-Host "A Windows reboot is required before the blocked WSL/BodyRig step can continue." -ForegroundColor Yellow
}
if ($blocked -gt 0) {
    Write-Host "Blocked items are safe to resolve and then re-run; completed steps are idempotent." -ForegroundColor Yellow
}
if ($fail -eq 0 -and $blocked -eq 0) {
    Write-Host "Bootstrap completed without blockers." -ForegroundColor Green
}

if ($script:TranscriptStarted) {
    Stop-Transcript | Out-Null
}

if ($fail -gt 0) { exit 1 }
if ($blocked -gt 0) { exit 2 }
exit 0

# Read-only old-rig/new-rig inventory and delta comparison.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Capture", "Compare")]
    [string]$Action,
    [string]$InstallRoot = "C:\Rig",
    [string]$Label = "",
    [string]$OutFile = "",
    [string[]]$AdditionalRepoRoot = @(),
    [string]$SourceManifest = "",
    [string]$TargetManifest = "",
    [string]$CompareOutFile = "",
    [switch]$SkipPythonPackages
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$Schema = "modelrig/rig-delta-inventory/v1"

function Write-Step {
    param([string]$Text)
    Write-Host ("== {0} ==" -f $Text) -ForegroundColor Cyan
}

function Normalize-Text {
    param([object]$Value)
    if ($null -eq $Value) { return "" }
    return ([string]$Value).Trim()
}

function Invoke-ExternalText {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$IgnoreExitCode
    )
    try {
        $output = @(& $FilePath @Arguments 2>$null)
        $exitCode = $LASTEXITCODE
        if (-not $IgnoreExitCode -and $exitCode -ne 0) {
            throw "$FilePath exited with code $exitCode"
        }
        return @($output | ForEach-Object { Normalize-Text $_ } | Where-Object { $_ })
    } catch {
        if ($IgnoreExitCode) { return @() }
        throw
    }
}

function Get-GitRepositoryInventory {
    param([string[]]$Roots)
    $seen = @{}
    $repos = New-Object System.Collections.Generic.List[object]

    foreach ($root in $Roots) {
        if ([string]::IsNullOrWhiteSpace($root) -or -not (Test-Path -LiteralPath $root -PathType Container)) {
            continue
        }

        $candidates = New-Object System.Collections.Generic.List[string]
        if (Test-Path -LiteralPath (Join-Path $root ".git")) {
            $candidates.Add((Resolve-Path -LiteralPath $root).Path)
        }
        foreach ($dir in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction SilentlyContinue)) {
            if (Test-Path -LiteralPath (Join-Path $dir.FullName ".git")) {
                $candidates.Add($dir.FullName)
            }
        }

        foreach ($path in @($candidates | Select-Object -Unique)) {
            $canonical = [IO.Path]::GetFullPath($path).TrimEnd('\')
            $key = $canonical.ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true

            $head = @(Invoke-ExternalText -FilePath "git.exe" -Arguments @("-C", $canonical, "rev-parse", "HEAD") -IgnoreExitCode)
            $branch = @(Invoke-ExternalText -FilePath "git.exe" -Arguments @("-C", $canonical, "branch", "--show-current") -IgnoreExitCode)
            $origin = @(Invoke-ExternalText -FilePath "git.exe" -Arguments @("-C", $canonical, "remote", "get-url", "origin") -IgnoreExitCode)
            $status = @(Invoke-ExternalText -FilePath "git.exe" -Arguments @("-C", $canonical, "status", "--porcelain") -IgnoreExitCode)
            $commitTime = @(Invoke-ExternalText -FilePath "git.exe" -Arguments @("-C", $canonical, "log", "-1", "--format=%cI") -IgnoreExitCode)

            $repos.Add([pscustomobject][ordered]@{
                name = Split-Path -Leaf $canonical
                path = $canonical
                origin = if ($origin.Count -gt 0) { $origin[0] } else { "" }
                head = if ($head.Count -gt 0) { $head[0] } else { "" }
                branch = if ($branch.Count -gt 0) { $branch[0] } else { "" }
                dirty = ($status.Count -gt 0)
                dirty_entries = $status.Count
                last_commit = if ($commitTime.Count -gt 0) { $commitTime[0] } else { "" }
            })
        }
    }

    return @($repos | Sort-Object name, path)
}

function Get-OllamaInventory {
    try {
        $response = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -Method Get -TimeoutSec 3
        return @($response.models | ForEach-Object {
            [pscustomobject][ordered]@{
                name = Normalize-Text $_.name
                digest = Normalize-Text $_.digest
                size_bytes = [int64]$_.size
                modified_at = Normalize-Text $_.modified_at
            }
        } | Sort-Object name)
    } catch {
        return @()
    }
}

function Get-InstalledApplicationInventory {
    $paths = @(
        "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $apps = New-Object System.Collections.Generic.List[object]
    $seen = @{}

    foreach ($path in $paths) {
        foreach ($item in @(Get-ItemProperty -Path $path -ErrorAction SilentlyContinue)) {
            $name = Normalize-Text $item.DisplayName
            if (-not $name) { continue }
            if ($item.PSObject.Properties.Name -contains "SystemComponent") {
                if ((Normalize-Text $item.SystemComponent) -eq "1") { continue }
            }
            $version = Normalize-Text $item.DisplayVersion
            $publisher = Normalize-Text $item.Publisher
            $key = ("{0}|{1}|{2}" -f $name, $version, $publisher).ToLowerInvariant()
            if ($seen.ContainsKey($key)) { continue }
            $seen[$key] = $true
            $apps.Add([pscustomobject][ordered]@{
                name = $name
                version = $version
                publisher = $publisher
            })
        }
    }

    return @($apps | Sort-Object name, version, publisher)
}

function Get-WslInventory {
    if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { return @() }

    $raw = @(Invoke-ExternalText -FilePath "wsl.exe" -Arguments @("-l", "-q") -IgnoreExitCode)
    $distros = @($raw | ForEach-Object { ($_ -replace [char]0, "").Trim() } | Where-Object { $_ } | Sort-Object -Unique)
    $result = @()

    foreach ($distro in $distros) {
        $os = @(Invoke-ExternalText -FilePath "wsl.exe" -Arguments @("-d", $distro, "--", "sh", "-lc", "cat /etc/os-release 2>/dev/null | grep -E '^(ID|VERSION_ID)=' | tr '\n' ' '") -IgnoreExitCode)
        $kernel = @(Invoke-ExternalText -FilePath "wsl.exe" -Arguments @("-d", $distro, "--", "sh", "-lc", "uname -r 2>/dev/null || true") -IgnoreExitCode)
        $manual = @(Invoke-ExternalText -FilePath "wsl.exe" -Arguments @("-d", $distro, "--", "sh", "-lc", "command -v apt-mark >/dev/null 2>&1 && apt-mark showmanual 2>/dev/null || true") -IgnoreExitCode)

        $result += [pscustomobject][ordered]@{
            name = $distro
            os_release = if ($os.Count -gt 0) { ($os -join " ") } else { "" }
            kernel = if ($kernel.Count -gt 0) { $kernel[0] } else { "" }
            manual_packages = @($manual | Sort-Object -Unique)
        }
    }

    return @($result | Sort-Object name)
}

function Get-NvidiaInventory {
    $exe = $null
    if (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue) { $exe = "nvidia-smi.exe" }
    elseif (Get-Command nvidia-smi -ErrorAction SilentlyContinue) { $exe = "nvidia-smi" }
    if ($null -eq $exe) { return @() }

    $lines = @(Invoke-ExternalText -FilePath $exe -Arguments @("--query-gpu=name,uuid,memory.total,driver_version", "--format=csv,noheader,nounits") -IgnoreExitCode)
    $gpus = New-Object System.Collections.Generic.List[object]
    foreach ($line in $lines) {
        $parts = @($line -split "," | ForEach-Object { $_.Trim() })
        if ($parts.Count -lt 4) { continue }
        $gpus.Add([pscustomobject][ordered]@{
            name = $parts[0]
            uuid = $parts[1]
            memory_mb = $parts[2]
            driver_version = $parts[3]
        })
    }
    return @($gpus)
}

function Get-ToolInventory {
    $names = @("git", "powershell", "pwsh", "python", "py", "node", "npm", "docker", "ollama", "ffmpeg", "nvidia-smi", "winget", "adb", "cmake", "ninja", "go", "rustc", "cargo", "dotnet", "java")
    return @($names | ForEach-Object {
        $command = Get-Command $_ -ErrorAction SilentlyContinue | Select-Object -First 1
        $available = ($null -ne $command)
        $path = ""
        $version = ""
        if ($available) {
            $path = Normalize-Text $command.Source
            if ($null -ne $command.Version) { $version = Normalize-Text $command.Version }
        }
        [pscustomobject][ordered]@{
            name = $_
            available = $available
            path = $path
            command_version = $version
        }
    })
}

function Get-TaskInventory {
    if (-not (Get-Command Get-ScheduledTask -ErrorAction SilentlyContinue)) { return @() }
    $pattern = "(?i)(rig|kaliv|modelrig|voicerig|bodyrig|visionrig|ollama)"
    try {
        return @(Get-ScheduledTask -ErrorAction Stop | Where-Object { ($_.TaskName + " " + $_.TaskPath) -match $pattern } | ForEach-Object {
            [pscustomobject][ordered]@{
                name = $_.TaskName
                path = $_.TaskPath
                state = Normalize-Text $_.State
            }
        } | Sort-Object path, name)
    } catch {
        return @()
    }
}

function Get-ServiceInventory {
    $pattern = "(?i)(rig|kaliv|modelrig|voicerig|bodyrig|visionrig|ollama)"
    try {
        return @(Get-Service -ErrorAction Stop | Where-Object { ($_.Name + " " + $_.DisplayName) -match $pattern } | ForEach-Object {
            $startType = ""
            if ($_.PSObject.Properties.Name -contains "StartType") { $startType = Normalize-Text $_.StartType }
            [pscustomobject][ordered]@{
                name = $_.Name
                display_name = $_.DisplayName
                status = Normalize-Text $_.Status
                start_type = $startType
            }
        } | Sort-Object name)
    } catch {
        return @()
    }
}

function Get-RigTopLevelInventory {
    param([string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return @() }
    return @(Get-ChildItem -LiteralPath $Root -Force -ErrorAction SilentlyContinue | ForEach-Object {
        [pscustomobject][ordered]@{
            name = $_.Name
            kind = if ($_.PSIsContainer) { "directory" } else { "file" }
            size_bytes = if ($_.PSIsContainer) { $null } else { [int64]$_.Length }
            last_write_utc = $_.LastWriteTimeUtc.ToString("o")
        }
    } | Sort-Object name)
}

function Get-PythonEnvironmentInventory {
    param([object[]]$Repos)
    $result = New-Object System.Collections.Generic.List[object]

    foreach ($repo in $Repos) {
        foreach ($candidate in @(".venv", "venv")) {
            $venv = Join-Path $repo.path $candidate
            $python = Join-Path $venv "Scripts\python.exe"
            if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { continue }

            $version = @(Invoke-ExternalText -FilePath $python -Arguments @("--version") -IgnoreExitCode)
            $packages = @()
            if (-not $SkipPythonPackages) {
                $packages = @(Invoke-ExternalText -FilePath $python -Arguments @("-m", "pip", "freeze", "--disable-pip-version-check") -IgnoreExitCode | Sort-Object -Unique)
            }

            $result.Add([pscustomobject][ordered]@{
                repo = $repo.name
                path = $venv
                python_version = if ($version.Count -gt 0) { $version[0] } else { "" }
                packages = @($packages)
            })
        }
    }

    return @($result | Sort-Object repo, path)
}

function Get-OsInventory {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        return [pscustomobject][ordered]@{
            caption = Normalize-Text $os.Caption
            version = Normalize-Text $os.Version
            build_number = Normalize-Text $os.BuildNumber
            architecture = Normalize-Text $os.OSArchitecture
        }
    } catch {
        $arch = "32-bit"
        if ([Environment]::Is64BitOperatingSystem) { $arch = "64-bit" }
        return [pscustomobject][ordered]@{
            caption = ""
            version = [Environment]::OSVersion.Version.ToString()
            build_number = ""
            architecture = $arch
        }
    }
}

function Read-InventoryManifest {
    param([string]$Path)
    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Inventory manifest not found: $Path"
    }
    $manifest = Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
    if ($manifest.schema -ne $Schema) {
        throw "Unsupported inventory schema '$($manifest.schema)' in $Path"
    }
    return $manifest
}

function New-Lookup {
    param([object[]]$Items, [scriptblock]$Key)
    $map = @{}
    foreach ($item in @($Items)) {
        $raw = & $Key $item
        $k = (Normalize-Text $raw).ToLowerInvariant()
        if (-not $map.ContainsKey($k)) { $map[$k] = $item }
    }
    return $map
}

function Compare-Keyed {
    param([object[]]$Source, [object[]]$Target, [scriptblock]$Key, [string[]]$Fields = @())
    $sourceMap = New-Lookup -Items $Source -Key $Key
    $targetMap = New-Lookup -Items $Target -Key $Key
    $sourceOnly = @()
    $targetOnly = @()
    $different = @()

    foreach ($k in @($sourceMap.Keys | Sort-Object)) {
        if (-not $targetMap.ContainsKey($k)) {
            $sourceOnly += $sourceMap[$k]
            continue
        }
        $changes = @()
        foreach ($field in $Fields) {
            $a = Normalize-Text $sourceMap[$k].$field
            $b = Normalize-Text $targetMap[$k].$field
            if ($a -ne $b) {
                $changes += [pscustomobject][ordered]@{ field = $field; source = $a; target = $b }
            }
        }
        if ($changes.Count -gt 0) {
            $different += [pscustomobject][ordered]@{ key = $k; changes = @($changes) }
        }
    }

    foreach ($k in @($targetMap.Keys | Sort-Object)) {
        if (-not $sourceMap.ContainsKey($k)) { $targetOnly += $targetMap[$k] }
    }

    return [pscustomobject][ordered]@{
        source_only = @($sourceOnly)
        target_only = @($targetOnly)
        different = @($different)
    }
}

function Compare-WslPackages {
    param([object[]]$Source, [object[]]$Target)
    $sourceMap = New-Lookup -Items $Source -Key { param($x) $x.name }
    $targetMap = New-Lookup -Items $Target -Key { param($x) $x.name }
    $result = @()

    foreach ($key in @($sourceMap.Keys | Sort-Object)) {
        if (-not $targetMap.ContainsKey($key)) { continue }
        $sourcePkgs = @($sourceMap[$key].manual_packages)
        $targetPkgs = @($targetMap[$key].manual_packages)
        $missing = @($sourcePkgs | Where-Object { $targetPkgs -notcontains $_ } | Sort-Object -Unique)
        $extra = @($targetPkgs | Where-Object { $sourcePkgs -notcontains $_ } | Sort-Object -Unique)
        if ($missing.Count -gt 0 -or $extra.Count -gt 0) {
            $result += [pscustomobject][ordered]@{ distro = $sourceMap[$key].name; missing_on_target = $missing; target_only = $extra }
        }
    }

    return @($result)
}

function Write-JsonAtomic {
    param([object]$Value, [string]$Path)
    $parent = Split-Path -Parent $Path
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    $tmp = "$Path.tmp"
    $Value | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $tmp -Encoding UTF8
    Move-Item -LiteralPath $tmp -Destination $Path -Force
}

if ($Action -eq "Capture") {
    if ([string]::IsNullOrWhiteSpace($OutFile)) {
        $safeLabel = $env:COMPUTERNAME
        if ($Label) { $safeLabel = $Label -replace "[^A-Za-z0-9._-]", "-" }
        $OutFile = Join-Path $env:USERPROFILE ("rig-inventory-{0}.json" -f $safeLabel)
    }

    Write-Step "Capturing repositories"
    $repoRoots = @((Join-Path $InstallRoot "src")) + @($AdditionalRepoRoot)
    $repos = @(Get-GitRepositoryInventory -Roots $repoRoots)

    Write-Step "Capturing host/runtime inventory"
    $manifest = [pscustomobject][ordered]@{
        schema = $Schema
        captured_utc = [DateTime]::UtcNow.ToString("o")
        label = $Label
        computer_name = $env:COMPUTERNAME
        install_root = [IO.Path]::GetFullPath($InstallRoot)
        secret_policy = "No environment-variable values, credential values, .env contents, tokens, passwords or private model payload bytes are captured."
        os = Get-OsInventory
        nvidia = @(Get-NvidiaInventory)
        tools = @(Get-ToolInventory)
        installed_applications = @(Get-InstalledApplicationInventory)
        wsl = @(Get-WslInventory)
        ollama_models = @(Get-OllamaInventory)
        repositories = $repos
        python_environments = @(Get-PythonEnvironmentInventory -Repos $repos)
        scheduled_tasks = @(Get-TaskInventory)
        services = @(Get-ServiceInventory)
        rig_top_level = @(Get-RigTopLevelInventory -Root $InstallRoot)
    }

    Write-JsonAtomic -Value $manifest -Path $OutFile
    Write-Host "RIG INVENTORY CAPTURED: $OutFile" -ForegroundColor Green
    Write-Host ("repos={0} apps={1} wsl={2} ollama_models={3} python_envs={4}" -f $manifest.repositories.Count, $manifest.installed_applications.Count, $manifest.wsl.Count, $manifest.ollama_models.Count, $manifest.python_environments.Count)
    return
}

$source = Read-InventoryManifest -Path $SourceManifest
$target = Read-InventoryManifest -Path $TargetManifest

Write-Step "Comparing old/source rig with new/target rig"

$repoDiff = Compare-Keyed -Source @($source.repositories) -Target @($target.repositories) -Key { param($x) if ($x.origin) { $x.origin } else { $x.name } } -Fields @("head", "branch", "dirty")
$appDiff = Compare-Keyed -Source @($source.installed_applications) -Target @($target.installed_applications) -Key { param($x) "{0}|{1}|{2}" -f $x.name, $x.version, $x.publisher }
$ollamaDiff = Compare-Keyed -Source @($source.ollama_models) -Target @($target.ollama_models) -Key { param($x) $x.name } -Fields @("digest", "size_bytes")
$wslDiff = Compare-Keyed -Source @($source.wsl) -Target @($target.wsl) -Key { param($x) $x.name } -Fields @("os_release")
$toolDiff = Compare-Keyed -Source @($source.tools) -Target @($target.tools) -Key { param($x) $x.name } -Fields @("available")
$taskDiff = Compare-Keyed -Source @($source.scheduled_tasks) -Target @($target.scheduled_tasks) -Key { param($x) "{0}|{1}" -f $x.path, $x.name }
$serviceDiff = Compare-Keyed -Source @($source.services) -Target @($target.services) -Key { param($x) $x.name } -Fields @("start_type")
$rigDiff = Compare-Keyed -Source @($source.rig_top_level) -Target @($target.rig_top_level) -Key { param($x) "{0}|{1}" -f $x.kind, $x.name }
$pythonDiff = Compare-Keyed -Source @($source.python_environments) -Target @($target.python_environments) -Key { param($x) $x.repo } -Fields @("python_version")
$wslPackages = @(Compare-WslPackages -Source @($source.wsl) -Target @($target.wsl))

$recommendations = @()
if ($repoDiff.source_only.Count -gt 0) { $recommendations += "Clone/reconcile repositories present only on the source rig." }
if ($repoDiff.different.Count -gt 0) { $recommendations += "Review repository HEAD/branch differences; preserve dirty source work before syncing through Git/GitHub." }
if ($ollamaDiff.source_only.Count -gt 0 -or $ollamaDiff.different.Count -gt 0) { $recommendations += "Pull missing or digest-different Ollama models on the target instead of copying opaque blob stores." }
if ($wslDiff.source_only.Count -gt 0) { $recommendations += "Install missing WSL distributions intentionally; do not copy a live distro filesystem." }
if ($wslPackages.Count -gt 0) { $recommendations += "Reconcile manually installed apt packages for matching WSL distributions." }
if ($appDiff.source_only.Count -gt 0) { $recommendations += "Review source-only Windows applications and install only those still needed on the new rig." }
if ($taskDiff.source_only.Count -gt 0 -or $serviceDiff.source_only.Count -gt 0) { $recommendations += "Recreate missing rig scheduled tasks/services through repository installers/bootstrap." }
if ($rigDiff.source_only.Count -gt 0) { $recommendations += "Inspect source-only top-level C:\Rig entries and use the owning subsystem migration path for mutable data." }

$report = [pscustomobject][ordered]@{
    schema = "modelrig/rig-delta-report/v1"
    compared_utc = [DateTime]::UtcNow.ToString("o")
    source = [pscustomobject][ordered]@{ label = $source.label; computer_name = $source.computer_name; captured_utc = $source.captured_utc; manifest = [IO.Path]::GetFullPath($SourceManifest) }
    target = [pscustomobject][ordered]@{ label = $target.label; computer_name = $target.computer_name; captured_utc = $target.captured_utc; manifest = [IO.Path]::GetFullPath($TargetManifest) }
    repositories = $repoDiff
    ollama_models = $ollamaDiff
    wsl_distributions = $wslDiff
    wsl_manual_packages = $wslPackages
    installed_applications = $appDiff
    tools = $toolDiff
    python_environments = $pythonDiff
    scheduled_tasks = $taskDiff
    services = $serviceDiff
    rig_top_level = $rigDiff
    recommended_actions = @($recommendations)
}

if (-not [string]::IsNullOrWhiteSpace($CompareOutFile)) {
    Write-JsonAtomic -Value $report -Path $CompareOutFile
}

Write-Host ("SOURCE-ONLY: repos={0} apps={1} ollama={2} wsl={3} tasks={4} services={5} rig_entries={6}" -f $report.repositories.source_only.Count, $report.installed_applications.source_only.Count, $report.ollama_models.source_only.Count, $report.wsl_distributions.source_only.Count, $report.scheduled_tasks.source_only.Count, $report.services.source_only.Count, $report.rig_top_level.source_only.Count) -ForegroundColor Yellow
if ($report.repositories.different.Count -gt 0) { Write-Host ("REPOSITORY DIFFERENCES: {0}" -f $report.repositories.different.Count) -ForegroundColor Yellow }
if ($report.ollama_models.different.Count -gt 0) { Write-Host ("OLLAMA DIGEST/SIZE DIFFERENCES: {0}" -f $report.ollama_models.different.Count) -ForegroundColor Yellow }
foreach ($item in $report.recommended_actions) { Write-Host (" - {0}" -f $item) }
if ($CompareOutFile) { Write-Host "RIG DELTA REPORT WRITTEN: $CompareOutFile" -ForegroundColor Green }

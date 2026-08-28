[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedSha,
    [Parameter(Mandatory = $true)][string]$OutputRoot,
    [string]$Serial
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$packageName = "dk.ternedal.modelrig.a425f"
$firewallRule = "ModelRig A4-25f isolated Pixel read"
$ports = @(18080, 18081, 18099)

function Resolve-Output {
    $full = if ([IO.Path]::IsPathRooted($OutputRoot)) {
        [IO.Path]::GetFullPath($OutputRoot)
    } else {
        [IO.Path]::GetFullPath((Join-Path (Get-Location) $OutputRoot))
    }
    $repoPrefix = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\') + '\'
    if ($full.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-25f output må ikke ligge i repositoryet."
    }
    return $full.TrimEnd('\')
}

function Assert-ExactCleanHead {
    if ($ExpectedSha -notmatch "^[0-9a-f]{40}$") { throw "ExpectedSha skal være 40 lowercase hex." }
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedSha) { throw "Forkert A4-25f checkout." }
    if (@(& git -C $repoRoot status --porcelain).Count -ne 0) { throw "A4-25f cleanup-audit kræver clean exact head." }
}

function Resolve-Serial {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw "adb mangler på PATH." }
    if (-not [string]::IsNullOrWhiteSpace($Serial)) { return $Serial }
    $devices = @(& adb devices | Where-Object { $_ -match "^\S+\s+device$" } | ForEach-Object { ($_ -split "\s+")[0] })
    if ($LASTEXITCODE -ne 0 -or $devices.Count -ne 1) { throw "Angiv -Serial eller tilslut præcis én adb-enhed." }
    return [string]$devices[0]
}

if ($env:OS -ne "Windows_NT") { throw "Cleanup verification skal køres på den fysiske Windows-rig." }
Assert-ExactCleanHead
$output = Resolve-Output
$statePath = Join-Path $output "a4-25f-operator-state.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "A4-25f operator-state mangler." }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ([string]$state.expected_sha -ne $ExpectedSha) { throw "Operator-state tilhører en anden head." }
if ([string]$state.phase -ne "stopped") { throw "Kør operatorens Stop før cleanup verification." }
if ([int]$state.backend_pid -ne 0 -or [int]$state.worker_pid -ne 0) { throw "Operator-state har stadig aktive A4-25f PIDs." }

$deviceSerial = Resolve-Serial
if (-not [string]::IsNullOrWhiteSpace([string]$state.adb_serial) -and [string]$state.adb_serial -ne $deviceSerial) {
    throw "Cleanup Pixel matcher ikke matrixens adb-serial."
}

# adb skriver rutinemaessigt til STDERR -- daemon-start, "device unauthorized",
# fremdrift. Med $ErrorActionPreference='Stop' og 2>&1 bliver de linjer til
# ErrorRecords i Windows PowerShell og udloeser NativeCommandError SELV naar
# adb returnerer 0. Praecis den fejl draebte beviskampagnen 18/8 (#631).
# Preferencen saenkes derfor omkring kaldet, og ErrorRecords flades til tekst.
# EXITKODEN er verdiktet, ikke stderr.
$_eap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    $packagePath = @(& adb -s $deviceSerial shell pm path $packageName 2>&1 | ForEach-Object {
        if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
    })
} finally { $ErrorActionPreference = $_eap }
if ($LASTEXITCODE -ne 0) { throw "Kunne ikke verificere A425f package cleanup via adb." }
if (($packagePath -join "").Trim().Length -ne 0) { throw "Den isolerede A425f APK er stadig installeret." }

$rule = @(Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue)
if ($rule.Count -ne 0) { throw "A4-25f firewall-reglen er stadig til stede." }

$listeners = @()
foreach ($port in $ports) {
    $listeners += @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
}
if ($listeners.Count -ne 0) {
    throw "En A4-25f reserveret listener-port er stadig aktiv: $($listeners.LocalPort -join ', ')."
}

$backendData = Join-Path $output "backend-device-store.json"
if (Test-Path -LiteralPath $backendData) { throw "Den isolerede backend device-store er ikke ryddet." }

$backendProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    ([string]$_.ExecutablePath).EndsWith("modelrig-a4-25f-backend.exe", [StringComparison]::OrdinalIgnoreCase)
})
if ($backendProcesses.Count -ne 0) { throw "A4-25f backend-processen er stadig aktiv." }
$workerProcesses = @(Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
    ([string]$_.CommandLine) -match [regex]::Escape("agent4_a4_25f_physical_host.py")
})
if ($workerProcesses.Count -ne 0) { throw "A4-25f worker-hostprocessen er stadig aktiv." }

$receipt = [ordered]@{
    schema = "modelrig-agent4/a4-25f-cleanup/v1"
    recorded_at = (Get-Date).ToUniversalTime().ToString("o")
    repository_sha = $ExpectedSha
    package_name = $packageName
    package_removed = $true
    firewall_rule_removed = $true
    reserved_ports_closed = $true
    backend_device_store_removed = $true
    backend_process_removed = $true
    worker_process_removed = $true
    adb_serial_sha256 = "sha256:$((Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($deviceSerial))) -Algorithm SHA256).Hash.ToLowerInvariant())"
    credential_in_receipt = $false
    public_network = $false
    physical_cleanup = $true
    production_activation = $false
}
$receipt | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $output "a4-25f-cleanup.json") -Encoding UTF8
Write-Host "A4-25f cleanup verification er grøn." -ForegroundColor Green

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
$activity = "dk.ternedal.modelrig.debug.Agent4PhysicalCursorProbeActivity"
$stages = @("root-mismatch", "resource-mismatch", "filter-mismatch", "campaign-mismatch")

function Assert-ExactCleanHead {
    if ($ExpectedSha -notmatch "^[0-9a-f]{40}$") { throw "ExpectedSha skal være 40 lowercase hex." }
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedSha) { throw "Forkert A4-25f checkout." }
    if (@(& git -C $repoRoot status --porcelain).Count -ne 0) { throw "A4-25f CursorMatrix kræver clean exact head." }
}

function Resolve-ExternalOutputRoot {
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

function Resolve-Serial {
    if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw "adb mangler på PATH." }
    if (-not [string]::IsNullOrWhiteSpace($Serial)) { return $Serial }
    $devices = @(& adb devices | Where-Object { $_ -match "^\S+\s+device$" } | ForEach-Object { ($_ -split "\s+")[0] })
    if ($LASTEXITCODE -ne 0 -or $devices.Count -ne 1) { throw "Angiv -Serial eller tilslut præcis én adb-enhed." }
    return [string]$devices[0]
}

function Invoke-Adb {
    param([string]$DeviceSerial, [Parameter(ValueFromRemainingArguments = $true)][string[]]$Arguments)
    # adb skriver rutinemaessigt til STDERR -- daemon-start, "device unauthorized",
    # fremdrift. Med $ErrorActionPreference='Stop' og 2>&1 bliver de linjer til
    # ErrorRecords i Windows PowerShell og udloeser NativeCommandError SELV naar
    # adb returnerer 0. Praecis den fejl draebte beviskampagnen 18/8 (#631).
    # Preferencen saenkes derfor omkring kaldet, og ErrorRecords flades til tekst.
    # EXITKODEN er verdiktet, ikke stderr.
    $_eap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& adb -s $DeviceSerial @Arguments 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
        })
    } finally { $ErrorActionPreference = $_eap }
    if ($LASTEXITCODE -ne 0) { throw "adb fejlede: $($lines -join ' ')" }
    return $lines
}

function Run-CursorStage {
    param([string]$DeviceSerial, [string]$Stage, [string]$PhoneReceipts)
    $file = "a4-25f-cursor-$Stage.json"
    Invoke-Adb -DeviceSerial $DeviceSerial shell run-as $packageName rm -f "files/$file" | Out-Null
    Invoke-Adb -DeviceSerial $DeviceSerial shell am force-stop $packageName | Out-Null
    Invoke-Adb -DeviceSerial $DeviceSerial shell am start -W -n "$packageName/$activity" --es stage $Stage | Out-Null
    $deadline = (Get-Date).AddSeconds(30)
    do {
        try {
            $raw = (Invoke-Adb -DeviceSerial $DeviceSerial shell run-as $packageName cat "files/$file") -join "`n"
            if (-not [string]::IsNullOrWhiteSpace($raw)) {
                $receipt = $raw | ConvertFrom-Json
                $raw | Set-Content -LiteralPath (Join-Path $PhoneReceipts $file) -Encoding UTF8
                if ($receipt.success -ne $true -or $receipt.local_rejection -ne $true -or [string]$receipt.error_kind -ne "PROTOCOL") {
                    throw "Cursor-probe '$Stage' gav ikke forventet lokal PROTOCOL-afvisning."
                }
                return $receipt
            }
        } catch { }
        Start-Sleep -Milliseconds 400
    } while ((Get-Date) -lt $deadline)
    throw "Cursor-probe '$Stage' producerede ikke en gyldig receipt."
}

Assert-ExactCleanHead
$output = Resolve-ExternalOutputRoot
$statePath = Join-Path $output "a4-25f-operator-state.json"
if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "A4-25f operator-state mangler." }
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
if ([string]$state.expected_sha -ne $ExpectedSha) { throw "Operator-state tilhører en anden exact head." }
if ([string]$state.phase -ne "matrix_complete") { throw "Kør hovedmatrixen før CursorMatrix." }
$deviceSerial = Resolve-Serial
if (-not [string]::IsNullOrWhiteSpace([string]$state.adb_serial) -and [string]$state.adb_serial -ne $deviceSerial) {
    throw "CursorMatrix adb-serial matcher ikke hovedmatrixens Pixel."
}
$phoneReceipts = Join-Path $output "phone-receipts"
New-Item -ItemType Directory -Path $phoneReceipts -Force | Out-Null
$receipts = @()
foreach ($stage in $stages) {
    $receipts += Run-CursorStage -DeviceSerial $deviceSerial -Stage $stage -PhoneReceipts $phoneReceipts
}
$files = @($stages | ForEach-Object { Get-Item -LiteralPath (Join-Path $phoneReceipts "a4-25f-cursor-$_.json") })
$summary = [ordered]@{
    schema = "modelrig-agent4/a4-25f-cursor-matrix/v1"
    recorded_at = (Get-Date).ToUniversalTime().ToString("o")
    repository_sha = $ExpectedSha
    package_name = $packageName
    adb_serial_sha256 = "sha256:$((Get-FileHash -InputStream ([IO.MemoryStream]::new([Text.Encoding]::UTF8.GetBytes($deviceSerial))) -Algorithm SHA256).Hash.ToLowerInvariant())"
    stages = @($stages)
    receipt_count = $files.Count
    receipts = @($files | ForEach-Object { [ordered]@{ name = $_.Name; sha256 = "sha256:$((Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())" } })
    credential_in_receipt = $false
    raw_cursor_in_receipt = $false
    public_network = $false
    physical_execution = $true
    production_activation = $false
}
$summary | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath (Join-Path $output "a4-25f-cursor-matrix.json") -Encoding UTF8
Write-Host "A4-25f CursorMatrix bestod alle fire lokale cursor-afvisninger." -ForegroundColor Green

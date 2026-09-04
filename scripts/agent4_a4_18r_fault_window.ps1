[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedSha,
    [Parameter(Mandatory = $true)][string]$OutputRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$faultScript = Join-Path $PSScriptRoot "agent4_a4_18r_fault_host.py"
$backendPort = 18180
$workerPort = 18199
$firewallRule = "ModelRig A4-18R isolated physical read"

function Resolve-ExternalOutputRoot {
    if ([IO.Path]::IsPathRooted($OutputRoot)) { $full = [IO.Path]::GetFullPath($OutputRoot) }
    else { $full = [IO.Path]::GetFullPath((Join-Path (Get-Location).Path $OutputRoot)) }
    $repo = [IO.Path]::GetFullPath($repoRoot).TrimEnd('\')
    if ($full.StartsWith($repo + '\', [StringComparison]::OrdinalIgnoreCase) -or
        [string]::Equals($full.TrimEnd('\'), $repo, [StringComparison]::OrdinalIgnoreCase)) {
        throw "A4-18R output må ikke ligge i repositoryet."
    }
    return $full.TrimEnd('\')
}

$output = Resolve-ExternalOutputRoot
$statePath = Join-Path $output "a4-18r-operator-state.json"
$pairingData = Join-Path $output "modelrig-data.json"
$adminKeyFile = Join-Path $output "admin-key.txt"
$backendExe = Join-Path $output "bin\modelrig-a4-18r-backend.exe"
$logsDir = Join-Path $output "logs"

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") { throw "A4-18R fault-vinduet må kun køres på Windows-riggen." }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw "Kør PowerShell som administrator." }
}

function Assert-ExactCleanHead {
    if ($ExpectedSha -notmatch "^[0-9a-f]{40}$") { throw "ExpectedSha skal være 40 lowercase hex." }
    $head = (& git -C $repoRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $head -ne $ExpectedSha) { throw "Forkert exact checkout." }
    if (@(& git -C $repoRoot status --porcelain).Count -ne 0) { throw "A4-18R fault-vinduet kræver ren working tree." }
}

function Read-State {
    if (-not (Test-Path -LiteralPath $statePath -PathType Leaf)) { throw "A4-18R state mangler." }
    $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
    if ([string]$state.expected_sha -ne $ExpectedSha) { throw "A4-18R state tilhører en anden exact SHA." }
    if (@("granted", "regranted") -notcontains [string]$state.phase) { throw "Malformed-wire-vinduet kræver granted/regranted fase." }
    return $state
}

function Write-State {
    param([Parameter(Mandatory = $true)]$State)
    $State.updated_at = (Get-Date).ToUniversalTime().ToString("o")
    $State | ConvertTo-Json -Depth 30 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Get-ProcessInfo {
    param([int]$ProcessId)
    return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction SilentlyContinue
}

function Assert-BackendProcess {
    param([int]$ProcessId)
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { throw "Recorded A4-18R backend PID findes ikke." }
    $actual = [string]$process.ExecutablePath
    if ([string]::IsNullOrWhiteSpace($actual) -or -not [string]::Equals(
        [IO.Path]::GetFullPath($actual), [IO.Path]::GetFullPath($backendExe), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Recorded backend PID tilhører ikke A4-18R; processen bevares."
    }
}

function Get-ListenerRows {
    param([int]$Port)
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Wait-Http200 {
    param([string]$Url, [int]$Seconds = 30)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2
            if ([int]$response.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 300
    } while ((Get-Date) -lt $deadline)
    throw "Endpoint blev ikke klar: $Url"
}

function Remove-Firewall {
    Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue | Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Install-Firewall {
    param([string]$Program, [string]$Address, [string]$PixelIp)
    Remove-Firewall
    New-NetFirewallRule -DisplayName $firewallRule -Direction Inbound -Action Allow -Program $Program `
        -Protocol TCP -LocalAddress $Address -LocalPort $backendPort -RemoteAddress $PixelIp -Profile Private | Out-Null
}

function Start-RealBackend {
    param($State)
    $key = (Get-Content -LiteralPath $adminKeyFile -Raw).Trim()
    if ($key.Length -lt 64) { throw "A4-18R admin-key mangler eller er ugyldig." }
    $names = @("MODELRIG_HOST", "MODELRIG_PORT", "MODELRIG_DATA", "MODELRIG_WORKER_URL", "MODELRIG_ADMIN_KEY", "KALIV_AGENT4_OPERATOR_API", "KALIV_AGENT4_GRANT_ADMIN")
    $saved = @{}
    foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
    try {
        $env:MODELRIG_HOST = [string]$State.lan_address
        $env:MODELRIG_PORT = "$backendPort"
        $env:MODELRIG_DATA = $pairingData
        $env:MODELRIG_WORKER_URL = "http://127.0.0.1:$workerPort"
        $env:MODELRIG_ADMIN_KEY = $key
        $env:KALIV_AGENT4_OPERATOR_API = "1"
        $env:KALIV_AGENT4_GRANT_ADMIN = "0"
        Start-Process -FilePath $backendExe -WorkingDirectory $output `
            -RedirectStandardOutput (Join-Path $logsDir "backend-lan.stdout.log") `
            -RedirectStandardError (Join-Path $logsDir "backend-lan.stderr.log") | Out-Null
    } finally {
        foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process") }
    }
    Wait-Http200 -Url "http://$($State.lan_address):$backendPort/healthz"
    $rows = @(Get-ListenerRows -Port $backendPort)
    if ($rows.Count -ne 1 -or [string]$rows[0].LocalAddress -ne [string]$State.lan_address) { throw "Den rigtige backend kom ikke tilbage på exact LAN-binding." }
    Assert-BackendProcess -ProcessId ([int]$rows[0].OwningProcess)
    return [int]$rows[0].OwningProcess
}

Assert-WindowsAdministrator
Assert-ExactCleanHead
$state = Read-State
$backendPid = [int]$state.backend_pid
Assert-BackendProcess -ProcessId $backendPid
$workerRows = @(Get-ListenerRows -Port $workerPort)
if ($workerRows.Count -ne 1 -or [string]$workerRows[0].LocalAddress -ne "127.0.0.1") { throw "A4-18R worker er ikke en entydig loopback-listener." }

Stop-Process -Id $backendPid -Force -ErrorAction Stop
$deadline = (Get-Date).AddSeconds(20)
while ($null -ne (Get-ProcessInfo -ProcessId $backendPid) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 250 }
if ($null -ne (Get-ProcessInfo -ProcessId $backendPid)) { throw "Backend kunne ikke stoppes sikkert før wire-fault." }
$state.backend_pid = 0
Write-State -State $state

$python = (Get-Command python -ErrorAction Stop).Source
$faultPid = 0
try {
    Install-Firewall -Program $python -Address ([string]$state.lan_address) -PixelIp ([string]$state.pixel_ip)
    Start-Process -FilePath $python -ArgumentList @($faultScript, "--host", [string]$state.lan_address, "--port", "$backendPort") `
        -WorkingDirectory $repoRoot -RedirectStandardOutput (Join-Path $logsDir "fault-host.stdout.log") `
        -RedirectStandardError (Join-Path $logsDir "fault-host.stderr.log") | Out-Null
    Wait-Http200 -Url "http://$($state.lan_address):$backendPort/healthz"
    $rows = @(Get-ListenerRows -Port $backendPort)
    if ($rows.Count -ne 1) { throw "Wire-fault host er ikke en entydig listener." }
    $faultPid = [int]$rows[0].OwningProcess
    $faultProcess = Get-ProcessInfo -ProcessId $faultPid
    if ($null -eq $faultProcess -or [string]$faultProcess.CommandLine -notmatch [regex]::Escape("agent4_a4_18r_fault_host.py")) {
        throw "Wire-fault listener ejes ikke af A4-18R fault host."
    }
    Write-Host "MALFORMED-WIRE WINDOW ER AKTIV" -ForegroundColor Yellow
    Write-Host "Åbn Agent 4 på den isolerede test-app og bekræft protocol-failure, aldrig success." -ForegroundColor Yellow
    [void](Read-Host "Tryk Enter når observationen er færdig; den rigtige backend gendannes derefter")
} finally {
    if ($faultPid -gt 0) {
        $process = Get-ProcessInfo -ProcessId $faultPid
        if ($null -ne $process -and [string]$process.CommandLine -match [regex]::Escape("agent4_a4_18r_fault_host.py")) {
            Stop-Process -Id $faultPid -Force -ErrorAction SilentlyContinue
        }
    }
    Remove-Firewall
    Install-Firewall -Program $backendExe -Address ([string]$state.lan_address) -PixelIp ([string]$state.pixel_ip)
    $state.backend_pid = Start-RealBackend -State $state
    Write-State -State $state
}

Write-Host "Den rigtige A4-18R backend er gendannet. Registrér nu malformed_schema_fail_closed med HTTP 200." -ForegroundColor Green

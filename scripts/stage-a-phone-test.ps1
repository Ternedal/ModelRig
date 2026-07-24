[CmdletBinding()]
param(
    [string]$PlannerModel,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtimeDir = Join-Path $repoRoot "validation\stage-a-runtime"
$statePath = Join-Path $runtimeDir "phone-test-state.json"
$instructionPath = Join-Path $runtimeDir "PHONE_TEST.txt"
$pairingDataPath = Join-Path $runtimeDir "phone-test-modelrig-data.json"
$backendExe = Join-Path $runtimeDir "modelrig-server-stage-a.exe"
$firewallRule = "ModelRig Stage A phone test 8080"

function Assert-WindowsAdministrator {
    if ($env:OS -ne "Windows_NT") {
        throw "Telefon-teststacken må kun køres på Windows-riggen."
    }
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Højreklik på launcheren og vælg 'Kør som administrator'."
    }
}

function Get-ListenerPid {
    param([int]$Port)
    $listener = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $listener) { return $null }
    return [int]$listener.OwningProcess
}

function Get-ProcessInfo {
    param([int]$ProcessId)
    try {
        return Get-CimInstance Win32_Process -Filter "ProcessId=$ProcessId" -ErrorAction Stop
    }
    catch {
        return $null
    }
}

function Test-RecordedProcess {
    param(
        [int]$ProcessId,
        [ValidateSet("backend", "worker")]
        [string]$Kind
    )
    $process = Get-ProcessInfo -ProcessId $ProcessId
    if ($null -eq $process) { return $false }
    if ($Kind -eq "backend") {
        return [string]::Equals(
            [IO.Path]::GetFullPath([string]$process.ExecutablePath),
            [IO.Path]::GetFullPath($backendExe),
            [StringComparison]::OrdinalIgnoreCase
        )
    }
    $commandLine = [string]$process.CommandLine
    return (
        [string]$process.Name -ieq "python.exe" -and
        $commandLine -match "uvicorn\s+app\.entrypoint:app" -and
        $commandLine -match "--port\s+8099"
    )
}

function Remove-TestFirewall {
    Get-NetFirewallRule -DisplayName $firewallRule -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule -ErrorAction SilentlyContinue
}

function Stop-TestStack {
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($entry in @(
                @{ Kind = "backend"; Port = 8080; ProcessId = [int]$state.backend_pid },
                @{ Kind = "worker"; Port = 8099; ProcessId = [int]$state.worker_pid }
            )) {
                if ($entry.ProcessId -le 0) { continue }
                $listenerPid = Get-ListenerPid -Port $entry.Port
                if ($listenerPid -eq $entry.ProcessId -and
                    (Test-RecordedProcess -ProcessId $entry.ProcessId -Kind $entry.Kind)) {
                    Stop-Process -Id $entry.ProcessId -Force -ErrorAction SilentlyContinue
                }
            }
        }
        catch {
            Write-Warning "Den gamle telefon-teststatus kunne ikke læses; ingen ukendt proces blev stoppet."
        }
        Remove-Item -LiteralPath $statePath -Force -ErrorAction SilentlyContinue
    }
    Remove-TestFirewall
    Write-Host "Telefon-teststacken er stoppet. Den isolerede pairing-store er bevaret." -ForegroundColor Green
}

function Assert-PortFree {
    param([int]$Port, [string]$Label)
    $processId = Get-ListenerPid -Port $Port
    if ($null -eq $processId) { return }
    $process = Get-ProcessInfo -ProcessId $processId
    $name = if ($process) { [string]$process.Name } else { "ukendt proces" }
    $path = if ($process) { [string]$process.ExecutablePath } else { "ukendt sti" }
    throw "$Label kan ikke startes: port $Port bruges af $name (proces $processId, $path). Luk den proces og kør launcheren igen."
}

function Resolve-LanAddress {
    $routes = @(
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -ne "0.0.0.0" } |
            Sort-Object RouteMetric, InterfaceMetric
    )
    foreach ($route in $routes) {
        $addresses = @(
            Get-NetIPAddress -AddressFamily IPv4 -InterfaceIndex $route.InterfaceIndex -ErrorAction SilentlyContinue |
                Where-Object {
                    $_.IPAddress -notmatch "^(127\.|169\.254\.)" -and
                    $_.AddressState -eq "Preferred"
                }
        )
        if ($addresses.Count -gt 0) {
            return [string]$addresses[0].IPAddress
        }
    }
    throw "Kunne ikke finde riggens aktive LAN-IP. Kontrollér at pc'en er på samme netværk som telefonen."
}

function Resolve-PlannerModel {
    if (-not [string]::IsNullOrWhiteSpace($PlannerModel)) { return $PlannerModel.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($env:KALIV_AGENT3_PLANNER_MODEL)) {
        return $env:KALIV_AGENT3_PLANNER_MODEL.Trim()
    }
    try {
        $tags = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 5
        $names = @($tags.models | ForEach-Object { [string]$_.name })
        foreach ($preferred in @("qwen3:14b", "qwen3:8b")) {
            if ($names -contains $preferred) { return $preferred }
        }
        $candidate = $names | Where-Object {
            $_ -and $_ -notmatch "embed" -and $_ -notmatch "^nomic-"
        } | Select-Object -First 1
        if ($candidate) { return [string]$candidate }
    }
    catch { }
    throw "Ollama svarer ikke, eller der findes ingen planner-model. Start Ollama og kør launcheren igen."
}

Assert-WindowsAdministrator
New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

if ($Stop) {
    Stop-TestStack
    return
}

# A previous run may have left only recorded test processes behind. Stop exactly
# those first; unrelated listeners are never killed by this launcher.
if (Test-Path -LiteralPath $statePath -PathType Leaf) {
    Stop-TestStack
}
Assert-PortFree -Port 8080 -Label "Backend"
Assert-PortFree -Port 8099 -Label "Worker"

$model = Resolve-PlannerModel
$lanAddress = Resolve-LanAddress
$lanUrl = "http://${lanAddress}:8080"

Remove-TestFirewall
New-NetFirewallRule `
    -DisplayName $firewallRule `
    -Direction Inbound `
    -Action Allow `
    -Protocol TCP `
    -LocalPort 8080 `
    -RemoteAddress LocalSubnet `
    -Profile Any | Out-Null

try {
    & (Join-Path $PSScriptRoot "start-stage-a-validation-stack.ps1") `
        -PlannerModel $model `
        -ValidationReport (Join-Path $repoRoot "validation\agent3-rig-validation-latest.json") `
        -BackendHost "0.0.0.0" `
        -PairingData $pairingDataPath `
        -EnableSchedulerApi

    $backendPid = Get-ListenerPid -Port 8080
    $workerPid = Get-ListenerPid -Port 8099
    if ($null -eq $backendPid -or $null -eq $workerPid) {
        throw "Telefon-teststacken startede ikke begge processer."
    }
    if (-not (Test-RecordedProcess -ProcessId $backendPid -Kind "backend")) {
        throw "Port 8080 ejes ikke af den forventede Stage A-backend."
    }
    if (-not (Test-RecordedProcess -ProcessId $workerPid -Kind "worker")) {
        throw "Port 8099 ejes ikke af den forventede Stage A-worker."
    }

    $health = Invoke-RestMethod -Uri "$lanUrl/healthz" -TimeoutSec 10
    if ($health.status -ne "ok") { throw "LAN-healthcheck returnerede ikke status=ok." }

    $pairing = Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:8080/api/v1/pair/start" `
        -TimeoutSec 10
    if ([string]::IsNullOrWhiteSpace([string]$pairing.code)) {
        throw "Backenden returnerede ingen parringskode."
    }

    $state = [ordered]@{
        schema = "kaliv-stage-a-phone-test-state/v1"
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        version = [string]$health.version
        lan_url = $lanUrl
        pairing_code = [string]$pairing.code
        pairing_expires_at = [string]$pairing.expires_at
        backend_pid = $backendPid
        worker_pid = $workerPid
        pairing_data = $pairingDataPath
        firewall_rule = $firewallRule
        production_activation = $false
    }
    $state | ConvertTo-Json -Depth 5 |
        Set-Content -LiteralPath $statePath -Encoding UTF8

    $instructions = @"
KALIV STAGE A - TELEFONFORBINDELSE

Server-URL:    $lanUrl
Parringskode:  $($pairing.code)
Udløber:       $($pairing.expires_at)
Version:       $($health.version)

I Kaliv:
1. Tryk Skift og vælg Rig.
2. Indsæt Server-URL'en ovenfor.
3. Indsæt parringskoden, også hvis appen allerede siger 'parret'.
4. Tryk Forbind.

Den nye kode er vigtig: den sikrer, at telefonens token hører til præcis
telefon-teststackens isolerede device-store og fjerner 401-fejlen.

Når testen er færdig, dobbeltklik STOP_STAGE_A_PHONE_TEST.cmd.
Ingen produktion er aktiveret.
"@
    Set-Content -LiteralPath $instructionPath -Value $instructions -Encoding UTF8

    Write-Host ""
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host "  KALIV TELEFON-TEST ER KLAR" -ForegroundColor Green
    Write-Host "===============================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Server-URL:   $lanUrl" -ForegroundColor Cyan
    Write-Host "  Parringskode: $($pairing.code)" -ForegroundColor Yellow
    Write-Host "  Version:      $($health.version)"
    Write-Host ""
    Write-Host "  Indtast koden i appen, også selv om den allerede siger 'parret'."
    Write-Host "  Derefter skal Forbind virke uden manuel tokenkopiering."
    Write-Host ""
    Write-Host "  Stop senere med: STOP_STAGE_A_PHONE_TEST.cmd"
    Write-Host "  Instruktion: $instructionPath"
    Write-Host ""
    Write-Host "  production_activation=false" -ForegroundColor DarkGray
}
catch {
    Stop-TestStack
    throw
}

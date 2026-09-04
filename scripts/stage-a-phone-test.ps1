[CmdletBinding()]
param(
    [string]$PlannerModel,
    [switch]$EnableSchedulerPilot,
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
        try {
            if ([string]::IsNullOrWhiteSpace([string]$process.ExecutablePath)) { return $false }
            return [string]::Equals(
                [IO.Path]::GetFullPath([string]$process.ExecutablePath),
                [IO.Path]::GetFullPath($backendExe),
                [StringComparison]::OrdinalIgnoreCase
            )
        }
        catch {
            return $false
        }
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
    Write-Host "Telefon-teststacken er stoppet. Isoleret pairing- og schedulerevidens er bevaret." -ForegroundColor Green
}

function Assert-PortFree {
    param([int]$Port, [string]$Label)
    $processId = Get-ListenerPid -Port $Port
    if ($null -eq $processId) { return }
    $process = Get-ProcessInfo -ProcessId $processId
    $name = if ($process) { [string]$process.Name } else { "ukendt proces" }
    $path = if ($process) { [string]$process.ExecutablePath } else { "ukendt sti" }

    # Stage A-wizarden starter SELV en validation-stack i trin 5/8 til de
    # automatiske beviser og river den ikke ned, foer telefon-testen skal bruge
    # de samme porte. Kampagnen kolliderede derfor med sig selv, og operatoeren
    # maatte lukke processen i haanden midt i en koersel -- tre gange 18/8.
    #
    # KUN vores EGEN runtime lukkes, og kun naar den ligger i dette repos
    # validation\stage-a-runtime. Alt andet paa porten er stadig en haard fejl:
    # en fremmed proces maa ikke stoppes af en test.
    $ownRuntime = (Join-Path $repoRoot "validation\stage-a-runtime").ToLowerInvariant()
    if ($path -and $path.ToLowerInvariant().StartsWith($ownRuntime)) {
        Write-Host "  Lukker vores egen stage-a-runtime paa port $Port (proces $processId)." -ForegroundColor Yellow
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Milliseconds 250
            if ($null -eq (Get-ListenerPid -Port $Port)) { return }
        }
        throw "$Label kan ikke startes: port $Port er stadig optaget efter at vores egen runtime blev lukket."
    }

    throw "$Label kan ikke startes: port $Port bruges af $name (proces $processId, $path). Luk den proces og kør launcheren igen."
}

function Resolve-LanAddress {
    $defaultInterfaces = @(
        Get-NetRoute -AddressFamily IPv4 -DestinationPrefix "0.0.0.0/0" -ErrorAction SilentlyContinue |
            Where-Object { $_.NextHop -ne "0.0.0.0" } |
            Sort-Object RouteMetric |
            ForEach-Object { [int]$_.InterfaceIndex }
    )
    $candidates = foreach ($address in @(
        Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
            Where-Object {
                $_.IPAddress -notmatch "^(127\.|169\.254\.)" -and
                $_.AddressState -eq "Preferred"
            }
    )) {
        $ip = [string]$address.IPAddress
        $alias = [string]$address.InterfaceAlias
        $score = 0
        if ($ip -match "^10\." -or
            $ip -match "^192\.168\." -or
            $ip -match "^172\.(1[6-9]|2[0-9]|3[01])\.") {
            $score += 200
        }
        if ($defaultInterfaces -contains [int]$address.InterfaceIndex) { $score += 100 }
        if ($alias -notmatch "(?i)tailscale|vethernet|wsl|hyper-v|docker|loopback") { $score += 50 }
        if ([string]$address.PrefixOrigin -eq "Dhcp") { $score += 10 }
        [pscustomobject]@{
            Address = $ip
            Alias = $alias
            Score = $score
        }
    }
    $selected = $candidates | Sort-Object Score -Descending | Select-Object -First 1
    if ($null -ne $selected) {
        Write-Host "  Valgt LAN-adresse: $($selected.Address) ($($selected.Alias))" -ForegroundColor DarkGray
        return [string]$selected.Address
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

function New-SchedulerApprovalSecret {
    $bytes = New-Object byte[] 48
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    }
    finally {
        $rng.Dispose()
    }
    return [Convert]::ToBase64String($bytes)
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
$schedulerDataDir = $null
$schedulerLogPath = $null
$schedulerSecretPath = $null
$schedulerSecret = $null

$stackArgs = @{
    PlannerModel = $model
    ValidationReport = (Join-Path $repoRoot "validation\agent3-rig-validation-latest.json")
    BackendHost = "0.0.0.0"
    PairingData = $pairingDataPath
}

if ($EnableSchedulerPilot) {
    $runId = Get-Date -Format "yyyyMMdd-HHmmss"
    $schedulerDataDir = Join-Path $runtimeDir "scheduler-pilot-$runId"
    $schedulerLogPath = Join-Path $schedulerDataDir "worker.log"
    $schedulerSecretPath = Join-Path $schedulerDataDir "approval-secret.txt"
    New-Item -ItemType Directory -Path $schedulerDataDir -Force | Out-Null
    $schedulerSecret = New-SchedulerApprovalSecret
    [IO.File]::WriteAllText($schedulerSecretPath, $schedulerSecret, [Text.Encoding]::ASCII)

    $stackArgs["EnableSchedulerApi"] = $true
    $stackArgs["EnableScheduler"] = $true
    $stackArgs["SchedulerDataDir"] = $schedulerDataDir
    $stackArgs["SchedulerApprovalSecret"] = $schedulerSecret
    $stackArgs["SchedulerPollSeconds"] = 5
    $stackArgs["WorkerLog"] = $schedulerLogPath
    $stackArgs["HeadlessWorker"] = $true
}

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
    & (Join-Path $PSScriptRoot "start-stage-a-validation-stack.ps1") @stackArgs

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

    $schedulerStatus = $null
    if ($EnableSchedulerPilot) {
        $schedulerStatus = Invoke-RestMethod -Uri "http://127.0.0.1:8099/schedules/status" -TimeoutSec 10
        if (-not $schedulerStatus.configured -or
            -not $schedulerStatus.running -or
            -not $schedulerStatus.resources_open -or
            -not [string]::IsNullOrWhiteSpace([string]$schedulerStatus.last_error)) {
            throw "Scheduler-stacken blev ikke klar: $($schedulerStatus | ConvertTo-Json -Compress)"
        }
    }

    $pairing = Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:8080/api/v1/pair/start" `
        -TimeoutSec 10
    if ([string]::IsNullOrWhiteSpace([string]$pairing.code)) {
        throw "Backenden returnerede ingen parringskode."
    }

    $state = [ordered]@{
        schema = "kaliv-stage-a-phone-test-state/v2"
        started_at = (Get-Date).ToUniversalTime().ToString("o")
        version = [string]$health.version
        lan_url = $lanUrl
        pairing_code = [string]$pairing.code
        pairing_expires_at = [string]$pairing.expires_at
        backend_pid = $backendPid
        worker_pid = $workerPid
        pairing_data = $pairingDataPath
        firewall_rule = $firewallRule
        scheduler = [ordered]@{
            enabled = [bool]$EnableSchedulerPilot
            configured = if ($schedulerStatus) { [bool]$schedulerStatus.configured } else { $false }
            running = if ($schedulerStatus) { [bool]$schedulerStatus.running } else { $false }
            resources_open = if ($schedulerStatus) { [bool]$schedulerStatus.resources_open } else { $false }
            data_dir = $schedulerDataDir
            worker_log = $schedulerLogPath
            approval_secret_file = $schedulerSecretPath
        }
        production_activation = $false
    }
    $state | ConvertTo-Json -Depth 8 |
        Set-Content -LiteralPath $statePath -Encoding UTF8

    $schedulerInstructions = if ($EnableSchedulerPilot) {
@"

Scheduler-pilotstack: KLAR
Isolerede data:       $schedulerDataDir
Worker-log:           $schedulerLogPath

Scheduleren og scheduler-API'et er kun aktiveret i denne isolerede teststack.
Selve pilotbeviset er endnu ikke gennemført.
"@
    }
    else {
@"

Scheduler-pilotstack: FRA
Den almindelige telefon/voice-test starter ingen scheduler.
"@
    }

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
$schedulerInstructions
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
    if ($EnableSchedulerPilot) {
        Write-Host "  Scheduler:    klar i isoleret testmappe" -ForegroundColor Green
        Write-Host "  Worker-log:   $schedulerLogPath"
    }
    else {
        Write-Host "  Scheduler:    fra" -ForegroundColor DarkGray
    }
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

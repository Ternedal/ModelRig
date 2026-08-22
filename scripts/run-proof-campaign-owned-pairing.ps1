[CmdletBinding()]
param(
  [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
  [int]$WorkflowRounds = 22,
  [double]$WorkflowThreshold = 0.95,
  [switch]$SkipStageA,
  [switch]$SkipForcedRecovery,
  [switch]$SkipWorkflows,
  [switch]$SkipT023,
  [switch]$SkipT033,
  [switch]$IncludeAgent4,
  [string]$Agent4OutputRoot = "",
  [string]$Agent4ApkPath = "",
  [string]$Agent4LanAddress = ""
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = '1'

function Invoke-Git([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args) {
  $gitExe = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $raw = & $gitExe @Args 2>&1
    $text = ($raw | ForEach-Object {
      if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { [string]$_ }
    }) -join "`n"
  } finally {
    $ErrorActionPreference = $previous
  }
  if ($LASTEXITCODE -ne 0) { throw $text }
  return $text.Trim()
}

function Get-FreeLoopbackPort {
  $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
  try {
    $listener.Start()
    return [int]([Net.IPEndPoint]$listener.LocalEndpoint).Port
  } finally {
    $listener.Stop()
  }
}

function New-RandomHex([int]$Bytes) {
  $buffer = New-Object byte[] $Bytes
  $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
  try { $rng.GetBytes($buffer) } finally { $rng.Dispose() }
  return (($buffer | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Wait-BootstrapHealth([string]$Url, [Diagnostics.Process]$Process, [int]$Seconds = 45) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  do {
    if ($Process.HasExited) {
      throw "Den ejede pairing-backend stoppede før healthz blev klar (exit $($Process.ExitCode))."
    }
    try {
      $health = Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec 2
      if ($null -ne $health) { return $health }
    } catch { }
    Start-Sleep -Milliseconds 300
  } while ((Get-Date) -lt $deadline)
  throw "Den ejede pairing-backend blev ikke klar: $Url"
}

function Restore-EnvValue([string]$Name, [string]$Value, [bool]$WasPresent) {
  if ($WasPresent) {
    [Environment]::SetEnvironmentVariable($Name, $Value, 'Process')
  } else {
    Remove-Item ("Env:" + $Name) -ErrorAction SilentlyContinue
  }
}

if ($env:OS -ne 'Windows_NT') { throw 'Beviskampagnen må kun køres på Windows-riggen.' }
foreach ($cmd in @('git','python','powershell.exe','go','ollama')) {
  if (-not (Get-Command $cmd -CommandType Application -ErrorAction SilentlyContinue)) {
    throw "$cmd mangler på PATH."
  }
}

# Bind bootstrapen til et eksakt, rent remote head før der bygges eller mintes noget.
$dirty = Invoke-Git status --porcelain
if ($dirty) { throw "Working tree skal være helt rent:`n$dirty" }
$branch = Invoke-Git branch --show-current
if ([string]::IsNullOrWhiteSpace($branch)) { throw 'Detached HEAD afvises.' }
Invoke-Git fetch --quiet origin $branch | Out-Null
Invoke-Git pull --ff-only origin $branch | Out-Null
$sha = Invoke-Git rev-parse HEAD
if ($sha -ne (Invoke-Git rev-parse "origin/$branch")) { throw 'HEAD matcher ikke remote.' }
$version = (Get-Content VERSION -Raw).Trim()

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$bootstrapDir = Join-Path $root ("validation\proof-bootstrap\{0}-{1}" -f $stamp, $sha.Substring(0,12))
New-Item -ItemType Directory -Path $bootstrapDir -Force | Out-Null
$backendExe = Join-Path $bootstrapDir 'modelrig-server-proof-pairing.exe'
$pairingStore = Join-Path $bootstrapDir 'pairing-data.json'
$stdoutLog = Join-Path $bootstrapDir 'backend.stdout.log'
$stderrLog = Join-Path $bootstrapDir 'backend.stderr.log'

Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host '  MODELRIG — EJET LOOPBACK-PARRING TIL FYSISK PROOF' -ForegroundColor Cyan
Write-Host '============================================================================' -ForegroundColor Cyan
Write-Host "  Kandidat: $version | $sha | $branch" -ForegroundColor DarkGray
Write-Host '  Pairing bootstrap bruger separat loopback-port og separat midlertidig store.' -ForegroundColor DarkGray
Write-Host '  Eksisterende listeners på 8080/8099 røres ikke af bootstrapen.' -ForegroundColor DarkGray

Push-Location (Join-Path $root 'backend')
try {
  & go build -o $backendExe .\cmd\modelrig-server
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke bygge exact-head pairing-backend.' }
} finally {
  Pop-Location
}

$bootstrapPort = Get-FreeLoopbackPort
$bootstrapAdminKey = New-RandomHex 32
$bootstrap = $null
$proofToken = $null
$coreExit = 1

$oldHostPresent = Test-Path Env:MODELRIG_HOST
$oldHost = [string]$env:MODELRIG_HOST
$oldPortPresent = Test-Path Env:MODELRIG_PORT
$oldPort = [string]$env:MODELRIG_PORT
$oldDataPresent = Test-Path Env:MODELRIG_DATA
$oldData = [string]$env:MODELRIG_DATA
$oldAdminPresent = Test-Path Env:MODELRIG_ADMIN_KEY
$oldAdmin = [string]$env:MODELRIG_ADMIN_KEY
$oldTokenPresent = Test-Path Env:MODELRIG_TOKEN
$oldToken = [string]$env:MODELRIG_TOKEN

try {
  $env:MODELRIG_HOST = '127.0.0.1'
  $env:MODELRIG_PORT = [string]$bootstrapPort
  $env:MODELRIG_DATA = $pairingStore
  $env:MODELRIG_ADMIN_KEY = $bootstrapAdminKey
  Remove-Item Env:MODELRIG_TOKEN -ErrorAction SilentlyContinue

  $bootstrap = Start-Process -FilePath $backendExe -WorkingDirectory $bootstrapDir -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $stdoutLog -RedirectStandardError $stderrLog

  $baseUrl = "http://127.0.0.1:$bootstrapPort"
  $health = Wait-BootstrapHealth -Url "$baseUrl/healthz" -Process $bootstrap
  if ([string]$health.version -ne $version) {
    throw "Pairing-backenden er version $($health.version), forventede exact-head version $version."
  }

  $headers = @{ 'X-Admin-Key' = $bootstrapAdminKey }
  $pair = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/pair/start" -Headers $headers -TimeoutSec 10
  $code = [string]$pair.code
  if ([string]::IsNullOrWhiteSpace($code)) { throw 'Pairing-start returnerede ingen engangskode.' }

  $claimBody = @{
    device_name = "proof-campaign-$env:COMPUTERNAME"
    code = $code
  } | ConvertTo-Json -Compress
  $claim = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/v1/pair/claim" `
    -ContentType 'application/json' -Body $claimBody -TimeoutSec 10
  $proofToken = [string]$claim.token
  if ($proofToken -notmatch '^[0-9a-fA-F]{64}$') {
    throw 'Pairing-claim returnerede ikke et gyldigt 64-hex device-token.'
  }

  Write-Host '  PASS: device-token mintet via /pair/start → /pair/claim; tokenet vises eller skrives ikke.' -ForegroundColor Green
} finally {
  # Bootstrap-oprydning er PID-ejet: vi stopper kun den proces, vi selv fik fra Start-Process -PassThru.
  if ($null -ne $bootstrap) {
    try {
      if (-not $bootstrap.HasExited) {
        Stop-Process -Id $bootstrap.Id -Force -ErrorAction Stop
        $bootstrap.WaitForExit(5000) | Out-Null
      }
    } catch {
      Write-Warning "Kunne ikke stoppe den ejede pairing-backend PID $($bootstrap.Id): $($_.Exception.Message)"
    }
  }
  Restore-EnvValue 'MODELRIG_HOST' $oldHost $oldHostPresent
  Restore-EnvValue 'MODELRIG_PORT' $oldPort $oldPortPresent
  Restore-EnvValue 'MODELRIG_ADMIN_KEY' $oldAdmin $oldAdminPresent
}

if ($proofToken -notmatch '^[0-9a-fA-F]{64}$') {
  Restore-EnvValue 'MODELRIG_DATA' $oldData $oldDataPresent
  Restore-EnvValue 'MODELRIG_TOKEN' $oldToken $oldTokenPresent
  throw 'Proof-token blev ikke etableret; core-kampagnen startes ikke.'
}

# Core arver kun den isolerede store og det mintede token. Den normale proof-engine
# ejer fortsat ALLE evidensgates, skip/reuse-semantikker og fysiske attesteringer.
$env:MODELRIG_DATA = $pairingStore
$env:MODELRIG_TOKEN = $proofToken
$coreArgs = @(
  '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run-proof-campaign.ps1'),
  '-PlannerModel',$PlannerModel,
  '-WorkflowRounds',[string]$WorkflowRounds,
  '-WorkflowThreshold',[string]$WorkflowThreshold
)
if ($SkipStageA) { $coreArgs += '-SkipStageA' }
if ($SkipForcedRecovery) { $coreArgs += '-SkipForcedRecovery' }
if ($SkipWorkflows) { $coreArgs += '-SkipWorkflows' }
if ($SkipT023) { $coreArgs += '-SkipT023' }
if ($SkipT033) { $coreArgs += '-SkipT033' }
if ($IncludeAgent4) { $coreArgs += '-IncludeAgent4' }
if (-not [string]::IsNullOrWhiteSpace($Agent4OutputRoot)) { $coreArgs += @('-Agent4OutputRoot',$Agent4OutputRoot) }
if (-not [string]::IsNullOrWhiteSpace($Agent4ApkPath)) { $coreArgs += @('-Agent4ApkPath',$Agent4ApkPath) }
if (-not [string]::IsNullOrWhiteSpace($Agent4LanAddress)) { $coreArgs += @('-Agent4LanAddress',$Agent4LanAddress) }

try {
  & powershell.exe @coreArgs
  $coreExit = $LASTEXITCODE
} finally {
  # Device-tokenet har kun levet i denne procesfamilie; pairing-store indeholder kun hash.
  $proofToken = $null
  Restore-EnvValue 'MODELRIG_TOKEN' $oldToken $oldTokenPresent
  Restore-EnvValue 'MODELRIG_DATA' $oldData $oldDataPresent
  try {
    if (Test-Path -LiteralPath $pairingStore -PathType Leaf) {
      Remove-Item -LiteralPath $pairingStore -Force -ErrorAction Stop
    }
  } catch {
    Write-Warning "Den isolerede pairing-store kunne ikke slettes efter proof-kørslen: $($_.Exception.Message)"
  }
}

exit $coreExit

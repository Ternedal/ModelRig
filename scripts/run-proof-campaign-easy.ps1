[CmdletBinding()]
param(
  [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
  [int]$WorkflowRounds = 22,
  [double]$WorkflowThreshold = 0.95,
  [switch]$SkipT023,
  [switch]$SkipT033
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = '1'

function Git([Parameter(ValueFromRemainingArguments=$true)][string[]]$A) {
  $previousErrorActionPreference = $ErrorActionPreference
  $v = ''
  $code = -1
  try {
    $ErrorActionPreference = 'Continue'
    $v = (& git.exe @A 2>&1 | ForEach-Object { $_.ToString() }) -join "`n"
    $code = $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $previousErrorActionPreference
  }
  if ($code -ne 0) { throw $v }
  return $v.Trim()
}

function Ensure-Ollama {
  try {
    return @((Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 5).models.name)
  } catch {
    Write-Host '  Starter Ollama...' -ForegroundColor DarkGray
    Start-Process ollama -ArgumentList 'serve' | Out-Null
    $deadline = (Get-Date).AddSeconds(30)
    do {
      Start-Sleep -Milliseconds 750
      try { return @((Invoke-RestMethod 'http://127.0.0.1:11434/api/tags' -TimeoutSec 3).models.name) } catch { }
    } while ((Get-Date) -lt $deadline)
    throw 'Ollama blev startet, men API-et blev ikke klar på 127.0.0.1:11434.'
  }
}

function Resolve-Planner([object[]]$Models) {
  if (-not [string]::IsNullOrWhiteSpace($PlannerModel)) { return $PlannerModel.Trim() }
  foreach ($m in @('qwen3:14b','qwen3:8b','qwen2.5:14b','hermes3:8b')) {
    if ($Models -contains $m) { return $m }
  }
  Write-Host '  Ingen planner-model fundet; henter qwen3:8b automatisk...' -ForegroundColor Yellow
  & ollama pull qwen3:8b
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke hente qwen3:8b.' }
  return 'qwen3:8b'
}

function New-LocalProofToken([string]$ExpectedVersion) {
  $health = Invoke-RestMethod 'http://127.0.0.1:8080/healthz' -TimeoutSec 10
  if ([string]$health.version -ne $ExpectedVersion) {
    throw "Den lokale test-backend er version $($health.version), forventede $ExpectedVersion."
  }
  $pair = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/api/v1/pair/start' -TimeoutSec 10
  if ([string]::IsNullOrWhiteSpace([string]$pair.code)) { throw 'Pairing-endpoint returnerede ingen kode.' }
  $body = @{
    device_name = "proof-campaign-$env:COMPUTERNAME"
    code = [string]$pair.code
  } | ConvertTo-Json -Compress
  $claim = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8080/api/v1/pair/claim' -ContentType 'application/json' -Body $body -TimeoutSec 10
  $token = [string]$claim.token
  if ($token -notmatch '^[0-9a-fA-F]{64}$') { throw 'Pairing-flowet returnerede ikke et gyldigt device-token.' }
  $env:MODELRIG_TOKEN = $token
  Write-Host '  Device-token: oprettet automatisk via lokal loopback-parring (vises/gemmes ikke).' -ForegroundColor Green
}

if ($env:OS -ne 'Windows_NT') { throw 'Beviskampagnen må kun køres på Windows-riggen.' }
foreach ($cmd in @('git','python','powershell.exe','go','ollama')) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd mangler på PATH." }
}

$dirty = Git status --porcelain
if ($dirty) { throw "Working tree skal være helt rent:`n$dirty" }
$branch = Git branch --show-current
if (-not $branch) { throw 'Detached HEAD afvises.' }
Git fetch --quiet origin $branch | Out-Null
Git pull --ff-only origin $branch | Out-Null
$sha = Git rev-parse HEAD
if ($sha -ne (Git rev-parse "origin/$branch")) { throw 'HEAD matcher ikke remote.' }
$version = (Get-Content VERSION -Raw).Trim()

$models = Ensure-Ollama
$PlannerModel = Resolve-Planner $models
if (-not ($models | Where-Object { $_ -eq 'nomic-embed-text' -or $_ -like 'nomic-embed-text:*' })) {
  Write-Host '  Henter nomic-embed-text automatisk...' -ForegroundColor Yellow
  & ollama pull nomic-embed-text
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke hente nomic-embed-text.' }
}
$env:KALIV_AGENT3_PLANNER_MODEL = $PlannerModel

$runtime = Join-Path $root 'validation\stage-a-runtime'
New-Item -ItemType Directory -Path $runtime -Force | Out-Null
$pairingData = Join-Path $runtime 'proof-campaign-pairing-data.json'
$env:MODELRIG_DATA = $pairingData
$cleanup = Join-Path $PSScriptRoot 'stop-stage-a-known-processes.ps1'
$stack = Join-Path $PSScriptRoot 'start-stage-a-validation-stack.ps1'
$bootstrapStarted = $false

Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host '  AUTOMATISK KLARGØRING — INGEN MANUEL TOKEN' -ForegroundColor Cyan
Write-Host '============================================================================' -ForegroundColor Cyan
try {
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleanup
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke rydde en kendt Stage A-teststack.' }

  Remove-Item -LiteralPath $pairingData -Force -ErrorAction SilentlyContinue
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $stack `
      -PlannerModel $PlannerModel `
      -ValidationReport (Join-Path $root 'validation\agent3-rig-validation-latest.json') `
      -BackendHost 127.0.0.1 `
      -PairingData $pairingData `
      -HeadlessWorker
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke starte bootstrap-stacken til lokal pairing.' }
  $bootstrapStarted = $true

  New-LocalProofToken -ExpectedVersion $version
} finally {
  if ($bootstrapStarted) {
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $cleanup
    if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke lukke bootstrap-stacken igen.' }
  }
}

$coreArgs = @(
  '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run-proof-campaign.ps1'),
  '-PlannerModel',$PlannerModel,
  '-WorkflowRounds',[string]$WorkflowRounds,
  '-WorkflowThreshold',[string]$WorkflowThreshold
)
if ($SkipT023) { $coreArgs += '-SkipT023' }
if ($SkipT033) { $coreArgs += '-SkipT033' }

try {
  & powershell.exe @coreArgs
  $rc = $LASTEXITCODE
} finally {
  # Tokenet lever kun i denne procesfamilie. Det vises aldrig og gemmes ikke af wrapperen.
  Remove-Item Env:MODELRIG_TOKEN -ErrorAction SilentlyContinue
}
exit $rc

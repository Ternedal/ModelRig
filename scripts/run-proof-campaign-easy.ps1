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
  $v = (& git @A 2>&1) -join "`n"
  if ($LASTEXITCODE -ne 0) { throw $v }
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

function Prepare-T033SecondUser([string]$Sha, [string]$Branch) {
  $states = Get-ChildItem (Join-Path $root 'validation\agent3-memory-protected-backup-physical') -Filter state.json -Recurse -ErrorAction SilentlyContinue |
    Sort-Object LastWriteTime -Descending
  $state = $null; $stateJson = $null
  foreach ($candidate in $states) {
    try {
      $j = Get-Content $candidate.FullName -Raw | ConvertFrom-Json
      if ([string]$j.candidate.git_sha -eq $Sha) { $state = $candidate; $stateJson = $j; break }
    } catch { }
  }
  if ($null -eq $state -or $null -eq $stateJson) { return $null }

  $request = [string]$stateJson.probe_request.public_request_path
  $probe = [string]$stateJson.probe_request.public_probe_path
  if ([string]::IsNullOrWhiteSpace($request) -or [string]::IsNullOrWhiteSpace($probe)) { return $null }

  $publicDocs = Join-Path $env:PUBLIC 'Documents\Kaliv-T033'
  $publicRepo = Join-Path $publicDocs ("candidate-" + $Sha.Substring(0,12))
  New-Item -ItemType Directory -Path $publicDocs -Force | Out-Null
  if (-not (Test-Path (Join-Path $publicRepo '.git'))) {
    if (Test-Path $publicRepo) { Remove-Item $publicRepo -Recurse -Force }
    Write-Host '  Forbereder en lokal, netværksfri kandidatkopi til den anden Windows-bruger...' -ForegroundColor DarkGray
    & git clone --quiet --local --no-hardlinks $root $publicRepo
    if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke lave den lokale T-033-kandidatkopi.' }
  }
  & git -C $publicRepo checkout --quiet -B $Branch $Sha
  if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke låse T-033-kandidatkopien til exact SHA.' }

  $desktop = Join-Path $env:PUBLIC 'Desktop'
  New-Item -ItemType Directory -Path $desktop -Force | Out-Null
  $launcher = Join-Path $desktop 'MODELRIG_T033_ANDEN_BRUGER.cmd'
  $content = @"
@echo off
setlocal
title ModelRig T-033 - anden Windows-bruger
echo ==============================================================
echo   MODELRIG T-033 - KUN DET UUNDGAAELIGE ANDEN-BRUGER-TRIN
echo ==============================================================
echo.
echo Denne fil bruger den ANDEN brugers egen Python via py.exe eller PATH.
echo Den bruger ingen GitHub-login og kandidaten er allerede laast til exact SHA.
echo.
where py >nul 2>&1
if "%ERRORLEVEL%"=="0" (
  py -3 "$publicRepo\scripts\proof_t033_current.py" probe --request "$request" --output "$probe"
) else (
  where python >nul 2>&1
  if not "%ERRORLEVEL%"=="0" (
    echo FEJL: Python findes ikke for denne Windows-bruger.
    echo Installer/aktiver Python for brugeren og dobbeltklik denne fil igen.
    pause
    exit /b 2
  )
  python "$publicRepo\scripts\proof_t033_current.py" probe --request "$request" --output "$probe"
)
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo PASS: Gaa tilbage til din normale Windows-konto og dobbeltklik START_PROOF_CAMPAIGN.cmd igen.
if not "%RC%"=="0" echo PROBEN BESTOD IKKE. Lad vinduet staa og tag fejlteksten med tilbage.
echo.
pause
exit /b %RC%
"@
  Set-Content -LiteralPath $launcher -Value $content -Encoding ASCII
  return $launcher
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

Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host '  AUTOMATISK KLARGØRING — INGEN TOKEN-KOPIERING' -ForegroundColor Cyan
Write-Host '============================================================================' -ForegroundColor Cyan
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stop-stage-a-known-processes.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke rydde en kendt Stage A-teststack.' }
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'start-stage-a-validation-stack.ps1') -PlannerModel $PlannerModel -ValidationReport (Join-Path $root 'validation\agent3-rig-validation-latest.json') -BackendHost 127.0.0.1 -PairingData $pairingData -HeadlessWorker
if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke starte bootstrap-stacken til lokal pairing.' }
New-LocalProofToken -ExpectedVersion $version
& powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'stop-stage-a-known-processes.ps1')
if ($LASTEXITCODE -ne 0) { throw 'Kunne ikke lukke bootstrap-stacken igen.' }

$coreArgs = @(
  '-NoProfile','-ExecutionPolicy','Bypass','-File',(Join-Path $PSScriptRoot 'run-proof-campaign.ps1'),
  '-PlannerModel',$PlannerModel,
  '-WorkflowRounds',[string]$WorkflowRounds,
  '-WorkflowThreshold',[string]$WorkflowThreshold
)
if ($SkipT023) { $coreArgs += '-SkipT023' }
if ($SkipT033) { $coreArgs += '-SkipT033' }

& powershell.exe @coreArgs
$rc = $LASTEXITCODE

if ($rc -eq 3) {
  try {
    $launcher = Prepare-T033SecondUser -Sha $sha -Branch $branch
    if ($launcher) {
      Write-Host "`n============================================================================" -ForegroundColor Yellow
      Write-Host '  SIDSTE TRUST-BOUND: ANDEN WINDOWS-BRUGER' -ForegroundColor Yellow
      Write-Host '============================================================================' -ForegroundColor Yellow
      Write-Host '  1. Skift til en anden Windows-konto på denne pc.'
      Write-Host '  2. Dobbeltklik denne fil på det offentlige skrivebord:'
      Write-Host "     $launcher" -ForegroundColor Cyan
      Write-Host '  3. Gå tilbage til din normale konto og dobbeltklik START_PROOF_CAMPAIGN.cmd igen.'
      Start-Process explorer.exe -ArgumentList "/select,`"$launcher`"" | Out-Null
    }
  } catch {
    Write-Warning "Kunne ikke bygge one-click T-033-hjælperen: $($_.Exception.Message)"
  }
}

# Tokenet lever kun i denne procesfamilie. Core-testen har arvet det; det skrives aldrig til disk.
Remove-Item Env:MODELRIG_TOKEN -ErrorAction SilentlyContinue
exit $rc

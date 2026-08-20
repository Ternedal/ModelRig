[CmdletBinding()]
param(
  [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
  [int]$WorkflowRounds = 22,
  [double]$WorkflowThreshold = 0.95,
  [switch]$SkipT023,
  [switch]$SkipT033,
  # Agent 4's fysiske kvalifikation (a4-25f). Suiten har ligget i repoet uden
  # at vaere koblet paa noget: kampagnen kaldte ikke eet eneste agent4-script,
  # saa de tre stderr-defekter i den var latente indtil 19/8. Den er
  # OPT-IN, fordi den kraever A425f-appen parret paa enheden een gang.
  [switch]$IncludeAgent4,
  [string]$Agent4OutputRoot = "$env:USERPROFILE\modelrig-a4-25f-evidence"
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
$env:PYTHONDONTWRITEBYTECODE = '1'
function Run([string]$Label, [scriptblock]$Action) {
  Write-Host "`n============================================================================" -ForegroundColor Cyan
  Write-Host "  $Label" -ForegroundColor Cyan
  Write-Host "============================================================================" -ForegroundColor Cyan
  & $Action
  if ($LASTEXITCODE -ne 0) { throw "$Label fejlede med exitkode $LASTEXITCODE" }
}
# git.exe opløses EKSPLICIT som Application. PowerShell opløser funktioner FØR
# eksterne programmer, saa "& git" inde i en funktion ved navn Git kalder sig
# selv -> CallDepthOverflow paa foerste kald. Launcheren koerer med -NoProfile,
# saa en brugerdefineret git-alias redder den ikke. Reproduceret 18/8.
$script:GitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue |
                  Select-Object -First 1).Source
if (-not $script:GitExe) { throw 'git mangler paa PATH.' }
# git skriver normal fremdrift til STDERR ("From https://...", ogsaa med
# --quiet). Med $ErrorActionPreference='Stop' og 2>&1 bliver de linjer til
# ErrorRecords i Windows PowerShell og udloeser NativeCommandError -- selv naar
# git returnerer 0. Derfor saenkes preferencen omkring selve kaldet, og
# ErrorRecords flades til tekst. EXITKODEN er verdiktet, ikke stderr.
function Git([Parameter(ValueFromRemainingArguments=$true)][string[]]$A) {
  $prev = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    $raw = & $script:GitExe @A 2>&1
    $v = ($raw | ForEach-Object {
      if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.ToString() } else { $_ }
    }) -join "`n"
  } finally { $ErrorActionPreference = $prev }
  if ($LASTEXITCODE -ne 0) { throw $v }
  return $v.Trim()
}
if ($env:OS -ne 'Windows_NT') { throw 'Beviskampagnen må kun køres på Windows-riggen.' }
# -CommandType Application: uden den finder Get-Command 'git' funktionen
# ovenfor, og tjekket kan aldrig fyre for netop det program det skal beskytte.
foreach ($cmd in @('git','python','powershell.exe','go','ollama')) {
  if (-not (Get-Command $cmd -CommandType Application -ErrorAction SilentlyContinue)) {
    throw "$cmd mangler på PATH."
  }
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
if ([string]::IsNullOrWhiteSpace($env:MODELRIG_TOKEN)) {
  $secure = Read-Host 'MODELRIG_TOKEN (skjult; gemmes ikke)' -AsSecureString
  $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
  try { $env:MODELRIG_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
  finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}
if ($env:MODELRIG_TOKEN -notmatch '^[0-9a-fA-F]{64}$') { throw 'MODELRIG_TOKEN skal være 64 hex-tegn.' }
try { $models = (Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 5).models.name } catch {
  Start-Process ollama -ArgumentList 'serve'; Start-Sleep 3
  $models = (Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 10).models.name
}
if (-not $PlannerModel) {
  foreach ($m in @('qwen3:14b','qwen3:8b','qwen2.5:14b','hermes3:8b')) { if ($models -contains $m) { $PlannerModel=$m; break } }
}
if (-not $PlannerModel) { & ollama pull qwen3:8b; if ($LASTEXITCODE) { throw 'Kunne ikke hente qwen3:8b.' }; $PlannerModel='qwen3:8b' }
if (-not ($models | Where-Object { $_ -eq 'nomic-embed-text' -or $_ -like 'nomic-embed-text:*' })) { & ollama pull nomic-embed-text; if ($LASTEXITCODE) { throw 'Kunne ikke hente nomic-embed-text.' } }
$env:KALIV_AGENT3_PLANNER_MODEL = $PlannerModel
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $root "validation\proof-campaign\$stamp-$($sha.Substring(0,12))"
$logs = Join-Path $out 'logs'; New-Item -ItemType Directory -Force $logs | Out-Null
Write-Host "`nModelRig $version | $sha | $branch | planner=$PlannerModel" -ForegroundColor Green
Run 'Stage A: samlet fysisk kampagne' { python scripts\proof_stage_a_current.py }
Run 'T-006: ægte hard-process recovery og lease recovery' { python scripts\forced_recovery_test.py }
Run 'Ryd runtime før workflow-bevis' { python scripts\stage_a_resume_cleanup.py }
Run 'Start exact-head stack til workflows' { powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start-stage-a-validation-stack.ps1 -PlannerModel $PlannerModel -ValidationReport validation\agent3-rig-validation-latest.json -BackendHost 127.0.0.1 -HeadlessWorker }
$rates = @(); $workflowFailures = 0
for ($i=1; $i -le $WorkflowRounds; $i++) {
  Write-Host "`n--- Workflow-run $i/$WorkflowRounds ---" -ForegroundColor Cyan
  & python scripts\workflow_baseline_one_click.py --model $PlannerModel
  if ($LASTEXITCODE -ne 0) { $workflowFailures++ }
  $src='validation\workflow-baseline-latest.json'; $raw='validation\workflow-run-latest.json'
  if (Test-Path $src) {
    Copy-Item $src (Join-Path $out ("workflow-baseline-{0:D2}.json" -f $i)) -Force
    $j=Get-Content $src -Raw | ConvertFrom-Json
    # Set-StrictMode goer $j.completion_rate til en KASTENDE fejl naar feltet
    # ikke findes -- ikke til $null. Derfor naaede elseif'en aldrig at proeve
    # summary-varianten, og kampagnen doede EFTER en gyldig maaling: 20/8 stod
    # der 10/14 paa skaermen, og saa faldt scriptet over sin egen aflaesning.
    # PSObject.Properties spoerger uden at kaste.
    $cr = $null
    if ($j.PSObject.Properties.Name -contains 'completion_rate') { $cr = $j.completion_rate }
    elseif (($j.PSObject.Properties.Name -contains 'summary') -and
            ($null -ne $j.summary) -and
            ($j.summary.PSObject.Properties.Name -contains 'completion_rate')) { $cr = $j.summary.completion_rate }
    if ($null -ne $cr) { $rates += [double]$cr }
  }
  if (Test-Path $raw) { Copy-Item $raw (Join-Path $out ("workflow-run-{0:D2}.json" -f $i)) -Force }
}
$mean = if ($rates.Count) { ($rates | Measure-Object -Average).Average } else { 0.0 }
$workflowPass = ($rates.Count -eq $WorkflowRounds -and $workflowFailures -eq 0 -and $mean -ge $WorkflowThreshold)
@{schema='modelrig-workflow-proof/v1';sha=$sha;rounds=$WorkflowRounds;executions=$WorkflowRounds*14;mean_completion_rate=$mean;threshold=$WorkflowThreshold;runner_failures=$workflowFailures;passed=$workflowPass} | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out 'workflow-aggregate.json') -Encoding UTF8
if (-not $workflowPass) { Write-Warning "Workflow-gaten er rød: mean=$mean failures=$workflowFailures" }
$t23pass=$true
if (-not $SkipT023) {
  Run 'Cleanup før T-023' { python scripts\stage_a_resume_cleanup.py }
  & python scripts\proof_t023_current.py
  $t23pass = ($LASTEXITCODE -eq 0)
  if (-not $t23pass) { Write-Warning 'T-023 er ikke grønt.' }
}
$t33pass=$true; $t33pending=$false
if (-not $SkipT033) {
  $latest='validation\agent3-memory-protected-backup-physical-latest.json'
  $validLatest=$false
  if (Test-Path $latest) { try { $lj=Get-Content $latest -Raw|ConvertFrom-Json; $validLatest=($lj.success -eq $true -and $lj.candidate.git_sha -eq $sha) } catch {} }
  if (-not $validLatest) {
    $states=Get-ChildItem 'validation\agent3-memory-protected-backup-physical' -Filter state.json -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    $state=$null
    foreach($s in $states){ try{$sj=Get-Content $s.FullName -Raw|ConvertFrom-Json;if($sj.candidate.git_sha -eq $sha){$state=$s;$stateJson=$sj;break}}catch{} }
    if ($state -and (Test-Path $stateJson.probe_request.public_probe_path)) {
      & python scripts\proof_t033_current.py collect --state $state.FullName --probe $stateJson.probe_request.public_probe_path
      $t33pass=($LASTEXITCODE -eq 0)
    } elseif ($state) {
      $t33pass=$false;$t33pending=$true
      Write-Host "`nT-033 mangler kun en anden Windows-SID. Kør fra den anden bruger:" -ForegroundColor Yellow
      Write-Host "python `"$root\scripts\proof_t033_current.py`" probe --request `"$($stateJson.probe_request.public_request_path)`" --output `"$($stateJson.probe_request.public_probe_path)`""
      Write-Host 'Kør derefter START_PROOF_CAMPAIGN.cmd igen; collect sker automatisk.' -ForegroundColor Yellow
    } else {
      & python scripts\proof_t033_current.py prepare
      if ($LASTEXITCODE -eq 0) { $t33pending=$true; $t33pass=$false } else { $t33pass=$false }
    }
  }
}
$a4pass = $null
if ($IncludeAgent4) {
  # RunMatrix er FULDAUTOMATISK: den driver adb, koerer mutationerne, fanger
  # snapshot-stadierne og haevder invarianterne i kode. Det eneste manuelle er
  # eengangs-parringen af A425f-appen mellem Prepare og DeviceInfo.
  $a4 = 'scripts\agent4_a4_25f_physical_operator.ps1'
  $a4args = @('-ExpectedSha', $sha, '-OutputRoot', $Agent4OutputRoot)
  try {
    Run 'Agent 4 (a4-25f): forbered fixture og stack' {
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 Prepare @a4args
    }
    Write-Host "`n  Par A425f-appen paa enheden nu, og tryk derefter Enter." -ForegroundColor Yellow
    [void](Read-Host)
    Run 'Agent 4: enhedsoplysninger' {
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 DeviceInfo @a4args
    }
    Run 'Agent 4: grant (agent4:read, pr. enhed)' {
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 Grant @a4args
    }
    Run 'Agent 4: koer matrix (automatisk)' {
      powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 RunMatrix @a4args
    }
    Run 'Agent 4: finalisér evidens' {
      python scripts\agent4_a4_25f_finalize_evidence.py --output-root $Agent4OutputRoot --expected-sha $sha
    }
    $a4pass = $true
  } catch {
    Write-Host "  Agent 4-kvalifikationen stoppede: $_" -ForegroundColor Yellow
    $a4pass = $false
  } finally {
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 Stop @a4args 2>$null | Out-Null
  }
}

# Agent 4 taeller IKKE med i $passed. Suiten er ny i kampagnen, den er opt-in,
# og dens evidens har endnu ingen validator i campaign-kontrakten. At lade den
# loefte et samlet PASS ville vaere den slags falske groenne repoet er bygget
# for at undgaa. Den rapporteres for sig.
$passed = $workflowPass -and $t23pass -and $t33pass
$summary=@{schema='modelrig-proof-day/v1';generated_at=(Get-Date).ToUniversalTime().ToString('o');candidate=@{version=$version;sha=$sha;branch=$branch};planner=$PlannerModel;stage_a=$true;forced_recovery=$true;workflow=@{passed=$workflowPass;rounds=$WorkflowRounds;executions=$WorkflowRounds*14;mean=$mean};t023=$t23pass;t033=@{passed=$t33pass;pending_second_sid=$t33pending};agent4_a4_25f=@{included=[bool]$IncludeAgent4;passed=$a4pass;counts_toward_passed=$false;output_root=$Agent4OutputRoot};stage_b_release_lifecycle=@{included=$false;reason='requires exact candidate to exist as a published release and rig to start on previous release; never inferred from source-only run'};passed=$passed;production_activation=$false}
$summary|ConvertTo-Json -Depth 8|Set-Content (Join-Path $out 'summary.json') -Encoding UTF8
Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host "  RESULTAT: $(if($passed){'PASS'}else{'IKKE FULDT BEVIST ENDNU'})" -ForegroundColor $(if($passed){'Green'}else{'Yellow'})
Write-Host "  Evidence: $out"
Write-Host "  Workflow: $($WorkflowRounds*14) executioner, mean=$mean"
Write-Host "  Stage B updater/reboot: separat release-bound gate; bliver aldrig fake-grøn her."
Write-Host "============================================================================"
if ($passed) { exit 0 }; if ($t33pending -and $workflowPass -and $t23pass) { exit 3 }; exit 1

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
function Run([string]$Label, [scriptblock]$Action) {
  Write-Host "`n============================================================================" -ForegroundColor Cyan
  Write-Host "  $Label" -ForegroundColor Cyan
  Write-Host "============================================================================" -ForegroundColor Cyan
  & $Action
  if ($LASTEXITCODE -ne 0) { throw "$Label fejlede med exitkode $LASTEXITCODE" }
}
function Git([Parameter(ValueFromRemainingArguments=$true)][string[]]$A) {
  $v = (& git @A 2>&1) -join "`n"; if ($LASTEXITCODE -ne 0) { throw $v }; return $v.Trim()
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
    if ($null -ne $j.completion_rate) { $rates += [double]$j.completion_rate }
    elseif ($null -ne $j.summary.completion_rate) { $rates += [double]$j.summary.completion_rate }
  }
  if (Test-Path $raw) { Copy-Item $raw (Join-Path $out ("workflow-run-{0:D2}.json" -f $i)) -Force }
}
$mean = if ($rates.Count) { ($rates | Measure-Object -Average).Average } else { 0.0 }
$workflowPass = ($rates.Count -eq $WorkflowRounds -and $workflowFailures -eq 0 -and $mean -ge $WorkflowThreshold)
@{schema='modelrig-workflow-proof/v1';sha=$sha;rounds=$WorkflowRounds;executions=$WorkflowRounds*14;mean_completion_rate=$mean;threshold=$WorkflowThreshold;runner_failures=$workflowFailures;passed=$workflowPass} | ConvertTo-Json -Depth 5 | Set-Content (Join-Path $out 'workflow-aggregate.json') -Encoding UTF8
if (-not $workflowPass) { Write-Warning "Workflow-gaten er rød: mean=$mean failures=$workflowFailures" }
# Skip switches are useful for partial diagnostic reruns, but a skipped physical
# gate is evidence that is absent, never evidence that passed. Keep them
# fail-closed so summary.passed cannot become true without both physical gates.
$t23pass=$false; $t23skipped=[bool]$SkipT023
if (-not $SkipT023) {
  Run 'Cleanup før T-023' { python scripts\stage_a_resume_cleanup.py }
  & python scripts\proof_t023_current.py
  $t23pass = ($LASTEXITCODE -eq 0)
  if (-not $t23pass) { Write-Warning 'T-023 er ikke grønt.' }
} else {
  Write-Warning 'T-023 blev sprunget over; fuld beviskampagne kan derfor ikke blive grøn.'
}
$t33pass=$false; $t33pending=$false; $t33skipped=[bool]$SkipT033
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
} else {
  Write-Warning 'T-033 blev sprunget over; fuld beviskampagne kan derfor ikke blive grøn.'
}
$passed = $workflowPass -and $t23pass -and $t33pass
$summary=@{schema='modelrig-proof-day/v1';generated_at=(Get-Date).ToUniversalTime().ToString('o');candidate=@{version=$version;sha=$sha;branch=$branch};planner=$PlannerModel;stage_a=$true;forced_recovery=$true;workflow=@{passed=$workflowPass;rounds=$WorkflowRounds;executions=$WorkflowRounds*14;mean=$mean};t023=$t23pass;t023_skipped=$t23skipped;t033=@{passed=$t33pass;pending_second_sid=$t33pending;skipped=$t33skipped};stage_b_release_lifecycle=@{included=$false;reason='requires exact candidate to exist as a published release and rig to start on previous release; never inferred from source-only run'};passed=$passed;production_activation=$false}
$summary|ConvertTo-Json -Depth 8|Set-Content (Join-Path $out 'summary.json') -Encoding UTF8
Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host "  RESULTAT: $(if($passed){'PASS'}else{'IKKE FULDT BEVIST ENDNU'})" -ForegroundColor $(if($passed){'Green'}else{'Yellow'})
Write-Host "  Evidence: $out"
Write-Host "  Workflow: $($WorkflowRounds*14) executioner, mean=$mean"
Write-Host "  Stage B updater/reboot: separat release-bound gate; bliver aldrig fake-grøn her."
Write-Host "============================================================================"
if ($passed) { exit 0 }; if ($t33pending -and $workflowPass -and $t23pass) { exit 3 }; exit 1
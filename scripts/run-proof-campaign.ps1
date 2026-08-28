[CmdletBinding()]
param(
  [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
  [int]$WorkflowRounds = 22,
  [double]$WorkflowThreshold = 0.95,
  # Skip betyder KUN "forsøg at genbruge et valideret receipt". Et manglende,
  # stale eller scope-ændret receipt efterlader gaten rød; skip er aldrig PASS.
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

function Run([string]$Label, [scriptblock]$Action) {
  Write-Host "`n============================================================================" -ForegroundColor Cyan
  Write-Host "  $Label" -ForegroundColor Cyan
  Write-Host "============================================================================" -ForegroundColor Cyan
  & $Action
  if ($LASTEXITCODE -ne 0) { throw "$Label fejlede med exitkode $LASTEXITCODE" }
}

function New-ProofGate([string]$Name) {
  return @{
    name = $Name
    executed = $false
    reused = $false
    evidence = $null
    taken_on_sha = $null
    passed = $false
  }
}

# BEGIN PROOF VERDICT FUNCTION
function Get-ProofCampaignPassed(
  [hashtable]$StageA,
  [hashtable]$ForcedRecovery,
  [hashtable]$Workflow,
  [hashtable]$T023,
  [hashtable]$T033
) {
  return [bool]($StageA.passed -and $ForcedRecovery.passed -and
                $Workflow.passed -and $T023.passed -and $T033.passed)
}
# END PROOF VERDICT FUNCTION

$script:GateReceiptPaths = @{
  stage_a = 'validation\proof-gates\stage-a-latest.json'
  forced_recovery = 'validation\proof-gates\forced-recovery-latest.json'
  workflows = 'validation\proof-gates\workflows-latest.json'
  t023 = 'validation\proof-gates\t023-latest.json'
  t033 = 'validation\proof-gates\t033-latest.json'
}

function Get-GateReceiptPath([string]$Name) {
  if (-not $script:GateReceiptPaths.ContainsKey($Name)) { throw "Ukendt proof-gate: $Name" }
  return [string]$script:GateReceiptPaths[$Name]
}

function Remove-GateReceipt([string]$Name) {
  $path = Get-GateReceiptPath $Name
  if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Force }
}

function Get-GateReceiptArgs([string]$Action, [string]$Name) {
  $args = @('scripts\proof_campaign_gate_receipt.py', $Action, '--gate', $Name)
  if ($Action -eq 'record') {
    $args += @('--sha', $sha, '--version', $version)
  } else {
    $args += @('--head-sha', $sha)
  }
  if ($Name -eq 'stage_a') {
    $args += @('--planner-model', $PlannerModel)
  } elseif ($Name -eq 'workflows') {
    $args += @('--planner-model', $PlannerModel,
               '--workflow-rounds', [string]$WorkflowRounds,
               '--workflow-threshold', [string]$WorkflowThreshold)
  }
  return $args
}

function Invoke-GateReceipt([string]$Action, [string]$Name, [bool]$Required) {
  $args = Get-GateReceiptArgs $Action $Name
  $raw = & python @args
  $code = $LASTEXITCODE
  $text = ($raw | ForEach-Object { [string]$_ }) -join "`n"
  $parsed = $null
  if (-not [string]::IsNullOrWhiteSpace($text)) {
    try { $parsed = $text | ConvertFrom-Json }
    catch { if ($Required) { throw "Gate-receipt $Action/$Name returnerede ugyldig JSON: $text" } }
  }
  if ($code -ne 0) {
    if ($Required) {
      $detail = if ($parsed -and $parsed.PSObject.Properties.Name -contains 'detail') { $parsed.detail } else { $text }
      throw "Gate-receipt $Action/$Name fejlede: $detail"
    }
    return $null
  }
  if ($null -eq $parsed -or $parsed.passed -ne $true) {
    if ($Required) { throw "Gate-receipt $Action/$Name gav ikke PASS." }
    return $null
  }
  return $parsed
}

function Try-ReuseGate([string]$Name) {
  $receipt = Invoke-GateReceipt 'validate' $Name $false
  if ($null -eq $receipt) {
    Write-Warning "$Name blev bedt sprunget over, men intet gyldigt reusable receipt findes. Gaten forbliver rød."
    return $null
  }
  Write-Host "  genbruger $Name fra $($receipt.taken_on_sha) via $($receipt.receipt)" -ForegroundColor DarkGray
  return $receipt
}

function Record-Gate([string]$Name) {
  return Invoke-GateReceipt 'record' $Name $true
}

# BEGIN WORKFLOW TRANSCRIPT COUNT FUNCTION
function Get-WorkflowTranscriptCount([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return 0 }
  try {
    $doc = Get-Content $Path -Raw | ConvertFrom-Json
    if ($null -eq $doc -or $doc -isnot [pscustomobject]) { return 0 }
    return @($doc.PSObject.Properties).Count
  } catch {
    return 0
  }
}
# END WORKFLOW TRANSCRIPT COUNT FUNCTION

# BEGIN WORKFLOW ROUND EVIDENCE FUNCTION
function Test-WorkflowRoundExecutionEvidence(
  [int]$Executions,
  [int]$ExpectedExecutions,
  $CompletionRate
) {
  return [bool]($Executions -eq $ExpectedExecutions -and $null -ne $CompletionRate)
}
# END WORKFLOW ROUND EVIDENCE FUNCTION

# git.exe opløses eksplicit som Application, så Git()-funktionen ikke kalder sig selv.
$script:GitExe = (Get-Command git -CommandType Application -ErrorAction SilentlyContinue |
                  Select-Object -First 1).Source
if (-not $script:GitExe) { throw 'git mangler paa PATH.' }
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
if (-not ($models | Where-Object { $_ -eq 'nomic-embed-text' -or $_ -like 'nomic-embed-text:*' })) {
  & ollama pull nomic-embed-text
  if ($LASTEXITCODE) { throw 'Kunne ikke hente nomic-embed-text.' }
}
$env:KALIV_AGENT3_PLANNER_MODEL = $PlannerModel

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $root "validation\proof-campaign\$stamp-$($sha.Substring(0,12))"
$logs = Join-Path $out 'logs'; New-Item -ItemType Directory -Force $logs | Out-Null
Write-Host "`nModelRig $version | $sha | $branch | planner=$PlannerModel" -ForegroundColor Green

$stageAGate = New-ProofGate 'stage_a'
$forcedRecoveryGate = New-ProofGate 'forced_recovery'
$workflowGate = New-ProofGate 'workflows'
$t23Gate = New-ProofGate 't023'
$t33Gate = New-ProofGate 't033'

# Stage A ---------------------------------------------------------------------
if ($SkipStageA) {
  $reuse = Try-ReuseGate 'stage_a'
  if ($reuse) {
    $stageAGate.reused = $true
    $stageAGate.evidence = $reuse.receipt
    $stageAGate.taken_on_sha = $reuse.taken_on_sha
    $stageAGate.passed = $true
  }
} else {
  Remove-GateReceipt 'stage_a'
  Run 'Stage A: samlet fysisk kampagne' { python scripts\proof_stage_a_current.py }
  [void](Record-Gate 'stage_a')
  $stageAGate.executed = $true
  $stageAGate.evidence = Get-GateReceiptPath 'stage_a'
  $stageAGate.taken_on_sha = $sha
  $stageAGate.passed = $true
}

# Forced recovery -------------------------------------------------------------
if ($SkipForcedRecovery) {
  $reuse = Try-ReuseGate 'forced_recovery'
  if ($reuse) {
    $forcedRecoveryGate.reused = $true
    $forcedRecoveryGate.evidence = $reuse.receipt
    $forcedRecoveryGate.taken_on_sha = $reuse.taken_on_sha
    $forcedRecoveryGate.passed = $true
  }
} else {
  Remove-GateReceipt 'forced_recovery'
  Run 'T-006: ægte hard-process recovery og lease recovery' { python scripts\forced_recovery_test.py }
  [void](Record-Gate 'forced_recovery')
  $forcedRecoveryGate.executed = $true
  $forcedRecoveryGate.evidence = Get-GateReceiptPath 'forced_recovery'
  $forcedRecoveryGate.taken_on_sha = $sha
  $forcedRecoveryGate.passed = $true
}

Run 'Ryd runtime før workflow-bevis' { python scripts\stage_a_resume_cleanup.py }
Run 'Start exact-head stack til workflows' {
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start-stage-a-validation-stack.ps1 `
    -PlannerModel $PlannerModel -ValidationReport validation\agent3-rig-validation-latest.json `
    -BackendHost 127.0.0.1 -HeadlessWorker
}

# Workflows -------------------------------------------------------------------
$mean = $null
$workflowRoundsMeasured = $null
$workflowExecutions = $null
$workflowFailures = $null
$workflowSpecCount = $null
$expectedWorkflowExecutions = $null
if ($SkipWorkflows) {
  $reuse = Try-ReuseGate 'workflows'
  if ($reuse) {
    $workflowSource = 'validation\workflow-proof-latest.json'
    $wj = Get-Content $workflowSource -Raw | ConvertFrom-Json
    # Receipt-validatoren har allerede hash-, verdict- og config-valideret filen.
    $workflowRoundsMeasured = [int]$wj.rounds
    $workflowExecutions = [int]$wj.executions
    $workflowFailures = [int]$wj.runner_failures
    $mean = [double]$wj.mean_completion_rate
    if ($wj.PSObject.Properties.Name -contains 'workflows_per_round') {
      $workflowSpecCount = [int]$wj.workflows_per_round
    }
    if ($wj.PSObject.Properties.Name -contains 'expected_executions') {
      $expectedWorkflowExecutions = [int]$wj.expected_executions
    }
    $workflowGate.reused = $true
    $workflowGate.evidence = $reuse.receipt
    $workflowGate.taken_on_sha = $reuse.taken_on_sha
    $workflowGate.passed = $true
  }
} else {
  Remove-GateReceipt 'workflows'
  $workflowLatest = 'validation\workflow-proof-latest.json'
  if (Test-Path -LiteralPath $workflowLatest) { Remove-Item -LiteralPath $workflowLatest -Force }
  $workflowSpecDoc = Get-Content 'eval\workflows_v1.json' -Raw | ConvertFrom-Json
  $workflowSpecCount = @($workflowSpecDoc.workflows).Count
  if ($workflowSpecCount -le 0) { throw 'Workflow-specen indeholder ingen workflows.' }
  $rates = @(); $workflowFailures = 0; $workflowExecutions = 0
  for ($i=1; $i -le $WorkflowRounds; $i++) {
    Write-Host "`n--- Workflow-run $i/$WorkflowRounds ---" -ForegroundColor Cyan
    $src='validation\workflow-baseline-latest.json'; $raw='validation\workflow-run-latest.json'
    foreach ($fresh in @($src, $raw)) {
      if (Test-Path -LiteralPath $fresh) { Remove-Item -LiteralPath $fresh -Force }
    }
    & python scripts\workflow_baseline_one_click.py --model $PlannerModel
    $roundExit = $LASTEXITCODE
    $roundRate = $null
    $roundExecutions = 0
    if (Test-Path $src) {
      Copy-Item $src (Join-Path $out ("workflow-baseline-{0:D2}.json" -f $i)) -Force
      $j=Get-Content $src -Raw | ConvertFrom-Json
      $cr = $null
      if ($j.PSObject.Properties.Name -contains 'completion_rate') { $cr = $j.completion_rate }
      elseif (($j.PSObject.Properties.Name -contains 'summary') -and
              ($null -ne $j.summary) -and
              ($j.summary.PSObject.Properties.Name -contains 'completion_rate')) { $cr = $j.summary.completion_rate }
      if ($null -ne $cr) {
        $roundRate = [double]$cr
        $rates += $roundRate
      }
    }
    if (Test-Path $raw) {
      Copy-Item $raw (Join-Path $out ("workflow-run-{0:D2}.json" -f $i)) -Force
      $roundExecutions = Get-WorkflowTranscriptCount $raw
      $workflowExecutions += $roundExecutions
    }

    $roundEvidenceComplete =
      Test-WorkflowRoundExecutionEvidence $roundExecutions $workflowSpecCount $roundRate

    if (-not $roundEvidenceComplete) {
      $workflowFailures++
      Write-Warning "Workflow-run $i mangler komplet execution-evidens: executions=$roundExecutions/$workflowSpecCount rate=$roundRate exit=$roundExit"
    } elseif ($roundExit -ne 0) {
      # workflow_eval returnerer nonzero ved kvalitetsfejl. Det er ikke en
      # runner-fejl naar transcriptet er komplet og completion_rate blev maalt.
      Write-Host "  workflow-run $i returnerede exit $roundExit pga. score; execution-evidensen er komplet." -ForegroundColor DarkGray
    }
  }
  $mean = if ($rates.Count) { ($rates | Measure-Object -Average).Average } else { 0.0 }
  $workflowRoundsMeasured = $rates.Count
  $expectedWorkflowExecutions = $WorkflowRounds * $workflowSpecCount
  $workflowPass = ($rates.Count -eq $WorkflowRounds -and
                   $workflowFailures -eq 0 -and
                   $workflowExecutions -eq $expectedWorkflowExecutions -and
                   $mean -ge $WorkflowThreshold)
  $workflowReport = [ordered]@{
    schema='modelrig-workflow-proof/v1'
    sha=$sha
    planner_model=$PlannerModel
    requested_rounds=$WorkflowRounds
    rounds=$workflowRoundsMeasured
    workflows_per_round=$workflowSpecCount
    expected_executions=$expectedWorkflowExecutions
    executions=$workflowExecutions
    mean_completion_rate=$mean
    threshold=$WorkflowThreshold
    runner_failures=$workflowFailures
    passed=$workflowPass
  }
  $workflowJson = $workflowReport | ConvertTo-Json -Depth 5
  $workflowJson | Set-Content (Join-Path $out 'workflow-aggregate.json') -Encoding UTF8
  $workflowJson | Set-Content $workflowLatest -Encoding UTF8
  $workflowGate.executed = $true
  $workflowGate.taken_on_sha = $sha
  if ($workflowPass) {
    [void](Record-Gate 'workflows')
    $workflowGate.evidence = Get-GateReceiptPath 'workflows'
    $workflowGate.passed = $true
  } else {
    Write-Warning "Workflow-gaten er rød: rounds=$workflowRoundsMeasured executions=$workflowExecutions/$expectedWorkflowExecutions mean=$mean failures=$workflowFailures"
  }
}

# T-023 -----------------------------------------------------------------------
if ($SkipT023) {
  $reuse = Try-ReuseGate 't023'
  if ($reuse) {
    $t23Gate.reused = $true
    $t23Gate.evidence = $reuse.receipt
    $t23Gate.taken_on_sha = $reuse.taken_on_sha
    $t23Gate.passed = $true
  }
} else {
  Remove-GateReceipt 't023'
  Run 'Frigiv 8080/8099 efter workflow-stakken' {
    $repoPrefix = (Resolve-Path '.').Path.TrimEnd('\') + '\'
    foreach ($port in 8080, 8099) {
      $pids = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
                Select-Object -Expand OwningProcess -Unique)
      foreach ($processId in $pids) {
        $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
        if ($null -eq $proc) { continue }
        $sti = [string]$proc.ExecutablePath
        $kommando = [string]$proc.CommandLine
        $vores = $sti.StartsWith($repoPrefix, [StringComparison]::OrdinalIgnoreCase) -or
                 $kommando -match 'app\.main|uvicorn|modelrig-server'
        if ($vores) {
          Write-Host "  lukker vores egen proces $processId paa $port" -ForegroundColor DarkGray
          Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
        } else {
          Write-Host "  LADER proces $processId paa $port staa (ikke vores: $sti)" -ForegroundColor Yellow
        }
      }
    }
    Start-Sleep -Seconds 3
    $global:LASTEXITCODE = 0
  }
  Run 'Cleanup før T-023' { python scripts\stage_a_resume_cleanup.py }
  & python scripts\proof_t023_current.py
  if ($LASTEXITCODE -eq 0) {
    [void](Record-Gate 't023')
    $t23Gate.executed = $true
    $t23Gate.evidence = Get-GateReceiptPath 't023'
    $t23Gate.taken_on_sha = $sha
    $t23Gate.passed = $true
  } else {
    $t23Gate.executed = $true
    $t23Gate.taken_on_sha = $sha
    Write-Warning 'T-023 er ikke grønt.'
  }
}

# T-033 -----------------------------------------------------------------------
$t33pending = $false
if ($SkipT033) {
  $reuse = Try-ReuseGate 't033'
  if ($reuse) {
    $t33Gate.reused = $true
    $t33Gate.evidence = $reuse.receipt
    $t33Gate.taken_on_sha = $reuse.taken_on_sha
    $t33Gate.passed = $true
  }
} else {
  $latest='validation\agent3-memory-protected-backup-physical-latest.json'
  $validLatest=$false
  if (Test-Path $latest) {
    try {
      $lj=Get-Content $latest -Raw|ConvertFrom-Json
      $generated = [DateTimeOffset]::Parse([string]$lj.generated_at).ToUniversalTime()
      $ageHours = ([DateTimeOffset]::UtcNow - $generated).TotalHours
      $validLatest=($lj.success -eq $true -and $lj.candidate.git_sha -eq $sha -and
                    $ageHours -ge -0.25 -and $ageHours -le 24.0)
    } catch { $validLatest=$false }
  }
  if ($validLatest) {
    # Et eksisterende, frisk exact-SHA fysisk report er allerede målingen.
    [void](Record-Gate 't033')
    $t33Gate.reused = $true
    $t33Gate.evidence = Get-GateReceiptPath 't033'
    $t33Gate.taken_on_sha = $sha
    $t33Gate.passed = $true
  } else {
    Remove-GateReceipt 't033'
    $states=Get-ChildItem 'validation\agent3-memory-protected-backup-physical' -Filter state.json -Recurse -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    $state=$null
    foreach($s in $states){
      try{
        $sj=Get-Content $s.FullName -Raw|ConvertFrom-Json
        if($sj.candidate.git_sha -eq $sha){$state=$s;$stateJson=$sj;break}
      }catch{}
    }
    if ($state -and (Test-Path $stateJson.probe_request.public_probe_path)) {
      & python scripts\proof_t033_current.py collect --state $state.FullName --probe $stateJson.probe_request.public_probe_path
      $t33Gate.executed = $true
      $t33Gate.taken_on_sha = $sha
      if ($LASTEXITCODE -eq 0) {
        [void](Record-Gate 't033')
        $t33Gate.evidence = Get-GateReceiptPath 't033'
        $t33Gate.passed = $true
      }
    } elseif ($state) {
      $t33pending=$true
      Write-Host "`nT-033 mangler kun en anden Windows-SID. Kør fra den anden bruger:" -ForegroundColor Yellow
      Write-Host "python `"$root\scripts\proof_t033_current.py`" probe --request `"$($stateJson.probe_request.public_request_path)`" --output `"$($stateJson.probe_request.public_probe_path)`""
      Write-Host 'Kør derefter START_PROOF_CAMPAIGN.cmd igen; collect sker automatisk.' -ForegroundColor Yellow
    } else {
      & python scripts\proof_t033_current.py prepare
      $t33Gate.executed = $true
      $t33Gate.taken_on_sha = $sha
      if ($LASTEXITCODE -eq 0) { $t33pending=$true }
    }
  }
}

# Agent 4 ---------------------------------------------------------------------
$a4pass = $null
$a4lan = $null
if ($IncludeAgent4) {
  $a4 = 'scripts\agent4_a4_25f_physical_operator.ps1'
  if ([string]::IsNullOrWhiteSpace($Agent4OutputRoot)) {
    $base = if ($env:USERPROFILE) { $env:USERPROFILE }
            elseif ($env:HOMEDRIVE -and $env:HOMEPATH) { Join-Path $env:HOMEDRIVE $env:HOMEPATH }
            else { [Environment]::GetFolderPath('UserProfile') }
    $Agent4OutputRoot = Join-Path $base 'modelrig-a4-25f-evidence'
  }
  $Agent4OutputRoot = [IO.Path]::GetFullPath($Agent4OutputRoot)
  New-Item -ItemType Directory -Force -Path $Agent4OutputRoot | Out-Null
  Write-Host "  Agent 4-evidens: $Agent4OutputRoot" -ForegroundColor DarkGray

  $a4lan = $Agent4LanAddress.Trim()
  if (-not [string]::IsNullOrWhiteSpace($a4lan)) {
    if ($a4lan -notmatch '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)') {
      throw "Agent4LanAddress skal være en privat RFC1918 IPv4-adresse: $a4lan"
    }
  } else {
    $a4lan = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
              Where-Object { $_.IPAddress -match '^(192\.168\.|10\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -and
                             $_.InterfaceAlias -notmatch 'Loopback|Tailscale' } |
              Select-Object -First 1 -Expand IPAddress)
  }
  if ([string]::IsNullOrWhiteSpace($a4lan)) {
    throw "Agent 4 kraever en privat LAN-adresse, og ingen blev fundet. Angiv den med -Agent4LanAddress."
  }
  Write-Host "  Agent 4 LAN-adresse: $a4lan" -ForegroundColor DarkGray
  $a4args = @('-ExpectedSha', $sha, '-OutputRoot', $Agent4OutputRoot, '-LanAddress', $a4lan)
  if (-not [string]::IsNullOrWhiteSpace($Agent4ApkPath)) {
    if (-not (Test-Path -LiteralPath $Agent4ApkPath -PathType Leaf)) {
      throw "Agent4ApkPath findes ikke: $Agent4ApkPath"
    }
    $a4args += @('-ApkPath', (Resolve-Path -LiteralPath $Agent4ApkPath).Path)
    Write-Host "  Agent 4 APK: $Agent4ApkPath" -ForegroundColor DarkGray
  }
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
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File $a4 Stop -ExpectedSha $sha -OutputRoot $Agent4OutputRoot 2>$null | Out-Null
  }
}

# Final verdict ---------------------------------------------------------------
$passed = Get-ProofCampaignPassed $stageAGate $forcedRecoveryGate $workflowGate $t23Gate $t33Gate
$summary=[ordered]@{
  schema='modelrig-proof-day/v2'
  generated_at=(Get-Date).ToUniversalTime().ToString('o')
  candidate=@{version=$version;sha=$sha;branch=$branch}
  planner=$PlannerModel
  stage_a=$stageAGate
  forced_recovery=$forcedRecoveryGate
  workflow=[ordered]@{
    name=$workflowGate.name
    executed=$workflowGate.executed
    reused=$workflowGate.reused
    evidence=$workflowGate.evidence
    taken_on_sha=$workflowGate.taken_on_sha
    passed=$workflowGate.passed
    requested_rounds=$WorkflowRounds
    rounds=$workflowRoundsMeasured
    workflows_per_round=$workflowSpecCount
    expected_executions=$expectedWorkflowExecutions
    executions=$workflowExecutions
    mean=$mean
    threshold=$WorkflowThreshold
    runner_failures=$workflowFailures
  }
  t023=$t23Gate
  t033=[ordered]@{
    name=$t33Gate.name
    executed=$t33Gate.executed
    reused=$t33Gate.reused
    evidence=$t33Gate.evidence
    taken_on_sha=$t33Gate.taken_on_sha
    passed=$t33Gate.passed
    pending_second_sid=$t33pending
  }
  agent4_a4_25f=@{included=[bool]$IncludeAgent4;passed=$a4pass;counts_toward_passed=$false;output_root=$Agent4OutputRoot;lan_address=$a4lan}
  stage_b_release_lifecycle=@{included=$false;reason='requires exact candidate to exist as a published release and rig to start on previous release; never inferred from source-only run'}
  passed=$passed
  production_activation=$false
}
$summary|ConvertTo-Json -Depth 8|Set-Content (Join-Path $out 'summary.json') -Encoding UTF8
Write-Host "`n============================================================================" -ForegroundColor Cyan
Write-Host "  RESULTAT: $(if($passed){'PASS'}else{'IKKE FULDT BEVIST ENDNU'})" -ForegroundColor $(if($passed){'Green'}else{'Yellow'})
Write-Host "  Evidence: $out"
if ($null -ne $workflowExecutions) {
  Write-Host "  Workflow: $workflowExecutions målte executioner, mean=$mean"
} else {
  Write-Host "  Workflow: ikke udført og intet gyldigt reusable receipt" -ForegroundColor Yellow
}
Write-Host "  Stage B updater/reboot: separat release-bound gate; bliver aldrig fake-grøn her."
Write-Host "============================================================================"
if ($passed) { exit 0 }
$otherFour = [bool]($stageAGate.passed -and $forcedRecoveryGate.passed -and $workflowGate.passed -and $t23Gate.passed)
if ($t33pending -and $otherFour) { exit 3 }
exit 1
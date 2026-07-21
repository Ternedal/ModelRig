[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$candidateBranch = "agent/t032-integration-candidate"
$expectedVersion = "1.58.141"
$operator = Join-Path $repoRoot "scripts\run-stage-a-physical-validation.ps1"
$campaignScript = Join-Path $repoRoot "scripts\physical_validation_candidate_campaign.py"
$campaignReport = Join-Path $repoRoot "validation\physical-validation-candidate-campaign-latest.json"
$statePath = Join-Path $repoRoot "validation\stage-a-easy-state.json"
$validationReport = Join-Path $repoRoot "validation\agent3-rig-validation-latest.json"
$proofOrder = @("preflight", "agent3", "model_eval", "voice", "rag", "scheduler_pilot")

function Write-Heading([string]$Text) {
    Write-Host ""
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
    Write-Host ("  " + $Text) -ForegroundColor Cyan
    Write-Host ("=" * 72) -ForegroundColor DarkCyan
}

function Write-Ok([string]$Text) { Write-Host ("  OK    " + $Text) -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host ("  ->    " + $Text) -ForegroundColor Yellow }

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$File,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [string]$WorkingDirectory = $repoRoot
    )
    Push-Location $WorkingDirectory
    try {
        & $File @Arguments
        if ($LASTEXITCODE -ne 0) {
            throw "$File stoppede med exitkode $LASTEXITCODE."
        }
    }
    finally { Pop-Location }
}

function Invoke-Git([string[]]$Arguments) {
    $output = & git @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git $($Arguments -join ' ') fejlede: $output" }
    return (($output | Out-String).Trim())
}

function Read-State {
    $state = @{}
    if (Test-Path -LiteralPath $statePath -PathType Leaf) {
        try {
            $raw = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
            foreach ($property in $raw.PSObject.Properties) { $state[$property.Name] = $property.Value }
        }
        catch { Write-Note "Den lokale wizard-status var ugyldig og nulstilles." }
    }
    return $state
}

function Save-State([hashtable]$State) {
    New-Item -ItemType Directory -Path (Split-Path $statePath -Parent) -Force | Out-Null
    $State | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $statePath -Encoding UTF8
}

function Archive-PreviousEvidence([string]$Sha, [hashtable]$State) {
    if ($State.ContainsKey("candidateSha") -and $State["candidateSha"] -eq $Sha) { return }
    $rolling = @(
        "pre-release-candidate-freeze-latest.json",
        "rig-preflight-latest.json",
        "agent3-rig-validation-latest.json",
        "agent3-model-eval-latest.json",
        "voice-baseline-latest.json",
        "rag-benchmark-latest.json",
        "scheduler-pilot-latest.json",
        "physical-validation-candidate-campaign-latest.json",
        "browser-peer-public-validation-physical-latest.json",
        "browser-peer-public-validation-latest.json",
        "physical-validation-candidate-final-latest.json"
    )
    $existing = @($rolling | ForEach-Object { Join-Path $repoRoot ("validation\" + $_) } | Where-Object { Test-Path -LiteralPath $_ -PathType Leaf })
    if ($existing.Count -gt 0) {
        $archive = Join-Path $repoRoot ("validation\archive\stage-a-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
        New-Item -ItemType Directory -Path $archive -Force | Out-Null
        foreach ($path in $existing) { Move-Item -LiteralPath $path -Destination $archive }
        Write-Note "Tidligere rolling reports er bevaret i $archive"
    }
    $State.Clear()
    $State["candidateSha"] = $Sha
    Save-State $State
}

function Ensure-Candidate {
    Write-Heading "1/8  Hent og lås den rigtige kandidat"
    if ($env:OS -ne "Windows_NT") { throw "Denne wizard må kun køres på Windows-riggen." }
    foreach ($command in @("git", "python", "powershell")) {
        if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { throw "$command blev ikke fundet på PATH." }
    }
    Push-Location $repoRoot
    try {
        $dirty = Invoke-Git @("status", "--porcelain")
        if ($dirty) { throw "Working tree er ikke ren. Flyt eller stash lokale filer først:`n$dirty" }
        Invoke-Git @("fetch", "--quiet", "origin", "main", $candidateBranch) | Out-Null
        $branch = Invoke-Git @("branch", "--show-current")
        if ($branch -ne $candidateBranch) {
            Write-Note "Skifter fra $branch til $candidateBranch"
            Invoke-Git @("switch", $candidateBranch) | Out-Null
        }
        Invoke-Git @("pull", "--ff-only", "origin", $candidateBranch) | Out-Null
        $sha = Invoke-Git @("rev-parse", "HEAD")
        $remoteSha = Invoke-Git @("rev-parse", ("origin/" + $candidateBranch))
        if ($sha -ne $remoteSha) { throw "Lokal HEAD matcher ikke origin/$candidateBranch." }
        $version = (Get-Content -LiteralPath (Join-Path $repoRoot "VERSION") -Raw).Trim()
        if ($version -ne $expectedVersion) { throw "VERSION er $version, forventede $expectedVersion." }
        Write-Ok "Kandidat $version på $sha"
        return $sha
    }
    finally { Pop-Location }
}

function Ensure-GitHubToken {
    Write-Heading "2/8  GitHub-login til exact-head-kontrollen"
    if ($env:GITHUB_TOKEN -or $env:GH_TOKEN) {
        Write-Ok "GitHub-token findes allerede i denne session."
        return
    }
    $gh = Get-Command gh -ErrorAction SilentlyContinue
    if ($null -eq $gh) {
        $winget = Get-Command winget -ErrorAction SilentlyContinue
        if ($null -eq $winget) { throw "GitHub CLI mangler. Installér 'GitHub CLI' og kør wizard'en igen." }
        $answer = Read-Host "GitHub CLI mangler. Tryk Enter for automatisk installation, eller skriv STOP"
        if ($answer -eq "STOP") { throw "Stoppet før installation." }
        Invoke-Checked -File $winget.Source -Arguments @("install", "--id", "GitHub.cli", "-e", "--source", "winget", "--accept-package-agreements", "--accept-source-agreements")
        $candidate = Join-Path $env:ProgramFiles "GitHub CLI\gh.exe"
        if (Test-Path -LiteralPath $candidate) { $gh = Get-Item $candidate }
        else { $gh = Get-Command gh -ErrorAction SilentlyContinue }
        if ($null -eq $gh) { throw "GitHub CLI blev installeret, men findes ikke på PATH endnu. Luk vinduet og dobbeltklik igen." }
    }
    & $gh.Source auth status -h github.com *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Note "Et browservindue åbnes til GitHub-login. Det er kun nødvendigt én gang."
        & $gh.Source auth login --web --git-protocol https
        if ($LASTEXITCODE -ne 0) { throw "GitHub-login blev ikke gennemført." }
    }
    $token = (& $gh.Source auth token).Trim()
    if (-not $token) { throw "GitHub CLI returnerede intet token." }
    $env:GH_TOKEN = $token
    Write-Ok "GitHub-login er klar; tokenet vises eller gemmes ikke af wizard'en."
}

function Get-OllamaModels {
    try {
        $payload = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 4
        return @($payload.models | ForEach-Object { $_.name })
    }
    catch { return @() }
}

function Ensure-Models {
    Write-Heading "3/8  Ollama og modeller"
    $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    if ($null -eq $ollama) { throw "Ollama blev ikke fundet på PATH." }
    $models = Get-OllamaModels
    if ($models.Count -eq 0) {
        Write-Note "Starter Ollama..."
        Start-Process -FilePath $ollama.Source -ArgumentList "serve" | Out-Null
        1..20 | ForEach-Object {
            Start-Sleep -Seconds 1
            $script:models = Get-OllamaModels
            if ($script:models.Count -gt 0) { return }
        }
        $models = Get-OllamaModels
    }
    if ($models.Count -eq 0) { throw "Ollama svarer ikke på http://127.0.0.1:11434." }

    $planner = $env:KALIV_AGENT3_PLANNER_MODEL
    if (-not $planner -or $planner -notin $models) {
        $planner = @($models | Where-Object { $_ -match '^qwen3:' } | Select-Object -First 1)[0]
        if (-not $planner) { $planner = @($models | Where-Object { $_ -match '^gemma3:' } | Select-Object -First 1)[0] }
        if (-not $planner) { $planner = @($models | Where-Object { $_ -notmatch 'embed' } | Select-Object -First 1)[0] }
    }
    if (-not $planner) {
        $answer = Read-Host "Ingen planner-model fundet. Tryk Enter for at hente qwen3:8b, eller skriv STOP"
        if ($answer -eq "STOP") { throw "Ingen planner-model valgt." }
        Invoke-Checked -File $ollama.Source -Arguments @("pull", "qwen3:8b")
        $planner = "qwen3:8b"
    }
    if ("nomic-embed-text:latest" -notin $models -and "nomic-embed-text" -notin $models) {
        $answer = Read-Host "Embeddingmodellen mangler. Tryk Enter for at hente nomic-embed-text, eller skriv STOP"
        if ($answer -eq "STOP") { throw "Embeddingmodellen mangler." }
        Invoke-Checked -File $ollama.Source -Arguments @("pull", "nomic-embed-text")
    }
    $env:KALIV_AGENT3_PLANNER_MODEL = $planner
    $env:KALIV_AGENT3_VALIDATION_REPORT = $validationReport
    Write-Ok "Planner/voice-model: $planner"
    Write-Ok "Embeddingmodel: nomic-embed-text"
    return $planner
}

function Ensure-DeviceToken {
    if ($env:MODELRIG_TOKEN) { return }
    Write-Heading "4/8  Parret device-token"
    Write-Host "  Indsæt tokenet. Det skjules, bruges kun i processen og skrives ikke til disk."
    $secure = Read-Host "  MODELRIG_TOKEN" -AsSecureString
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try { $plain = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
    if (-not $plain) { throw "Device-tokenet var tomt." }
    $env:MODELRIG_TOKEN = $plain
    Write-Ok "Device-token er sat i denne session."
}

function Run-StrictStageA([string]$Action, [string]$Sha, [string]$Url = "") {
    $arguments = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $operator, "-Action", $Action, "-ExpectedSha", $Sha)
    if ($Url) { $arguments += @("-Url", $Url) }
    Invoke-Checked -File "powershell.exe" -Arguments $arguments
}

function Refresh-Campaign {
    Invoke-Checked -File "python" -Arguments @($campaignScript, "--mode", "prepare", "--report", $campaignReport)
    return (Get-Content -LiteralPath $campaignReport -Raw | ConvertFrom-Json)
}

function Show-Progress($Campaign) {
    Write-Host ""
    Write-Host "  Stage A-status" -ForegroundColor Cyan
    foreach ($name in $proofOrder) {
        if ($name -in @($Campaign.summary.passed)) { Write-Host "    [OK]      $name" -ForegroundColor Green }
        elseif ($name -in @($Campaign.summary.failed)) { Write-Host "    [FEJL]    $name" -ForegroundColor Red }
        else { Write-Host "    [MANGLER] $name" -ForegroundColor Yellow }
    }
}

function Run-Preflight([string]$PlannerModel) {
    Write-Heading "5/8  Start riggen og kør de automatiske beviser"
    & python scripts\rig_preflight.py --base-url http://127.0.0.1:8080 --report validation\rig-preflight-latest.json
    if ($LASTEXITCODE -eq 0) { Write-Ok "Rig preflight bestod."; return }

    Write-Note "Wizard'en kan starte backend og worker direkte fra den eksakte kandidat."
    $answer = Read-Host "Tryk Enter for at erstatte lokale processer på port 8080/8099 med kandidat-stacken, eller skriv STOP"
    if ($answer -eq "STOP") { throw "Riggen var ikke klar." }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File scripts\start-stage-a-validation-stack.ps1 -PlannerModel $PlannerModel -ValidationReport $validationReport -ReplaceLocalProcesses
    if ($LASTEXITCODE -ne 0) { throw "Kandidat-stacken kunne ikke startes." }
    Invoke-Checked -File "python" -Arguments @("scripts\rig_preflight.py", "--base-url", "http://127.0.0.1:8080", "--report", "validation\rig-preflight-latest.json")
    Write-Ok "Rig preflight bestod på den eksakte kandidat-stack."
}

function Run-Voice([string]$Model) {
    $fixtureDir = Join-Path $repoRoot "validation\voice-fixtures"
    $manual = Join-Path $repoRoot "validation\voice-manual-observations.json"
    New-Item -ItemType Directory -Path $fixtureDir -Force | Out-Null
    if (-not (Test-Path -LiteralPath $manual)) {
        Copy-Item -LiteralPath (Join-Path $repoRoot "eval\voice_manual_observations.example.json") -Destination $manual
    }
    while (@(Get-ChildItem -LiteralPath $fixtureDir -Filter "turn-*.wav" -File -ErrorAction SilentlyContinue).Count -ne 20) {
        Write-Heading "MANUELT PAUSEPUNKT  Voice-fixtures"
        Write-Host "  Optag de 20 fraser som turn-01.wav ... turn-20.wav."
        Write-Host "  Manifestet og mappen åbnes nu. Når alle 20 filer ligger der, tryk Enter."
        Start-Process (Join-Path $repoRoot "eval\voice_baseline_manifest.v1.json") | Out-Null
        Start-Process explorer.exe -ArgumentList ('"' + $fixtureDir + '"') | Out-Null
        Read-Host | Out-Null
    }
    Invoke-Checked -File "python" -Arguments @("scripts\voice_baseline.py", "--validate-only", "--report", "validation\voice-baseline-fixture-check.json")

    Write-Heading "MANUELT PAUSEPUNKT  Pixel stop/barge-in"
    Write-Host "  Kør de fem trials på Pixel 6a og udfyld filen, der åbnes nu."
    Start-Process notepad.exe -ArgumentList ('"' + $manual + '"') | Out-Null
    Read-Host "Når de fem trials er udfyldt med rigtige booleans og tider, tryk Enter" | Out-Null

    Invoke-Checked -File "python" -Arguments @(
        "scripts\voice_baseline.py", "--worker-url", "http://127.0.0.1:8099",
        "--model", $Model, "--repetitions", "2", "--cold-start-confirmed",
        "--cancellation-probes", "4", "--manual-observations", "validation\voice-manual-observations.json",
        "--require-manual", "--report", "validation\voice-baseline-latest.json"
    )
}

function Run-Scheduler([hashtable]$State) {
    Write-Heading "MANUELT PAUSEPUNKT  Scheduler-pilot"
    if (-not $State.ContainsKey("readScheduleId") -or -not $State["readScheduleId"]) {
        $body = @{ tool = "rig_status"; args = @{}; cadence = "every:60"; ttl_days = 1; max_runs = 3 } | ConvertTo-Json -Compress
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8099/schedules/preview" -ContentType "application/json" -Body $body | Out-Null
        $created = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8099/schedules" -ContentType "application/json" -Body $body
        $State["readScheduleId"] = $created.schedule_id
        Save-State $State
    }
    Write-Ok "Read schedule-id: $($State['readScheduleId'])"
    Write-Host ""
    Write-Host "  I appens schedule-flow skal du oprette PRÆCIS:"
    Write-Host "    tool: note_append"
    Write-Host "    args: {`"text`": `"pilot`"}"
    Write-Host "    cadence: every:60, max_runs: 2, ttl_days: 1"
    Write-Host "  Godkend den fra den parrede enhed."
    $writeId = Read-Host "  Indsæt write schedule-id bagefter"
    if (-not $writeId) { throw "Write schedule-id mangler." }
    $State["writeScheduleId"] = $writeId
    Save-State $State

    Write-Host ""
    Write-Host "  Pausér read-planen mens en occurrence er i gang, så jobbet bliver cancelled."
    Write-Host "  Dræb derefter worker under et scheduled job, start den igen og kopiér recovery-linjen."
    $revoked = Read-Host "  Skriv JA, når revocation/cancel er observeret"
    if ($revoked -ne "JA") { throw "Revocation blev ikke bekræftet." }
    $recovery = Read-Host "  Indsæt hele linjen der starter med 'scheduler: recovered'"
    if ($recovery -notmatch '^scheduler: recovered ') { throw "Recovery-linjen har forkert format." }

    @{ revocation_confirmed = $true; recovery_line = $recovery; operator = "Anders" } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repoRoot "validation\scheduler-manual-observations.json") -Encoding UTF8
    Invoke-Checked -File "python" -Arguments @(
        "scripts\scheduler_pilot_report.py", "--worker-url", "http://127.0.0.1:8099",
        "--read-schedule-id", [string]$State["readScheduleId"], "--write-schedule-id", $writeId,
        "--manual-observations", "validation\scheduler-manual-observations.json",
        "--report", "validation\scheduler-pilot-latest.json"
    )
}

Push-Location $repoRoot
try {
    Clear-Host
    Write-Heading "Kaliv Stage A — lettest mulige fysiske test"
    Write-Host "  Wizard'en kan genoptages ved at dobbeltklikke START_STAGE_A_TEST.cmd igen."
    Write-Host "  Den kan ikke merge, tagge, release eller aktivere produktion."

    $sha = Ensure-Candidate
    $state = Read-State
    Archive-PreviousEvidence -Sha $sha -State $state
    Ensure-GitHubToken
    $planner = Ensure-Models

    Write-Heading "Exact-head freeze og checklist"
    Run-StrictStageA -Action "Prepare" -Sha $sha
    Ensure-DeviceToken

    $campaign = Get-Content -LiteralPath $campaignReport -Raw | ConvertFrom-Json
    Show-Progress $campaign

    if ("preflight" -notin @($campaign.summary.passed)) { Run-Preflight -PlannerModel $planner; $campaign = Refresh-Campaign }
    if ("agent3" -notin @($campaign.summary.passed)) {
        Invoke-Checked -File "powershell.exe" -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "scripts\run-agent3-rig-validation.ps1", "-BaseUrl", "http://127.0.0.1:8080", "-PlannerModel", $planner)
        $campaign = Refresh-Campaign
    }
    if ("model_eval" -notin @($campaign.summary.passed)) {
        Invoke-Checked -File "python" -Arguments @("scripts\agent3_model_eval.py", "--planner-model", $planner, "--repetitions", "1", "--fail-under", "1.0", "--report", "validation\agent3-model-eval-latest.json")
        $campaign = Refresh-Campaign
    }
    if ("rag" -notin @($campaign.summary.passed)) {
        Invoke-Checked -File "python" -Arguments @("scripts\rag_benchmark.py", "--scales", "1000,10000", "--queries", "40", "--repetitions", "2", "--embedding-model", "nomic-embed-text", "--report", "validation\rag-benchmark-latest.json")
        $campaign = Refresh-Campaign
    }
    if ("voice" -notin @($campaign.summary.passed)) { Run-Voice -Model $planner; $campaign = Refresh-Campaign }
    if ("scheduler_pilot" -notin @($campaign.summary.passed)) { Run-Scheduler -State $state; $campaign = Refresh-Campaign }

    Show-Progress $campaign
    Run-StrictStageA -Action "Verify" -Sha $sha

    Write-Heading "8/8  Sidste browserbevis"
    $url = Read-Host "Eksakt forhåndsgodkendt HTTPS/443-URL [https://example.com/]"
    if (-not $url) { $url = "https://example.com/" }
    Write-Note "Den eksisterende one-use browsergate viser URL'en og kræver din sidste eksplicitte bekræftelse."
    Run-StrictStageA -Action "Complete" -Sha $sha -Url $url

    Write-Heading "STAGE A BESTÅET"
    Write-Ok "Syv fysiske beviser er bundet til $sha"
    Write-Host "  Rapport: validation\physical-validation-candidate-final-latest.json"
    Write-Host "  Releasevalidering mangler fortsat, og production_activation er fortsat false."
}
catch {
    Write-Host ""
    Write-Host ("  SIKKERT STOP: " + $_.Exception.Message) -ForegroundColor Red
    Write-Host "  Intet blev merget, releaset eller aktiveret. Ret problemet og dobbeltklik igen."
    exit 1
}
finally { Pop-Location }

exit 0

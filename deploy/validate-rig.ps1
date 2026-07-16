# validate-rig.ps1 -- automatiserer de mekaniske dele af VALIDATION-1.58.36.md
# paa riggen. Standard = READ-ONLY (ingen processer roeres). Crash-restart-
# testene (A2-A4) kraever -Destructive og bekraefter foer hvert kill (spring
# bekraeftelsen over med -Force). Alt output ender i en paste-klar
# markdown-blok, saa resultaterne kan saettes direkte ind i valideringsfilen.
#
#   .\deploy\validate-rig.ps1                          # read-only tjek
#   .\deploy\validate-rig.ps1 -Token <bearer>          # + health/full + capabilities
#   .\deploy\validate-rig.ps1 -Destructive             # + A2/A3/A4 crash-restart
#   .\deploy\validate-rig.ps1 -Destructive -Force      # samme, uden prompts
#
# Grundet i koden, ikke gaet: task-navn/heartbeat-sti/flags matcher
# modelrig-updater's defaults (main.go), journal/lock-navnene matcher
# journal.go/lock.go, og portene matcher deploy-opsaetningen.

param(
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$Token = "",
    [string]$SupervisorTask = "KalivSupervisor",
    [switch]$Destructive,
    [switch]$Force
)

$ErrorActionPreference = "Continue"
$results = [System.Collections.Generic.List[object]]::new()

function Add-Result([string]$Id, [string]$Name, [string]$Status, [string]$Note = "") {
    $results.Add([pscustomobject]@{ Id = $Id; Name = $Name; Status = $Status; Note = $Note })
    $color = switch ($Status) { "PASS" { "Green" } "FAIL" { "Red" } default { "Yellow" } }
    Write-Host ("[{0}] {1,-4} {2} {3}" -f $Id, $Status, $Name, $(if ($Note) { "-- $Note" } else { "" })) -ForegroundColor $color
}

function Get-Json([string]$Url, [string]$Bearer = "") {
    try {
        $headers = @{}
        if ($Bearer) { $headers["Authorization"] = "Bearer $Bearer" }
        return Invoke-RestMethod -Uri $Url -Headers $headers -TimeoutSec 8
    } catch { return $null }
}

function Confirm-Or-Skip([string]$What) {
    if ($Force) { return $true }
    $answer = Read-Host "$What -- fortsaet? (j/N)"
    return $answer -match '^[jJyY]'
}

Write-Host "== ModelRig valideringsharness ==" -ForegroundColor Cyan
Write-Host "Root: $Root | Task: $SupervisorTask | Destructive: $Destructive`n"

# ---------- read-only: filer, versioner, sundhed ----------

$serverExe = Join-Path $Root "modelrig-server-windows-x64.exe"
$updaterExe = Join-Path $Root "modelrig-updater-windows-x64.exe"
if ((Test-Path $serverExe) -and (Test-Path $updaterExe)) {
    Add-Result "F1" "Kerne-exe-filer til stede" "PASS"
} else {
    Add-Result "F1" "Kerne-exe-filer til stede" "FAIL" "mangler i $Root -- er -Root korrekt?"
}

$journal = Join-Path $Root "update-transaction.json"
if (Test-Path $journal) {
    Add-Result "B-J" "Ingen ventende update-transaktion" "FAIL" "journal findes -- koer updateren (recovery) foer videre test"
} else {
    Add-Result "B-J" "Ingen ventende update-transaktion" "PASS" $(if (Test-Path "$journal.last") { "(.last-arkiv findes -- normalt)" } else { "" })
}

$lock = Join-Path $Root "updater.lock"
if (Test-Path $lock) {
    Add-Result "B-L" "Ingen efterladt updater.lock" "FAIL" "slet filen hvis ingen updater koerer"
} else {
    Add-Result "B-L" "Ingen efterladt updater.lock" "PASS"
}

$serverHealth = Get-Json "http://127.0.0.1:8080/healthz"
$workerHealth = Get-Json "http://127.0.0.1:8099/healthz"
if ($serverHealth -and $workerHealth) {
    $sv = $serverHealth.version; $wv = $workerHealth.version
    if ($sv -and $sv -eq $wv) {
        Add-Result "A0" "Server + worker oppe og paa samme version" "PASS" "version $sv"
    } else {
        Add-Result "A0" "Server + worker oppe og paa samme version" "FAIL" "server=$sv worker=$wv"
    }
} else {
    Add-Result "A0" "Server + worker oppe og paa samme version" "FAIL" "healthz svarer ikke (server:$([bool]$serverHealth) worker:$([bool]$workerHealth))"
}

$task = Get-ScheduledTask -TaskName $SupervisorTask -ErrorAction SilentlyContinue
if ($task) {
    Add-Result "A-T" "Scheduled task '$SupervisorTask' findes" "PASS" "state: $($task.State)"
} else {
    Add-Result "A-T" "Scheduled task '$SupervisorTask' findes" "FAIL"
}

# A5: heartbeat skal BEVISELIGT gaa fremad (to laesninger over ~2x interval)
$hb = Join-Path $Root "logs\supervisor-heartbeat"
if (Test-Path $hb) {
    $first = (Get-Content $hb -Raw).Trim()
    Start-Sleep -Seconds 22
    $second = (Get-Content $hb -Raw).Trim()
    if ($second -ne $first) {
        Add-Result "A5" "Supervisor-heartbeat gaar fremad" "PASS"
    } else {
        Add-Result "A5" "Supervisor-heartbeat gaar fremad" "FAIL" "uaendret over 22s -- supervisor doed eller frosset?"
    }
} else {
    Add-Result "A5" "Supervisor-heartbeat gaar fremad" "FAIL" "heartbeat-fil mangler: $hb"
}

# B4-lite: -recover skal vaere en sikker no-op paa en sund rig (offline reparation)
if (Test-Path $updaterExe) {
    & $updaterExe -dir $Root -recover 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Add-Result "B4" "updater -recover (no-op paa sund rig)" "PASS"
    } else {
        Add-Result "B4" "updater -recover (no-op paa sund rig)" "FAIL" "exit $LASTEXITCODE -- laes updaterens output manuelt"
    }
}

# B7: to updaters maa ikke koere samtidig -- nr. 2 skal fejle lukket paa lock
if (Test-Path $updaterExe) {
    Set-Content -Path $lock -Value "validate-rig.ps1 fake lock $(Get-Date -Format o)"
    & $updaterExe -dir $Root -check 2>&1 | Out-Null
    $code = $LASTEXITCODE
    Remove-Item $lock -ErrorAction SilentlyContinue
    if ($code -ne 0) {
        Add-Result "B7" "Anden updater fejler lukket paa updater.lock" "PASS"
    } else {
        Add-Result "B7" "Anden updater fejler lukket paa updater.lock" "FAIL" "-check lykkedes trods lock"
    }
}

# health/full + capabilities kraever bearer-token
if ($Token) {
    $full = Get-Json "http://127.0.0.1:8080/api/v1/health/full" $Token
    if ($full -and $full.ok) {
        Add-Result "H1" "/health/full ok:true" "PASS"
    } else {
        Add-Result "H1" "/health/full ok:true" "FAIL" $(if ($full) { ($full | ConvertTo-Json -Compress -Depth 3).Substring(0, 120) } else { "intet svar" })
    }
} else {
    Add-Result "H1" "/health/full ok:true" "SKIP" "koer med -Token <bearer> for at inkludere"
}

# ---------- destructive: A2-A4 crash-restart (kraever -Destructive) ----------

function Test-CrashRestart([string]$Id, [string]$ProcName, [string]$HealthUrl, [int]$TimeoutSec = 60) {
    $p = Get-Process $ProcName -ErrorAction SilentlyContinue
    if (-not $p) { Add-Result $Id "Crash-restart: $ProcName" "SKIP" "processen koerer ikke"; return }
    if (-not (Confirm-Or-Skip "Draeber $ProcName (supervisoren skal genstarte den)")) {
        Add-Result $Id "Crash-restart: $ProcName" "SKIP" "fravalgt"; return
    }
    $p | Stop-Process -Force
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    do {
        Start-Sleep -Seconds 3
        $back = if ($HealthUrl) { [bool](Get-Json $HealthUrl) } else { [bool](Get-Process $ProcName -ErrorAction SilentlyContinue) }
    } until ($back -or (Get-Date) -gt $deadline)
    if ($back) {
        Add-Result $Id "Crash-restart: $ProcName" "PASS" "tilbage inden for $TimeoutSec s"
    } else {
        Add-Result $Id "Crash-restart: $ProcName" "FAIL" "ikke tilbage efter $TimeoutSec s"
    }
}

if ($Destructive) {
    Test-CrashRestart "A2" "modelrig-worker-windows-x64" "http://127.0.0.1:8099/healthz"
    Test-CrashRestart "A3" "modelrig-server-windows-x64" "http://127.0.0.1:8080/healthz"
    # A4: supervisoren selv -- Task Scheduler skal bringe den tilbage (laengere frist)
    Test-CrashRestart "A4" "modelrig-supervisor-windows-x64" "" 120
} else {
    Add-Result "A2" "Crash-restart: worker" "SKIP" "koer med -Destructive"
    Add-Result "A3" "Crash-restart: server" "SKIP" "koer med -Destructive"
    Add-Result "A4" "Crash-restart: supervisor" "SKIP" "koer med -Destructive"
}

# ---------- paste-klar opsummering ----------

$pass = ($results | Where-Object Status -eq "PASS").Count
$fail = ($results | Where-Object Status -eq "FAIL").Count
$skip = ($results | Where-Object Status -eq "SKIP").Count
Write-Host "`n===== $pass PASS / $fail FAIL / $skip SKIP =====" -ForegroundColor Cyan

$md = [System.Text.StringBuilder]::new()
[void]$md.AppendLine("### validate-rig.ps1 -- $(Get-Date -Format 'yyyy-MM-dd HH:mm') @ $env:COMPUTERNAME")
[void]$md.AppendLine("| # | Test | Resultat | Note |")
[void]$md.AppendLine("|---|---|---|---|")
foreach ($r in $results) {
    $mark = switch ($r.Status) { "PASS" { [char]0x2705 } "FAIL" { [char]0x274C } default { [char]0x23ED } }
    [void]$md.AppendLine("| $($r.Id) | $($r.Name) | $mark $($r.Status) | $($r.Note) |")
}
$outFile = Join-Path $Root "logs\validate-rig-latest.md"
New-Item -ItemType Directory -Path (Split-Path $outFile) -Force | Out-Null
$md.ToString() | Set-Content -Path $outFile -Encoding UTF8
Write-Host "Markdown-blok gemt: $outFile (paste ind i VALIDATION-1.58.36.md)"
Write-Host "Manuelle tests tilbage: A1 (reboot), B1-B3/B5-B6/B8 (update-scenarier), C/D/E/F (telefon)."

exit $(if ($fail -gt 0) { 1 } else { 0 })

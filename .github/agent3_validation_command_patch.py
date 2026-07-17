from __future__ import annotations

from pathlib import Path

ROOT = Path.cwd()


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one anchor, got {count}: {old!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# One source of truth for the rolling on-rig report path. The harness writes it,
# local readiness reads it, .gitignore protects it, and the operator wrapper
# exports the same path to the worker. A successful test must not disappear
# merely because two scripts remembered two different defaults.
(ROOT / "scripts" / "agent3_validation_paths.py").write_text(
    '''from __future__ import annotations

from pathlib import Path

DEFAULT_REPORT_RELATIVE = Path("validation") / "agent3-rig-validation-latest.json"
DEFAULT_REPORT_TEXT = DEFAULT_REPORT_RELATIVE.as_posix()


def default_report_path(repo_root: Path) -> Path:
    return repo_root / DEFAULT_REPORT_RELATIVE
''',
    encoding="utf-8",
)

replace_once(
    "scripts/agent3_rig_validation.py",
    "import agent3_rig_validation as validation\n",
    "import agent3_rig_validation as validation\nfrom agent3_validation_paths import DEFAULT_REPORT_TEXT\n",
)
replace_once(
    "scripts/agent3_rig_validation.py",
    '''        default=os.getenv(
            "KALIV_AGENT3_VALIDATION_REPORT",
            "validation/agent3-rig-validation-latest.json",
        ),''',
    '''        default=os.getenv(
            "KALIV_AGENT3_VALIDATION_REPORT",
            DEFAULT_REPORT_TEXT,
        ),''',
)

replace_once(
    "scripts/activation_readiness.py",
    "from pathlib import Path\n",
    "from pathlib import Path\n\nfrom agent3_validation_paths import DEFAULT_REPORT_TEXT\n",
)
replace_once(
    "scripts/activation_readiness.py",
    '    path = os.getenv(REPORT_ENV) or "agent3-validation-latest.json"',
    "    path = os.getenv(REPORT_ENV) or DEFAULT_REPORT_TEXT",
)

# Monotonic Android identity for 1.58.82. version_tool updates the semantic
# version sites later; versionCode is intentionally independent and explicit.
replace_once(
    "android/app/build.gradle.kts",
    "versionCode = 213",
    "versionCode = 214",
)

(ROOT / "scripts" / "run-agent3-rig-validation.ps1").write_text(
    r'''[CmdletBinding()]
param(
    [string]$BaseUrl = $(
        if ([string]::IsNullOrWhiteSpace($env:MODELRIG_BASE_URL)) {
            "http://127.0.0.1:8080"
        } else {
            $env:MODELRIG_BASE_URL
        }
    ),
    [string]$PlannerModel = $env:KALIV_AGENT3_PLANNER_MODEL,
    [string]$ReportPath = "",
    [switch]$ApproveWrite,
    [switch]$SkipReadinessRegeneration
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($ReportPath)) {
    $ReportPath = Join-Path $repoRoot "validation\agent3-rig-validation-latest.json"
} elseif (-not [System.IO.Path]::IsPathRooted($ReportPath)) {
    $ReportPath = Join-Path $repoRoot $ReportPath
}
$ReportPath = [System.IO.Path]::GetFullPath($ReportPath)

if ([string]::IsNullOrWhiteSpace($env:MODELRIG_TOKEN)) {
    throw "MODELRIG_TOKEN mangler. Brug et paired device-token i miljøet; skriv det ikke på kommandolinjen."
}
if ([string]::IsNullOrWhiteSpace($PlannerModel)) {
    throw "Planner-model mangler. Sæt KALIV_AGENT3_PLANNER_MODEL eller brug -PlannerModel."
}

$reportDirectory = Split-Path -Parent $ReportPath
New-Item -ItemType Directory -Force -Path $reportDirectory | Out-Null

# Child processes and the local readiness generator now use the exact same
# absolute report. This cannot change an already-running worker process; the
# status check below proves whether that worker was started with the same path.
$env:MODELRIG_BASE_URL = $BaseUrl
$env:KALIV_AGENT3_PLANNER_MODEL = $PlannerModel
$env:KALIV_AGENT3_VALIDATION_REPORT = $ReportPath

$evidenceArgs = @(
    (Join-Path $repoRoot "scripts\agent3_rig_evidence.py"),
    "--base-url", $BaseUrl,
    "--planner-model", $PlannerModel,
    "--report", $ReportPath
)
if ($ApproveWrite) {
    $evidenceArgs += "--approve-write"
}

Write-Host "[1/3] Kører fysisk Agent3-evidens mod $BaseUrl"
& python @evidenceArgs
if ($LASTEXITCODE -ne 0) {
    throw "Agent3-evidens fejlede med exit code $LASTEXITCODE. Rapport: $ReportPath"
}

Write-Host "[2/3] Kontrollerer at den kørende worker vurderer samme rapport"
$headers = @{ Authorization = "Bearer $env:MODELRIG_TOKEN" }
$status = Invoke-RestMethod `
    -Method Get `
    -Uri ($BaseUrl.TrimEnd("/") + "/api/v1/experimental/agent3/status") `
    -Headers $headers
$rig = $status.rig_validation
if ($null -eq $rig) {
    throw "Agent3-status mangler rig_validation. Backend/worker er ikke den forventede build."
}
if ($rig.configured -ne $true) {
    throw (
        "Evidensen er skrevet, men workeren blev ikke startet med rapportstien. " +
        "Sæt KALIV_AGENT3_VALIDATION_REPORT='$ReportPath' før worker-start, genstart workeren og kør kommandoen igen."
    )
}
if ($rig.present -ne $true) {
    $reasons = @($rig.reasons) -join ", "
    throw (
        "Workeren kan ikke se rapporten på sin konfigurerede sti. " +
        "Forventet lokal rapport: $ReportPath. Blockers: $reasons"
    )
}
if ($rig.eligible_for_developer_preview -ne $true) {
    $reasons = @($rig.reasons) -join ", "
    throw "Rapporten blev fundet, men promotion-gaten afviste den: $reasons"
}
if ($rig.production_activation -ne $false) {
    throw "Sikkerhedsbrud: status må aldrig sætte production_activation=true."
}

if (-not $SkipReadinessRegeneration) {
    Write-Host "[3/3] Regenererer lokal ACTIVATION_READINESS.md fra samme rapport"
    & python (Join-Path $repoRoot "scripts\activation_readiness.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Evidensen bestod, men readiness-generatoren fejlede med exit code $LASTEXITCODE."
    }
} else {
    Write-Host "[3/3] Readiness-regenerering blev eksplicit sprunget over"
}

$level = if ($rig.eligible_for_write_pilot -eq $true) { "write-pilot" } else { "developer-preview" }
Write-Host "PASS: fysisk Agent3-evidens er synlig for workeren ($level, production_activation=false)"
Write-Host "Rapport: $ReportPath"
''',
    encoding="utf-8",
)

replace_once(
    "AGENT3_RIG_VALIDATION.md",
    '''15. Læsning af backend-versionen fra den beskyttede `/api/v1/status`.
16. Læsning af worker-versionen fra Agent 3.0-status.
17. Afvisning før testen, hvis backend- og worker-version ikke matcher.
18. Krav om en eksplicit navngivet lokal planner-model.
19. Atomisk versionsbinding af den persistente rapport.
20. Evaluering af freshness, versionsmatch, receipt-binding, events, single-use og cleanup.
21. Permanent `production_activation=false`, uanset rapportens resultat.''',
    '''15. Læsning af backend-versionen fra den beskyttede `/api/v1/status`.
16. Læsning af worker-versionen fra Agent 3.0-status.
17. Binding til workerens konkrete code-fingerprint, ikke kun versionsnavnet.
18. Afvisning før testen, hvis backend- og worker-version ikke matcher.
19. Krav om en eksplicit navngivet lokal planner-model.
20. Atomisk versions- og kodebinding af den persistente rapport.
21. Evaluering af freshness, versionsmatch, kode-match, receipt-binding, events, single-use og cleanup.
22. Permanent `production_activation=false`, uanset rapportens resultat.''',
)
replace_once(
    "AGENT3_RIG_VALIDATION.md",
    '''- Branchen `agent/agent3-integration-draft-v2` er checket ud.
- Go-backend og worker kører fra samme build/version.''',
    '''- `main` eller det konkrete release-tag, der skal valideres, er checket ud.
- Go-backend og worker kører fra samme commit, version og code-fingerprint.''',
)
replace_once(
    "AGENT3_RIG_VALIDATION.md",
    "## Sikker standardkørsel — developer-preview-evidens\n",
    '''## Anbefalet one-command-kørsel

Fra repository-roden på ModelRig-maskinen:

```powershell
.\\scripts\\run-agent3-rig-validation.ps1 `
  -BaseUrl http://127.0.0.1:8080 `
  -PlannerModel qwen3:8b
```

Kommandoen bruger kun tokenet fra `MODELRIG_TOKEN`, skriver den flydende rapport til den
fælles standardsti, kører promotion-wrapperen, henter workerens redigerede status bagefter
og regenererer den lokale `ACTIVATION_READINESS.md` fra præcis samme rapport. Den fejler
lukket, hvis workeren ikke blev startet med samme `KALIV_AGENT3_VALIDATION_REPORT`.

Scriptet genstarter ikke services, ændrer ingen runtime-flags og aktiverer aldrig produktion.
En write-pilot kræver fortsat det eksplicitte flag `-ApproveWrite`.

## Sikker standardkørsel — developer-preview-evidens
''',
)

replace_once(
    "AGENT3_VALIDATION_CENTER.md",
    "- Promotion-evidens produceres separat med `scripts/agent3_rig_evidence.py`.",
    "- Promotion-evidens produceres med `scripts/run-agent3-rig-validation.ps1` (eller den underliggende `scripts/agent3_rig_evidence.py`).",
)

(ROOT / "tests" / "worker_agent3_validation_path_contract.py").write_text(
    '''from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import activation_readiness as readiness  # noqa: E402
import agent3_rig_validation as validation  # noqa: E402
from agent3_validation_paths import (  # noqa: E402
    DEFAULT_REPORT_RELATIVE,
    DEFAULT_REPORT_TEXT,
    default_report_path,
)

passed = 0


def check(condition: bool, name: str) -> None:
    global passed
    assert condition, name
    passed += 1


check(
    DEFAULT_REPORT_TEXT == "validation/agent3-rig-validation-latest.json",
    "the shared rolling report path is stable and repo-relative",
)
check(
    default_report_path(ROOT) == ROOT / DEFAULT_REPORT_RELATIVE,
    "the shared helper resolves below the repository root",
)

saved = os.environ.pop("KALIV_AGENT3_VALIDATION_REPORT", None)
try:
    check(
        validation.parse_args([]).report == DEFAULT_REPORT_TEXT,
        "the evidence harness defaults to the shared report path",
    )
    assessment = readiness.validation()
    check(
        assessment["path"] == DEFAULT_REPORT_TEXT,
        "local activation readiness defaults to the exact same report path",
    )
finally:
    if saved is not None:
        os.environ["KALIV_AGENT3_VALIDATION_REPORT"] = saved

ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
check(
    f"/{DEFAULT_REPORT_TEXT}" in ignore,
    "the rolling host-bound report remains git-ignored",
)

wrapper = (ROOT / "scripts" / "run-agent3-rig-validation.ps1").read_text(encoding="utf-8")
check(
    "validation\\agent3-rig-validation-latest.json" in wrapper,
    "the PowerShell operator command uses the shared report location",
)
check(
    "KALIV_AGENT3_VALIDATION_REPORT" in wrapper
    and "eligible_for_developer_preview" in wrapper
    and "production_activation" in wrapper,
    "the operator command verifies worker visibility and the fail-closed promotion result",
)
check(
    "--token" not in wrapper and "MODELRIG_TOKEN" in wrapper,
    "the operator command keeps the paired token out of command history",
)

doc = (ROOT / "AGENT3_RIG_VALIDATION.md").read_text(encoding="utf-8")
check(
    "agent/agent3-integration-draft-v2" not in doc
    and "run-agent3-rig-validation.ps1" in doc,
    "the physical validation guide no longer points at a merged branch and names the one-command path",
)

print(f"{passed} passed, 0 failed")
''',
    encoding="utf-8",
)

print("Agent3 validation command patch applied")

from __future__ import annotations

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
    DEFAULT_REPORT_TEXT in wrapper,
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

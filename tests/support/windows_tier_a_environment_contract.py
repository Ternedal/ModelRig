"""Real-Windows contract for the two-layer Tier-A environment allowlist."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from app.windows_restricted import RestrictedLaunchError  # noqa: E402
from app.windows_tier_a import appcontainer_environment  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def rejects(application_env, text, message):
    try:
        appcontainer_environment(
            dict(os.environ), application_env=application_env
        )
    except RestrictedLaunchError as exc:
        check(text in str(exc), message)
    else:
        check(False, message)


source = dict(os.environ)
source.update(
    {
        "GITHUB_TOKEN": "must-not-travel",
        "ACTIONS_RUNTIME_TOKEN": "must-not-travel",
        "OLLAMA_API_KEY": "must-not-travel",
    }
)
filtered = appcontainer_environment(
    source,
    application_env={
        "CI": "1",
        "MODELRIG_DEVCONTROL": "1",
        "GOTOOLCHAIN": "local",
        "PYTHONDONTWRITEBYTECODE": "1",
    },
)
check(filtered["CI"] == "1", "reviewed CI value is admitted")
check(
    filtered["GOTOOLCHAIN"] == "local",
    "reviewed toolchain value is admitted",
)
check(
    all(
        key not in filtered
        for key in ("GITHUB_TOKEN", "ACTIONS_RUNTIME_TOKEN", "OLLAMA_API_KEY")
    ),
    "parent credentials remain excluded when application values are added",
)
rejects(
    {"GITHUB_TOKEN": "secret"},
    "not reviewed",
    "an unreviewed application key is rejected",
)
rejects(
    {"CI": "false"},
    "value is not reviewed",
    "a reviewed key with an altered value is rejected",
)
rejects(
    {"CI": "1", "ci": "1"},
    "duplicate key",
    "case-insensitive duplicate application keys are rejected",
)

print(f"\n===== WINDOWS TIER-A ENV: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

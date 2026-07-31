"""Agent 4 identity guard plus the health intervention test cases."""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORE = Path(__file__).with_name("agent4_health_intervention_cases_core.py")
LEGACY = re.compile(r"(?:\bT-03\d\b|agent/t03)")
SKIP = {
    ROOT / "docs" / "AGENT_4_IDENTITY.md",
    Path(__file__).resolve(),
}
ALLOWED_HISTORICAL_COMMENTS = {
    "worker/app/agent4/resource_admission.py": {
        "This module is deliberately additive.  It composes the T-030 lifecycle service",
        "with the T-032 lease kernel without activating a background loop or changing the",
    },
    "worker/app/agent4/resources.py": {
        "is deliberately process-local: T-031 startup recovery fails interrupted",
    },
    "worker/app/agent4/failure_handling.py": {
        "# the existing T-031 startup recovery path.",
    },
}


def _verify_agent4_identity() -> None:
    candidates: list[Path] = []
    for root in (
        ROOT / "agent4",
        ROOT / "docs",
        ROOT / "worker" / "app" / "agent4",
        ROOT / "tests",
    ):
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".md", ".py"}:
                continue
            if path in SKIP:
                continue
            if root == ROOT / "docs" and not path.name.startswith("AGENT_4_"):
                continue
            if root == ROOT / "tests" and "agent4" not in path.as_posix().lower():
                continue
            candidates.append(path)

    violations: list[str] = []
    allowed_seen: set[tuple[str, str]] = set()
    for path in sorted(set(candidates)):
        relative = path.relative_to(ROOT).as_posix()
        allowed = ALLOWED_HISTORICAL_COMMENTS.get(relative, set())
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not LEGACY.search(stripped):
                continue
            if stripped in allowed:
                allowed_seen.add((relative, stripped))
                continue
            violations.append(f"{relative}:{number}: {stripped}")

    expected_allowed = {
        (path, line)
        for path, lines in ALLOWED_HISTORICAL_COMMENTS.items()
        for line in lines
    }
    violations.extend(
        f"historical allowlist entry no longer matches: {path}: {line}"
        for path, line in sorted(expected_allowed - allowed_seen)
    )
    if violations:
        raise AssertionError(
            "Agent 4 legacy identity contract failed:\n  " + "\n  ".join(violations)
        )


_verify_agent4_identity()

_spec = importlib.util.spec_from_file_location(
    "agent4_health_intervention_cases_core",
    CORE,
)
assert _spec is not None and _spec.loader is not None
_core = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_core)
Agent4HealthInterventionTests = _core.Agent4HealthInterventionTests

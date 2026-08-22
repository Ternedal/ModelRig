#!/usr/bin/env python3
"""Guard the live A4-25f runbook against stale physical SHA authority."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNBOOK = (ROOT / "docs" / "agent4" / "A4-25F_PHYSICAL_QUALIFICATION_RUNBOOK.md").read_text(
    encoding="utf-8"
)

assert "freshly exact-head-qualified current-main" in RUNBOOK
assert "agent4-a4-25f-harness" in RUNBOOK
assert "exact-head-qualification" in RUNBOOK
assert "Issue #474" in RUNBOOK
assert "historical reference material" in RUNBOOK
assert "Never use PR #475" in RUNBOOK
assert "371b0dc4da35461cfa670305f2839a0d8d5e4462" in RUNBOOK
assert "recorded on PR #475 / issue #474" not in RUNBOOK
assert '$sha = "371b0dc4da35461cfa670305f2839a0d8d5e4462"' not in RUNBOOK

print("A4-25f runbook current-main authority contract: PASS")

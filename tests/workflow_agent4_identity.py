#!/usr/bin/env python3
"""Agent 4 must use A4-* identities, never ModelRig T-03x task numbers."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY = re.compile(r"(?:\bT-03\d\b|agent/t03)")
SKIP = {ROOT / "docs" / "AGENT_4_IDENTITY.md"}

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
for path in sorted(set(candidates)):
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if LEGACY.search(line):
            violations.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")

if violations:
    print("Agent 4 legacy identity references remain:")
    for item in violations:
        print(f"  FAIL: {item}")
    raise SystemExit(1)

print(f"Agent 4 identity gate: {len(set(candidates))} files checked, 0 legacy references")

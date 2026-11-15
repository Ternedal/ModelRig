#!/usr/bin/env python3
"""Root launchers must not leave bytecode in the checkout.

`candidate_freeze_check._stray_bytecode` rejects any `.pyc` or `__pycache__`
outside `.git` and `validation`. A launcher that runs Python without
`PYTHONDONTWRITEBYTECODE=1` writes one for every local module its entry script
imports, and the next freeze check then reports NOT FROZEN on a candidate that
did not change (#2371).

The rule: a root `.cmd` that invokes Python either sets the variable before its
first invocation, or passes `-B` on every invocation. `rem` and `echo` lines
are not commands and satisfy nothing. A launcher that hands over to PowerShell
must set the variable too, because the script it starts inherits the
environment and `-B` cannot reach it.

Run: python3 tests/workflow_launcher_bytecode.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SET_FLAG = re.compile(r'^set\s+"?PYTHONDONTWRITEBYTECODE=1"?$', re.IGNORECASE)
PYTHON = re.compile(r"(?<![\w\\./-])(?:python|py)(?:\.exe)?\s+(?P<args>.*)$", re.IGNORECASE)
POWERSHELL = re.compile(r"(?<![\w\\./-])(?:powershell|pwsh)(?:\.exe)?\s", re.IGNORECASE)
NOT_A_COMMAND = re.compile(r"^(?:@?rem\b|::|@?echo\b|title\b|where\b)", re.IGNORECASE)


def verdict(text: str) -> tuple[int, str | None]:
    """Return (python invocations, problem or None) for one launcher."""
    flagged = False
    invocations = 0
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip().lstrip("(").strip()
        if not line or NOT_A_COMMAND.match(line):
            continue
        if SET_FLAG.match(line):
            flagged = True
            continue
        if POWERSHELL.search(line):
            invocations += 1
            if flagged:
                continue
            return invocations, f"line {number} starts PowerShell before PYTHONDONTWRITEBYTECODE=1"
        match = PYTHON.search(line)
        if not match:
            continue
        invocations += 1
        if flagged or re.match(r"-B(\s|$)", match.group("args")):
            continue
        return invocations, f"line {number} runs Python before PYTHONDONTWRITEBYTECODE=1 and without -B"
    return invocations, None


passed = failed = 0


def check(ok: bool, label: str) -> None:
    global passed, failed
    if ok:
        passed += 1
    else:
        failed += 1
        print(f"FAIL: {label}")


# The rule itself, on text it must accept and text it must reject.
GOOD = '@echo off\ncd /d "%~dp0"\nset "PYTHONDONTWRITEBYTECODE=1"\npython scripts\\x.py\n'
check(verdict(GOOD) == (1, None), "flag before the invocation is accepted")
check(verdict("python -B scripts\\x.py\n") == (1, None), "-B on the invocation is accepted")
check(verdict("python scripts\\x.py\n")[1] is not None, "a bare invocation is rejected")
check(verdict('python scripts\\x.py\nset "PYTHONDONTWRITEBYTECODE=1"\n')[1] is not None,
      "a flag set after the invocation is rejected")
check(verdict('rem set "PYTHONDONTWRITEBYTECODE=1"\npython scripts\\x.py\n')[1] is not None,
      "a commented-out flag is rejected")
check(verdict('echo set "PYTHONDONTWRITEBYTECODE=1"\npython scripts\\x.py\n')[1] is not None,
      "an echoed flag is rejected")
check(verdict("if x (\n  python scripts\\x.py prepare\n)\n")[1] is not None,
      "an invocation inside a block is seen")
check(verdict("python -B a.py\npython b.py\n")[1] is not None,
      "-B on one invocation does not cover the next")
check(verdict("echo python is required\nwhere python >nul 2>nul\n") == (0, None),
      "echo and where are not invocations")

check(verdict("powershell -File scripts\\x.ps1\n")[1] is not None,
      "a PowerShell hand-over without the flag is rejected")
check(verdict("python -B a.py\npowershell -File scripts\\x.ps1\n")[1] is not None,
      "-B does not cover a PowerShell hand-over")
check(verdict('set "PYTHONDONTWRITEBYTECODE=1"\npowershell -File scripts\\x.ps1\n') == (1, None),
      "a PowerShell hand-over after the flag is accepted")

launchers = sorted(ROOT.glob("*.cmd"))
check(len(launchers) >= 20, "the root launchers are found")
running_python = 0
for launcher in launchers:
    count, problem = verdict(launcher.read_text(encoding="utf-8", errors="replace"))
    running_python += 1 if count else 0
    check(problem is None, f"{launcher.name}: {problem}")
check(running_python >= 15, "the scan sees the launchers that run Python")

print(f"\n===== LAUNCHER BYTECODE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

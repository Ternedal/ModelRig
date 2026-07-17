#!/usr/bin/env python3
"""Generate CURRENT_STATE.md from the repo -- never by hand.

F-209: the authoritative docs disagreed with each other and with main. The
root cause is not laziness, it is the design: README promised that "STATUS.md
line 3 is always the current one-liner", which required every session to
remember. Line 3 spent 55 releases claiming 1.58.2. A convention that depends
on memory is a convention that is already dead; it just has not been noticed.

So this file is derived from the things that cannot lie -- VERSION, the tool
registry, the env switches in the source, the test glob -- and CI regenerates
it and fails if the committed copy differs (tests/workflow_current_state.py).
Drift becomes a red build instead of a wrong answer six weeks later.

Deliberately NO dates and no prose-by-hand: a timestamp would make the check
fail every midnight, and a hand-written sentence is exactly the thing that
rots. If a fact belongs here, teach the generator to read it.

Run: python3 scripts/current_state.py [--check]
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "CURRENT_STATE.md"


def _tools() -> list[tuple[str, str, str]]:
    """Ask the registry itself. A doc that lists tools by hand lists them wrong."""
    tmp = tempfile.mkdtemp(prefix="kaliv-state-")
    env = dict(os.environ)
    env.update({
        "KALIV_AUDIT_DB": os.path.join(tmp, "a.db"),
        "KALIV_TOOLS_STATE": os.path.join(tmp, "s.json"),
        "KALIV_JOBS_DB": os.path.join(tmp, "j.db"),
        "KALIV_TOOLS_DIR": tmp,
        "PYTHONPATH": str(ROOT / "worker"),
    })
    code = (
        "from app.tools import REGISTRY\n"
        "for n, t in sorted(REGISTRY.items()):\n"
        "    print(f'{n}|{t.risk}|{t.sensitivity}|{int(bool(t.isolate))}')\n"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, env=env, cwd=str(ROOT / "worker"), timeout=60)
    if out.returncode != 0:
        raise SystemExit(f"cannot read the tool registry:\n{out.stderr[-800:]}")
    rows = []
    for line in out.stdout.strip().splitlines():
        name, risk, sens, iso = line.split("|")
        rows.append((name, risk, sens, iso == "1"))
    return rows


def _switches() -> list[tuple[str, str]]:
    """Every env switch this SYSTEM reads, with its default.

    It used to say "the worker" and scan worker/**/*.py, which meant
    KALIV_SCHEDULER_API -- the Go switch deciding whether the schedule admin
    surface is reachable remotely at all -- was absent from the page whose
    promise is that it cannot be wrong (F-613). The system is Go and Python; a
    scan of one language's directory measures my search path, not the system.
    """
    found: dict[str, str] = {}
    pat = re.compile(r'getenv\(\s*"(KALIV_[A-Z0-9_]+)"\s*(?:,\s*"([^"]*)")?')
    for py in sorted((ROOT / "worker").rglob("*.py")):
        for m in pat.finditer(py.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(m.group(1), m.group(2) if m.group(2) is not None else "(unset)")
    # os.Getenv("X") == "1" is unambiguous: off unless someone sets it to 1.
    # Only that pattern is listed -- a key or a path read from the Go
    # environment is a setting, and padding a switch table with settings is how
    # a table stops being read.
    go = re.compile(r'os\.Getenv\(\s*"((?:KALIV|MODELRIG)_[A-Z0-9_]+)"\s*\)\s*==\s*"1"')
    for src in sorted((ROOT / "backend").rglob("*.go")):
        if src.name.endswith("_test.go"):
            continue
        for m in go.finditer(src.read_text(encoding="utf-8", errors="replace")):
            found.setdefault(m.group(1), "0")
    return sorted(found.items())


def _suites() -> list[str]:
    return sorted(p.name for p in (ROOT / "tests").glob("*.py"))


def _designs() -> list[tuple[str, str]]:
    """Design docs and the STATUS line each one declares about itself."""
    rows = []
    for p in sorted(ROOT.glob("*.md")):
        if not (p.name.endswith("_DESIGN.md") or p.name.startswith("VALIDATION-")):
            continue
        status = "(no status header)"
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines()[:12]:
            if line.startswith("**Status:**"):
                status = line[len("**Status:**"):].strip()
                break
        rows.append((p.name, status))
    return rows


def render() -> str:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    L: list[str] = []
    L.append("# CURRENT_STATE.md")
    L.append("")
    L.append("> **GENERATED — do not edit.** `python3 scripts/current_state.py`")
    L.append("> regenerates this; CI fails if the committed copy has drifted")
    L.append("> (`tests/workflow_current_state.py`). Everything here is read out of the")
    L.append("> code, so it cannot quietly become untrue. If a fact belongs here, teach")
    L.append("> the generator to read it -- do not type it in.")
    L.append("")
    L.append(f"**Version:** {version}")
    L.append("")
    L.append("## Tools the model can see")
    L.append("")
    L.append("`risk` gates what a tool may DO. `sensitivity` gates where its ANSWER may")
    L.append("travel. They are orthogonal.")
    L.append("")
    L.append("| Tool | risk | sensitivity | isolated |")
    L.append("|---|---|---|---|")
    for name, risk, sens, iso in _tools():
        L.append(f"| `{name}` | {risk} | {sens} | {'yes' if iso else 'no'} |")
    L.append("")
    L.append("## Switches (default = what a rig does today)")
    L.append("")
    L.append("| Env | Default |")
    L.append("|---|---|")
    for k, v in _switches():
        L.append(f"| `{k}` | `{v}` |")
    L.append("")
    L.append("## Design docs and what they claim about themselves")
    L.append("")
    L.append("| Doc | Status |")
    L.append("|---|---|")
    for name, status in _designs():
        L.append(f"| `{name}` | {status} |")
    L.append("")
    L.append("## Test suites in CI")
    L.append("")
    L.append("Run by glob, so a file that matches is a file that runs")
    L.append("(`tests/workflow_test_coverage.py` proves none can hide).")
    L.append("")
    for name in _suites():
        L.append(f"- `tests/{name}`")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("CURRENT_STATE.md is stale. Run: python3 scripts/current_state.py")
            raise SystemExit(1)
        print("CURRENT_STATE.md is current")
        raise SystemExit(0)
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")

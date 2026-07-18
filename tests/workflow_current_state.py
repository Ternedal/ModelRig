"""Contract test: CURRENT_STATE.md cannot go stale.

The doc it guards is generated from the code. This asserts the committed copy
still matches what the generator produces, so drift is a red build rather than
a wrong answer to whoever reads it next.

Why this exists at all (F-209): README promised "STATUS.md line 3 is always the
current one-liner". It required every session to remember. Line 3 spent 55
releases claiming version 1.58.2 while main was at 1.58.57, and nothing ever
said so. Conventions that depend on memory do not fail loudly -- they just
quietly stop being true.

Run: python3 tests/workflow_current_state.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


gen = ROOT / "scripts" / "current_state.py"
doc = ROOT / "CURRENT_STATE.md"

check(gen.exists(), "the generator exists")
check(doc.exists(), "CURRENT_STATE.md is committed")

r = subprocess.run([sys.executable, str(gen), "--check"], capture_output=True,
                   text=True, cwd=str(ROOT), timeout=120)
check(r.returncode == 0,
      "CURRENT_STATE.md matches the code"
      if r.returncode == 0
      else f"CURRENT_STATE.md HAS DRIFTED -- run: python3 scripts/current_state.py ({r.stdout.strip()})")

text = doc.read_text(encoding="utf-8")
version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
check(f"**Version:** {version}" in text, f"the doc names the real version ({version})")
check("GENERATED — do not edit" in text, "the doc says loudly that it is generated")

# The facts a reader most needs, straight from the registry. list_documents is
# the private read: risk read, impact read, sensitivity private.
check("| `list_documents` | read | read | private |" in text,
      "the tool table carries the live risk, impact AND sensitivity")
check("`KALIV_EGRESS_GATE`" in text and "`KALIV_TOOL_ISOLATION`" in text,
      "the dormant switches are listed with their real defaults")

# The detector must be able to fail, or it is decoration.
mutated = text.replace(f"**Version:** {version}", "**Version:** 9.9.9")
backup = text
try:
    doc.write_text(mutated, encoding="utf-8")
    r2 = subprocess.run([sys.executable, str(gen), "--check"], capture_output=True,
                        text=True, cwd=str(ROOT), timeout=120)
    check(r2.returncode != 0, "self-test: a doctored CURRENT_STATE.md IS detected as stale")
finally:
    doc.write_text(backup, encoding="utf-8")

# --- the page must measure the SYSTEM, not my search path (F-613) ----------
# The scan covered worker/**/*.py, so KALIV_SCHEDULER_API -- the Go switch that
# decides whether the schedule admin surface is reachable REMOTELY at all -- was
# absent from the page whose whole promise is that it cannot be wrong. Not a
# stale fact: a fact that was never in scope. Same shape as the entrypoint scan
# that walked only the folders I thought of, and as running the test suites I
# considered relevant instead of the glob.

check("KALIV_SCHEDULER_API" in text,
      "the Go backend's switches are on the page too -- the system is not one "
      "language, and a scan of one directory measures the scanner")

import sys as _sys  # noqa: E402
_sys.path.insert(0, str(ROOT / "scripts"))
import current_state as _CS  # noqa: E402

_names = {n for n, _ in _CS._switches()}
check("KALIV_SCHEDULER_API" in _names, "the generator finds it, not just the committed copy")
check("KALIV_AGENT3_ENABLED" in _names, "and it did not lose the Python ones on the way")

# Drive it: a Go switch that does not exist must not appear.
check("KALIV_NOT_A_REAL_SWITCH" not in _names,
      "self-test: the scanner reports what is in the code, not what it hopes")

# Settings are not switches. A key read from the environment is not a decision,
# and padding the table with them is how a table stops being read.
check("MODELRIG_ADMIN_KEY" not in _names,
      "a credential read from the Go environment is not listed as a switch")

# --- the authoritative page shows every axis the registry owns (F-718) ------
# It showed risk, sensitivity, isolation and hid impact, schedulable,
# cancellation, idempotent -- so it could not say what runs unattended or
# replays, which is exactly what those axes decide. A hand-picked column set
# hides the next axis added, so assert the table against the tools that carry
# the decisions.

for _needle in ("| impact |", "| sched |", "| stop |", "| replay |"):
    check(_needle in text,
          f"the tool table has a {_needle.strip(' |')} column")

# The dangerous tools must be legible as dangerous FROM THIS PAGE, not just in
# code: delete_model destructive and unschedulable, pull_model cooperative.
import re as _re2  # noqa: E402
_row = {}
for _line in text.splitlines():
    _m = _re2.match(r"\| `([a-z_]+)` \|(.+)\|", _line)
    if _m:
        _row[_m.group(1)] = [c.strip() for c in _m.group(2).split("|")]

check("destructive" in _row.get("delete_model", []),
      "delete_model reads as destructive on the page, not only in the registry")
check("cooperative" in _row.get("pull_model", []),
      "pull_model's cancellation is visible")
# schedulable and replay are the columns a person scans before trusting a
# schedule; they must carry the real answer.
check(_row.get("delete_model", ["", "", "", "", "no"])[4] == "no",
      "delete_model shows it cannot be scheduled")
check(_row.get("note_append", ["", "", "", "", "", "", "no"])[-1] == "no",
      "note_append shows re-running it is not free")

# --- the page must not claim physical proof it cannot see (F-813) -----------
# CURRENT_STATE used to say "Ægte DPAPI bevist på Windows-runner: ja" because a
# job name was in the workflow and a test file was on disk. That proves the test
# is DEFINED, not that it PASSED on this commit -- the same overclaim as a
# readiness page attesting to the door it read. The generator runs offline and
# cannot see CI status, so it must not assert the stronger claim.

check("bevist på Windows-runner** | ja" not in text
      and "DPAPI bevist på Windows-runner | ja" not in text,
      "the page no longer claims DPAPI is PROVEN from a job name and a filename")
check("kan ikke verificeres offline" in text,
      "and it says plainly that passed-on-this-commit needs CI status the "
      "offline generator does not have")
# The weaker, true claim is still made, so we did not just delete the signal.
check("defineret og koblet i CI" in text,
      "the true, filesystem-checkable claim -- the test is defined and wired -- "
      "is still reported")

print(f"\n===== CURRENT STATE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

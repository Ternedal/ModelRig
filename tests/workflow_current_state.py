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

# The two facts a reader most needs, and the two most likely to rot by hand.
check("| `list_documents` | read | private |" in text,
      "the tool table carries the live risk AND sensitivity, straight from the registry")
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

print(f"\n===== CURRENT STATE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

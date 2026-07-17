"""ACTIVATION_READINESS.md is generated, and must not drift (F-306).

Doc drift is cosmetic when it describes a feature. It is a safety failure when
it describes READINESS, because that page is what a person reads in the moment
they decide to let software act on its own. The analysis found four documents
answering that question and all four were wrong at once: ROADMAP described a
pre-Agent-3 repo, HANDOFF said 1.58.52 while main was 60 releases past it, the
Agent 3 document listed delivered features as missing, and the validation
instructions pointed at a branch that had already merged. Each was written by
someone who believed it at the time.

Run: python3 tests/workflow_activation_readiness.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "ACTIVATION_READINESS.md"
GEN = ROOT / "scripts" / "activation_readiness.py"

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


check(GEN.exists(), "the generator exists")
check(DOC.exists(), "ACTIVATION_READINESS.md exists")

r = subprocess.run([sys.executable, str(GEN), "--check"],
                   capture_output=True, text=True, cwd=str(ROOT))
check(r.returncode == 0,
      "the committed page matches the code"
      if r.returncode == 0
      else f"DRIFTED -- regenerate it: {r.stdout.strip()}")

text = DOC.read_text(encoding="utf-8")
check("Ret ikke i hånden" in text, "the page says not to hand-edit it")
check((ROOT / "VERSION").read_text().strip() in text,
      "it names the version on main, so it cannot silently describe an older repo")

# It must fail closed. Today there is no physical validation report for main,
# so the only honest answer is NO -- and if this ever flips to JA without a
# report appearing, the generator has stopped being fail-closed.
has_report = (ROOT / "agent3-validation-latest.json").exists()
if not has_report:
    check("aktiveres nu? **NEJ**" in text,
          "with no validation report on disk, the answer is NO -- fail closed")
    check("fysisk validering er ikke kørt" in text,
          "and it says exactly what is missing, not just that something is")

check("agent3-validation-latest.json" in text and "/home/" not in text,
      "the report path is relative -- an absolute one bakes one machine into a "
      "committed file")

print(f"\n===== ACTIVATION READINESS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

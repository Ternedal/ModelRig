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

# --- the blocker that would otherwise be forgotten (F-310) ------------------
# Physical validation is the blocker everyone knows about. This is the one that
# is invisible from the outside, is nobody's bug, and disappears on its own when
# the planner lands -- which is exactly why a human reading this page after a
# clean rig run would flip the flag without ever hearing about it.

import sys as _sys  # noqa: E402
_sys.path.insert(0, str(ROOT / "scripts"))
import activation_readiness as AR  # noqa: E402

server_plans, note = AR.plan_authority()
check(server_plans is False,
      "the run API still takes a client-supplied plan, and the page says so "
      "rather than leaving physical validation as the only blocker")
check("serveren" in note, "the blocker explains WHOSE promise the plan is")
check("plans/{plan_id}/start" in note,
      "and names the server-authored path that ALREADY exists -- my first "
      "version of this blocker claimed there was none, having read one "
      "endpoint and stopped reading")
check("runs" in note,
      "while still naming the client-plan door that is open beside it")
check(note in text, "the computed blocker actually reaches the rendered page")

# Drive the detector: if the API ever stops taking a plan, this must flip.
from app.agent3 import api as _api  # noqa: E402
_saved = _api.StartReq.model_fields
try:
    _api.StartReq.model_fields = {k: v for k, v in _saved.items() if k != "plan"}
    ok, _ = AR.plan_authority()
    check(ok is True,
          "self-test: with no client plan field, the blocker clears -- a check "
          "that can only fail is as useless as one that can only pass")
finally:
    _api.StartReq.model_fields = _saved

# --- the scheduler's approval proves knowledge, not consent (F-503/F-504) ---

approval_ok, approval_note = AR.schedule_approval_authority()
check(approval_ok is False,
      "the page says a scheduled write's approval does not prove a human decided")
check("kendskab" in approval_note and "samtykke" in approval_note,
      "and names the actual distinction: knowing the arguments is not consenting")
check("Latent" in approval_note,
      "and says it is latent today rather than crying wolf -- no tool can reach "
      "loopback yet")
check(approval_note in text, "the blocker reaches the rendered page")

check("## Kan scheduleren aktiveres nu?" in text,
      "the scheduler has its OWN verdict: pooling blockers would tell a reader "
      "Agent 3 is held up by something unrelated to Agent 3")
check(approval_note not in text.split("## Kan scheduleren")[0],
      "...and the scheduler's blocker does not appear under the Agent 3 verdict")

# Drive it: if the API grows a real approval mechanism, this must clear.
from app.schedule_api import CreateScheduleReq as _CSR  # noqa: E402
_saved = _CSR.model_fields
try:
    _CSR.model_fields = {k: v for k, v in _saved.items() if k != "approved_fingerprint"}
    ok, _ = AR.schedule_approval_authority()
    check(ok is True,
          "self-test: with no client-supplied fingerprint the blocker clears")
finally:
    _CSR.model_fields = _saved

print(f"\n===== ACTIVATION READINESS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

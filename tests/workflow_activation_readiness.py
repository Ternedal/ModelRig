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
sys.path.insert(0, str(ROOT / "scripts"))
from agent3_validation_paths import DEFAULT_REPORT_RELATIVE, DEFAULT_REPORT_TEXT  # noqa: E402

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
has_report = (ROOT / DEFAULT_REPORT_RELATIVE).exists()
if not has_report:
    check("aktiveres nu? **NEJ**" in text,
          "with no validation report on disk, the answer is NO -- fail closed")
    check("fysisk validering er ikke kørt" in text,
          "and it says exactly what is missing, not just that something is")

check(DEFAULT_REPORT_TEXT in text and "/home/" not in text,
      "the report path is relative -- an absolute one bakes one machine into a "
      "committed file")

# --- server plan authority (F-310 closed) -------------------------------------
import sys as _sys  # noqa: E402
_sys.path.insert(0, str(ROOT / "scripts"))
import activation_readiness as AR  # noqa: E402

server_plans, note = AR.plan_authority()
check(server_plans is True,
      "production run creation is server-authoritative")
check("serveren" in note and "plan-id" in note,
      "the readiness explanation names the server-owned single-use plan")
check("Serverbygget plan:** ja" in text,
      "the generated page records that the client-plan blocker is closed")
check(note in text, "the computed authority result reaches the rendered page")

# Drive the detector in the unsafe direction: reintroducing a plan field must
# fail closed instead of silently keeping the green verdict.
from app.agent3 import api as _api  # noqa: E402
_saved = _api.StartReq.model_fields
try:
    _api.StartReq.model_fields = {**_saved, "plan": object()}
    ok, unsafe_note = AR.plan_authority()
    check(ok is False and "klienten" in unsafe_note,
          "self-test: a reintroduced client plan field restores the blocker")
finally:
    _api.StartReq.model_fields = _saved

# --- scheduler approval is backend-issued consent, not a known digest ---------

approval_ok, approval_note = AR.schedule_approval_authority()
check(approval_ok is True,
      "scheduled writes require a backend-issued cryptographic approval")
check("Ed25519" in approval_note and "private" in approval_note
      and "én gang" in approval_note,
      "the explanation names asymmetric authority, short lifetime and replay stop")
check(approval_note in text, "the computed scheduler authority reaches the page")

check("## Kan scheduleren aktiveres nu?" in text,
      "the scheduler has its OWN verdict")
check("Beviser en godkendelse et menneske:** ja" in text,
      "the generated page records that the consent blocker is closed")

# Drive the detector unsafe: restoring the old client-computable field must
# restore the blocker before any prose can claim otherwise.
from app.schedule_api import CreateScheduleReq as _CSR  # noqa: E402
_saved = _CSR.model_fields
try:
    _CSR.model_fields = {
        **{k: v for k, v in _saved.items() if k != "approval_token"},
        "approved_fingerprint": object(),
    }
    ok, unsafe_note = AR.schedule_approval_authority()
    check(ok is False and "klient" in unsafe_note,
          "self-test: reintroducing a client fingerprint restores the blocker")
finally:
    _CSR.model_fields = _saved

# --- the gate must try the door, not read about it (F-612) -----------------
# This check used to grep schedule_api.py for "Bearer", "Depends(" and friends.
# A TODO comment mentioning Bearer flipped the verdict from blocked to safe --
# verified, it did. A gate whose job is to stop someone activating on a false
# premise, defeated by a comment, is a false premise wearing a badge.

_opened = AR._try_to_mint_a_standing_grant()
check(_opened is False,
      "the gate proves the door is closed: a forged local token is refused, a "
      "backend-signed token works once, and replay is refused"
      if _opened is False
      else f"the approval probe did not prove the full contract (got {_opened!r})")

# The comment trick must not work any more.
_api = ROOT / "worker" / "app" / "schedule_api.py"
_orig = _api.read_text(encoding="utf-8")
try:
    _api.write_text("# TODO: consider Bearer tokens and Depends() one day\n" + _orig,
                    encoding="utf-8")
    _ok, _ = AR.schedule_approval_authority()
    check(_ok is True,
          "a comment saying 'Bearer' cannot change the executable approval proof")
finally:
    _api.write_text(_orig, encoding="utf-8")

print(f"\n===== ACTIVATION READINESS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

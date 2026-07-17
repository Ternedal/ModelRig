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

import os
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

def _doors_with_fixture() -> list[str]:
    """Build the router WITH the client-plan fixture on and count the doors.

    A detector that always answers [] is indistinguishable from a closed door,
    and mine did exactly that for one build: reading body_field.type_ instead of
    field_info.annotation returned None on pydantic v2, so it reported zero
    doors while /replan stood open. This is the check that tells the difference.
    """
    import tempfile as _tf

    tmp = _tf.mkdtemp()
    for var, name in (("KALIV_AUDIT_DB", "a.db"), ("KALIV_TOOLS_STATE", "s.json"),
                      ("MODELRIG_DB", "r.db")):
        os.environ.setdefault(var, os.path.join(tmp, name))
    os.environ.setdefault("KALIV_TOOLS_DIR", tmp)

    from app.agent3.api import build_router as _br
    from app.agent3.core import Agent3Orchestrator as _Orch, AgentRunStore as _St
    from app.agent3.integration import V2ToolAdapter as _Ad

    ad = _Ad()
    router = _br(_Orch(_St(os.path.join(tmp, "runs.db")), ad.execute, max_steps=8),
                 ad, worker_version="selftest", allow_client_plans=True)
    out = []
    for route in router.routes:
        body = getattr(route, "body_field", None)
        model = None
        if body is not None:
            model = (getattr(getattr(body, "field_info", None), "annotation", None)
                     or getattr(body, "type_", None))
        if model is not None and "plan" in getattr(model, "model_fields", {}):
            out.append(getattr(route, "path", "?"))
    return sorted(out)


# Drive the detector in the unsafe direction. This used to overwrite
# StartReq.model_fields with a fake dict, which simulated a door by poking
# pydantic. The gate no longer reads models -- it builds the production router
# and looks at the routes -- so the fake dict now breaks the BUILD, which is
# fail-closed and correct but reports a different reason. Better: open a real
# door and check it is seen.
_fixture_doors = _doors_with_fixture()
check(len(_fixture_doors) == 2,
      f"self-test: with the fixture flag on, the detector finds both real "
      f"client-plan doors ({_fixture_doors}) -- so [] in production means "
      "closed, not blind"
      if len(_fixture_doors) == 2
      else f"the detector found {len(_fixture_doors)} of 2 known doors: "
           f"{_fixture_doors}")

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

# --- the gate must try the door, not read about it (F-612) -----------------
# This check used to grep schedule_api.py for "Bearer", "Depends(" and friends.
# A TODO comment mentioning Bearer flipped the verdict from blocked to safe --
# verified, it did. A gate whose job is to stop someone activating on a false
# premise, defeated by a comment, is a false premise wearing a badge.

_opened = AR._try_to_mint_a_standing_grant()
check(_opened is True,
      "the gate PROVES the bypass rather than describing it: a loopback caller "
      "with no credential previews, gets the fingerprint, and creates a standing "
      "grant for a write tool"
      if _opened is True
      else f"the probe could not demonstrate the bypass (got {_opened!r}) -- a gate "
           "that cannot test is back to guessing")

# The comment trick must not work any more.
_api = ROOT / "worker" / "app" / "schedule_api.py"
_orig = _api.read_text(encoding="utf-8")
try:
    _api.write_text("# TODO: consider Bearer tokens and Depends() one day\n" + _orig,
                    encoding="utf-8")
    _ok, _ = AR.schedule_approval_authority()
    check(_ok is False,
          "a comment saying 'Bearer' no longer makes the approval look safe")
finally:
    _api.write_text(_orig, encoding="utf-8")

# --- plan authority is a property, not a door (F-608) ----------------------
# The gate read StartReq, found no client plan, and wrote "the plan is built and
# stored on the server". ReplanReq.plan was open the whole time and the page
# said SAFE -- verified, it did. It attested to the door I had just fixed.

_doors = AR._client_plan_routes()
check(_doors is not None,
      "the gate can build the production router and look"
      if _doors is not None
      else "the gate could not build the router -- it must not report safety it "
           "could not check")
check(_doors == [],
      "no production route accepts a client-authored plan"
      if _doors == []
      else f"client-authored plans are reachable via {_doors}")



print(f"\n===== ACTIVATION READINESS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

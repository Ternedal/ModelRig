"""ACTIVATION_READINESS.md is generated, and must not drift (F-306).

Doc drift is cosmetic when it describes a feature. It is a safety failure when
it describes READINESS, because that page is what a person reads in the moment
they decide to let software act on its own.

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

r = subprocess.run(
    [sys.executable, str(GEN), "--check"],
    capture_output=True,
    text=True,
    cwd=str(ROOT),
)
check(
    r.returncode == 0,
    "the committed page matches the code"
    if r.returncode == 0
    else f"DRIFTED -- regenerate it: {r.stdout.strip()}",
)

text = DOC.read_text(encoding="utf-8")
check("Ret ikke i hånden" in text, "the page says not to hand-edit it")
check(
    (ROOT / "VERSION").read_text().strip() in text,
    "it names the version on main, so it cannot silently describe an older repo",
)

# It must fail closed. Today there is no physical validation report for main,
# so the only honest answer is NO -- and if this ever flips to JA without a
# report appearing, the generator has stopped being fail-closed.
has_report = (ROOT / DEFAULT_REPORT_RELATIVE).exists()
if not has_report:
    check(
        "aktiveres nu? **NEJ**" in text,
        "with no validation report on disk, the answer is NO -- fail closed",
    )
    check(
        "fysisk validering er ikke kørt" in text,
        "and it says exactly what is missing, not just that something is",
    )

check(
    DEFAULT_REPORT_TEXT in text and "/home/" not in text,
    "the report path is relative -- an absolute one bakes one machine into a committed file",
)

# --- server plan authority (F-310 closed) -----------------------------------
import sys as _sys  # noqa: E402

_sys.path.insert(0, str(ROOT / "scripts"))
import activation_readiness as AR  # noqa: E402

server_plans, note = AR.plan_authority()
check(server_plans is True, "production run creation is server-authoritative")
check(
    "serveren" in note and "plan-id" in note,
    "the readiness explanation names the server-owned single-use plan",
)
check(
    "Serverbygget plan:** ja" in text,
    "the generated page records that the client-plan blocker is closed",
)
check(note in text, "the computed authority result reaches the rendered page")


def _doors_with_fixture() -> list[str]:
    """Build the router WITH the client-plan fixture on and count the doors."""
    import tempfile as _tf

    tmp = _tf.mkdtemp()
    for var, name in (
        ("KALIV_AUDIT_DB", "a.db"),
        ("KALIV_TOOLS_STATE", "s.json"),
        ("MODELRIG_DB", "r.db"),
    ):
        os.environ.setdefault(var, os.path.join(tmp, name))
    os.environ.setdefault("KALIV_TOOLS_DIR", tmp)

    from app.agent3.api import build_router as _br
    from app.agent3.core import Agent3Orchestrator as _Orch, AgentRunStore as _St
    from app.agent3.integration import V2ToolAdapter as _Ad

    ad = _Ad()
    router = _br(
        _Orch(_St(os.path.join(tmp, "runs.db")), ad.execute, max_steps=8),
        ad,
        worker_version="selftest",
        allow_client_plans=True,
    )
    out = []
    for route in router.routes:
        body = getattr(route, "body_field", None)
        model = None
        if body is not None:
            model = (
                getattr(getattr(body, "field_info", None), "annotation", None)
                or getattr(body, "type_", None)
            )
        if model is not None and "plan" in getattr(model, "model_fields", {}):
            out.append(getattr(route, "path", "?"))
    return sorted(out)


_fixture_doors = _doors_with_fixture()
check(
    len(_fixture_doors) == 2,
    f"self-test: with the fixture flag on, the detector finds both real client-plan doors ({_fixture_doors})"
    if len(_fixture_doors) == 2
    else f"the detector found {len(_fixture_doors)} of 2 known doors: {_fixture_doors}",
)

# --- scheduled-write consent is now issued, expiring and one-shot (F-503/504) -
#
# The old contract let a loopback caller compute sha256(tool,args), return it to
# /schedules and mint a standing write grant. The readiness gate must drive that
# exact attack and see it fail. Merely spotting a field or a comment is not proof.

# The probe returned False, which is the answer we want, and False is also what
# a probe returns when it is aiming at a door that no longer exists. Anders
# replaced the forgeable fingerprint with backend-issued single-use tokens while
# this gate was still pointed at the old field; a probe that only knows
# yesterday's attack reports safety forever. So require it to still be able to
# REACH a create attempt -- if it cannot, every False it has returned means
# "I could not find the door", which reads identically to safety.
def _probe_can_still_reach_the_door() -> bool:
    import tempfile as _tf

    tmp = _tf.mkdtemp()
    for var, name in (("KALIV_SCHEDULE_DB", "s.db"), ("KALIV_AUDIT_DB", "a.db"),
                      ("KALIV_TOOLS_STATE", "st.json"), ("MODELRIG_DB", "r.db")):
        os.environ.setdefault(var, os.path.join(tmp, name))
    os.environ.setdefault("KALIV_TOOLS_DIR", tmp)
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import schedule_api as _sapi

    app = FastAPI()
    app.include_router(_sapi.build_schedule_router())
    client = TestClient(app, client=("127.0.0.1", 51234))
    pv = client.post("/schedules/preview",
                     json={"tool": "note_append", "args": {"text": "probe"},
                           "cadence": "daily:03:00"})
    return (pv.status_code == 200
            and pv.json().get("preview", {}).get("approval_fingerprint") is not None)


check(_probe_can_still_reach_the_door(),
      "the bypass probe can still get a preview and a fingerprint, so its False "
      "means 'refused' and not 'I could not find the way in'")

approval_ok, approval_note = AR.schedule_approval_authority()
check(
    approval_ok is True,
    "a local process without an authenticated confirmation cannot mint a standing write grant",
)
check(
    "uden legitimation" in approval_note and "ikke oprette" in approval_note,
    "the readiness result says what was actually attempted and refused",
)
check(
    "Beviser en godkendelse et menneske:** ja" in text,
    "the generated scheduler verdict records that the consent blocker is closed",
)
check(
    "Ingen blokerende fund specifikke for scheduleren." in text,
    "the old predictable-fingerprint blocker is absent from the rendered page",
)
check(
    "## Kan scheduleren aktiveres nu?" in text,
    "the scheduler keeps its own verdict rather than borrowing Agent 3 blockers",
)

from app.schedule_api import CreateScheduleReq as _CSR  # noqa: E402
from app.schedule_approval import MAX_TOKEN_LIFETIME_SECONDS as _MAX_TOKEN  # noqa: E402

_fields = _CSR.model_fields
check(
    "approval_token" in _fields,
    "write creation accepts an opaque issued approval token",
)
check(
    "approved_fingerprint" in _fields
    and _fields["approved_fingerprint"].annotation in (None, type(None)),
    "the retired fingerprint remains only as a rejecting tombstone so the negative probe keeps running",
)
check(
    _MAX_TOKEN <= 180,
    "approval tokens have a minutes-long maximum lifetime, not a standing lifetime",
)

_opened = AR._try_to_mint_a_standing_grant()
check(
    _opened is False,
    "the end-to-end bypass probe is refused"
    if _opened is False
    else f"the old loopback fingerprint bypass still opened (got {_opened!r})",
)

# Mutation-check the readiness decision in the unsafe direction. If the probe
# can mint again, the page must immediately go red; otherwise the detector could
# be a constant True wearing a security badge.
_saved_probe = AR._try_to_mint_a_standing_grant
try:
    AR._try_to_mint_a_standing_grant = lambda: True
    unsafe_ok, unsafe_note = AR.schedule_approval_authority()
    check(
        unsafe_ok is False and "kendskab" in unsafe_note and "samtykke" in unsafe_note,
        "self-test: reopening the old bypass flips readiness back to blocked",
    )
finally:
    AR._try_to_mint_a_standing_grant = _saved_probe

# A comment must not affect the result. This used to grep source text for words
# such as Bearer and Depends(), so a TODO could make the page claim safety.
_api = ROOT / "worker" / "app" / "schedule_api.py"
_orig = _api.read_text(encoding="utf-8")
try:
    _api.write_text("# TODO: consider Bearer tokens and Depends() one day\n" + _orig, encoding="utf-8")
    _ok, _ = AR.schedule_approval_authority()
    check(_ok is True, "a comment cannot change the measured approval result")
finally:
    _api.write_text(_orig, encoding="utf-8")

# --- plan authority is a property, not a door (F-608) ----------------------
_doors = AR._client_plan_routes()
check(
    _doors is not None,
    "the gate can build the production router and look"
    if _doors is not None
    else "the gate could not build the router -- it must not report safety it could not check",
)
check(
    _doors == [],
    "no production route accepts a client-authored plan"
    if _doors == []
    else f"client-authored plans are reachable via {_doors}",
)

print(f"\n===== ACTIVATION READINESS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

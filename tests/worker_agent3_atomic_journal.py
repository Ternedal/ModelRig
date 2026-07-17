"""State and the event explaining it must land together, or not at all (F-309).

They were two commits. A crash in the gap leaves a rig whose state nothing
accounts for: a run sitting in CANCELLED with no run_cancelled event, or an
event saying a step started against a state that never moved. That is worse
than a crash -- the machine has a history that disagrees with itself, and every
later question ("who cancelled this?", "did the tool actually run?") gets an
answer built on the disagreement.

SQLite gives this for free on one connection: the two INSERTs only had to share
a commit. It was never a hard problem. It was an unasked question.

Run: PYTHONPATH=worker python3 tests/worker_agent3_atomic_journal.py
"""
from __future__ import annotations

import os
import sys
import tempfile

_tmp = tempfile.mkdtemp(prefix="kaliv-atomic-")
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "a.db"))
os.environ.setdefault("KALIV_TOOLS_STATE", os.path.join(_tmp, "s.json"))
os.environ.setdefault("KALIV_JOBS_DB", os.path.join(_tmp, "j.db"))
os.environ.setdefault("KALIV_TOOLS_DIR", _tmp)
os.environ["KALIV_AGENT3_DB"] = os.path.join(_tmp, "agent3.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.agent3.core import (  # noqa: E402
    Agent3Orchestrator,
    AgentRun,
    AgentRunStore,
    AgentStep,
    RiskClass,
    RouteKind,
    RoutePlan,
    RunState,
    StepState,
    Sensitivity,
    TurnRequest,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def make_run(rid: str, state=RunState.RUNNING) -> AgentRun:
    return AgentRun(
        request=TurnRequest("atomic", mode="rig", tools=True, rag=False,
                            voice=False, conversation_id="c"),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "t", uses_cloud=False,
                        uses_rig=True, uses_tools=True, uses_rag=False),
        steps=[AgentStep(tool="note_append", args={}, risk=RiskClass.WRITE,
                         sensitivity=Sensitivity.PRIVATE, summary="s")],
        state=state, id=rid,
    )


store = AgentRunStore(os.environ["KALIV_AGENT3_DB"])

# --- the happy path: both halves land --------------------------------------

run = make_run("r-1")
store.save(run)
run.state = RunState.CANCELLED
store.save_with_event(run, "run_cancelled", {})

check(store.load("r-1").state == RunState.CANCELLED, "the state landed")
kinds = [e.get("kind") or e.get("type") for e in store.events("r-1")]
check("run_cancelled" in kinds, "and so did the event that explains it")

# --- the point of the exercise: neither half, rather than half a truth ------

run2 = make_run("r-2")
store.save(run2)
before_state = store.load("r-2").state
before_events = len(store.events("r-2"))

class CrashOnEventInsert:
    """sqlite3.Connection.execute is read-only, so stand in front of it.

    This is a crash simulated at the only place it matters: after the state
    INSERT, before the event INSERT -- the gap the two-commit version left
    open.
    """

    def __init__(self, real):
        self._real = real

    def execute(self, sql, *a, **kw):
        if "agent_events" in sql:
            raise RuntimeError("crash between the two writes")
        return self._real.execute(sql, *a, **kw)

    def commit(self):
        return self._real.commit()

    def rollback(self):
        return self._real.rollback()


real_conn = store._conn
store._conn = CrashOnEventInsert(real_conn)  # type: ignore[assignment]
try:
    run2.state = RunState.CANCELLED
    store.save_with_event(run2, "run_cancelled", {})
    check(False, "a failing event write must not pass silently")
except RuntimeError:
    check(True, "the failure surfaces to the caller")
finally:
    store._conn = real_conn  # type: ignore[assignment]

after = store.load("r-2")
check(after.state == before_state,
      f"the state did NOT change when its event could not be written "
      f"({before_state} -> {after.state}) -- this is the whole point")
check(len(store.events("r-2")) == before_events,
      "and no orphan event was left behind either")

# --- and the old two-step path really was non-atomic ------------------------
# Drive the detector: prove the test can tell the difference, or it proves
# nothing about the fix.

run3 = make_run("r-3")
store.save(run3)
run3.state = RunState.CANCELLED
store.save(run3)                       # the OLD way: state first...
# ...and the crash happens here, before store.event() is reached.
check(store.load("r-3").state == RunState.CANCELLED
      and not [e for e in store.events("r-3")
               if (e.get("kind") or e.get("type")) == "run_cancelled"],
      "the two-step path CAN leave a cancelled run with no cancellation event "
      "-- which is exactly the state save_with_event makes unreachable")

# --- the claim I made in 1.58.70, now enforced instead of asserted ----------
# I wrote that the remaining save/event pairs were "progress reporting, where an
# orphan is noise rather than a lie". I did not check. Nine of the twelve were
# state transitions -- including confirmation_approved (the record that a human
# said yes), run_completed, and, with some irony, interrupted_execution. Two of
# them wrote the event BEFORE the save, which is the same lie mirrored: a
# timeline saying step_succeeded against a state still reading EXECUTING.
#
# So this does not trust my reading of the file. It reads the file.

import re as _re  # noqa: E402
from pathlib import Path as _Path  # noqa: E402

_src = (_Path(__file__).resolve().parents[1] / "worker" / "app" / "agent3"
        / "core.py").read_text(encoding="utf-8").splitlines()

_offenders = []
for _i, _line in enumerate(_src):
    if not _re.search(r"self\.store\.event\(", _line):
        continue
    _window = "\n".join(_src[max(0, _i - 6):_i])
    if _re.search(r"(run|step)\.state\s*=", _window):
        _kind = _re.search(r'event\(\s*run\.id,\s*"([^"]+)"', _line)
        _offenders.append(f"core.py:{_i + 1} ({_kind.group(1) if _kind else '?'})")

check(not _offenders,
      "every state transition writes its state and its event in one commit"
      if not _offenders
      else "STATE CHANGED, EVENT COMMITTED SEPARATELY -- a crash in the gap "
           f"leaves a history that disagrees with itself: {', '.join(_offenders)}")

# The detector must be able to fail, or it is decoration.
_fake = ["        run.state = RunState.COMPLETED", '        self.store.event(run.id, "x", {})']
_hit = _re.search(r"self\.store\.event\(", _fake[1]) and _re.search(r"(run|step)\.state\s*=", _fake[0])
check(bool(_hit), "self-test: a two-step state transition IS detected")

# save() alone remains legitimate -- not every write is a transition.
check(any("self.store.save(run)" in ln for ln in _src),
      "plain save() still exists: this is about transitions, not a ban on writing")

# --- recovery replays only what said it may be replayed (F-614) -------------
#
# A crash mid-step leaves EXECUTING in the journal and nobody knows whether the
# side effect landed. Blocking the run and telling a person to verify by hand is
# right for note_append and absurd for rig_status, which has no side effect to
# verify -- and five of nine tools are reads, so the safe answer made recovery
# useless for the case it happens in most. The step now carries the registry's
# answer, stamped when it was built.

def _interrupted(tool: str, idempotent: bool) -> tuple[Agent3Orchestrator, str]:
    """A run whose current step was EXECUTING when the process died."""
    st = AgentRunStore(os.path.join(_tmp, f"recover-{tool}-{idempotent}.db"))
    executed: list[str] = []

    def _executor(step):
        executed.append(step.tool)
        return "ok"

    orch = Agent3Orchestrator(st, _executor, max_steps=4)
    run = AgentRun(
        request=TurnRequest("recover", mode="rig", tools=True, rag=False,
                            voice=False, conversation_id="c"),
        route=RoutePlan(RouteKind.RIG_TOOLS_LOCAL, "t", uses_cloud=False,
                        uses_rig=True, uses_tools=True, uses_rag=False),
        steps=[AgentStep(tool=tool, args={}, risk=RiskClass.READ,
                         sensitivity=Sensitivity.OPERATIONAL,
                         idempotent=idempotent, state=StepState.EXECUTING)],
        state=RunState.RUNNING,
    )
    st.save(run)
    return orch, run.id, executed


_orch, _rid, _executed = _interrupted("rig_status", idempotent=True)
_recovered = _orch.advance(_rid)
check(_recovered.state != RunState.BLOCKED,
      "an interrupted READ is replayed, not escalated to a human who has "
      "nothing to verify"
      if _recovered.state != RunState.BLOCKED
      else f"a replayable read was blocked anyway ({_recovered.state})")
check("rig_status" in _executed, "and it actually ran on the second pass")

_orch2, _rid2, _executed2 = _interrupted("note_append", idempotent=False)
_blocked = _orch2.advance(_rid2)
check(_blocked.state == RunState.BLOCKED,
      "an interrupted WRITE still blocks -- we do not know if the line landed")
check(_executed2 == [],
      "and it is NOT re-run: a second append is a second line, and nobody asked "
      "for the first one twice")
check("verify the side effect" in (_blocked.error or ""),
      "the block says what a person has to go and check")

print(f"\n===== AGENT3 ATOMIC JOURNAL: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

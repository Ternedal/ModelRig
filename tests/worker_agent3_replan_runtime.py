from __future__ import annotations

import os
import tempfile
from copy import deepcopy

from app.agent3.core import (
    AgentRun,
    AgentRunStore,
    AgentStep,
    EgressClass,
    RiskClass,
    RouteKind,
    RoutePlan,
    Sensitivity,
    StepState,
    TurnRequest,
)
from app.agent3.replan_runtime import (
    PersistentReadReplanner,
    ReplanJournal,
    ReplanJournalError,
    plan_digest,
)
from app.agent3.replanner import ReadSuffixReplanner, ReplanError


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def expect_error(exc_type, fn, name):
    try:
        fn()
    except exc_type:
        check(True, name)
    else:
        check(False, name)


def make_step(tool, risk=RiskClass.READ, *, state=StepState.PENDING, args=None):
    step = AgentStep(
        tool=tool,
        args={} if args is None else dict(args),
        risk=risk,
        sensitivity=Sensitivity.OPERATIONAL,
        egress=EgressClass.LOCAL,
        origin="local",
        conversation_id="conv-1",
        summary=f"summary:{tool}",
        state=state,
    )
    return step


def make_run(label):
    done = make_step("rig_status", state=StepState.SUCCEEDED)
    done.result = f"online:{label}"
    return AgentRun(
        request=TurnRequest(label, mode="rig", tools=True, conversation_id="conv-1"),
        route=RoutePlan(
            RouteKind.RIG_TOOLS_LOCAL,
            "test",
            uses_cloud=False,
            uses_rig=True,
            uses_tools=True,
            uses_rag=False,
        ),
        steps=[
            done,
            make_step("list_models"),
            make_step("current_datetime"),
            make_step("note_append", RiskClass.WRITE, args={"text": label}),
        ],
        current_step=1,
    )


root = tempfile.mkdtemp(prefix="agent3-replan-runtime-")
run_store = AgentRunStore(os.path.join(root, "runs.db"))
journal = ReplanJournal(os.path.join(root, "replans.db"))
policy = ReadSuffixReplanner(max_steps=8, max_replans=3)
service = PersistentReadReplanner(run_store, journal, policy)

# ---- normal committed revision ----
run = make_run("normal")
run_store.save(run)
saved, receipt = service.apply(
    run.id,
    [make_step("rig_status", args={"detail": True})],
    reason="Replace two reads with one more useful read",
)
check([step.tool for step in saved.steps] == ["rig_status", "rig_status", "note_append"], "committed replan persists revised read window")
check(saved.steps[-1].args == {"text": "normal"} and saved.steps[-1].risk == RiskClass.WRITE, "committed replan preserves write tail")
check(receipt.to_revision == 1 and receipt.replan_number == 1, "first committed replan receives revision one")
revision, count = journal.revision_state(run.id)
check((revision, count) == (1, 1), "journal exposes committed revision state")
history = journal.history(run.id)
check(len(history) == 1 and history[0]["state"] == "committed", "journal transaction is committed")
events = [event["kind"] for event in run_store.events(run.id)]
check("replan_committed" in events, "committed replan writes an AgentRun event")

# A second revision derives its counters from committed journal state, not client input.
saved2, receipt2 = service.apply(run.id, [], reason="No more reads are needed")
check([step.tool for step in saved2.steps] == ["rig_status", "note_append"], "second revision may remove remaining read work")
check(receipt2.from_revision == 1 and receipt2.to_revision == 2 and receipt2.replan_number == 2, "second revision is server-derived")

# ---- crash before authoritative run save -> ABORTED ----
abort_run = make_run("abort")
run_store.save(abort_run)
abort_before = plan_digest(abort_run)
abort_revised = deepcopy(abort_run)
abort_receipt = policy.apply(
    abort_revised,
    [make_step("rig_status")],
    reason="prepared but never saved",
    revision=0,
    replan_count=0,
    now=10.0,
)
abort_after = plan_digest(abort_revised)
abort_tx = journal.prepare(
    abort_run.id,
    abort_receipt,
    before_digest=abort_before,
    after_digest=abort_after,
)
outcomes = service.recover(abort_run.id)
check(outcomes == [{"transaction_id": abort_tx, "outcome": "aborted"}], "prepared transaction aborts when run still matches before digest")
check(journal.history(abort_run.id)[0]["state"] == "aborted", "aborted transaction is terminal")
check(plan_digest(run_store.load(abort_run.id)) == abort_before, "abort recovery never mutates the run")

# ---- crash after run save but before journal commit -> COMMITTED ----
commit_run = make_run("recover-commit")
run_store.save(commit_run)
commit_before = plan_digest(commit_run)
commit_revised = deepcopy(commit_run)
commit_receipt = policy.apply(
    commit_revised,
    [make_step("current_datetime")],
    reason="saved before process crash",
    revision=0,
    replan_count=0,
    now=20.0,
)
commit_after = plan_digest(commit_revised)
commit_tx = journal.prepare(
    commit_run.id,
    commit_receipt,
    before_digest=commit_before,
    after_digest=commit_after,
)
run_store.save(commit_revised)
outcomes = service.recover(commit_run.id)
check(outcomes == [{"transaction_id": commit_tx, "outcome": "committed"}], "prepared transaction commits when persisted run matches after digest")
check(journal.revision_state(commit_run.id) == (1, 1), "recovered commit counts as a real revision")
check("replan_recovered_committed" in [event["kind"] for event in run_store.events(commit_run.id)], "recovered commit is auditable")

# ---- neither digest matches -> permanent CONFLICT ----
conflict_run = make_run("conflict")
run_store.save(conflict_run)
conflict_before = plan_digest(conflict_run)
expected = deepcopy(conflict_run)
conflict_receipt = policy.apply(
    expected,
    [make_step("rig_status")],
    reason="expected revision",
    revision=0,
    replan_count=0,
    now=30.0,
)
conflict_after = plan_digest(expected)
conflict_tx = journal.prepare(
    conflict_run.id,
    conflict_receipt,
    before_digest=conflict_before,
    after_digest=conflict_after,
)
# Persist a third plan shape that is neither the before nor after side.
tampered = deepcopy(conflict_run)
tampered.steps[1:3] = [make_step("list_documents")]
run_store.save(tampered)
outcomes = service.recover(conflict_run.id)
check(outcomes == [{"transaction_id": conflict_tx, "outcome": "conflict"}], "unknown persisted shape becomes a conflict")
check(journal.conflicts(conflict_run.id)[0]["state"] == "conflict", "conflict remains visible and unresolved")
expect_error(
    ReplanJournalError,
    lambda: service.apply(conflict_run.id, [make_step("rig_status")], reason="must not continue"),
    "unresolved conflict blocks future replans",
)

# ---- unresolved PREPARED transaction blocks a second reservation ----
open_run = make_run("open")
run_store.save(open_run)
open_revised = deepcopy(open_run)
open_receipt = policy.apply(
    open_revised,
    [make_step("rig_status")],
    reason="open transaction",
    revision=0,
    replan_count=0,
)
journal.prepare(
    open_run.id,
    open_receipt,
    before_digest=plan_digest(open_run),
    after_digest=plan_digest(open_revised),
)
expect_error(
    ReplanJournalError,
    lambda: journal.prepare(
        open_run.id,
        open_receipt,
        before_digest=plan_digest(open_run),
        after_digest=plan_digest(open_revised),
    ),
    "a run cannot reserve two open replan transactions",
)

# ---- max_replans derives from committed rows ----
limit_run = make_run("limit")
run_store.save(limit_run)
limit_service = PersistentReadReplanner(
    run_store,
    journal,
    ReadSuffixReplanner(max_steps=8, max_replans=1),
)
limit_service.apply(limit_run.id, [make_step("rig_status")], reason="only allowed revision")
expect_error(
    ReplanError,
    lambda: limit_service.apply(limit_run.id, [], reason="second revision is forbidden"),
    "committed journal count enforces max_replans",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

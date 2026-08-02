#!/usr/bin/env python3
"""ADR-A4-008 Slice 5 end-to-end proof with the real Agent 3 adapter."""

from __future__ import annotations

import ast
import inspect
import re
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app.agent3.campaign_adapter as agent3_adapter_module
import app.agent4.handoff_runtime as handoff_runtime_module
from app.agent3.campaign_adapter import (
    Agent3CampaignDispatchTombstonedError,
    Agent3CampaignHandoffAdapter,
    Agent3CampaignLaunch,
)
from app.agent3.core import (
    Agent3Orchestrator,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    TurnRequest,
)
from app.agent4.campaign_queue import CampaignQueue
from app.agent4.domain import (
    CampaignRecord,
    CampaignSpec,
    CampaignState,
    CampaignStatus,
)
from app.agent4.event_bus import InMemoryCampaignEventBus
from app.agent4.handoff import CampaignDispatchRequest
from app.agent4.handoff_persistence import CampaignHandoffPhase
from app.agent4.handoff_runtime import (
    RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
    CampaignHandoffRecoveryService,
    CampaignHandoffSchedulerService,
    CampaignHandoffUncertainError,
    CampaignResourceReconciliationBlockedError,
    HandoffRecoveryAction,
    ResourceAwareCampaignHandoffSchedulerService,
    ResourceReconciliationResolutionReason,
)
from app.agent4.repository import JsonCampaignRepository
from app.agent4.resources import InMemoryResourceLeaseManager


ROOT = Path(__file__).resolve().parent.parent
NOW = datetime(2026, 8, 2, 17, 0, tzinfo=timezone.utc)
TTL = timedelta(minutes=5)


ADR_A4_008_TRACEABILITY: dict[int, tuple[tuple[str, str, str], ...]] = {
    1: (("tests/worker_agent4_handoff_runtime.py", "Slice3Tests", "test_requested_state_and_intent_share_replace_boundary"),),
    2: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_crash_before_receiver_call_tombstones_and_requires_new_attempt"),),
    3: (
        ("tests/worker_agent3_campaign_adapter.py", "CampaignAdapterTests", "test_dispatch_is_atomic_and_idempotent_for_same_request"),
        ("tests/worker_agent3_campaign_adapter_races.py", "CampaignAdapterRaceTests", "test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack"),
    ),
    4: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_crash_after_receiver_acceptance_recovers_terminal_without_redispatch"),),
    5: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_missing_receiver_run_recovers_unknown_without_redispatch"),),
    6: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_crash_before_receiver_call_tombstones_and_requires_new_attempt"),),
    7: (("tests/worker_agent3_campaign_adapter.py", "CampaignAdapterTests", "test_signal_is_requested_before_call_and_never_redelivered"),),
    8: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_stack_is_caller_driven_and_starts_no_background_work"),),
    9: (("tests/worker_agent4_handoff_persistence.py", "Agent4HandoffPersistenceTests", "test_v3_round_trip_contains_both_typed_collections"),),
    10: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_storage_and_dormant_architecture_gates_are_armed"),),
    11: (
        ("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_crash_before_receiver_call_tombstones_and_requires_new_attempt"),
        ("tests/worker_agent3_campaign_adapter_races.py", "CampaignAdapterRaceTests", "test_bind_dispatch_rechecks_tombstone_after_prepare_gap"),
    ),
    12: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_crash_before_receiver_call_tombstones_and_requires_new_attempt"),),
    13: (("tests/worker_agent4_handoff_runtime.py", "Slice3Tests", "test_not_dispatched_is_ready_without_auto_redispatch"),),
    14: (
        ("tests/worker_agent4_handoff_runtime.py", "Slice3Tests", "test_accepted_running_and_unknown_follow_marker_rule"),
        ("tests/worker_agent4_handoff_runtime.py", "Slice3Tests", "test_terminal_attestation_never_auto_clears_existing_marker"),
    ),
    15: (
        ("tests/worker_agent4_handoff_barrier_placement.py", "BarrierPlacementTests", "test_existing_marker_blocks_before_any_lease_acquire_attempt"),
        ("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_real_adapter_is_not_reached_when_resource_barrier_is_set"),
    ),
    16: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_recovery_and_barrier_have_no_automatic_execution_calls"),),
    17: (("tests/worker_agent4_handoff_e2e.py", "Agent4Agent3EndToEndTests", "test_terminal_recovery_preserves_marker_until_explicit_resolution"),),
}


class FixedClock:
    def now(self) -> datetime:
        return NOW


class CountingToolExecutor:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, step: AgentStep):
        self.calls += 1
        return {"tool": step.tool, "ok": True}


class LaunchResolver:
    def __init__(self, *, risk: RiskClass = RiskClass.READ) -> None:
        self.risk = risk
        self.calls = 0

    def __call__(self, request: CampaignDispatchRequest) -> Agent3CampaignLaunch:
        self.calls += 1
        return Agent3CampaignLaunch(
            request=TurnRequest(
                message=f"Campaign {request.campaign_id}",
                mode="rig",
                tools=True,
            ),
            capabilities=CapabilitySnapshot(
                rig_reachable=True,
                worker_ready=True,
                tools_ready=True,
            ),
            steps=(
                AgentStep(
                    tool="campaign_probe",
                    args={"campaign_id": request.campaign_id},
                    risk=self.risk,
                    idempotent=self.risk is RiskClass.READ,
                    summary="Run the campaign probe",
                ),
            ),
        )


class Agent4Agent3EndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.repository = JsonCampaignRepository(self.root / "campaigns")
        self.queue = CampaignQueue()
        self.events = InMemoryCampaignEventBus()
        self.clock = FixedClock()
        self.tool_executor = CountingToolExecutor()
        self.resolver = LaunchResolver()
        self.agent3_store = AgentRunStore(str(self.root / "agent3.db"))
        self.agent3 = Agent3Orchestrator(
            store=self.agent3_store,
            executor=self.tool_executor,
        )
        self.adapter = Agent3CampaignHandoffAdapter(
            orchestrator=self.agent3,
            resolve_launch=self.resolver,
        )

    def tearDown(self) -> None:
        if self.agent3_store._conn.in_transaction:
            self.agent3_store._conn.rollback()
        self.agent3_store._conn.close()
        self.temp.cleanup()

    @staticmethod
    def spec(
        campaign_id: str = "campaign-e2e",
        *,
        resources: dict[str, int] | None = None,
    ) -> CampaignSpec:
        return CampaignSpec(
            campaign_id=campaign_id,
            name=campaign_id,
            workflow="agent3.write-pilot",
            created_at=NOW,
            max_attempts=3,
            parameters={"resources": resources or {}},
        )

    def service(self) -> CampaignHandoffSchedulerService:
        return CampaignHandoffSchedulerService(
            repository=self.repository,
            executor=self.adapter,
            events=self.events,
            clock=self.clock,
            queue=self.queue,
        )

    def resource_service(
        self,
        leases: InMemoryResourceLeaseManager,
    ) -> ResourceAwareCampaignHandoffSchedulerService:
        return ResourceAwareCampaignHandoffSchedulerService(
            repository=self.repository,
            executor=self.adapter,
            events=self.events,
            clock=self.clock,
            queue=self.queue,
            resource_leases=leases,
            resource_resolver=lambda spec: spec.parameters.get("resources", {}),
            resource_lease_ttl=TTL,
        )

    def count_agent3(self, table: str) -> int:
        with self.agent3_store._lock:
            return int(
                self.agent3_store._conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )

    def test_real_adapter_dispatch_commits_both_authoritative_sides(self) -> None:
        service = self.service()
        service.submit(self.spec())
        result = service.dispatch_ready()

        self.assertIsNotNone(result)
        self.assertTrue(result.succeeded)
        self.assertEqual(self.tool_executor.calls, 1)
        self.assertEqual(self.resolver.calls, 1)
        self.assertEqual(self.count_agent3("agent_runs"), 1)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 1)
        handoff = self.repository.pending_handoffs("campaign-e2e")[0]
        self.assertIs(handoff.phase, CampaignHandoffPhase.ACKNOWLEDGED)
        self.assertEqual(
            handoff.acknowledgement.runtime_reference,
            result.runtime_reference,
        )
        outcome = self.adapter.query_outcome(handoff.intent_id)
        self.assertEqual(outcome.kind.value, "completed")
        self.assertTrue(outcome.resources_released)

    def test_crash_after_receiver_acceptance_recovers_terminal_without_redispatch(
        self,
    ) -> None:
        service = self.service()
        service.submit(self.spec("campaign-after-accept"))
        with patch.object(
            self.repository,
            "acknowledge_handoff",
            side_effect=OSError("crash after Agent 3 acceptance"),
        ):
            result = service.dispatch_ready()

        self.assertIsNotNone(result)
        self.assertFalse(result.succeeded)
        self.assertIn("unresolved handoff", result.dispatch_error)
        requested = self.repository.pending_handoffs("campaign-after-accept")[0]
        self.assertIs(requested.phase, CampaignHandoffPhase.REQUESTED)
        self.assertEqual(self.tool_executor.calls, 1)
        self.assertEqual(self.count_agent3("agent_runs"), 1)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 1)

        report = service.recover()

        self.assertEqual(report.decisions[0].action, HandoffRecoveryAction.COMPLETED)
        current = self.repository.get("campaign-after-accept")
        self.assertEqual(current.state.status, CampaignStatus.SUCCEEDED)
        recovered = self.repository.pending_handoffs("campaign-after-accept")[0]
        self.assertIs(recovered.phase, CampaignHandoffPhase.ACKNOWLEDGED)
        self.assertEqual(self.tool_executor.calls, 1)
        self.assertEqual(self.count_agent3("agent_runs"), 1)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 1)

    def test_crash_before_receiver_call_tombstones_and_requires_new_attempt(
        self,
    ) -> None:
        service = self.service()
        service.submit(self.spec("campaign-before-call"))
        with patch.object(
            service,
            "_before_external_dispatch",
            side_effect=RuntimeError("crash before receiver call"),
        ):
            with self.assertRaisesRegex(RuntimeError, "crash before receiver call"):
                service.dispatch_ready()

        requested = self.repository.pending_handoffs("campaign-before-call")[0]
        self.assertIs(requested.phase, CampaignHandoffPhase.REQUESTED)
        old_dispatch_id = requested.intent_id
        self.assertEqual(self.tool_executor.calls, 0)
        self.assertEqual(self.count_agent3("agent_runs"), 0)

        report = service.recover()

        self.assertEqual(
            report.decisions[0].action,
            HandoffRecoveryAction.NOT_DISPATCHED_READY,
        )
        current = self.repository.get("campaign-before-call")
        self.assertEqual(current.state.status, CampaignStatus.QUEUED)
        self.assertFalse(current.state.resource_reconciliation_required)
        self.assertEqual(self.tool_executor.calls, 0)
        self.assertEqual(self.count_agent3("agent_runs"), 0)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 1)
        with self.assertRaises(Agent3CampaignDispatchTombstonedError):
            self.adapter.dispatch(requested.request)
        self.assertEqual(self.tool_executor.calls, 0)

        retried = service.dispatch_ready()

        self.assertIsNotNone(retried)
        self.assertTrue(retried.succeeded)
        latest = self.repository.pending_handoffs("campaign-before-call")[-1]
        self.assertNotEqual(latest.intent_id, old_dispatch_id)
        self.assertEqual(retried.record.state.attempt, 2)
        self.assertEqual(self.tool_executor.calls, 1)
        self.assertEqual(self.count_agent3("agent_runs"), 1)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 2)

    def test_missing_receiver_run_recovers_unknown_without_redispatch(self) -> None:
        service = self.service()
        service.submit(self.spec("campaign-missing-run"))
        with patch.object(
            self.repository,
            "acknowledge_handoff",
            side_effect=OSError("crash before sender confirmation"),
        ):
            result = service.dispatch_ready()

        self.assertFalse(result.succeeded)
        intent = self.repository.pending_handoffs("campaign-missing-run")[0]
        with self.agent3_store._lock:
            row = self.agent3_store._conn.execute(
                "SELECT run_id,disposition FROM agent_campaign_effects "
                "WHERE effect_id=?",
                (intent.intent_id,),
            ).fetchone()
            self.assertEqual(row[1], "accepted")
            self.agent3_store._conn.execute(
                "DELETE FROM agent_runs WHERE id=?",
                (row[0],),
            )
            self.agent3_store._conn.commit()
        dispatch_calls = self.tool_executor.calls

        report = service.recover()

        self.assertEqual(
            report.decisions[0].action,
            HandoffRecoveryAction.UNKNOWN_INTERVENTION,
        )
        current = self.repository.get("campaign-missing-run")
        self.assertEqual(current.state.status, CampaignStatus.RUNNING)
        self.assertTrue(current.state.execution_intervention_required)
        self.assertTrue(current.state.resource_reconciliation_required)
        self.assertNotIn("campaign-missing-run", self.queue)
        self.assertEqual(self.tool_executor.calls, dispatch_calls)
        self.assertIs(
            self.repository.pending_handoffs("campaign-missing-run")[0].phase,
            CampaignHandoffPhase.REQUESTED,
        )
        with self.agent3_store._lock:
            effect = self.agent3_store._conn.execute(
                "SELECT disposition,outcome,error,resources_released FROM "
                "agent_campaign_effects WHERE effect_id=?",
                (intent.intent_id,),
            ).fetchone()
        self.assertEqual(
            effect,
            ("accepted", "unknown", "bound Agent 3 run is missing", None),
        )

    def test_pause_is_requested_but_recovery_never_redelivers_signal(self) -> None:
        service = self.service()
        service.submit(self.spec("campaign-pause"))
        service.dispatch_ready()
        with self.assertRaises(CampaignHandoffUncertainError):
            service.request_pause("campaign-pause")

        current = self.repository.get("campaign-pause")
        self.assertEqual(current.state.status, CampaignStatus.PAUSING)
        pending = self.repository.pending_handoffs("campaign-pause")
        self.assertEqual(len(pending), 2)
        self.assertIs(pending[-1].phase, CampaignHandoffPhase.REQUESTED)
        with patch.object(self.adapter, "signal", wraps=self.adapter.signal) as signal_spy:
            report = service.recover()

        signal_spy.assert_not_called()
        self.assertEqual(
            report.decisions[0].action,
            HandoffRecoveryAction.SIGNAL_INTERVENTION,
        )
        recovered = self.repository.get("campaign-pause")
        self.assertEqual(recovered.state.status, CampaignStatus.PAUSING)
        self.assertTrue(recovered.state.execution_intervention_required)
        self.assertTrue(recovered.state.resource_reconciliation_required)

    def test_real_adapter_is_not_reached_when_resource_barrier_is_set(self) -> None:
        marker_spec = self.spec("marker")
        self.repository.save(
            CampaignRecord(
                spec=marker_spec,
                state=CampaignState(
                    campaign_id="marker",
                    status=CampaignStatus.RUNNING,
                    revision=1,
                    attempt=1,
                    updated_at=NOW,
                    resource_reconciliation_required=True,
                ),
            )
        )
        leases = InMemoryResourceLeaseManager({"gpu": 1})
        service = self.resource_service(leases)
        service.submit(self.spec("blocked", resources={"gpu": 1}))
        before = self.repository.get("blocked")
        with patch.object(leases, "try_acquire", wraps=leases.try_acquire) as acquire_spy:
            with self.assertRaisesRegex(
                CampaignResourceReconciliationBlockedError,
                RESOURCE_RECONCILIATION_BLOCKED_MESSAGE,
            ):
                service.dispatch_ready()

        acquire_spy.assert_not_called()
        self.assertEqual(self.repository.get("blocked"), before)
        self.assertEqual(service.queued_count, 1)
        self.assertEqual(self.tool_executor.calls, 0)
        self.assertEqual(self.resolver.calls, 0)
        self.assertEqual(self.count_agent3("agent_campaign_effects"), 0)

    def test_terminal_recovery_preserves_marker_until_explicit_resolution(
        self,
    ) -> None:
        service = self.service()
        service.submit(self.spec("campaign-resolution"))
        with patch.object(
            self.repository,
            "acknowledge_handoff",
            side_effect=OSError("crash before confirmation"),
        ):
            service.dispatch_ready()

        current = self.repository.get("campaign-resolution")
        self.repository.save(
            CampaignRecord(
                spec=current.spec,
                state=replace(
                    current.state,
                    resource_reconciliation_required=True,
                ),
            )
        )
        service.recover()

        terminal = self.repository.get("campaign-resolution")
        self.assertEqual(terminal.state.status, CampaignStatus.SUCCEEDED)
        self.assertTrue(terminal.state.resource_reconciliation_required)
        resolved = service.resolve_resource_reconciliation(
            "campaign-resolution",
            reason=ResourceReconciliationResolutionReason.RUNTIME_VERIFIED_TERMINAL,
            evidence_pointer="agent3-terminal:campaign-resolution",
        )
        self.assertFalse(resolved.state.resource_reconciliation_required)
        restarted = JsonCampaignRepository(self.root / "campaigns")
        self.assertFalse(
            restarted.get("campaign-resolution").state.resource_reconciliation_required
        )

    def test_recovery_and_barrier_have_no_automatic_execution_calls(self) -> None:
        recovery_tree = ast.parse(
            textwrap.dedent(inspect.getsource(CampaignHandoffRecoveryService))
        )
        forbidden = {"dispatch", "signal", "cancel", "try_acquire", "renew"}
        recovery_calls = {
            node.func.attr
            for node in ast.walk(recovery_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(forbidden.isdisjoint(recovery_calls))
        self.assertIn("query_outcome", recovery_calls)

        barrier_tree = ast.parse(
            textwrap.dedent(
                inspect.getsource(
                    ResourceAwareCampaignHandoffSchedulerService._require_resource_admission_open
                )
            )
        )
        barrier_calls = {
            node.func.attr
            for node in ast.walk(barrier_tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertTrue(
            {"try_acquire", "dispatch", "signal", "cancel"}.isdisjoint(
                barrier_calls
            )
        )

    def test_stack_is_caller_driven_and_starts_no_background_work(self) -> None:
        before = {thread.ident for thread in threading.enumerate()}
        empty_root = self.root / "empty-campaigns"
        repository = JsonCampaignRepository(empty_root)
        service = CampaignHandoffSchedulerService(
            repository=repository,
            executor=self.adapter,
            events=InMemoryCampaignEventBus(),
            clock=self.clock,
            queue=CampaignQueue(),
        )
        report = service.recover()

        after = {thread.ident for thread in threading.enumerate()}
        self.assertEqual(report.scanned, 0)
        self.assertEqual(after, before)
        self.assertFalse(empty_root.exists())
        source = (
            inspect.getsource(agent3_adapter_module)
            + inspect.getsource(handoff_runtime_module)
        )
        for forbidden in (
            "threading.Thread(",
            "Thread(",
            "create_task(",
            "schedule(",
            "Timer(",
            "while True:",
            "import requests",
            "import httpx",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    def test_storage_and_dormant_architecture_gates_are_armed(self) -> None:
        for script in (
            "tests/workflow_agent4_storage_boundary.py",
            "tests/workflow_agent4_dormant_runtime.py",
        ):
            with self.subTest(script=script):
                result = subprocess.run(
                    [sys.executable, script],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    result.stdout + "\n" + result.stderr,
                )

    def test_all_seventeen_adr_contracts_have_named_automated_tests(self) -> None:
        adr = (
            ROOT / "docs" / "agent4" / "ADR-A4-008_SIDE_EFFECT_HANDOFF.md"
        ).read_text(encoding="utf-8")
        section = adr.split("## Obligatoriske kontrakttests", 1)[1].split(
            "## Konsekvenser",
            1,
        )[0]
        numbered = {int(value) for value in re.findall(r"(?m)^(\d+)\.\s", section)}
        self.assertEqual(numbered, set(range(1, 18)))
        self.assertEqual(set(ADR_A4_008_TRACEABILITY), set(range(1, 18)))

        parsed: dict[str, ast.Module] = {}
        for number, references in ADR_A4_008_TRACEABILITY.items():
            self.assertTrue(references, f"ADR test {number} has no references")
            for relative_path, class_name, method_name in references:
                if relative_path not in parsed:
                    parsed[relative_path] = ast.parse(
                        (ROOT / relative_path).read_text(encoding="utf-8")
                    )
                classes = [
                    node
                    for node in parsed[relative_path].body
                    if isinstance(node, ast.ClassDef) and node.name == class_name
                ]
                self.assertEqual(
                    len(classes),
                    1,
                    f"ADR test {number}: missing {class_name} in {relative_path}",
                )
                methods = [
                    node
                    for node in classes[0].body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == method_name
                ]
                self.assertEqual(
                    len(methods),
                    1,
                    f"ADR test {number}: missing {class_name}.{method_name}",
                )

        proof = (
            ROOT / "docs" / "agent4" / "A4-008_SLICE_5_PROOF.md"
        ).read_text(encoding="utf-8")
        for number in range(1, 18):
            self.assertIn(f"| {number} |", proof)


if __name__ == "__main__":
    unittest.main()

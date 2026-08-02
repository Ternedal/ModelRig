#!/usr/bin/env python3
"""Real-store proofs for ADR-A4-008 Slice 4's Agent 3 adapter."""

from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import app.agent3.campaign_adapter as campaign_adapter_module
from app.agent3.campaign_adapter import (
    Agent3CampaignDispatchConflictError,
    Agent3CampaignDispatchTombstonedError,
    Agent3CampaignHandoffAdapter,
    Agent3CampaignLaunch,
    Agent3CampaignSignalUncertainError,
    Agent3CampaignSignalUnsupportedError,
)
from app.agent3.core import (
    Agent3Orchestrator,
    AgentRunStore,
    AgentStep,
    CapabilitySnapshot,
    RiskClass,
    RunState,
    StepState,
    TurnRequest,
)
from app.agent4.handoff import (
    CampaignDispatchRequest,
    CampaignSignalRequest,
    CampaignSignalType,
    DispatchOutcomeKind,
    campaign_dispatch_id,
)


class CountingResolver:
    def __init__(self, *, risk: RiskClass = RiskClass.READ) -> None:
        self.risk = risk
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, request: CampaignDispatchRequest) -> Agent3CampaignLaunch:
        with self._lock:
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


class CountingExecutor:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error
        self._lock = threading.Lock()

    def __call__(self, step: AgentStep):
        with self._lock:
            self.calls += 1
        if self.error is not None:
            raise self.error
        return {"tool": step.tool, "ok": True}


class BlockingExecutor:
    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def __call__(self, step: AgentStep):
        self.calls += 1
        self.started.set()
        if not self.release.wait(timeout=10):
            raise TimeoutError("test executor was not released")
        return {"tool": step.tool, "ok": True}


class CampaignAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "agent3.db")
        self.stores: list[AgentRunStore] = []

    def tearDown(self) -> None:
        for store in self.stores:
            store._conn.close()
        self.temp.cleanup()

    def stack(
        self,
        *,
        executor=None,
        resolver: CountingResolver | None = None,
        separate_store: bool = False,
    ):
        store = AgentRunStore(self.db_path)
        self.stores.append(store)
        runtime_executor = executor or CountingExecutor()
        orchestrator = Agent3Orchestrator(
            store=store,
            executor=runtime_executor,
        )
        launch_resolver = resolver or CountingResolver()
        adapter = Agent3CampaignHandoffAdapter(
            orchestrator=orchestrator,
            resolve_launch=launch_resolver,
        )
        return adapter, orchestrator, store, runtime_executor, launch_resolver

    @staticmethod
    def dispatch_request(
        *,
        campaign_id: str = "campaign-a",
        attempt: int = 1,
        workflow: str = "agent3.write-pilot",
        parameters: dict | None = None,
    ) -> CampaignDispatchRequest:
        return CampaignDispatchRequest(
            campaign_id=campaign_id,
            attempt=attempt,
            workflow=workflow,
            campaign_revision=attempt,
            parameters=parameters or {"dry_run": True},
        )

    def count_rows(self, store: AgentRunStore, table: str) -> int:
        with store._lock:
            return int(store._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])

    def test_dispatch_is_atomic_and_idempotent_for_same_request(self) -> None:
        adapter, _orchestrator, store, executor, resolver = self.stack()
        request = self.dispatch_request()

        first = adapter.dispatch(request)
        second = adapter.dispatch(request)

        self.assertEqual(first, second)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(resolver.calls, 1)
        self.assertEqual(self.count_rows(store, "agent_runs"), 1)
        self.assertEqual(self.count_rows(store, "agent_campaign_effects"), 1)
        with store._lock:
            run_id, disposition = store._conn.execute(
                "SELECT run_id,disposition FROM agent_campaign_effects "
                "WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()
            event_count = store._conn.execute(
                "SELECT COUNT(*) FROM agent_events "
                "WHERE run_id=? AND kind='run_created'",
                (run_id,),
            ).fetchone()[0]
        self.assertEqual(disposition, "accepted")
        self.assertEqual(event_count, 1)

    def test_same_identity_with_different_request_is_a_conflict(self) -> None:
        adapter, _orchestrator, _store, executor, resolver = self.stack()
        first = self.dispatch_request(parameters={"value": 1})
        conflicting = self.dispatch_request(parameters={"value": 2})

        adapter.dispatch(first)
        with self.assertRaises(Agent3CampaignDispatchConflictError):
            adapter.dispatch(conflicting)

        self.assertEqual(executor.calls, 1)
        self.assertEqual(resolver.calls, 1)

    def test_unknown_query_tombstones_before_return_and_rejects_delayed_dispatch(self) -> None:
        adapter, _orchestrator, store, executor, resolver = self.stack()
        request = self.dispatch_request()

        outcome = adapter.query_outcome(request.dispatch_id)

        self.assertEqual(outcome.kind, DispatchOutcomeKind.NOT_DISPATCHED)
        self.assertTrue(outcome.resources_released)
        with store._lock:
            disposition = store._conn.execute(
                "SELECT disposition FROM agent_campaign_effects WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()[0]
        self.assertEqual(disposition, "tombstoned")

        with self.assertRaises(Agent3CampaignDispatchTombstonedError):
            adapter.dispatch(request)
        self.assertEqual(executor.calls, 0)
        self.assertEqual(resolver.calls, 0)

    def test_two_simultaneous_unknown_queries_commit_one_tombstone(self) -> None:
        adapter_a, *_ = self.stack()
        adapter_b, *_ = self.stack(separate_store=True)
        dispatch_id = campaign_dispatch_id("campaign-race", 1)
        barrier = threading.Barrier(3)
        outcomes = []
        errors = []

        def query(adapter):
            try:
                barrier.wait(timeout=5)
                outcomes.append(adapter.query_outcome(dispatch_id))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=query, args=(adapter_a,)),
            threading.Thread(target=query, args=(adapter_b,)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(outcomes), 2)
        self.assertTrue(
            all(item.kind is DispatchOutcomeKind.NOT_DISPATCHED for item in outcomes)
        )
        store = self.stores[0]
        with store._lock:
            rows = store._conn.execute(
                "SELECT disposition,COUNT(*) FROM agent_campaign_effects "
                "WHERE effect_id=? GROUP BY disposition",
                (dispatch_id,),
            ).fetchall()
        self.assertEqual(rows, [("tombstoned", 1)])

    def test_two_simultaneous_dispatches_create_one_run_and_one_effect(self) -> None:
        executor = CountingExecutor()
        resolver = CountingResolver()
        adapter_a, *_rest_a = self.stack(executor=executor, resolver=resolver)
        adapter_b, *_rest_b = self.stack(executor=executor, resolver=resolver)
        request = self.dispatch_request(campaign_id="campaign-concurrent")
        barrier = threading.Barrier(3)
        acknowledgements = []
        errors = []

        def dispatch(adapter):
            try:
                barrier.wait(timeout=5)
                acknowledgements.append(adapter.dispatch(request))
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        threads = [
            threading.Thread(target=dispatch, args=(adapter_a,)),
            threading.Thread(target=dispatch, args=(adapter_b,)),
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=5)
        for thread in threads:
            thread.join(timeout=10)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(len(acknowledgements), 2)
        self.assertEqual(
            {item.runtime_reference for item in acknowledgements},
            {acknowledgements[0].runtime_reference},
        )
        self.assertEqual(executor.calls, 1)
        self.assertEqual(self.count_rows(self.stores[0], "agent_runs"), 1)
        self.assertEqual(
            self.count_rows(self.stores[0], "agent_campaign_effects"),
            1,
        )

    def test_completed_failed_and_waiting_confirmation_map_conservatively(self) -> None:
        completed, *_ = self.stack()
        completed_request = self.dispatch_request(campaign_id="completed")
        completed.dispatch(completed_request)
        self.assertEqual(
            completed.query_outcome(completed_request.dispatch_id).kind,
            DispatchOutcomeKind.COMPLETED,
        )

        failed_executor = CountingExecutor(error=RuntimeError("boom"))
        failed, *_ = self.stack(
            executor=failed_executor,
            resolver=CountingResolver(),
        )
        failed_request = self.dispatch_request(campaign_id="failed")
        failed.dispatch(failed_request)
        failed_outcome = failed.query_outcome(failed_request.dispatch_id)
        self.assertEqual(failed_outcome.kind, DispatchOutcomeKind.FAILED)
        self.assertTrue(failed_outcome.resources_released)
        self.assertIn("boom", failed_outcome.error)

        waiting, waiting_orchestrator, *_ = self.stack(
            resolver=CountingResolver(risk=RiskClass.WRITE),
        )
        waiting_request = self.dispatch_request(campaign_id="waiting")
        acknowledgement = waiting.dispatch(waiting_request)
        run_id = acknowledgement.runtime_reference.removeprefix("agent3-run:")
        self.assertEqual(
            waiting_orchestrator.store.load(run_id).state,
            RunState.WAITING_CONFIRMATION,
        )
        waiting_outcome = waiting.query_outcome(waiting_request.dispatch_id)
        self.assertEqual(waiting_outcome.kind, DispatchOutcomeKind.ACCEPTED)
        self.assertIsNone(waiting_outcome.resources_released)

    def test_cancel_during_synchronous_execution_is_unknown_until_effect_finishes(self) -> None:
        executor = BlockingExecutor()
        adapter, orchestrator, store, _executor, _resolver = self.stack(
            executor=executor,
        )
        request = self.dispatch_request(campaign_id="late-cancel")
        dispatch_result = {}
        dispatch_error = []

        def dispatch():
            try:
                dispatch_result["ack"] = adapter.dispatch(request)
            except Exception as exc:  # pragma: no cover - asserted below
                dispatch_error.append(exc)

        thread = threading.Thread(target=dispatch)
        thread.start()
        self.assertTrue(executor.started.wait(timeout=5))

        running = adapter.query_outcome(request.dispatch_id)
        self.assertEqual(running.kind, DispatchOutcomeKind.RUNNING)

        signal = CampaignSignalRequest(
            campaign_id=request.campaign_id,
            attempt=request.attempt,
            signal_type=CampaignSignalType.CANCEL,
            resulting_revision=2,
        )
        adapter.signal(signal)
        uncertain = adapter.query_outcome(request.dispatch_id)
        self.assertEqual(uncertain.kind, DispatchOutcomeKind.UNKNOWN)
        self.assertIsNone(uncertain.resources_released)

        executor.release.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(dispatch_error, [])
        terminal = adapter.query_outcome(request.dispatch_id)
        self.assertEqual(terminal.kind, DispatchOutcomeKind.FAILED)
        self.assertTrue(terminal.resources_released)

        run_id = dispatch_result["ack"].runtime_reference.removeprefix("agent3-run:")
        run = store.load(run_id)
        self.assertEqual(run.state, RunState.CANCELLED)
        self.assertEqual(run.steps[0].state, StepState.COMPLETED_AFTER_CANCEL)

    def test_signal_is_requested_before_call_and_never_redelivered(self) -> None:
        adapter, orchestrator, store, _executor, _resolver = self.stack()
        request = self.dispatch_request(campaign_id="signal")
        adapter.dispatch(request)
        signal = CampaignSignalRequest(
            campaign_id=request.campaign_id,
            attempt=request.attempt,
            signal_type=CampaignSignalType.RESUME,
            resulting_revision=2,
        )

        with patch.object(
            orchestrator,
            "advance",
            wraps=orchestrator.advance,
        ) as advance_spy:
            first = adapter.signal(signal)
            second = adapter.signal(signal)

        self.assertEqual(first, second)
        self.assertEqual(advance_spy.call_count, 1)
        with store._lock:
            disposition = store._conn.execute(
                "SELECT disposition FROM agent_campaign_effects WHERE effect_id=?",
                (signal.signal_id,),
            ).fetchone()[0]
        self.assertEqual(disposition, "signal_acknowledged")

        uncertain_signal = CampaignSignalRequest(
            campaign_id=request.campaign_id,
            attempt=request.attempt,
            signal_type=CampaignSignalType.RESUME,
            resulting_revision=3,
        )
        with patch.object(
            orchestrator,
            "advance",
            side_effect=RuntimeError("signal boundary failed"),
        ) as failing_advance:
            with self.assertRaisesRegex(RuntimeError, "signal boundary failed"):
                adapter.signal(uncertain_signal)
            with self.assertRaises(Agent3CampaignSignalUncertainError):
                adapter.signal(uncertain_signal)
        self.assertEqual(failing_advance.call_count, 1)

    def test_pause_fails_closed_without_false_acknowledgement(self) -> None:
        adapter, _orchestrator, store, *_ = self.stack()
        request = self.dispatch_request(campaign_id="pause")
        adapter.dispatch(request)
        signal = CampaignSignalRequest(
            campaign_id=request.campaign_id,
            attempt=request.attempt,
            signal_type=CampaignSignalType.PAUSE,
            resulting_revision=2,
        )

        with self.assertRaises(Agent3CampaignSignalUnsupportedError):
            adapter.signal(signal)

        with store._lock:
            row = store._conn.execute(
                "SELECT disposition FROM agent_campaign_effects WHERE effect_id=?",
                (signal.signal_id,),
            ).fetchone()
        self.assertIsNone(row)

    def test_committed_terminal_attestation_survives_missing_run_row(self) -> None:
        adapter, _orchestrator, store, *_ = self.stack()
        request = self.dispatch_request(campaign_id="terminal-proof")
        acknowledgement = adapter.dispatch(request)
        first = adapter.query_outcome(request.dispatch_id)
        self.assertEqual(first.kind, DispatchOutcomeKind.COMPLETED)

        run_id = acknowledgement.runtime_reference.removeprefix("agent3-run:")
        with store._lock:
            store._conn.execute("DELETE FROM agent_runs WHERE id=?", (run_id,))
            store._conn.commit()

        second = adapter.query_outcome(request.dispatch_id)
        self.assertEqual(second, first)
        self.assertTrue(second.resources_released)

    def test_adapter_is_dormant_and_has_no_transport_or_background_surface(self) -> None:
        source = inspect.getsource(campaign_adapter_module)
        for forbidden in (
            "import requests",
            "import httpx",
            "import subprocess",
            "APIRouter",
            "FastAPI",
            "Thread(",
            "create_task(",
            "schedule(",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()

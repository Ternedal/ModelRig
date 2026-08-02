#!/usr/bin/env python3
"""Deterministic race proofs for ADR-A4-008 Slice 4's Agent 3 adapter."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

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
from app.agent4.handoff import (
    CampaignDispatchRequest,
    DispatchOutcomeKind,
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
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    def __call__(self, step: AgentStep):
        with self._lock:
            self.calls += 1
        return {"tool": step.tool, "ok": True}


class CampaignAdapterRaceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp.name) / "agent3.db")
        self.stores: list[AgentRunStore] = []

    def tearDown(self) -> None:
        for store in self.stores:
            if store._conn.in_transaction:
                store._conn.rollback()
            store._conn.close()
        self.temp.cleanup()

    def stack(
        self,
        *,
        executor: CountingExecutor | None = None,
        resolver: CountingResolver | None = None,
    ):
        store = AgentRunStore(self.db_path)
        self.stores.append(store)
        runtime_executor = executor or CountingExecutor()
        launch_resolver = resolver or CountingResolver()
        orchestrator = Agent3Orchestrator(
            store=store,
            executor=runtime_executor,
        )
        adapter = Agent3CampaignHandoffAdapter(
            orchestrator=orchestrator,
            resolve_launch=launch_resolver,
        )
        return adapter, orchestrator, store, runtime_executor, launch_resolver

    @staticmethod
    def request(campaign_id: str) -> CampaignDispatchRequest:
        return CampaignDispatchRequest(
            campaign_id=campaign_id,
            attempt=1,
            workflow="agent3.write-pilot",
            campaign_revision=1,
            parameters={"dry_run": True},
        )

    @staticmethod
    def count_rows(store: AgentRunStore, table: str) -> int:
        with store._lock:
            return int(
                store._conn.execute(
                    f"SELECT COUNT(*) FROM {table}"
                ).fetchone()[0]
            )

    def test_bind_dispatch_rechecks_tombstone_after_prepare_gap(self) -> None:
        adapter_a, _orchestrator_a, store_a, executor_a, resolver_a = self.stack()
        adapter_b, *_ = self.stack()
        request = self.request("campaign-tombstone-gap")
        original_prepare = adapter_a._prepare_run

        def prepare_after_tombstone(launch: Agent3CampaignLaunch):
            outcome = adapter_b.query_outcome(request.dispatch_id)
            self.assertEqual(outcome.kind, DispatchOutcomeKind.NOT_DISPATCHED)
            self.assertTrue(outcome.resources_released)
            return original_prepare(launch)

        with patch.object(
            adapter_a,
            "_prepare_run",
            side_effect=prepare_after_tombstone,
        ) as prepare_spy:
            with self.assertRaises(Agent3CampaignDispatchTombstonedError):
                adapter_a.dispatch(request)

        self.assertEqual(prepare_spy.call_count, 1)
        self.assertEqual(resolver_a.calls, 1)
        self.assertEqual(executor_a.calls, 0)
        self.assertEqual(self.count_rows(store_a, "agent_runs"), 0)
        with store_a._lock:
            row = store_a._conn.execute(
                "SELECT disposition,run_id FROM agent_campaign_effects "
                "WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()
        self.assertEqual(row, ("tombstoned", None))

    def test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack(self) -> None:
        executor = CountingExecutor()
        resolver = CountingResolver()
        adapter_a, _orchestrator_a, store_a, _executor_a, _resolver_a = self.stack(
            executor=executor,
            resolver=resolver,
        )
        adapter_b, *_ = self.stack(executor=executor, resolver=resolver)
        request = self.request("campaign-duplicate-gap")
        original_prepare = adapter_a._prepare_run
        original_bind = adapter_a._bind_dispatch
        competing: dict[str, object] = {}
        created_values: list[bool] = []

        def prepare_after_competing_dispatch(launch: Agent3CampaignLaunch):
            competing["ack"] = adapter_b.dispatch(request)
            return original_prepare(launch)

        def record_bind(*args, **kwargs):
            result = original_bind(*args, **kwargs)
            created_values.append(result[1])
            return result

        with patch.object(
            adapter_a,
            "_prepare_run",
            side_effect=prepare_after_competing_dispatch,
        ), patch.object(
            adapter_a,
            "_bind_dispatch",
            side_effect=record_bind,
        ), patch.object(
            adapter_a,
            "_advance_preserving_late_cancel",
            wraps=adapter_a._advance_preserving_late_cancel,
        ) as advance_a:
            acknowledgement = adapter_a.dispatch(request)

        self.assertEqual(acknowledgement, competing["ack"])
        self.assertEqual(created_values, [False])
        self.assertEqual(advance_a.call_count, 0)
        self.assertEqual(executor.calls, 1)
        self.assertEqual(resolver.calls, 2)
        self.assertEqual(self.count_rows(store_a, "agent_runs"), 1)
        self.assertEqual(self.count_rows(store_a, "agent_campaign_effects"), 1)
        with store_a._lock:
            row = store_a._conn.execute(
                "SELECT runtime_reference,disposition FROM "
                "agent_campaign_effects WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()
        self.assertEqual(row, (acknowledgement.runtime_reference, "accepted"))

    def test_missing_run_row_for_nonterminal_effect_is_unknown(self) -> None:
        resolver = CountingResolver(risk=RiskClass.WRITE)
        adapter, _orchestrator, store, _executor, _resolver = self.stack(
            resolver=resolver,
        )
        request = self.request("campaign-missing-run")
        acknowledgement = adapter.dispatch(request)
        run_id = acknowledgement.runtime_reference.removeprefix("agent3-run:")

        with store._lock:
            before = store._conn.execute(
                "SELECT disposition,outcome,resources_released FROM "
                "agent_campaign_effects WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()
            store._conn.execute("DELETE FROM agent_runs WHERE id=?", (run_id,))
            store._conn.commit()
        self.assertEqual(before, ("accepted", "accepted", None))

        outcome = adapter.query_outcome(request.dispatch_id)

        self.assertEqual(outcome.kind, DispatchOutcomeKind.UNKNOWN)
        self.assertIsNone(outcome.resources_released)
        self.assertEqual(outcome.error, "bound Agent 3 run is missing")
        with store._lock:
            after = store._conn.execute(
                "SELECT disposition,outcome,error,resources_released FROM "
                "agent_campaign_effects WHERE effect_id=?",
                (request.dispatch_id,),
            ).fetchone()
        self.assertEqual(
            after,
            (
                "accepted",
                "unknown",
                "bound Agent 3 run is missing",
                None,
            ),
        )

    def test_transaction_is_immediate_and_blocks_competing_writer(self) -> None:
        adapter_a, _orchestrator_a, _store_a, *_ = self.stack()
        _adapter_b, _orchestrator_b, store_b, *_ = self.stack()
        with store_b._lock:
            store_b._conn.execute("PRAGMA busy_timeout=50")

        blocked_error: sqlite3.OperationalError | None = None
        with adapter_a._transaction() as connection:
            self.assertTrue(connection.in_transaction)
            try:
                with store_b._lock:
                    store_b._conn.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                blocked_error = exc
            finally:
                with store_b._lock:
                    if store_b._conn.in_transaction:
                        store_b._conn.rollback()

        self.assertIsNotNone(blocked_error)
        self.assertIn("locked", str(blocked_error).lower())


if __name__ == "__main__":
    unittest.main()

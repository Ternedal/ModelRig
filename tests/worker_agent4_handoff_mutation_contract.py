#!/usr/bin/env python3
"""Mutation proofs for ADR-A4-008 Slice 5.

Each test copies the production package to a temporary PYTHONPATH, breaks one
safety property, and proves that the named contract test becomes red. A syntax
or import failure is not accepted as proof.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


class Slice5MutationProofTests(unittest.TestCase):
    maxDiff = None

    def _mutate_and_require_red(
        self,
        *,
        source_path: str,
        old: str,
        new: str,
        test_script: str,
        test_name: str,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sandbox = Path(directory)
            mutated_worker = sandbox / "worker"
            shutil.copytree(ROOT / "worker" / "app", mutated_worker / "app")
            target = mutated_worker / source_path
            source = target.read_text(encoding="utf-8")
            occurrences = source.count(old)
            self.assertEqual(
                occurrences,
                1,
                f"mutation seam drifted in {source_path}: found {occurrences}",
            )
            target.write_text(source.replace(old, new, 1), encoding="utf-8")

            env = os.environ.copy()
            existing = env.get("PYTHONPATH", "")
            env["PYTHONPATH"] = (
                str(mutated_worker)
                if not existing
                else str(mutated_worker) + os.pathsep + existing
            )
            result = subprocess.run(
                [sys.executable, test_script, "-k", test_name],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            output = result.stdout + "\n" + result.stderr
            self.assertNotEqual(
                result.returncode,
                0,
                f"mutation survived {test_name}\n{output}",
            )
            self.assertIn(test_name, output)
            self.assertNotIn("SyntaxError", output)
            self.assertNotIn("ImportError", output)
            self.assertNotIn("ModuleNotFoundError", output)

    def test_sabotage_01_deferred_transaction_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='            connection.execute("BEGIN IMMEDIATE")',
            new='            connection.execute("BEGIN")',
            test_script="tests/worker_agent3_campaign_adapter_races.py",
            test_name="test_transaction_is_immediate_and_blocks_competing_writer",
        )

    def test_sabotage_02_removed_tombstone_recheck_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''            if existing is not None:
                if existing.disposition == "tombstoned":
                    raise Agent3CampaignDispatchTombstonedError(
                        "dispatch identity is permanently tombstoned"
                    )
                self._require_same_request(existing, "dispatch", request_hash)
''',
            new='''            if existing is not None:
                if False and existing.disposition == "tombstoned":
                    raise Agent3CampaignDispatchTombstonedError(
                        "dispatch identity is permanently tombstoned"
                    )
                self._require_same_request(existing, "dispatch", request_hash)
''',
            test_script="tests/worker_agent3_campaign_adapter_races.py",
            test_name="test_bind_dispatch_rechecks_tombstone_after_prepare_gap",
        )

    def test_sabotage_03_duplicate_created_true_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''                    False,
                )

            now = time.time()
''',
            new='''                    True,
                )

            now = time.time()
''',
            test_script="tests/worker_agent3_campaign_adapter_races.py",
            test_name="test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack",
        )

    def test_sabotage_04_duplicate_unconditional_advance_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''        if created:
            # External execution is deliberately outside the registry
''',
            new='''        if True:
            # MUTATION: duplicate acknowledgements execute again.
''',
            test_script="tests/worker_agent3_campaign_adapter_races.py",
            test_name="test_bind_dispatch_duplicate_after_prepare_gap_returns_existing_ack",
        )

    def test_sabotage_05_missing_run_terminal_attestation_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''            if row is None:
                return self._persist_unknown(
                    connection,
                    effect,
                    "bound Agent 3 run is missing",
                )
''',
            new='''            if row is None:
                return CampaignDispatchOutcome(
                    dispatch_id=effect.effect_id,
                    kind=DispatchOutcomeKind.COMPLETED,
                    runtime_reference=effect.runtime_reference,
                    evidence_pointer="mutation:false-terminal",
                    resources_released=True,
                )
''',
            test_script="tests/worker_agent3_campaign_adapter_races.py",
            test_name="test_missing_run_row_for_nonterminal_effect_is_unknown",
        )

    def test_sabotage_06_signal_not_requested_before_call_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''                    "signal_requested",
                    request.campaign_id,
''',
            new='''                    "signal_acknowledged",
                    request.campaign_id,
''',
            test_script="tests/worker_agent3_campaign_adapter.py",
            test_name="test_signal_is_requested_before_call_and_never_redelivered",
        )

    def test_sabotage_07_unresolved_signal_replay_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent3/campaign_adapter.py",
            old='''                raise Agent3CampaignSignalUncertainError(
                    "signal outcome is unresolved and will not be replayed"
                )
''',
            new='''                connection.execute(
                    "DELETE FROM agent_campaign_effects WHERE effect_id=?",
                    (request.signal_id,),
                )
''',
            test_script="tests/worker_agent3_campaign_adapter.py",
            test_name="test_signal_is_requested_before_call_and_never_redelivered",
        )

    def test_sabotage_08_unknown_automatic_requeue_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent4/handoff_runtime.py",
            old='''    def _unknown(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        *,
        recovered_at: datetime,
        detail: str,
    ) -> CampaignHandoffRecoveryDecision:
        updated = CampaignRecord(
''',
            new='''    def _unknown(
        self,
        record: CampaignRecord,
        intent: CampaignHandoffIntent,
        *,
        recovered_at: datetime,
        detail: str,
    ) -> CampaignHandoffRecoveryDecision:
        self._queue.enqueue(record.spec)
        updated = CampaignRecord(
''',
            test_script="tests/worker_agent4_handoff_e2e.py",
            test_name="test_missing_receiver_run_recovers_unknown_without_redispatch",
        )

    def test_sabotage_09_terminal_auto_clear_marker_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent4/handoff_runtime.py",
            old='''        terminal = CampaignRecord(spec=record.spec, state=state)
        acknowledgement = CampaignDispatchAcknowledgement(
''',
            new='''        state = replace(
            state,
            resource_reconciliation_required=False,
        )
        terminal = CampaignRecord(spec=record.spec, state=state)
        acknowledgement = CampaignDispatchAcknowledgement(
''',
            test_script="tests/worker_agent4_handoff_runtime.py",
            test_name="test_terminal_attestation_never_auto_clears_existing_marker",
        )

    def test_sabotage_10_resource_barrier_bypass_is_caught(self) -> None:
        self._mutate_and_require_red(
            source_path="app/agent4/handoff_runtime.py",
            old='''        if blocked:
            raise CampaignResourceReconciliationBlockedError(
''',
            new='''        if False and blocked:
            raise CampaignResourceReconciliationBlockedError(
''',
            test_script="tests/worker_agent4_handoff_barrier_placement.py",
            test_name="test_existing_marker_blocks_before_any_lease_acquire_attempt",
        )


if __name__ == "__main__":
    unittest.main()

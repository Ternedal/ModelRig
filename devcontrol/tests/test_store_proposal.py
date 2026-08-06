from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from kaliv_dev_control.campaign import (
    CampaignError,
    CampaignState,
    DevelopmentCampaign,
)
from kaliv_dev_control.proposal import DraftProposalBuilder, ProposalError
from kaliv_dev_control.review import IndependentPolicyReviewer, ReviewRequest
from kaliv_dev_control.store import CampaignStore, CampaignStoreError
from test_campaign_review import command_receipt, patch_receipt, task


class StoreProposalTests(unittest.TestCase):
    def test_store_create_load_and_single_append_cas(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            store = CampaignStore(Path(temporary) / "campaigns")
            store.create(campaign)
            self.assertEqual(
                store.load("SDC-004").canonical_json(),
                campaign.canonical_json(),
            )

            previous = campaign.events[-1].event_sha256
            updated = campaign.advance(
                CampaignState.WORKSPACE_READY,
                evidence_sha256="2" * 64,
                detail="workspace ready",
            )
            store.save(updated, expected_previous_event_sha256=previous)
            self.assertEqual(
                store.load("SDC-004").state,
                CampaignState.WORKSPACE_READY,
            )

            with self.assertRaises(CampaignStoreError):
                store.save(updated, expected_previous_event_sha256=previous)

    def test_store_rejects_tampered_record(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            store = CampaignStore(root)
            path = store.create(campaign)
            path.write_text('{"schema":"tampered"}\n', encoding="utf-8")
            with self.assertRaises(CampaignStoreError):
                store.load("SDC-004")

    def test_campaign_reload_rejects_invalid_task_id(self) -> None:
        campaign = DevelopmentCampaign.create("SDC-004", task())
        value = campaign.to_dict()
        value["task_id"] = "lowercase"
        with self.assertRaisesRegex(CampaignError, "task id"):
            DevelopmentCampaign.from_mapping(value)

    def test_store_rejects_existing_malformed_lock(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            root.mkdir()
            (root / ".SDC-004.lock").write_text("held\n", encoding="utf-8")
            with self.assertRaises(CampaignStoreError):
                CampaignStore(root).create(campaign)

    def test_store_recovers_a_provably_dead_owner_lock(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            root.mkdir()
            lock = root / ".SDC-004.lock"
            lock.write_text(
                json.dumps(
                    {
                        "schema": "kaliv-development-campaign-lock/v1",
                        "pid": 999999,
                        "identity": "dead-owner",
                        "nonce": "a" * 64,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "kaliv_dev_control.store._identity",
                side_effect=("current-owner", ""),
            ):
                path = CampaignStore(root).create(campaign)
            self.assertTrue(path.is_file())
            self.assertFalse(lock.exists())

    def test_store_never_reclaims_a_live_owner_lock(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            root.mkdir()
            lock = root / ".SDC-004.lock"
            lock.write_text(
                json.dumps(
                    {
                        "schema": "kaliv-development-campaign-lock/v1",
                        "pid": 123,
                        "identity": "live-owner",
                        "nonce": "b" * 64,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            with patch(
                "kaliv_dev_control.store._identity",
                side_effect=("current-owner", "live-owner"),
            ):
                with self.assertRaisesRegex(CampaignStoreError, "live operation"):
                    CampaignStore(root).create(campaign)
            self.assertTrue(lock.is_file())

    def test_campaign_guard_serializes_the_reclaim_window(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = CampaignStore(Path(temporary) / "campaigns")
            store._prepare_root()
            first_entered = threading.Event()
            release_first = threading.Event()
            second_entered = threading.Event()
            errors: list[BaseException] = []

            def first() -> None:
                try:
                    with store._campaign_guard("SDC-004"):
                        first_entered.set()
                        if not release_first.wait(5):
                            raise RuntimeError("guard test timed out")
                except BaseException as exc:  # test worker propagation
                    errors.append(exc)

            def second() -> None:
                try:
                    if not first_entered.wait(5):
                        raise RuntimeError("first guard never entered")
                    with store._campaign_guard("SDC-004"):
                        second_entered.set()
                except BaseException as exc:  # test worker propagation
                    errors.append(exc)

            first_thread = threading.Thread(target=first)
            second_thread = threading.Thread(target=second)
            first_thread.start()
            self.assertTrue(first_entered.wait(5))
            second_thread.start()
            self.assertFalse(second_entered.wait(0.2))
            release_first.set()
            first_thread.join(5)
            second_thread.join(5)
            self.assertFalse(first_thread.is_alive())
            self.assertFalse(second_thread.is_alive())
            self.assertTrue(second_entered.is_set())
            self.assertEqual(errors, [])

    def test_concurrent_stale_reclaim_has_exactly_one_creator(self) -> None:
        campaign = DevelopmentCampaign.create("SDC-004", task())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "campaigns"
            root.mkdir()
            lock = root / ".SDC-004.lock"
            lock.write_text(
                json.dumps(
                    {
                        "schema": "kaliv-development-campaign-lock/v1",
                        "pid": 999999,
                        "identity": "dead-owner",
                        "nonce": "c" * 64,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n",
                encoding="utf-8",
            )
            start = threading.Barrier(2)

            def identity(pid: int) -> str:
                return "" if pid == 999999 else "current-owner"

            def create() -> Path | CampaignStoreError:
                start.wait(timeout=5)
                try:
                    return CampaignStore(root).create(campaign)
                except CampaignStoreError as exc:
                    return exc

            with patch("kaliv_dev_control.store._identity", side_effect=identity):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: create(), range(2)))
            winners = [item for item in results if isinstance(item, Path)]
            losers = [item for item in results if isinstance(item, CampaignStoreError)]
            self.assertEqual(len(winners), 1)
            self.assertEqual(len(losers), 1)
            self.assertEqual(
                CampaignStore(root).load("SDC-004").canonical_json(),
                campaign.canonical_json(),
            )
            self.assertFalse(lock.exists())

    @unittest.skipUnless(
        sys.platform.startswith("linux") and hasattr(os, "fork"),
        "zombie process identity is Linux-specific",
    )
    def test_linux_zombie_lock_owner_is_treated_as_dead(self) -> None:
        from kaliv_dev_control import store as store_module

        pid = os.fork()
        if pid == 0:
            os._exit(0)
        try:
            observed: str | None = None
            for _ in range(200):
                observed = store_module._identity(pid)
                if observed == "":
                    break
                time.sleep(0.01)
            self.assertEqual(observed, "")
        finally:
            os.waitpid(pid, 0)

    def test_nested_store_creation_syncs_each_new_parent(self) -> None:
        value = task()
        campaign = DevelopmentCampaign.create("SDC-004", value)
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            root = base / "first" / "second"
            from kaliv_dev_control import store as store_module

            real_sync = store_module.sync_directory
            with patch(
                "kaliv_dev_control.store.sync_directory",
                wraps=real_sync,
            ) as directory_sync:
                CampaignStore(root).create(campaign)
            synced = {call.args[0] for call in directory_sync.call_args_list}
            self.assertIn(base, synced)
            self.assertIn(base / "first", synced)
            self.assertIn(root, synced)

    def _reviewed(self):
        value = task()
        request = ReviewRequest.from_evidence(
            task=value,
            developer_actor_id="developer-a",
            patch=patch_receipt(value),
            commands=(
                command_receipt(value, "test.unit", passed=True),
                command_receipt(value, "test.contract", passed=True),
            ),
        )
        verdict = IndependentPolicyReviewer().review(
            request,
            reviewer_actor_id="reviewer-b",
        )
        campaign = DevelopmentCampaign.create("SDC-004", value)
        for state, evidence in (
            (CampaignState.WORKSPACE_READY, "2" * 64),
            (CampaignState.PATCH_STAGED, "3" * 64),
            (CampaignState.TESTED, "4" * 64),
            (CampaignState.REVIEWED, "5" * 64),
        ):
            campaign = campaign.advance(
                state,
                evidence_sha256=evidence,
                detail=state.value,
            )
        return value, campaign, request, verdict

    def test_proposal_is_deterministic_and_draft_only(self) -> None:
        value, campaign, request, verdict = self._reviewed()
        first = DraftProposalBuilder.build(
            task=value,
            campaign=campaign,
            request=request,
            verdict=verdict,
        )
        second = DraftProposalBuilder.build(
            task=value,
            campaign=campaign,
            request=request,
            verdict=verdict,
        )
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertTrue(first.draft)
        self.assertEqual(first.merge_authority, "human")
        self.assertTrue(first.head_branch.startswith("kaliv-dev/"))
        self.assertIn("Semantic human review", first.body)

    def test_proposal_rejects_unreviewed_campaign(self) -> None:
        value, _, request, verdict = self._reviewed()
        unreviewed = DevelopmentCampaign.create("SDC-004", value)
        with self.assertRaises(ProposalError):
            DraftProposalBuilder.build(
                task=value,
                campaign=unreviewed,
                request=request,
                verdict=verdict,
            )


if __name__ == "__main__":
    unittest.main()

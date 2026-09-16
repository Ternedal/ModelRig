"""Adversarial contract for ADR-DC-067 exact release transaction."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))
from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_authorization as release_auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_state_observation as release_state,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_transaction as release_tx,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _cleanup_case,
)
from rsi_pilot_exact_task_release_authorization_contract import (  # noqa: E402
    _config,
    _dual_authority,
    _ledger as _auth_ledger,
    _live_clear_observation,
    _payload,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-release-transaction-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_release_transaction.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-067 unexpectedly accepted unsafe release transaction")


def _ledger(prefix: str):
    temp = tempfile.TemporaryDirectory(prefix=prefix)
    root = Path(temp.name) / "ledger"
    root.mkdir()
    return temp, release_tx._PilotExactTaskReleaseTransactionLedger(root)


class _AuthorizationTransport:
    def __init__(self, plan, readiness):
        self.plan = plan
        self.credential_config_sha256 = readiness.publisher_credential_config_sha256
        self.credential_path_sha256 = readiness.publisher_credential_path_sha256

    def observe(self, plan):
        assert plan.sha256 == self.plan.sha256
        return release_state._RemoteReleaseState(
            repository=plan.repository,
            repository_id=plan.repository_id,
            tag_state="absent",
            tag_target_sha=None,
            release_state="absent",
            release_id=None,
            release_node_id_sha256=None,
            release_tag_name=None,
            release_name=None,
            release_body_sha256=None,
            release_draft=None,
            release_prerelease=None,
            release_asset_count=None,
            remote_state_class="clear",
        )


def _live_authority():
    case, readiness, plan, observation = _live_clear_observation()
    auth_temp, auth_ledger = _auth_ledger("rsi-exact-task-release-tx-auth-")
    config = _config(observation)
    payload = _payload(observation, config)
    verifier, op_sig, review_sig = _dual_authority(payload)
    authority = release_auth._authorize_verified_pilot_exact_task_release(
        release_state_observation=observation,
        release_config=config,
        authorization_payload=payload,
        operator_signature=op_sig,
        reviewer_signature=review_sig,
        verifier=verifier,
        ledger=auth_ledger,
        transport=_AuthorizationTransport(plan, readiness),
        now_provider=lambda: "2026-09-15T09:44:30Z",
    )
    assert authority.authorization_authenticated is True
    return case, auth_temp, plan, authority


class _Transport:
    def __init__(
        self,
        plan,
        authority,
        *,
        fail_tag=False,
        fail_release=False,
        wrong_tag_target=False,
        final_drift=False,
    ):
        self.plan = plan
        self.credential_config_sha256 = authority.publisher_credential_config_sha256
        self.credential_path_sha256 = authority.publisher_credential_path_sha256
        self.fail_tag = fail_tag
        self.fail_release = fail_release
        self.wrong_tag_target = wrong_tag_target
        self.final_drift = final_drift
        self.tag_written = False
        self.release_written = False
        self.release_id = 7001
        self.node_hash = "a" * 64
        self.calls = []

    def _clear(self):
        return release_state._RemoteReleaseState(
            repository=self.plan.repository,
            repository_id=self.plan.repository_id,
            tag_state="absent",
            tag_target_sha=None,
            release_state="absent",
            release_id=None,
            release_node_id_sha256=None,
            release_tag_name=None,
            release_name=None,
            release_body_sha256=None,
            release_draft=None,
            release_prerelease=None,
            release_asset_count=None,
            remote_state_class="clear",
        )

    def _exact(self):
        return release_state._RemoteReleaseState(
            repository=self.plan.repository,
            repository_id=self.plan.repository_id,
            tag_state="exact",
            tag_target_sha=self.plan.tag_target_sha,
            release_state="exact-draft",
            release_id=self.release_id,
            release_node_id_sha256=("b" * 64 if self.final_drift else self.node_hash),
            release_tag_name=self.plan.tag_name,
            release_name=self.plan.release_name,
            release_body_sha256=self.plan.release_body_sha256,
            release_draft=True,
            release_prerelease=True,
            release_asset_count=0,
            remote_state_class="exact-existing",
        )

    def observe(self, plan):
        self.calls.append("observe")
        assert plan.sha256 == self.plan.sha256
        return self._exact() if self.release_written else self._clear()

    def observe_tag_phase(self, plan):
        self.calls.append("observe_tag_phase")
        assert plan.sha256 == self.plan.sha256
        if not self.tag_written:
            return ("absent", None, True)
        target = "f" * 40 if self.wrong_tag_target else self.plan.tag_target_sha
        return ("exact", target, not self.release_written)

    def create_tag(self, authority):
        self.calls.append("create_tag")
        if self.fail_tag:
            raise ValueError("simulated tag failure")
        self.tag_written = True
        return "f" * 40 if self.wrong_tag_target else authority.tag_target_sha

    def create_release(self, authority, *, release_body):
        self.calls.append("create_release")
        assert release_body == self.plan.release_body
        if self.fail_release:
            raise ValueError("simulated release failure")
        self.release_written = True
        return self.release_id, self.node_hash


def _execute(authority, transport, ledger):
    times = iter(
        (
            "2026-09-15T09:44:31Z",
            "2026-09-15T09:44:32Z",
            "2026-09-15T09:44:33Z",
            "2026-09-15T09:44:34Z",
            "2026-09-15T09:44:35Z",
            "2026-09-15T09:44:36Z",
            "2026-09-15T09:44:37Z",
        )
    )
    return release_tx._execute_verified_pilot_exact_task_release(
        release_authorization=authority,
        transport=transport,
        ledger=ledger,
        now_provider=lambda: next(times),
    )


def _phase_paths(ledger, authority):
    return ledger._paths(authority.execution_nonce_sha256)


def run_contract() -> None:
    if os.name == "nt":
        return

    case, auth_temp, plan, authority = _live_authority()
    tx_temp, ledger = _ledger("rsi-exact-task-release-tx-")
    try:
        transport = _Transport(plan, authority)
        receipt = _execute(authority, transport, ledger)
        assert receipt.transaction_authenticated is True
        assert receipt.release_key_sha256 == authority.execution_nonce_sha256
        assert receipt.release_authorization_sha256 == authority.sha256
        assert receipt.release_plan_sha256 == authority.release_plan_sha256
        assert receipt.release_intent_sha256 == authority.release_intent_sha256
        assert receipt.repository == authority.repository
        assert receipt.repository_id == authority.repository_id
        assert receipt.merge_commit_sha == authority.merge_commit_sha
        assert receipt.tag_name == authority.tag_name
        assert receipt.tag_target_sha == authority.tag_target_sha
        assert receipt.release_name == authority.release_name
        assert receipt.release_body_sha256 == authority.release_body_sha256
        assert receipt.release_id == transport.release_id
        assert receipt.release_node_id_sha256 == transport.node_hash
        assert receipt.release_authorization_authenticated is True
        assert receipt.release_authority_consumed is True
        assert receipt.host_transaction_lock_committed is True
        assert receipt.exact_clear_lane_revalidated is True
        assert receipt.tag_created is True
        assert receipt.tag_marker_committed is True
        assert receipt.release_created is True
        assert receipt.release_marker_committed is True
        assert receipt.final_remote_state_verified is True
        assert receipt.double_final_observation_matched is True
        assert receipt.transaction_completed is True
        assert receipt.tag_write_authorized is False
        assert receipt.release_mutation_authorized is False
        assert receipt.release_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False
        assert transport.calls == [
            "observe",
            "observe",
            "observe",
            "observe",
            "create_tag",
            "observe_tag_phase",
            "observe_tag_phase",
            "create_release",
            "observe",
            "observe",
        ]

        final, lock, tag_marker, release_marker = _phase_paths(ledger, authority)
        assert all(path.exists() for path in (final, lock, tag_marker, release_marker))
        assert hashlib.sha256(lock.read_bytes()).hexdigest() == receipt.transaction_lock_sha256
        assert hashlib.sha256(tag_marker.read_bytes()).hexdigest() == receipt.tag_marker_sha256
        assert hashlib.sha256(release_marker.read_bytes()).hexdigest() == receipt.release_marker_sha256

        reloaded = release_tx.PilotExactTaskReleaseTransactionReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.transaction_authenticated is False

        _reject(lambda: _execute(authority, _Transport(plan, authority), ledger))

        reloaded_auth = release_auth.PilotExactTaskReleaseAuthorizationReceipt.from_mapping(
            authority.to_dict()
        )
        assert reloaded_auth.authorization_authenticated is False
        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-stale-")
        try:
            _reject(
                lambda: _execute(
                    reloaded_auth,
                    _Transport(plan, authority),
                    fresh_ledger,
                )
            )
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-cred-")
        try:
            drift = _Transport(plan, authority)
            drift.credential_config_sha256 = "9" * 64
            _reject(lambda: _execute(authority, drift, fresh_ledger))
            assert not any(path.exists() for path in _phase_paths(fresh_ledger, authority))
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-tag-fail-")
        try:
            _reject(
                lambda: _execute(
                    authority,
                    _Transport(plan, authority, fail_tag=True),
                    fresh_ledger,
                )
            )
            final, lock, tag_marker, release_marker = _phase_paths(
                fresh_ledger, authority
            )
            assert lock.exists()
            assert not final.exists()
            assert not tag_marker.exists()
            assert not release_marker.exists()
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-tag-drift-")
        try:
            _reject(
                lambda: _execute(
                    authority,
                    _Transport(plan, authority, wrong_tag_target=True),
                    fresh_ledger,
                )
            )
            final, lock, tag_marker, release_marker = _phase_paths(
                fresh_ledger, authority
            )
            assert lock.exists()
            assert not final.exists()
            assert not tag_marker.exists()
            assert not release_marker.exists()
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-release-fail-")
        try:
            _reject(
                lambda: _execute(
                    authority,
                    _Transport(plan, authority, fail_release=True),
                    fresh_ledger,
                )
            )
            final, lock, tag_marker, release_marker = _phase_paths(
                fresh_ledger, authority
            )
            assert lock.exists()
            assert tag_marker.exists()
            assert not release_marker.exists()
            assert not final.exists()
        finally:
            fresh_temp.cleanup()

        fresh_temp, fresh_ledger = _ledger("rsi-exact-task-release-tx-final-drift-")
        try:
            _reject(
                lambda: _execute(
                    authority,
                    _Transport(plan, authority, final_drift=True),
                    fresh_ledger,
                )
            )
            final, lock, tag_marker, release_marker = _phase_paths(
                fresh_ledger, authority
            )
            assert lock.exists()
            assert tag_marker.exists()
            assert release_marker.exists()
            assert not final.exists()
        finally:
            fresh_temp.cleanup()

        for field, value in (
            ("release_authorization_authenticated", False),
            ("release_authority_consumed", False),
            ("host_transaction_lock_committed", False),
            ("exact_clear_lane_revalidated", False),
            ("tag_created", False),
            ("tag_marker_committed", False),
            ("release_created", False),
            ("release_marker_committed", False),
            ("final_remote_state_verified", False),
            ("double_final_observation_matched", False),
            ("transaction_completed", False),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("release_authorized", True),
            ("remote_write_authorized", True),
            ("merge_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    release_tx.PilotExactTaskReleaseTransactionReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(code_of(SCHEMA))
        receipt_fields = set(
            release_tx.PilotExactTaskReleaseTransactionReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 69
        for name in (
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
            "merge_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert schema["properties"][name]["const"] is False

        signature = inspect.signature(release_tx.execute_pilot_exact_task_release)
        assert list(signature.parameters) == ["release_authorization"]

        source_text = code_of(SOURCE)
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert source_text.count('method="POST"') == 1
        assert 'f"{root}/git/refs"' in source_text
        assert 'f"{root}/releases"' in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
    finally:
        tx_temp.cleanup()
        auth_temp.cleanup()
        _cleanup_case(case)


if __name__ == "__main__":
    run_contract()

"""Adversarial contract for ADR-DC-063 exact release-readiness evaluation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
from source_code import code_of  # noqa: E402
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_merge_attestation as post_merge,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_readiness_evaluation as release,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _attest,
    _cleanup_case,
    _normal_completion,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-release-readiness-evaluation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_release_readiness_evaluation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-063 unexpectedly accepted unsafe release readiness")


class _Transport:
    def __init__(
        self,
        source,
        *,
        current_base_sha=None,
        parent_sha=None,
    ):
        self.source = source
        self.credential_config_sha256 = source.publisher_credential_config_sha256
        self.credential_path_sha256 = source.publisher_credential_path_sha256
        self.current_base_sha = current_base_sha or source.merge_commit_sha
        self.parent_sha = parent_sha or source.authorized_base_sha
        self.scripted = []
        self.calls = []

    def _state(self, *, current_base_sha=None, parent_sha=None, head_sha=None):
        return release._ReleaseReadinessRemoteState(
            repository=self.source.repository,
            repository_id=self.source.repository_id,
            base_branch=self.source.base_branch,
            current_base_sha=current_base_sha or self.current_base_sha,
            head_branch=self.source.head_branch,
            head_sha=head_sha or self.source.head_sha,
            pull_request_number=self.source.pull_request_number,
            pull_request_api_url=self.source.pull_request_api_url,
            pull_request_node_id_sha256=self.source.pull_request_node_id_sha256,
            merge_commit_sha=self.source.merge_commit_sha,
            merge_commit_parent_sha=parent_sha or self.parent_sha,
            merged=True,
            draft=False,
            state="closed",
            maintainer_can_modify=False,
        )

    def observe(self, source):
        self.calls.append("observe")
        assert source.sha256 == self.source.sha256
        if self.scripted:
            return self.scripted.pop(0)
        return self._state()


def _policy(source, **overrides):
    values = {
        "repository": source.repository,
        "repository_id": source.repository_id,
        "release_base_branch": source.base_branch,
        "allowed_completion_sources": ("recovery", "transaction"),
        "required_merge_method": "squash",
        "require_current_base_head": True,
        "require_exact_authorized_parent": True,
    }
    values.update(overrides)
    return release.PilotExactTaskReleaseReadinessPolicy(**values)


def _evaluate(source, policy, transport, *, now="2026-09-15T09:42:00Z"):
    return release._evaluate_verified_pilot_exact_task_release_readiness(
        post_merge_attestation=source,
        policy=policy,
        policy_sha256=policy.sha256,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    case = _normal_completion()
    try:
        (
            _bundle,
            _up_tx,
            _up_recovery,
            auth_temp,
            tx_temp,
            recovery_temp,
            authorization,
            _merge_receipt,
            observer,
        ) = case
        source = _attest(
            authorization,
            tx_temp,
            auth_temp,
            recovery_temp,
            observer,
        )
        assert source.attestation_authenticated is True

        policy = _policy(source)
        transport = _Transport(source)
        receipt = _evaluate(source, policy, transport)
        assert transport.calls == ["observe", "observe"]
        assert receipt.evaluation_authenticated is True
        assert receipt.post_merge_attestation_sha256 == source.sha256
        assert receipt.merge_authorization_sha256 == source.merge_authorization_sha256
        assert receipt.release_readiness_policy_sha256 == policy.sha256
        assert receipt.execution_nonce_sha256 == source.execution_nonce_sha256
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.base_branch == source.base_branch
        assert receipt.release_base_branch == source.base_branch
        assert receipt.authorized_base_sha == source.authorized_base_sha
        assert receipt.current_base_sha == source.merge_commit_sha
        assert receipt.head_branch == source.head_branch
        assert receipt.head_sha == source.head_sha
        assert receipt.pull_request_number == source.pull_request_number
        assert receipt.pull_request_node_id_sha256 == source.pull_request_node_id_sha256
        assert receipt.merge_method == "squash"
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.completion_source == "transaction"
        assert receipt.allowed_completion_sources == ("recovery", "transaction")
        assert receipt.blocker_codes == ()
        assert receipt.post_merge_attestation_authenticated is True
        assert receipt.release_readiness_policy_host_pinned is True
        assert receipt.exact_merge_revalidated is True
        assert receipt.exact_authorized_parent_satisfied is True
        assert receipt.double_observation_matched is True
        assert receipt.base_branch_policy_satisfied is True
        assert receipt.merge_method_policy_satisfied is True
        assert receipt.completion_source_policy_satisfied is True
        assert receipt.current_base_head_satisfied is True
        assert receipt.release_readiness_evaluated is True
        assert receipt.release_ready is True
        assert receipt.release_readiness_authorized is False
        assert receipt.release_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.nonce_reusable is False

        reloaded = release.PilotExactTaskReleaseReadinessEvaluationReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.evaluation_authenticated is False

        branch_policy = _policy(source, release_base_branch="release")
        branch_receipt = _evaluate(source, branch_policy, _Transport(source))
        assert branch_receipt.release_ready is False
        assert branch_receipt.blocker_codes == ("base-branch-not-release-target",)

        source_policy = _policy(
            source,
            allowed_completion_sources=("recovery",),
        )
        source_receipt = _evaluate(source, source_policy, _Transport(source))
        assert source_receipt.release_ready is False
        assert source_receipt.blocker_codes == (
            "completion-source-not-release-approved",
        )

        moved_sha = "f" * 40
        if moved_sha in {
            source.merge_commit_sha,
            source.authorized_base_sha,
            source.head_sha,
        }:
            moved_sha = "e" * 40
        moved = _evaluate(
            source,
            policy,
            _Transport(source, current_base_sha=moved_sha),
        )
        assert moved.release_ready is False
        assert moved.current_base_head_satisfied is False
        assert moved.blocker_codes == ("merge-commit-not-current-base-head",)

        drift = _Transport(source)
        drift.scripted = [
            drift._state(),
            drift._state(current_base_sha=moved_sha),
        ]
        _reject(lambda: _evaluate(source, policy, drift))

        wrong_parent = "d" * 40
        if wrong_parent in {
            source.merge_commit_sha,
            source.authorized_base_sha,
            source.head_sha,
        }:
            wrong_parent = "c" * 40
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source, parent_sha=wrong_parent),
            )
        )

        wrong_head = "b" * 40
        if wrong_head in {
            source.merge_commit_sha,
            source.authorized_base_sha,
            source.head_sha,
        }:
            wrong_head = "a" * 40
        identity_drift = _Transport(source)
        identity_drift.scripted = [
            identity_drift._state(head_sha=wrong_head),
        ]
        _reject(lambda: _evaluate(source, policy, identity_drift))

        credential_drift = _Transport(source)
        credential_drift.credential_config_sha256 = "9" * 64
        _reject(lambda: _evaluate(source, policy, credential_drift))

        reloaded_source = (
            post_merge.PilotExactTaskPostMergeAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert reloaded_source.attestation_authenticated is False
        _reject(
            lambda: release._evaluate_verified_pilot_exact_task_release_readiness(
                post_merge_attestation=reloaded_source,
                policy=policy,
                policy_sha256=policy.sha256,
                transport=_Transport(source),
                now_provider=lambda: "2026-09-15T09:42:00Z",
            )
        )

        _reject(
            lambda: release._evaluate_verified_pilot_exact_task_release_readiness(
                post_merge_attestation=source,
                policy=policy,
                policy_sha256="8" * 64,
                transport=_Transport(source),
                now_provider=lambda: "2026-09-15T09:42:00Z",
            )
        )
        other_policy = release.PilotExactTaskReleaseReadinessPolicy(
            repository="example/other",
            repository_id=source.repository_id,
            release_base_branch=source.base_branch,
        )
        _reject(
            lambda: release._evaluate_verified_pilot_exact_task_release_readiness(
                post_merge_attestation=source,
                policy=other_policy,
                policy_sha256=other_policy.sha256,
                transport=_Transport(source),
                now_provider=lambda: "2026-09-15T09:42:00Z",
            )
        )
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source),
                now="2026-09-15T09:40:59Z",
            )
        )

        _reject(
            lambda: release.PilotExactTaskReleaseReadinessPolicy(
                repository=source.repository,
                repository_id=source.repository_id,
                release_base_branch=source.base_branch,
                allowed_completion_sources=("transaction", "recovery"),
            )
        )
        _reject(
            lambda: release.PilotExactTaskReleaseReadinessPolicy(
                repository=source.repository,
                repository_id=source.repository_id,
                release_base_branch=source.base_branch,
                require_current_base_head=False,
            )
        )
        _reject(
            lambda: release.PilotExactTaskReleaseReadinessPolicy(
                repository=source.repository,
                repository_id=source.repository_id,
                release_base_branch=source.base_branch,
                require_exact_authorized_parent=False,
            )
        )

        for field, value in (
            ("post_merge_attestation_authenticated", False),
            ("release_readiness_policy_host_pinned", False),
            ("exact_merge_revalidated", False),
            ("exact_authorized_parent_satisfied", False),
            ("double_observation_matched", False),
            ("release_readiness_evaluated", False),
            ("release_ready", False),
            ("release_readiness_authorized", True),
            ("merge_authorized", True),
            ("remote_write_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("ready_for_review_authorized", True),
            ("reviewer_request_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("release_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    release.PilotExactTaskReleaseReadinessEvaluationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: release.PilotExactTaskReleaseReadinessEvaluationReceipt.from_mapping(
                {
                    **receipt.to_dict(),
                    "blocker_codes": ["merge-commit-not-current-base-head"],
                }
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            release.PilotExactTaskReleaseReadinessEvaluationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert schema["properties"]["release_authorized"]["const"] is False
        assert schema["properties"]["deploy_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert schema["properties"]["release_ready"]["type"] == "boolean"

        signature = inspect.signature(
            release.evaluate_pilot_exact_task_release_readiness
        )
        assert list(signature.parameters) == ["post_merge_attestation"]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert "method='POST'" not in source_text
        assert 'method="PUT"' not in source_text
        assert "method='PUT'" not in source_text
        assert "merge_pull_request" not in source_text
        assert "create_release" not in source_text
        assert "create_git_tag" not in source_text
        assert "Ed25519PrivateKey" not in source_text
        assert "subprocess" not in source_text
    finally:
        _cleanup_case(case)


if __name__ == "__main__":
    run_contract()

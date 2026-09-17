"""Adversarial contract for ADR-DC-070 exact staging deploy-readiness."""
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
    improvement_pilot_exact_task_deploy_readiness_evaluation as deploy_ready,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_post_release_attestation as post_release,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_recovery as recovery,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _cleanup_case,
)
import rsi_pilot_exact_task_post_release_attestation_contract as post_release_contract  # noqa: E402
import rsi_pilot_exact_task_release_transaction_contract_base as tx_contract  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-deploy-readiness-evaluation-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_deploy_readiness_evaluation.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-070 unexpectedly accepted unsafe deploy readiness")


def _live_source():
    case, auth_temp, plan, authority = tx_contract._live_authority()
    tx_temp, tx_ledger = tx_contract._ledger(
        "rsi-exact-task-deploy-readiness-tx-"
    )
    recovery_temp, recovery_root = post_release_contract._recovery_root(
        "rsi-exact-task-deploy-readiness-empty-"
    )
    tx_transport = tx_contract._Transport(plan, authority)
    tx_receipt = tx_contract._execute(authority, tx_transport, tx_ledger)
    source = post_release_contract._attest(
        authority,
        auth_temp,
        tx_temp,
        recovery_root,
        post_release_contract._Observer(
            authority,
            tx_receipt.release_id,
            tx_receipt.release_node_id_sha256,
        ),
        "2026-09-15T09:46:00Z",
    )
    assert source.attestation_authenticated is True
    return case, auth_temp, tx_temp, recovery_temp, source


def _cleanup_source(items) -> None:
    case, auth_temp, tx_temp, recovery_temp, _source = items
    recovery_temp.cleanup()
    tx_temp.cleanup()
    auth_temp.cleanup()
    _cleanup_case(case)


def _policy(
    source,
    *,
    base_branch: str | None = None,
    completion_sources: tuple[str, ...] = ("recovery", "transaction"),
    source_actions: tuple[str, ...] = (
        "create_missing_release",
        "execute_exact_release",
        "finalize_existing_state",
    ),
):
    return deploy_ready.PilotExactTaskDeployReadinessPolicy(
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment="staging",
        deployment_base_branch=(
            source.release_base_branch if base_branch is None else base_branch
        ),
        allowed_completion_sources=completion_sources,
        allowed_source_actions=source_actions,
    )


class _Transport:
    def __init__(
        self,
        source,
        *,
        release_id: int | None = None,
        node_hash: str | None = None,
        state_class: str = "exact_existing",
        scripted: list[str] | None = None,
    ):
        self.source = source
        self.credential_config_sha256 = source.publisher_credential_config_sha256
        self.credential_path_sha256 = source.publisher_credential_path_sha256
        self.release_id = source.release_id if release_id is None else release_id
        self.node_hash = (
            source.release_node_id_sha256 if node_hash is None else node_hash
        )
        self.state_class = state_class
        self.scripted = list(scripted or ())
        self.calls = 0

    def _state(self, state_class: str):
        if state_class == "clear":
            return recovery._ReleaseRecoveryRemoteState(
                repository=self.source.repository,
                repository_id=self.source.repository_id,
                tag_state="absent",
                tag_target_sha=None,
                release_state="absent",
                release_id=None,
                release_node_id_sha256=None,
                remote_state_class="clear",
            )
        if state_class != "exact_existing":
            raise AssertionError("unsupported deploy-readiness test state")
        return recovery._ReleaseRecoveryRemoteState(
            repository=self.source.repository,
            repository_id=self.source.repository_id,
            tag_state="exact",
            tag_target_sha=self.source.tag_target_sha,
            release_state="exact-draft",
            release_id=self.release_id,
            release_node_id_sha256=self.node_hash,
            remote_state_class="exact_existing",
        )

    def observe(self, source):
        self.calls += 1
        assert source.sha256 == self.source.sha256
        state_class = self.scripted.pop(0) if self.scripted else self.state_class
        return self._state(state_class)


def _evaluate(source, policy, transport, *, now="2026-09-15T09:47:00Z"):
    return deploy_ready._evaluate_verified_pilot_exact_task_deploy_readiness(
        post_release_attestation=source,
        policy=policy,
        policy_sha256=policy.sha256,
        transport=transport,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    items = _live_source()
    source = items[-1]
    try:
        policy = _policy(source)
        transport = _Transport(source)
        receipt = _evaluate(source, policy, transport)
        assert receipt.evaluation_authenticated is True
        assert receipt.post_release_attestation_sha256 == source.sha256
        assert receipt.deploy_readiness_policy_sha256 == policy.sha256
        assert receipt.deployment_environment == "staging"
        assert receipt.release_base_branch == source.release_base_branch
        assert receipt.deployment_base_branch == source.release_base_branch
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.tag_target_sha == source.merge_commit_sha
        assert receipt.release_id == source.release_id
        assert receipt.release_node_id_sha256 == source.release_node_id_sha256
        assert receipt.blocker_codes == ()
        assert receipt.base_branch_policy_satisfied is True
        assert receipt.completion_source_policy_satisfied is True
        assert receipt.source_action_policy_satisfied is True
        assert receipt.exact_tag_target_satisfied is True
        assert receipt.exact_draft_release_satisfied is True
        assert receipt.zero_release_assets_satisfied is True
        assert receipt.deploy_ready is True
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert transport.calls == 2

        reloaded = (
            deploy_ready.PilotExactTaskDeployReadinessEvaluationReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert reloaded == receipt
        assert reloaded.evaluation_authenticated is False

        base_policy = _policy(source, base_branch="release-candidate")
        negative = _evaluate(
            source,
            base_policy,
            _Transport(source),
            now="2026-09-15T09:47:01Z",
        )
        assert negative.deploy_ready is False
        assert negative.blocker_codes == ("base-branch-not-deployment-target",)

        completion_policy = _policy(source, completion_sources=("recovery",))
        completion_negative = _evaluate(
            source,
            completion_policy,
            _Transport(source),
            now="2026-09-15T09:47:02Z",
        )
        assert completion_negative.deploy_ready is False
        assert completion_negative.blocker_codes == (
            "completion-source-not-deployment-approved",
        )

        action_policy = _policy(
            source,
            source_actions=("finalize_existing_state",),
        )
        action_negative = _evaluate(
            source,
            action_policy,
            _Transport(source),
            now="2026-09-15T09:47:03Z",
        )
        assert action_negative.deploy_ready is False
        assert action_negative.blocker_codes == (
            "completion-action-not-deployment-approved",
        )

        stale_source = (
            post_release.PilotExactTaskPostReleaseAttestationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert stale_source.attestation_authenticated is False
        _reject(lambda: _evaluate(stale_source, policy, _Transport(source)))

        bad_repo = deploy_ready.PilotExactTaskDeployReadinessPolicy(
            repository="other/repo",
            repository_id=source.repository_id,
            deployment_environment="staging",
            deployment_base_branch=source.release_base_branch,
        )
        _reject(
            lambda: deploy_ready._evaluate_verified_pilot_exact_task_deploy_readiness(
                post_release_attestation=source,
                policy=bad_repo,
                policy_sha256=bad_repo.sha256,
                transport=_Transport(source),
                now_provider=lambda: "2026-09-15T09:47:04Z",
            )
        )
        _reject(
            lambda: deploy_ready._evaluate_verified_pilot_exact_task_deploy_readiness(
                post_release_attestation=source,
                policy=policy,
                policy_sha256="9" * 64,
                transport=_Transport(source),
                now_provider=lambda: "2026-09-15T09:47:04Z",
            )
        )

        cred = _Transport(source)
        cred.credential_path_sha256 = "8" * 64
        _reject(lambda: _evaluate(source, policy, cred))
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source, release_id=source.release_id + 1),
            )
        )
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source, node_hash="e" * 64),
            )
        )
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source, scripted=["exact_existing", "clear"]),
            )
        )
        _reject(
            lambda: _evaluate(
                source,
                policy,
                _Transport(source),
                now="2026-09-15T09:45:00Z",
            )
        )

        _reject(
            lambda: deploy_ready.PilotExactTaskDeployReadinessPolicy(
                repository=source.repository,
                repository_id=source.repository_id,
                deployment_environment="production",
                deployment_base_branch=source.release_base_branch,
            )
        )
        _reject(
            lambda: deploy_ready.PilotExactTaskDeployReadinessPolicy(
                repository=source.repository,
                repository_id=source.repository_id,
                deployment_environment="staging",
                deployment_base_branch=source.release_base_branch,
                require_exact_draft_release=False,
            )
        )

        for field, value in (
            ("post_release_attestation_authenticated", False),
            ("deploy_readiness_policy_host_pinned", False),
            ("exact_remote_release_revalidated", False),
            ("double_observation_matched", False),
            ("exact_tag_target_satisfied", False),
            ("exact_draft_release_satisfied", False),
            ("zero_release_assets_satisfied", False),
            ("deploy_readiness_evaluated", False),
            ("deploy_readiness_authorized", True),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("release_authorized", True),
            ("remote_write_authorized", True),
            ("merge_authorized", True),
            ("push_authorized", True),
            ("pr_mutation_authorized", True),
            ("review_submission_authorized", True),
            ("review_thread_mutation_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    deploy_ready.PilotExactTaskDeployReadinessEvaluationReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            deploy_ready.PilotExactTaskDeployReadinessEvaluationReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 70

        signature = inspect.signature(
            deploy_ready.evaluate_pilot_exact_task_deploy_readiness
        )
        assert list(signature.parameters) == ["post_release_attestation"]

        source_text = code_of(SOURCE)
        assert 'method="POST"' not in source_text
        assert 'method="PUT"' not in source_text
        assert 'method="PATCH"' not in source_text
        assert 'method="DELETE"' not in source_text
        assert "create_tag(" not in source_text
        assert "create_release(" not in source_text
        assert "/deployments" not in source_text
        assert "create_deployment" not in source_text
        assert "merge_pull_request" not in source_text
        assert "enable_auto_merge" not in source_text
    finally:
        _cleanup_source(items)


if __name__ == "__main__":
    run_contract()

"""Adversarial contract for ADR-DC-064 deterministic exact release plan."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_plan as release_plan,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_release_readiness_evaluation as release_readiness,
)
from rsi_pilot_exact_task_post_merge_attestation_contract import (  # noqa: E402
    _attest,
    _cleanup_case,
    _normal_completion,
)
from rsi_pilot_exact_task_release_readiness_evaluation_contract import (  # noqa: E402
    _Transport,
    _evaluate,
    _policy,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-release-plan-v1.schema.json"
)
SOURCE = (
    ROOT
    / "devcontrol"
    / "src"
    / "kaliv_dev_control"
    / "improvement_pilot_exact_task_release_plan.py"
)


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-064 unexpectedly accepted unsafe release intent")


def _config(source, **overrides):
    values = {
        "repository": source.repository,
        "repository_id": source.repository_id,
    }
    values.update(overrides)
    return release_plan.PilotExactTaskReleasePlanConfig(**values)


def _plan(source, config, *, now="2026-09-15T09:43:00Z", digest=None):
    return release_plan._materialize_verified_pilot_exact_task_release_plan(
        release_readiness_evaluation=source,
        config=config,
        config_sha256=digest or config.sha256,
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
        post_merge = _attest(
            authorization,
            tx_temp,
            auth_temp,
            recovery_temp,
            observer,
        )
        readiness_policy = _policy(post_merge)
        readiness = _evaluate(
            post_merge,
            readiness_policy,
            _Transport(post_merge),
        )
        assert readiness.evaluation_authenticated is True
        assert readiness.release_ready is True
        assert readiness.blocker_codes == ()

        config = _config(readiness)
        receipt = _plan(readiness, config)
        assert receipt.plan_authenticated is True
        assert receipt.release_readiness_evaluation_sha256 == readiness.sha256
        assert receipt.post_merge_attestation_sha256 == readiness.post_merge_attestation_sha256
        assert receipt.release_readiness_policy_sha256 == readiness.release_readiness_policy_sha256
        assert receipt.release_plan_config_sha256 == config.sha256
        assert receipt.execution_nonce_sha256 == readiness.execution_nonce_sha256
        assert receipt.development_task_sha256 == readiness.development_task_sha256
        assert receipt.candidate_patch_sha256 == readiness.candidate_patch_sha256
        assert receipt.pr_intent_sha256 == readiness.pr_intent_sha256
        assert receipt.transaction_lock_sha256 == readiness.transaction_lock_sha256
        assert receipt.repository == readiness.repository
        assert receipt.repository_id == readiness.repository_id
        assert receipt.release_base_branch == readiness.release_base_branch
        assert receipt.merge_commit_sha == readiness.merge_commit_sha
        assert receipt.release_version == f"rsi-{readiness.merge_commit_sha}"
        assert receipt.tag_name == f"modelrig-rsi-{readiness.merge_commit_sha}"
        assert receipt.tag_target_sha == readiness.merge_commit_sha
        assert receipt.release_name == f"ModelRig RSI {readiness.merge_commit_sha[:12]}"
        assert receipt.release_body_sha256 == hashlib.sha256(
            receipt.release_body.encode("utf-8")
        ).hexdigest()
        assert readiness.sha256 in receipt.release_body
        assert readiness.merge_commit_sha in receipt.release_body
        assert receipt.release_draft is True
        assert receipt.release_prerelease is True
        assert receipt.make_latest is False
        assert receipt.release_readiness_authenticated is True
        assert receipt.release_ready is True
        assert receipt.release_plan_config_host_pinned is True
        assert receipt.release_intent_materialized is True
        assert receipt.tag_creation_planned is True
        assert receipt.github_release_creation_planned is True
        assert receipt.tag_write_authorized is False
        assert receipt.release_mutation_authorized is False
        assert receipt.release_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.merge_authorized is False
        assert receipt.deploy_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        expected_intent = release_plan._release_intent_sha256_fields(
            release_readiness_evaluation_sha256=receipt.release_readiness_evaluation_sha256,
            post_merge_attestation_sha256=receipt.post_merge_attestation_sha256,
            release_readiness_policy_sha256=receipt.release_readiness_policy_sha256,
            release_plan_config_sha256=receipt.release_plan_config_sha256,
            execution_nonce_sha256=receipt.execution_nonce_sha256,
            development_task_sha256=receipt.development_task_sha256,
            candidate_patch_sha256=receipt.candidate_patch_sha256,
            pr_intent_sha256=receipt.pr_intent_sha256,
            transaction_lock_sha256=receipt.transaction_lock_sha256,
            repository=receipt.repository,
            repository_id=receipt.repository_id,
            release_base_branch=receipt.release_base_branch,
            merge_commit_sha=receipt.merge_commit_sha,
            release_version=receipt.release_version,
            tag_name=receipt.tag_name,
            tag_target_sha=receipt.tag_target_sha,
            release_name=receipt.release_name,
            release_body=receipt.release_body,
        )
        assert receipt.release_intent_sha256 == expected_intent

        reloaded = release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
            receipt.to_dict()
        )
        assert reloaded == receipt
        assert reloaded.plan_authenticated is False

        reloaded_readiness = (
            release_readiness.PilotExactTaskReleaseReadinessEvaluationReceipt.from_mapping(
                readiness.to_dict()
            )
        )
        assert reloaded_readiness.evaluation_authenticated is False
        _reject(lambda: _plan(reloaded_readiness, config))

        moved_sha = "f" * 40
        if moved_sha in {
            post_merge.merge_commit_sha,
            post_merge.authorized_base_sha,
            post_merge.head_sha,
        }:
            moved_sha = "e" * 40
        blocked = _evaluate(
            post_merge,
            readiness_policy,
            _Transport(post_merge, current_base_sha=moved_sha),
        )
        assert blocked.release_ready is False
        assert blocked.blocker_codes == ("merge-commit-not-current-base-head",)
        _reject(lambda: _plan(blocked, _config(blocked)))

        _reject(lambda: _plan(readiness, config, digest="8" * 64))
        other_config = release_plan.PilotExactTaskReleasePlanConfig(
            repository="example/other",
            repository_id=readiness.repository_id,
        )
        _reject(lambda: _plan(readiness, other_config))

        canonical = config.canonical_json().encode("utf-8")
        parsed = release_plan._parse_config(canonical)
        assert parsed == config
        _reject(lambda: release_plan._parse_config(canonical + b"\n"))
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                release_draft=False,
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                release_prerelease=False,
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                make_latest=True,
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanConfig(
                repository=readiness.repository,
                repository_id=readiness.repository_id,
                version_scheme="semver-v1",
            )
        )

        _reject(
            lambda: _plan(
                readiness,
                config,
                now="2026-09-15T09:41:59Z",
            )
        )

        for field, value in (
            ("release_readiness_authenticated", False),
            ("release_ready", False),
            ("release_plan_config_host_pinned", False),
            ("release_intent_materialized", False),
            ("tag_creation_planned", False),
            ("github_release_creation_planned", False),
            ("tag_write_authorized", True),
            ("release_mutation_authorized", True),
            ("release_authorized", True),
            ("remote_write_authorized", True),
            ("merge_authorized", True),
            ("deploy_authorized", True),
            ("production_activation_authorized", True),
            ("product_pilot_started", True),
            ("nonce_reusable", True),
        ):
            _reject(
                lambda field=field, value=value: (
                    release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                        {**receipt.to_dict(), field: value}
                    )
                )
            )

        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                {**receipt.to_dict(), "tag_name": "caller-controlled-tag"}
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                {**receipt.to_dict(), "release_version": "1.2.3"}
            )
        )
        mutated_body = receipt.release_body + "\ncaller mutation"
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                {
                    **receipt.to_dict(),
                    "release_body": mutated_body,
                    "release_body_sha256": hashlib.sha256(
                        mutated_body.encode("utf-8")
                    ).hexdigest(),
                }
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                {**receipt.to_dict(), "release_intent_sha256": "7" * 64}
            )
        )
        _reject(
            lambda: release_plan.PilotExactTaskReleasePlanReceipt.from_mapping(
                {**receipt.to_dict(), "post_merge_attestation_sha256": "6" * 64}
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        receipt_fields = set(
            release_plan.PilotExactTaskReleasePlanReceipt.__dataclass_fields__
        )
        assert set(schema["properties"]) == receipt_fields
        assert set(schema["required"]) == receipt_fields
        assert len(receipt_fields) == 43
        assert schema["properties"]["release_draft"]["const"] is True
        assert schema["properties"]["release_prerelease"]["const"] is True
        assert schema["properties"]["make_latest"]["const"] is False
        assert schema["properties"]["release_authorized"]["const"] is False
        assert schema["properties"]["deploy_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        signature = inspect.signature(
            release_plan.materialize_pilot_exact_task_release_plan
        )
        assert list(signature.parameters) == ["release_readiness_evaluation"]

        source_text = SOURCE.read_text(encoding="utf-8")
        assert "urllib" not in source_text
        assert "subprocess" not in source_text
        assert "requests" not in source_text
        assert "httpx" not in source_text
        assert "create_release" not in source_text
        assert "create_git_tag" not in source_text
        assert "create_ref" not in source_text
        assert "git push" not in source_text
        assert "Ed25519PrivateKey" not in source_text
    finally:
        _cleanup_case(case)


if __name__ == "__main__":
    run_contract()

"""Adversarial contract for ADR-DC-067 host-pinned reviewer target attestation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_handoff_requirements as handoff  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_target_attestation as target  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_reviewer_target_attestation_impl as impl  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_pr_reviewer_target_attestation_production_boundary as production  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_handoff_requirements_contract import (  # noqa: E402
    _live_ready_transaction,
    _reader,
)

POLICY_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-reviewer-target-policy-v1.schema.json"
ATTESTATION_SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-reviewer-target-attestation-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (
        target.PilotExactTaskPrReviewerTargetAttestationError,
        production.PilotExactTaskPrReviewerTargetAttestationProductionBoundaryError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-067 unexpectedly accepted unsafe reviewer target")


def _live_handoff():
    tx, _requirements, cleanup = _live_ready_transaction()
    result = handoff._materialize_verified_pilot_exact_task_pr_reviewer_handoff_requirements(
        ready_transaction=tx,
        reader=_reader,
        now_provider=lambda: "2026-09-15T06:25:10Z",
    )
    assert result.requirements_authenticated is True
    return result, cleanup


def run_contract() -> None:
    if os.name == "nt":
        return

    requirements, cleanup = _live_handoff()
    try:
        policy = target.PilotExactTaskPrReviewerTargetPolicy(
            policy_epoch=1,
            reviewer_login="modelrig-reviewer",
            reviewer_user_id=246813579,
        )
        result = target._attest_verified_pilot_exact_task_pr_reviewer_target(
            reviewer_handoff_requirements=requirements,
            reviewer_target_policy=policy,
            now_provider=lambda: "2026-09-15T06:25:11Z",
        )
        assert result.attestation_authenticated is True
        assert result.reviewer_handoff_requirements_sha256 == requirements.sha256
        assert result.ready_transaction_sha256 == requirements.ready_transaction_sha256
        assert result.predicted_commit_sha == requirements.predicted_commit_sha
        assert result.reviewer_handoff_plan_sha256 == requirements.reviewer_handoff_plan_sha256
        assert result.required_reviewer_authorizer_actor_id == requirements.required_reviewer_authorizer_actor_id
        assert result.pull_request_number == requirements.pull_request_number
        assert result.pull_request_node_id_sha256 == requirements.pull_request_node_id_sha256
        assert result.ready_updated_at_utc == requirements.ready_updated_at_utc
        assert result.reviewer_target_policy_sha256 == policy.sha256
        assert result.reviewer_target_policy_epoch == 1
        assert result.reviewer_provider == "github"
        assert result.reviewer_kind == "user"
        assert result.reviewer_login == "modelrig-reviewer"
        assert result.reviewer_user_id == 246813579
        assert result.attested_at_utc == "2026-09-15T06:25:11Z"

        for field in (
            "reviewer_target_host_pinned",
            "exactly_one_reviewer_required",
            "reviewer_identity_observation_required",
            "reviewer_requestability_observation_required",
            "separate_human_reviewer_authorization_required",
            "one_shot_reviewer_request_nonce_required",
            "fresh_pr_state_revalidation_before_reviewer_request_required",
            "reviewer_request_transaction_required",
            "team_reviewers_forbidden",
            "self_review_forbidden",
            "label_mutation_separate_authority_required",
            "merge_separate_authority_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_mutation_authorized",
            "reviewer_request_performed",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        reloaded = target.PilotExactTaskPrReviewerTargetAttestation.from_mapping(serialized)
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.attestation_authenticated is False

        reloaded_requirements = handoff.PilotExactTaskPrReviewerHandoffRequirements.from_mapping(
            requirements.to_dict()
        )
        assert reloaded_requirements.requirements_authenticated is False
        _reject(lambda: target._require_live_requirements(reloaded_requirements))

        _reject(lambda: target.PilotExactTaskPrReviewerTargetPolicy(
            policy_epoch=1,
            reviewer_login="bad reviewer",
            reviewer_user_id=1,
        ))
        _reject(lambda: target.PilotExactTaskPrReviewerTargetPolicy(
            policy_epoch=1,
            reviewer_login="modelrig-reviewer",
            reviewer_user_id=246813579,
            team_reviewers_forbidden=False,
        ))
        _reject(lambda: target.PilotExactTaskPrReviewerTargetPolicy(
            policy_epoch=1,
            reviewer_login="modelrig-reviewer",
            reviewer_user_id=246813579,
            reviewer_requestability_observation_required=False,
        ))

        with TemporaryDirectory(prefix="rsi-reviewer-target-policy-067-") as tmp:
            path = Path(tmp) / "policy.json"
            path.write_bytes(policy.canonical_json().encode("utf-8"))
            loaded = production._load_reviewer_policy_at(
                impl,
                path,
                require_host_control=False,
            )
            assert loaded == policy
            path.write_bytes(policy.canonical_json().encode("utf-8") + b"\n")
            _reject(lambda: production._load_reviewer_policy_at(
                impl,
                path,
                require_host_control=False,
            ))

        assert list(inspect.signature(
            target.attest_pilot_exact_task_pr_reviewer_target
        ).parameters) == ["reviewer_handoff_requirements"]
        source = inspect.getsource(impl) + inspect.getsource(production)
        for forbidden in (
            "urllib.request",
            "requests.",
            "subprocess",
            "request_pull_request_reviewers",
            "mark_pull_request_ready_for_review",
            "merge_pull_request",
        ):
            assert forbidden not in source

        policy_schema = json.loads(POLICY_SCHEMA.read_text(encoding="utf-8"))
        attestation_schema = json.loads(ATTESTATION_SCHEMA.read_text(encoding="utf-8"))
        assert set(policy_schema["properties"]) == set(
            target.PilotExactTaskPrReviewerTargetPolicy.__dataclass_fields__
        )
        assert set(policy_schema["required"]) == set(policy_schema["properties"])
        assert set(attestation_schema["properties"]) == set(
            target.PilotExactTaskPrReviewerTargetAttestation.__dataclass_fields__
        )
        assert set(attestation_schema["required"]) == set(attestation_schema["properties"])
    finally:
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()

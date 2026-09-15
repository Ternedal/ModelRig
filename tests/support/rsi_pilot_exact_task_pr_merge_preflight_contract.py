"""Adversarial contract for ADR-DC-080 fresh semantic merge preflight."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path:
        sys.path.insert(0, str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_merge_preflight as preflight  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_disposition as disposition  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_observation as observation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_observation_checkpoint as checkpoint_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_transaction as transaction_boundary  # noqa: E402
import rsi_pilot_exact_task_pr_review_disposition_contract as parent  # noqa: E402
import rsi_pilot_exact_task_pr_submitted_review_observation_contract as review_parent  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_request_attestation_contract as attestation_parent  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_write_transaction_contract as write_parent  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-merge-preflight-v1.schema.json"
UPDATED = "2026-09-15T06:25:50Z"


def _reject(fn) -> None:
    try:
        fn()
    except (
        preflight.PilotExactTaskPrMergePreflightError,
        disposition.PilotExactTaskPrReviewDispositionError,
        observation.PilotExactTaskPrSubmittedReviewObservationError,
        checkpoint_boundary.PilotExactTaskPrReviewObservationCheckpointError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-080 unexpectedly accepted unsafe merge preflight")


def _semantic_artifact(capability):
    assert capability.capability_authenticated is True
    (
        checked_capability,
        _reviewer_preflight,
        _precondition,
        _reservation,
        _target,
        requirements,
        _descriptor,
    ) = transaction_boundary._require_live_capability(capability)
    assert checked_capability is capability
    assert requirements.requirements_authenticated is True
    return requirements.to_dict()


def _approved_chain():
    # Keep the ADR-074 capability strongly reachable while materializing ADR-075
    # and ADR-076. ADR-075 deliberately stores only a weak capability reference;
    # relying on the older ADR-076 helper's temporary local would make this new
    # fixture GC-sensitive rather than proving the production provenance chain.
    capability, _broker_path, _broker_raw, write_temp, parent_temp, cleanup = (
        write_parent._live_capability()
    )
    semantic = _semantic_artifact(capability)

    tx_ledger = TemporaryDirectory(prefix="rsi-merge-preflight-080-tx-")
    broker_calls = []
    transaction = write_parent._execute(
        capability,
        transaction_boundary._TransactionLedger(Path(tx_ledger.name)),
        broker_calls,
    )
    assert transaction.transaction_authenticated is True
    assert len(broker_calls) == 1

    reader, attestation_calls = attestation_parent._reader(transaction)
    source = attestation_parent._attest(transaction, reader)
    assert source.attestation_authenticated is True
    assert len(attestation_calls) == 2

    ledger_temp = TemporaryDirectory(prefix="rsi-merge-preflight-080-checkpoint-")
    ledger = checkpoint_boundary._ReviewObservationCheckpointLedger(
        Path(ledger_temp.name),
        require_host_control=False,
    )
    checkpoint = checkpoint_boundary._checkpoint_verified_pilot_exact_task_pr_review_observation(
        reviewer_request_attestation=source,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:25:46Z",
    )
    assert checkpoint.checkpoint_authenticated is True
    assert hashlib.sha256(
        json.dumps(
            semantic,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest() == checkpoint.reviewer_handoff_requirements_sha256

    # Simulate the real restart boundary: old write/attestation provenance is no
    # longer required after the host-controlled ADR-077 checkpoint exists.
    checkpoint_boundary._live_records.clear()
    attestation_boundary._implementation._live_records.clear()
    transaction_boundary._implementation._live_records.clear()
    loaded = ledger.load(checkpoint.checkpoint_key_sha256)
    assert loaded.checkpoint_authenticated is True

    reviews = [
        review_parent._review(
            loaded,
            review_id=10080,
            node_id="PRR_080_APPROVED",
            state="APPROVED",
            submitted_at="2026-09-15T06:25:47Z",
        )
    ]
    review_observation = review_parent._observe(
        loaded,
        review_parent._stable_transport(loaded, reviews, requested=False),
    )
    assert review_observation.observation_authenticated is True
    approved = disposition._evaluate_verified_pilot_exact_task_pr_review_disposition(
        submitted_review_observation=review_observation,
        now_provider=lambda: "2026-09-15T06:25:50Z",
    )
    assert approved.disposition_authenticated is True
    assert approved.review_disposition == "APPROVED"
    return (
        approved,
        review_observation,
        loaded,
        semantic,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    )


def _pr_document(checkpoint, semantic, *, title=None, body=None, head_sha=None, node_id=None,
                 maintainer_can_modify=False, reviewers=None, updated_at=UPDATED):
    if reviewers is None:
        reviewers = []
    return {
        "number": checkpoint.pull_request_number,
        "node_id": review_parent.PR_NODE_ID if node_id is None else node_id,
        "url": checkpoint.pull_request_api_url,
        "html_url": checkpoint.pull_request_html_url,
        "state": "open",
        "closed_at": None,
        "merged_at": None,
        "draft": False,
        "title": semantic["pr_title"] if title is None else title,
        "body": semantic["pr_body"] if body is None else body,
        "maintainer_can_modify": maintainer_can_modify,
        "updated_at": updated_at,
        "user": {
            "login": checkpoint.pull_request_author_login,
            "id": checkpoint.pull_request_author_user_id,
        },
        "requested_reviewers": reviewers,
        "requested_teams": [],
        "head": {
            "ref": checkpoint.head_branch,
            "sha": checkpoint.predicted_commit_sha if head_sha is None else head_sha,
            "repo": {"full_name": checkpoint.repository},
        },
        "base": {
            "ref": checkpoint.base_branch,
            "repo": {"full_name": checkpoint.repository},
        },
    }


def _transport(checkpoint, semantic, *, first=None, second=None, requested=False):
    reviewer = {
        "login": checkpoint.reviewer_login,
        "id": checkpoint.reviewer_user_id,
        "node_id": review_parent.REVIEWER_NODE_ID,
    }
    default = _pr_document(
        checkpoint,
        semantic,
        reviewers=[reviewer] if requested else [],
    )
    first_doc = default if first is None else first
    second_doc = first_doc if second is None else second
    return review_parent._Transport(
        [
            review_parent._response(first_doc, etag='W/"merge-preflight-080"'),
            review_parent._response(second_doc, etag='W/"merge-preflight-080"'),
        ]
    )


def _run(value, semantic, transport, times=("2026-09-15T06:25:51Z", "2026-09-15T06:25:52Z")):
    clock = iter(times)
    return preflight._preflight_verified_pilot_exact_task_pr_merge(
        review_disposition=value,
        semantic_requirements_artifact=semantic,
        transport=transport,
        now_provider=clock.__next__,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    (
        approved,
        review_observation,
        checkpoint,
        semantic,
        ledger_temp,
        tx_ledger,
        write_temp,
        parent_temp,
        cleanup,
    ) = _approved_chain()
    try:
        result = _run(
            approved,
            semantic,
            _transport(checkpoint, semantic, requested=False),
        )
        assert result.preflight_authenticated is True
        assert result.review_disposition_sha256 == approved.sha256
        assert result.submitted_review_observation_sha256 == review_observation.sha256
        assert result.review_observation_checkpoint_sha256 == checkpoint.sha256
        assert result.reviewer_handoff_requirements_sha256 == checkpoint.reviewer_handoff_requirements_sha256
        assert result.semantic_pr_title_sha256 == hashlib.sha256(semantic["pr_title"].encode("utf-8")).hexdigest()
        assert result.semantic_pr_body_sha256 == hashlib.sha256(semantic["pr_body"].encode("utf-8")).hexdigest()
        assert result.review_disposition == "APPROVED"
        assert result.requested_reviewer_count == 0
        assert result.requested_team_count == 0
        assert result.pinned_reviewer_request_present is False
        assert result.first_response_body_sha256 == result.second_response_body_sha256
        assert result.first_response_etag_sha256 == result.second_response_etag_sha256
        assert result.observed_updated_at_utc == UPDATED

        for field in (
            "source_review_disposition_verified",
            "source_exact_head_approval_verified",
            "semantic_requirements_replay_verified",
            "semantic_metadata_policy_restored",
            "semantic_metadata_verified",
            "maintainer_can_modify_false_verified",
            "exact_pr_identity_revalidated",
            "exact_head_revalidated",
            "exact_base_revalidated",
            "exact_author_revalidated",
            "open_ready_state_revalidated",
            "requested_reviewer_shape_revalidated",
            "stable_double_observation_verified",
            "credential_free_reads",
            "fixed_origin_reads",
            "redirects_forbidden",
            "response_bounded",
            "fresh_review_disposition_age_verified",
            "metadata_and_review_preflight_passed",
            "fresh_review_reobservation_before_merge_required",
            "required_status_checks_preflight_required",
            "review_threads_preflight_required",
            "branch_policy_preflight_required",
            "fresh_merge_transaction_revalidation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        retained = _run(
            approved,
            semantic,
            _transport(checkpoint, semantic, requested=True),
        )
        assert retained.requested_reviewer_count == 1
        assert retained.pinned_reviewer_request_present is True

        replayed = preflight.PilotExactTaskPrMergePreflight.from_mapping(result.to_dict())
        assert replayed == result and replayed.sha256 == result.sha256
        assert replayed.preflight_authenticated is False

        loose_disposition = disposition.PilotExactTaskPrReviewDisposition.from_mapping(approved.to_dict())
        assert loose_disposition.disposition_authenticated is False
        _reject(lambda: _run(
            loose_disposition,
            semantic,
            _transport(checkpoint, semantic),
        ))

        tampered_semantic = dict(semantic)
        tampered_semantic["pr_body"] = semantic["pr_body"] + "\nunauthorized"
        _reject(lambda: _run(
            approved,
            tampered_semantic,
            _transport(checkpoint, semantic),
        ))

        _reject(lambda: _run(
            approved,
            semantic,
            _transport(checkpoint, semantic),
            times=("2026-09-15T06:26:01Z", "2026-09-15T06:26:02Z"),
        ))

        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, title="drifted title"),
            ),
        ))
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, body="drifted body"),
            ),
        ))
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, maintainer_can_modify=True),
            ),
        ))
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, head_sha="1" * 40),
            ),
        ))
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, node_id="PR_wrong_080"),
            ),
        ))

        foreign = [{
            "login": "someone-else",
            "id": checkpoint.reviewer_user_id + 1,
            "node_id": "U_foreign_080",
        }]
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(
                checkpoint,
                semantic,
                first=_pr_document(checkpoint, semantic, reviewers=foreign),
            ),
        ))

        first = _pr_document(checkpoint, semantic, updated_at=UPDATED)
        second = _pr_document(checkpoint, semantic, updated_at="2026-09-15T06:25:51Z")
        _reject(lambda: _run(
            approved,
            semantic,
            _transport(checkpoint, semantic, first=first, second=second),
        ))

        tampered_receipt = result.to_dict()
        tampered_receipt["second_response_body_sha256"] = "1" * 64
        _reject(lambda: preflight.PilotExactTaskPrMergePreflight.from_mapping(tampered_receipt))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(preflight.PilotExactTaskPrMergePreflight.__dataclass_fields__)
        assert len(fields) == 71
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["metadata_and_review_preflight_passed"]["const"] is True
        assert schema["properties"]["fresh_review_reobservation_before_merge_required"]["const"] is True
        assert schema["properties"]["required_status_checks_preflight_required"]["const"] is True
        assert schema["properties"]["review_threads_preflight_required"]["const"] is True
        assert schema["properties"]["branch_policy_preflight_required"]["const"] is True
        assert schema["properties"]["merge_readiness_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(preflight.preflight_pilot_exact_task_pr_merge).parameters
        ) == ("review_disposition", "semantic_requirements_artifact")
        source = inspect.getsource(preflight)
        assert "UrllibReadOnlyTransport" in source
        assert "maintainer_can_modify" in source
        for forbidden in (
            'method="POST"',
            "run_bounded_subprocess",
            "request_pull_request_reviewers",
            "add_review_to_pr",
            "resolve_review_thread",
            "merge_pull_request(",
            "label_pr(",
            "enable_auto_merge",
        ):
            assert forbidden not in source
    finally:
        ledger_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()

"""Adversarial contract for ADR-DC-077 restart-safe review-observation checkpoint."""
from __future__ import annotations

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

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_observation_checkpoint as checkpoint  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_request_attestation_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-review-observation-checkpoint-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        checkpoint.PilotExactTaskPrReviewObservationCheckpointError,
        attestation.PilotExactTaskPrReviewerRequestAttestationError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-077 unexpectedly accepted unsafe checkpoint state")


def _live_attestation():
    transaction, tx_ledger, write_temp, parent_temp, cleanup = parent._live_transaction()
    reader, calls = parent._reader(transaction)
    value = parent._attest(transaction, reader)
    assert value.attestation_authenticated is True
    assert len(calls) == 2
    return value, tx_ledger, write_temp, parent_temp, cleanup


def _checkpoint(value, ledger):
    return checkpoint._checkpoint_verified_pilot_exact_task_pr_review_observation(
        reviewer_request_attestation=value,
        ledger=ledger,
        now_provider=lambda: "2026-09-15T06:25:46Z",
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    source, tx_ledger, write_temp, parent_temp, cleanup = _live_attestation()
    ledger_temp = TemporaryDirectory(prefix="rsi-review-checkpoint-077-")
    other_temp = TemporaryDirectory(prefix="rsi-review-checkpoint-077-other-")
    try:
        ledger = checkpoint._ReviewObservationCheckpointLedger(
            Path(ledger_temp.name),
            require_host_control=False,
        )
        result = _checkpoint(source, ledger)

        assert result.checkpoint_authenticated is True
        assert result.checkpoint_key_sha256 == source.sha256
        assert result.source_reviewer_request_attestation_sha256 == source.sha256
        assert result.reviewer_write_transaction_sha256 == source.reviewer_write_transaction_sha256
        assert result.reviewer_request_nonce_sha256 == source.reviewer_request_nonce_sha256
        assert result.pull_request_number == source.pull_request_number
        assert result.predicted_commit_sha == source.predicted_commit_sha
        assert result.reviewer_login == source.reviewer_login
        assert result.reviewer_user_id == source.reviewer_user_id
        assert result.source_second_observed_at_utc == source.second_observed_at_utc

        for field in (
            "source_attestation_verified",
            "durable_checkpoint_committed",
            "restart_safe_reauthentication_supported",
            "exact_pr_identity_bound",
            "exact_head_sha_bound",
            "exact_reviewer_identity_bound",
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "future_review_observation_must_revalidate_exact_pr",
            "submitted_reviews_read_only_observation_only",
            "reviewer_request_nonce_consumed",
            "observation_checkpoint_reusable",
        ):
            assert getattr(result, field) is True

        for field in (
            "credential_material_in_artifact",
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

        reloaded = checkpoint.PilotExactTaskPrReviewObservationCheckpoint.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.checkpoint_authenticated is False

        _reject(lambda: _checkpoint(source, ledger))
        _reject(
            lambda: checkpoint._require_checkpoint_window(
                source,
                at_utc="2026-09-15T06:26:46Z",
            )
        )

        checkpoint._live_records.clear()
        attestation._implementation._live_records.clear()
        loaded = ledger.load(result.checkpoint_key_sha256)
        assert loaded == result
        assert loaded.checkpoint_authenticated is True
        assert loaded.source_reviewer_request_attestation_sha256 == source.sha256

        other = checkpoint._ReviewObservationCheckpointLedger(
            Path(other_temp.name),
            require_host_control=False,
        )
        _reject(lambda: other.load(result.checkpoint_key_sha256))

        path = ledger._path(result.checkpoint_key_sha256)
        original = path.read_bytes()
        path.write_bytes(original + b"\n")
        _reject(lambda: ledger.load(result.checkpoint_key_sha256))
        assert loaded.checkpoint_authenticated is False
        path.write_bytes(original)
        path.chmod(0o600)
        loaded_again = ledger.load(result.checkpoint_key_sha256)
        assert loaded_again.checkpoint_authenticated is True

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            checkpoint.PilotExactTaskPrReviewObservationCheckpoint.__dataclass_fields__
        )
        assert len(fields) == 59
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["durable_checkpoint_committed"]["const"] is True
        assert schema["properties"]["observation_checkpoint_reusable"]["const"] is True
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                checkpoint.checkpoint_pilot_exact_task_pr_review_observation
            ).parameters
        ) == ("reviewer_request_attestation",)
        assert tuple(
            inspect.signature(
                checkpoint.load_pilot_exact_task_pr_review_observation_checkpoint
            ).parameters
        ) == ("checkpoint_key_sha256",)

        source_code = inspect.getsource(checkpoint)
        assert "create_once_file" in source_code
        assert "_require_host_controlled_ledger_root" in source_code
        for forbidden in (
            "urllib",
            "requests.",
            "httpx",
            "run_bounded_subprocess",
            "request_pull_request_reviewers",
            "add_review_to_pr",
            "resolve_review_thread",
            "merge_pull_request(",
            "label_pr(",
        ):
            assert forbidden not in source_code
    finally:
        ledger_temp.cleanup()
        other_temp.cleanup()
        tx_ledger.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()

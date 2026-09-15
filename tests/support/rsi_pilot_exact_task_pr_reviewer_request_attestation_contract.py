"""Adversarial contract for ADR-DC-076 post-reviewer-request attestation."""
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

from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_transaction as transaction  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_write_transaction_contract as parent  # noqa: E402

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-pr-reviewer-request-attestation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        attestation.PilotExactTaskPrReviewerRequestAttestationError,
        transaction.PilotExactTaskPrReviewerWriteTransactionError,
        ValueError,
        TypeError,
        OSError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-076 unexpectedly accepted unsafe post-request state")


def _live_transaction():
    cap, _path, _raw, write_temp, parent_temp, cleanup = parent._live_cap()
    ledger_temp = TemporaryDirectory(prefix="rsi-reviewer-attestation-076-tx-")
    calls = []
    value = parent._execute(
        cap,
        transaction._TransactionLedger(Path(ledger_temp.name)),
        calls,
    )
    assert value.transaction_authenticated is True
    assert len(calls) == 1
    return value, ledger_temp, write_temp, parent_temp, cleanup


def _reader(value, *, drift_second: bool = False):
    calls = []

    def read(**kwargs):
        assert kwargs["expected_updated_at_utc"] == value.requested_updated_at_utc
        calls.append(dict(kwargs))
        body = b"post-request-attestation-076"
        if drift_second and len(calls) == 2:
            body = b"post-request-attestation-076-drift"
        return {
            "response_body_sha256": hashlib.sha256(body).hexdigest(),
            "response_etag_sha256": hashlib.sha256(b"etag-076").hexdigest(),
            "updated_at_utc": value.requested_updated_at_utc,
            "requested_reviewer_count": 1,
            "requested_team_count": 0,
        }

    return read, calls


def _attest(value, reader):
    times = iter(("2026-09-15T06:25:44Z", "2026-09-15T06:25:45Z"))
    return attestation._attest_verified_pilot_exact_task_pr_reviewer_request(
        reviewer_write_transaction=value,
        reader=reader,
        now_provider=times.__next__,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    parent.run_contract()
    value, ledger_temp, write_temp, parent_temp, cleanup = _live_transaction()
    try:
        reader, calls = _reader(value)
        result = _attest(value, reader)
        assert result.attestation_authenticated is True
        assert result.reviewer_write_transaction_sha256 == value.sha256
        assert result.transaction_start_sha256 == value.transaction_start_sha256
        assert result.reviewer_request_nonce_sha256 == value.reviewer_request_nonce_sha256
        assert result.pull_request_number == value.pull_request_number
        assert result.predicted_commit_sha == value.predicted_commit_sha
        assert result.reviewer_login == value.reviewer_login
        assert result.reviewer_user_id == value.reviewer_user_id
        assert result.requested_updated_at_utc == value.requested_updated_at_utc
        assert len(calls) == 2

        for field in (
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "exact_pr_state_verified",
            "stable_double_observation_verified",
            "credential_free_reads",
            "redirects_forbidden",
            "response_bounded",
            "review_state_attestation_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "nonce_reusable",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "merge_readiness_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        reloaded = attestation.PilotExactTaskPrReviewerRequestAttestation.from_mapping(
            result.to_dict()
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.attestation_authenticated is False

        reloaded_tx = transaction.PilotExactTaskPrReviewerWriteTransaction.from_mapping(
            value.to_dict()
        )
        assert reloaded_tx.transaction_authenticated is False
        _reject(lambda: attestation._require_live_transaction(reloaded_tx))

        drift_reader, drift_calls = _reader(value, drift_second=True)
        _reject(lambda: _attest(value, drift_reader))
        assert len(drift_calls) == 2

        backwards_reader, backwards_calls = _reader(value)
        _reject(
            lambda: attestation._attest_verified_pilot_exact_task_pr_reviewer_request(
                reviewer_write_transaction=value,
                reader=backwards_reader,
                now_provider=iter(
                    ("2026-09-15T06:25:45Z", "2026-09-15T06:25:44Z")
                ).__next__,
            )
        )
        assert len(backwards_calls) == 1

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields = set(
            attestation.PilotExactTaskPrReviewerRequestAttestation.__dataclass_fields__
        )
        assert len(fields) == 53
        assert set(schema["properties"]) == fields
        assert set(schema["required"]) == fields
        assert schema["properties"]["reviewer_request_performed_verified"]["const"] is True
        assert schema["properties"]["review_submission_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        assert tuple(
            inspect.signature(
                attestation.attest_pilot_exact_task_pr_reviewer_request
            ).parameters
        ) == ("reviewer_write_transaction",)

        source = inspect.getsource(attestation)
        for forbidden in (
            "import subprocess",
            "run_bounded_subprocess",
            "create_once_file",
            'method=\"POST\"',
            "request-pull-request-reviewer",
            "merge_pull_request(",
            "label_pr(",
        ):
            assert forbidden not in source
        assert "transaction_boundary._read_post_request_pr" in source
    finally:
        ledger_temp.cleanup()
        write_temp.cleanup()
        parent_temp.cleanup()
        for item in cleanup:
            item.cleanup()


if __name__ == "__main__":
    run_contract()

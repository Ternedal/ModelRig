"""Adversarial contract for ADR-DC-065 exact GraphQL ready transaction."""
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
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_node_identity as node_identity  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_state_observation as state  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ready_for_review_transaction as transaction  # noqa: E402
from kaliv_dev_control.bounded_subprocess import BoundedStreamEvidence, BoundedSubprocessResult  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_node_identity_contract import NODE_ID, _descriptor, _node_reader  # noqa: E402
from rsi_pilot_exact_task_pr_ready_for_review_state_observation_contract import _fresh_reader, _material  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-ready-for-review-transaction-v1.schema.json"
READY_UPDATED = "2026-09-15T06:25:00Z"


def _reject(fn) -> None:
    try:
        fn()
    except (
        transaction.PilotExactTaskPrReadyTransactionError,
        node_identity.PilotExactTaskPrReadyNodeIdentityError,
        capability.PilotExactTaskPrReadyCredentialCapabilityError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-065 unexpectedly accepted unsafe ready transaction")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def _broker_runner(*, identity, capability_value, calls):
    def run(
        command,
        *,
        cwd,
        env,
        stdin_bytes,
        timeout_seconds,
        max_output_bytes,
        stdout_prefix_bytes,
        stderr_prefix_bytes,
    ):
        args = tuple(command)
        environment = dict(env)
        request = json.loads(stdin_bytes.decode("utf-8"))
        request_sha256 = hashlib.sha256(stdin_bytes).hexdigest()
        calls.append((args, Path(cwd), environment, request))
        assert args[0].endswith("rsi-github-pr-ready-broker-v1")
        assert args[1:] == (
            "--protocol",
            "github-graphql-ready-for-review-broker-v1",
            "--request-stdin-json",
            "--response-stdout-json",
        )
        assert timeout_seconds == 60
        assert max_output_bytes == 64 * 1024
        assert stdout_prefix_bytes == 64 * 1024
        assert stderr_prefix_bytes == 64 * 1024
        assert not any(
            marker in key.upper()
            for key in environment
            for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION", "BEARER")
        )
        assert request == {
            "schema": transaction.PILOT_EXACT_TASK_PR_READY_BROKER_REQUEST_SCHEMA,
            "operation": "mark-pull-request-ready-for-review",
            "graphql_mutation": "markPullRequestReadyForReview",
            "api_origin": "https://api.github.com/graphql",
            "repository": "Ternedal/ModelRig",
            "pull_request_number": identity.pull_request_number,
            "pull_request_id": identity.pull_request_node_id,
            "pull_request_id_sha256": identity.pull_request_node_id_sha256,
            "head_sha": identity.predicted_commit_sha,
            "review_handoff_plan_sha256": identity.review_handoff_plan_sha256,
            "ready_for_review_nonce_sha256": identity.ready_for_review_nonce_sha256,
        }
        response = {
            "schema": transaction.PILOT_EXACT_TASK_PR_READY_BROKER_RESPONSE_SCHEMA,
            "status": "ready-for-review",
            "graphql_mutation": "markPullRequestReadyForReview",
            "request_sha256": request_sha256,
            "ready_for_review_nonce_sha256": identity.ready_for_review_nonce_sha256,
            "repository": "Ternedal/ModelRig",
            "pull_request_number": identity.pull_request_number,
            "pull_request_id": identity.pull_request_node_id,
            "pull_request_id_sha256": identity.pull_request_node_id_sha256,
            "head_sha": identity.predicted_commit_sha,
            "is_draft": False,
            "updated_at_utc": READY_UPDATED,
        }
        stdout = json.dumps(
            response,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return BoundedSubprocessResult(
            args=args,
            returncode=0,
            stdout=_stream(stdout),
            stderr=_stream(b""),
            total_output_bytes=len(stdout),
            output_limit_exceeded=False,
            timed_out=False,
            process_tree_terminated=False,
        )
    return run


def _readback_reader(*, identity, requirements, expected_updated_at_utc):
    assert expected_updated_at_utc == READY_UPDATED
    return {
        "response_body_sha256": hashlib.sha256(b"ready-readback-065").hexdigest(),
        "response_etag_sha256": hashlib.sha256(b"ready-etag-065").hexdigest(),
        "pull_request_node_id_sha256": identity.pull_request_node_id_sha256,
        "updated_at_utc": READY_UPDATED,
    }


def _live_identity():
    tx, requirements, source_identity, receipt, ledger_temp, cleanup = _material()
    broker_temp = TemporaryDirectory(prefix="rsi-pr-ready-transaction-broker-065-")
    observation = state._observe_verified_pilot_exact_task_pr_ready_for_review_state(
        ready_for_review_reservation=receipt,
        reader=_fresh_reader,
        now_provider=lambda: "2026-09-15T06:24:50Z",
    )
    broker_path = Path(broker_temp.name) / "rsi-github-pr-ready-broker-v1"
    broker_path.write_bytes(b"ready-broker-064")
    cap = capability._materialize_verified_pilot_exact_task_pr_ready_credential_capability(
        ready_state_observation=observation,
        broker_descriptor=_descriptor(broker_path),
        now_provider=lambda: "2026-09-15T06:24:51Z",
    )
    identity = node_identity._attest_verified_pilot_exact_task_pr_ready_node_identity(
        ready_credential_capability=cap,
        reader=_node_reader,
        now_provider=lambda: "2026-09-15T06:24:55Z",
    )
    return (
        tx,
        requirements,
        source_identity,
        receipt,
        observation,
        cap,
        identity,
        broker_temp,
        ledger_temp,
        cleanup,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    (
        tx,
        requirements,
        source_identity,
        receipt,
        observation,
        cap,
        identity,
        broker_temp,
        reservation_ledger_temp,
        cleanup,
    ) = _live_identity()
    transaction_temp = TemporaryDirectory(prefix="rsi-pr-ready-transaction-065-")
    failure_temp = TemporaryDirectory(prefix="rsi-pr-ready-transaction-failure-065-")
    try:
        ledger = transaction._PilotExactTaskPrReadyTransactionLedger(
            Path(transaction_temp.name)
        )
        broker_calls = []
        times = iter(
            (
                "2026-09-15T06:24:56Z",
                "2026-09-15T06:24:57Z",
                "2026-09-15T06:24:58Z",
                "2026-09-15T06:24:59Z",
            )
        )
        result = transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
            ready_node_identity=identity,
            ledger=ledger,
            state_reader=_node_reader,
            subprocess_runner=_broker_runner(
                identity=identity,
                capability_value=cap,
                calls=broker_calls,
            ),
            readback_reader=_readback_reader,
            now_provider=lambda: next(times),
            broker_host_control_required=False,
        )
        assert len(broker_calls) == 1
        assert result.transaction_authenticated is True
        assert result.node_identity_sha256 == identity.sha256
        assert result.ready_credential_capability_sha256 == cap.sha256
        assert result.ready_state_observation_sha256 == observation.sha256
        assert result.ready_for_review_reservation_sha256 == receipt.sha256
        assert result.review_handoff_requirements_sha256 == requirements.sha256
        assert result.pr_create_transaction_sha256 == tx.sha256
        assert result.predicted_commit_sha == source_identity.predicted_commit_sha
        assert result.pull_request_node_id == NODE_ID
        assert result.pull_request_node_id_sha256 == identity.pull_request_node_id_sha256
        assert result.transaction_key_sha256 == identity.ready_for_review_nonce_sha256
        assert result.pre_ready_updated_at_utc == identity.observed_updated_at_utc
        assert result.ready_updated_at_utc == READY_UPDATED
        assert result.started_at_utc == "2026-09-15T06:24:57Z"
        assert result.mutated_at_utc == "2026-09-15T06:24:58Z"
        assert result.verified_at_utc == "2026-09-15T06:24:59Z"
        assert ledger._start_path(identity.ready_for_review_nonce_sha256).is_file()
        assert ledger._final_path(identity.ready_for_review_nonce_sha256).is_file()

        for field in (
            "host_transaction_start_committed",
            "ready_for_review_authorization_consumed",
            "ready_for_review_slot_consumed",
            "fresh_pr_state_revalidated_before_ready",
            "exact_graphql_node_identity_revalidated",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_without_secret_exposure",
            "exact_graphql_ready_request_performed",
            "ready_for_review_performed",
            "post_ready_readback_verified",
            "draft_state_cleared_verified",
            "exact_head_sha_verified",
            "exact_base_verified",
            "exact_metadata_verified",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "pr_mutation_authorized",
            "pull_request_create_authorized",
            "ready_for_review_authorized",
            "reviewer_mutation_authorized",
            "label_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        reloaded = transaction.PilotExactTaskPrReadyTransaction.from_mapping(serialized)
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.transaction_authenticated is False
        assert "broker_executable_path" not in serialized
        assert os.fspath(Path(broker_temp.name) / "rsi-github-pr-ready-broker-v1") not in result.canonical_json()

        reloaded_identity = node_identity.PilotExactTaskPrReadyNodeIdentity.from_mapping(
            identity.to_dict()
        )
        assert reloaded_identity.identity_authenticated is False
        _reject(lambda: transaction._require_live_identity(reloaded_identity))

        # Ambiguous failure after durable start permanently blocks automatic retry.
        failure_ledger = transaction._PilotExactTaskPrReadyTransactionLedger(
            Path(failure_temp.name)
        )
        failing_times = iter(
            (
                "2026-09-15T06:24:56Z",
                "2026-09-15T06:24:57Z",
            )
        )
        def failed_broker(command, **kwargs):
            args = tuple(command)
            stderr = b"ambiguous GraphQL failure"
            return BoundedSubprocessResult(
                args=args,
                returncode=1,
                stdout=_stream(b""),
                stderr=_stream(stderr),
                total_output_bytes=len(stderr),
                output_limit_exceeded=False,
                timed_out=False,
                process_tree_terminated=False,
            )

        _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
            ready_node_identity=identity,
            ledger=failure_ledger,
            state_reader=_node_reader,
            subprocess_runner=failed_broker,
            readback_reader=lambda **_: (_ for _ in ()).throw(AssertionError("readback must not run")),
            now_provider=lambda: next(failing_times),
            broker_host_control_required=False,
        ))
        assert failure_ledger._start_path(identity.ready_for_review_nonce_sha256).is_file()
        assert not failure_ledger._final_path(identity.ready_for_review_nonce_sha256).exists()

        retry_calls = []
        retry_times = iter(("2026-09-15T06:24:56Z", "2026-09-15T06:24:57Z"))
        _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
            ready_node_identity=identity,
            ledger=failure_ledger,
            state_reader=_node_reader,
            subprocess_runner=_broker_runner(identity=identity, capability_value=cap, calls=retry_calls),
            readback_reader=_readback_reader,
            now_provider=lambda: next(retry_times),
            broker_host_control_required=False,
        ))
        assert retry_calls == []

        # Wrong node identity or post-ready state must fail closed.
        def wrong_node_reader(*, ready_credential_capability, review_handoff_requirements):
            evidence = dict(_node_reader(
                ready_credential_capability=ready_credential_capability,
                review_handoff_requirements=review_handoff_requirements,
            ))
            wrong = "PR_kwDOTMQCit4WRONG"
            evidence["pull_request_node_id"] = wrong
            evidence["pull_request_node_id_sha256"] = hashlib.sha256(wrong.encode()).hexdigest()
            return evidence

        untouched_temp = TemporaryDirectory(prefix="rsi-pr-ready-wrong-node-065-")
        try:
            untouched_ledger = transaction._PilotExactTaskPrReadyTransactionLedger(
                Path(untouched_temp.name)
            )
            _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
                ready_node_identity=identity,
                ledger=untouched_ledger,
                state_reader=wrong_node_reader,
                subprocess_runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("broker must not run")),
                readback_reader=_readback_reader,
                now_provider=iter(("2026-09-15T06:24:56Z",)).__next__,
                broker_host_control_required=False,
            ))
            assert list(Path(untouched_temp.name).iterdir()) == []
        finally:
            untouched_temp.cleanup()

        bad_readback_temp = TemporaryDirectory(prefix="rsi-pr-ready-bad-readback-065-")
        try:
            bad_ledger = transaction._PilotExactTaskPrReadyTransactionLedger(
                Path(bad_readback_temp.name)
            )
            bad_times = iter(
                (
                    "2026-09-15T06:24:56Z",
                    "2026-09-15T06:24:57Z",
                    "2026-09-15T06:24:58Z",
                )
            )
            _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_ready_for_review(
                ready_node_identity=identity,
                ledger=bad_ledger,
                state_reader=_node_reader,
                subprocess_runner=_broker_runner(identity=identity, capability_value=cap, calls=[]),
                readback_reader=lambda **_: {
                    "response_body_sha256": hashlib.sha256(b"bad").hexdigest(),
                    "response_etag_sha256": hashlib.sha256(b"bad-etag").hexdigest(),
                    "pull_request_node_id_sha256": "f" * 64,
                    "updated_at_utc": READY_UPDATED,
                },
                now_provider=lambda: next(bad_times),
                broker_host_control_required=False,
            ))
            assert bad_ledger._start_path(identity.ready_for_review_nonce_sha256).is_file()
            assert not bad_ledger._final_path(identity.ready_for_review_nonce_sha256).exists()
        finally:
            bad_readback_temp.cleanup()

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["ready_for_review_performed"]["const"] is True
        assert schema["properties"]["ready_for_review_authorized"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_pr_ready_for_review
        ).parameters
        assert tuple(public_parameters) == ("ready_node_identity",)

        source = inspect.getsource(transaction)
        assert "markPullRequestReadyForReview" in source
        assert "https://api.github.com/graphql" in source
        assert "create_pull_request(" not in source
        assert "update_pull_request(" not in source
        assert "request_pull_request_reviewers(" not in source
        assert "merge_pull_request(" not in source
        assert "ready_for_review_authorized: bool = False" in source
        assert "ready_for_review_performed: bool = True" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        failure_temp.cleanup()
        transaction_temp.cleanup()
        broker_temp.cleanup()
        reservation_ledger_temp.cleanup()
        for temp in cleanup:
            temp.cleanup()


if __name__ == "__main__":
    run_contract()

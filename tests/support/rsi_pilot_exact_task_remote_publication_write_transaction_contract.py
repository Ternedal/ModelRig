"""Adversarial contract for ADR-DC-053 exact remote publication transaction."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_credential_capability as capability  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_publication_write_transaction as transaction  # noqa: E402
from kaliv_dev_control.bounded_subprocess import (  # noqa: E402
    BoundedStreamEvidence,
    BoundedSubprocessResult,
)
from rsi_pilot_exact_task_remote_publication_credential_capability_contract import (  # noqa: E402
    _broker_descriptor,
    _reservation_material,
)
from rsi_pilot_exact_task_remote_publication_state_observation_contract import (  # noqa: E402
    _observation_reader,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-write-transaction-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        transaction.PilotExactTaskRemotePublicationWriteTransactionError,
        ValueError,
        TypeError,
        AssertionError,
    ):
        return
    raise AssertionError("ADR-DC-053 unexpectedly accepted unsafe remote transaction")


def _stream(payload: bytes) -> BoundedStreamEvidence:
    return BoundedStreamEvidence(
        prefix=payload,
        total_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        truncated=False,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    material, ledger_temp, reservation_receipt = _reservation_material()
    (
        source_temp,
        admission_ledger_temp,
        executor_capability_temp,
        local_reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        completed,
        requirements,
        attestation,
    ) = material
    broker_temp = TemporaryDirectory(prefix="rsi-remote-write-transaction-053-")
    try:
        descriptor, _policy_path, broker_path, _policy = _broker_descriptor(broker_temp)
        credential_capability = capability._materialize_verified_pilot_exact_task_remote_publication_credential_capability(
            remote_write_reservation=reservation_receipt,
            broker_descriptor=descriptor,
            now_provider=lambda: "2026-09-15T06:21:45Z",
        )
        assert credential_capability.capability_authenticated is True

        _calls, remote_args, base_reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
        )
        remote_reads: list[tuple[str, ...]] = []

        def git_reader(args, *, cwd, stdin=None, **kwargs):
            exact = tuple(args)
            if exact == remote_args:
                remote_reads.append(exact)
                if len(remote_reads) == 1:
                    return b""
                if len(remote_reads) == 2:
                    return (
                        identity.predicted_commit_sha
                        + "\t"
                        + attestation.destination_ref
                        + "\n"
                    ).encode("ascii")
                raise AssertionError("unexpected additional remote read")
            return base_reader(args, cwd=cwd, stdin=stdin, **kwargs)

        push_calls: list[tuple[tuple[str, ...], dict[str, str]]] = []

        def bounded_push(
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
            push_calls.append((args, environment))
            assert Path(cwd).is_absolute()
            assert stdin_bytes is None
            assert timeout_seconds == 60
            assert max_output_bytes == 64 * 1024
            assert stdout_prefix_bytes == 64 * 1024
            assert stderr_prefix_bytes == 64 * 1024
            assert environment["GIT_ASKPASS"] == os.fspath(broker_path)
            assert environment["GIT_ASKPASS_REQUIRE"] == "force"
            assert environment["GIT_TERMINAL_PROMPT"] == "0"
            assert environment["GCM_INTERACTIVE"] == "Never"
            assert not any(
                marker in key.upper()
                for key in environment
                for marker in ("TOKEN", "PASSWORD", "AUTHORIZATION")
            )
            assert "push" in args
            assert "--porcelain" in args
            assert (
                f"--force-with-lease={attestation.destination_ref}:" in args
            )
            assert "--force" not in args
            assert not any(item.startswith("+") for item in args)
            assert credential_capability.canonical_remote_url in args
            assert (
                f"{identity.predicted_commit_sha}:{attestation.destination_ref}" in args
            )
            assert "protocol.allow=never" in args
            assert "protocol.https.allow=always" in args
            assert "http.followRedirects=false" in args
            assert "credential.helper=" in args
            stdout = (
                "To https://github.com/Ternedal/ModelRig.git\n"
                "*\t"
                + identity.predicted_commit_sha
                + ":"
                + attestation.destination_ref
                + "\t[new branch]\nDone\n"
            ).encode("utf-8")
            stderr = b""
            return BoundedSubprocessResult(
                args=args,
                returncode=0,
                stdout=_stream(stdout),
                stderr=_stream(stderr),
                total_output_bytes=len(stdout),
                output_limit_exceeded=False,
                timed_out=False,
                process_tree_terminated=False,
            )

        times = iter(
            (
                "2026-09-15T06:21:46Z",
                "2026-09-15T06:21:47Z",
                "2026-09-15T06:21:48Z",
                "2026-09-15T06:21:49Z",
                "2026-09-15T06:21:50Z",
            )
        )
        with patch.object(fixture["git_runner"], "run", side_effect=git_reader), patch.object(
            transaction,
            "run_bounded_subprocess",
            side_effect=bounded_push,
        ):
            result = transaction._execute_verified_pilot_exact_task_remote_publication_write(
                credential_capability=credential_capability,
                now_provider=lambda: next(times),
                broker_host_control_required=False,
            )

        assert len(push_calls) == 1
        assert len(remote_reads) == 2
        assert result.credential_capability_sha256 == credential_capability.sha256
        assert result.remote_write_reservation_sha256 == reservation_receipt.sha256
        assert result.target_attestation_sha256 == attestation.sha256
        assert result.authorization_proof_sha256 == credential_capability.authorization_proof_sha256
        assert result.local_commit_publication_requirements_sha256 == requirements.sha256
        assert result.local_commit_write_transaction_sha256 == completed.sha256
        assert result.remote_publication_nonce_sha256 == credential_capability.remote_publication_nonce_sha256
        assert result.predicted_commit_sha == identity.predicted_commit_sha
        assert result.destination_ref == attestation.destination_ref
        assert result.expected_old_remote_sha == "0" * 40
        assert result.broker_policy_sha256 == credential_capability.broker_policy_sha256
        assert result.broker_executable_path_sha256 == credential_capability.broker_executable_path_sha256
        assert result.broker_executable_sha256 == credential_capability.broker_executable_sha256
        assert result.started_at_utc == "2026-09-15T06:21:46Z"
        assert result.pushed_at_utc == "2026-09-15T06:21:49Z"
        assert result.verified_at_utc == "2026-09-15T06:21:50Z"
        assert result.transaction_authenticated is True

        for field in (
            "host_replay_guard_committed",
            "remote_publication_authorization_consumed",
            "remote_write_slot_consumed",
            "credential_broker_freshly_verified",
            "credential_broker_invoked_by_git_only",
            "fresh_remote_state_revalidated_before_write",
            "create_only_compare_and_swap_performed",
            "unconditional_force_push_forbidden",
            "remote_write_performed",
            "push_performed",
            "remote_ref_verified",
            "remote_publication_completed",
            "separate_pr_mutation_authorization_required",
        ):
            assert getattr(result, field) is True
        for field in (
            "credential_material_in_artifact",
            "credential_material_in_process_arguments",
            "credential_material_in_environment",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(result, field) is False

        serialized = result.to_dict()
        assert "broker_executable_path" not in serialized
        assert os.fspath(broker_path) not in result.canonical_json()
        reloaded = transaction.PilotExactTaskRemotePublicationWriteTransaction.from_mapping(
            serialized
        )
        assert reloaded == result
        assert reloaded.sha256 == result.sha256
        assert reloaded.transaction_authenticated is False

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(serialized)
        assert set(schema["required"]) == set(serialized)
        assert schema["properties"]["remote_write_performed"]["const"] is True
        assert schema["properties"]["push_performed"]["const"] is True
        assert schema["properties"]["pr_mutation_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        reloaded_capability = capability.PilotExactTaskRemotePublicationCredentialCapability.from_mapping(
            credential_capability.to_dict()
        )
        assert reloaded_capability.capability_authenticated is False
        _reject(
            lambda: transaction._require_live_capability(reloaded_capability)
        )
        _reject(
            lambda: transaction._require_transaction_window(
                credential_capability,
                at_utc="2026-09-15T06:23:00Z",
            )
        )

        broker_path.write_bytes(b"tampered-after-capability\n")
        _reject(
            lambda: transaction._fresh_broker_binary(
                descriptor,
                require_host_control=False,
            )
        )

        public_parameters = inspect.signature(
            transaction.execute_pilot_exact_task_remote_publication_write
        ).parameters
        assert tuple(public_parameters) == ("credential_capability",)

        source = inspect.getsource(transaction)
        assert "shell=True" not in source
        assert '"--force",' not in source
        assert 'startswith("+")' in source
        assert "--force-with-lease=" in source
        assert "http.followRedirects=false" in source
        assert "credential.helper=" in source
        assert "create_pull_request" not in source
        assert "merge_pull_request" not in source
        assert "release_authorized: bool = False" in source
        assert "production_activation_authorized: bool = False" in source
    finally:
        broker_temp.cleanup()
        ledger_temp.cleanup()
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        local_reservation_temp.cleanup()
        executor_capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()

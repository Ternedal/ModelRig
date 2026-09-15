"""Adversarial contract for ADR-DC-050 read-only remote state observation."""
from __future__ import annotations

import inspect
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_local_commit_publication_requirements as publication,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_authorization as auth,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_state_observation as state,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_remote_publication_target_attestation as target,
)
from kaliv_dev_control import trusted_git_runtime_runner  # noqa: E402
from rsi_pilot_exact_task_local_commit_publication_requirements_contract import (  # noqa: E402
    _completed_transaction_fixture,
    _verification_reader,
)
from rsi_pilot_exact_task_remote_publication_authorization_contract import (  # noqa: E402
    _claim,
    _human_authority,
)

SCHEMA = (
    ROOT
    / "devcontrol"
    / "schemas"
    / "rsi-pilot-exact-task-remote-publication-state-observation-v1.schema.json"
)


def _reject(fn) -> None:
    try:
        fn()
    except (
        state.PilotExactTaskRemotePublicationStateObservationError,
        ValueError,
        TypeError,
    ):
        return
    raise AssertionError("ADR-DC-050 unexpectedly accepted unsafe remote state")


def _attested_material():
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
        execution_temp,
        source_reservation_temp,
        transaction_temp,
        identity,
        task,
        fixture,
        staged,
        index_payload,
        _write_reservation,
        completed,
    ) = _completed_transaction_fixture()
    _calls, reader = _verification_reader(
        fixture=fixture,
        task=task,
        identity=identity,
        staged=staged,
        index_payload=index_payload,
        transaction_receipt=completed,
    )
    with patch.object(fixture["git_runner"], "run", side_effect=reader), patch.object(
        publication,
        "_now_utc_seconds",
        return_value="2026-09-15T06:15:00Z",
    ):
        requirements = publication.materialize_pilot_exact_task_local_commit_publication_requirements(
            completed
        )
    claim = _claim(requirements)
    verifier, signature = _human_authority(claim)
    proof = auth._verify_pilot_exact_task_remote_publication_authorization(
        local_commit_publication_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:17:00Z",
    )
    fresh = auth._verify_pilot_exact_task_remote_publication_authorization(
        local_commit_publication_requirements=requirements,
        authorization=claim,
        signature=signature,
        verifier=verifier,
        now_provider=lambda: "2026-09-15T06:18:00Z",
    )
    policy = target.PilotExactTaskRemotePublicationTargetPolicy(policy_epoch=1)
    attestation = target._attest_verified_pilot_exact_task_remote_publication_target(
        authorization_proof=proof,
        fresh_authorization_proof=fresh,
        target_policy=policy,
        now_provider=lambda: "2026-09-15T06:19:00Z",
    )
    assert attestation.target_attestation_authenticated is True
    return (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
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
    )


def _observation_reader(
    *,
    fixture,
    task,
    identity,
    staged: bytes,
    index_payload: bytes,
    completed,
    attestation,
    destination_exists: bool = False,
):
    _base_calls, base_reader = _verification_reader(
        fixture=fixture,
        task=task,
        identity=identity,
        staged=staged,
        index_payload=index_payload,
        transaction_receipt=completed,
    )
    calls: list[tuple[str, ...]] = []
    remote_args = (
        "-c",
        "protocol.https.allow=always",
        "-c",
        "http.followRedirects=false",
        "-c",
        "credential.helper=",
        "ls-remote",
        "--refs",
        attestation.canonical_remote_url,
        attestation.destination_ref,
    )

    def run(args, *, cwd, stdin=None, **kwargs):
        args = tuple(args)
        calls.append(args)
        if args == remote_args:
            assert stdin is None
            assert kwargs.get("maximum") == 4096
            assert kwargs.get("timeout_seconds") == 30
            if destination_exists:
                return (
                    identity.predicted_commit_sha
                    + "\t"
                    + attestation.destination_ref
                    + "\n"
                ).encode("ascii")
            return b""
        return base_reader(args, cwd=cwd, stdin=stdin, **kwargs)

    return calls, remote_args, run


def run_contract() -> None:
    if os.name == "nt":
        return

    material = _attested_material()
    (
        source_temp,
        admission_ledger_temp,
        capability_temp,
        reservation_temp,
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
    try:
        calls, remote_args, reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
        )
        times = iter(("2026-09-15T06:20:00Z", "2026-09-15T06:21:00Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=reader):
            observation = state._observe_verified_pilot_exact_task_remote_publication_state(
                target_attestation=attestation,
                now_provider=lambda: next(times),
            )

        assert calls.count(remote_args) == 1
        assert observation.target_attestation_sha256 == attestation.sha256
        assert observation.authorization_proof_sha256 == attestation.authorization_proof_sha256
        assert (
            observation.local_commit_publication_requirements_sha256
            == requirements.sha256
        )
        assert (
            observation.local_commit_write_transaction_sha256
            == completed.sha256
        )
        assert (
            observation.remote_publication_nonce_sha256
            == attestation.remote_publication_nonce_sha256
        )
        assert observation.predicted_commit_sha == identity.predicted_commit_sha
        assert observation.target_policy_sha256 == attestation.target_policy_sha256
        assert observation.target_provider == "github"
        assert observation.target_host == "github.com"
        assert observation.target_repository == "Ternedal/ModelRig"
        assert observation.canonical_remote_url == "https://github.com/Ternedal/ModelRig.git"
        assert observation.destination_ref == attestation.destination_ref
        assert observation.expected_old_remote_sha == "0" * 40
        assert observation.observed_at_utc == "2026-09-15T06:21:00Z"
        assert observation.observation_authenticated is True

        for field in (
            "target_attestation_verified",
            "fresh_local_commit_revalidated",
            "remote_state_observed",
            "remote_destination_ref_absent",
            "expected_old_remote_sha_bound",
            "create_only_remote_ref_required",
            "https_only_remote_read",
            "redirects_forbidden",
            "credential_helpers_disabled",
            "interactive_auth_disabled",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            assert getattr(observation, field) is True
        for field in (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            assert getattr(observation, field) is False

        reloaded = state.PilotExactTaskRemotePublicationStateObservation.from_mapping(
            observation.to_dict()
        )
        assert reloaded == observation
        assert reloaded.sha256 == observation.sha256
        assert reloaded.observation_authenticated is False

        reloaded_attestation = target.PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
            attestation.to_dict()
        )
        assert reloaded_attestation.target_attestation_authenticated is False
        _reject(lambda: state._require_live_target_attestation(reloaded_attestation))

        # Any pre-existing destination blocks the create-only publication chain.
        existing_calls, existing_args, existing_reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
            destination_exists=True,
        )
        existing_times = iter(("2026-09-15T06:20:10Z", "2026-09-15T06:21:10Z"))
        with patch.object(fixture["git_runner"], "run", side_effect=existing_reader):
            _reject(
                lambda: state._observe_verified_pilot_exact_task_remote_publication_state(
                    target_attestation=attestation,
                    now_provider=lambda: next(existing_times),
                )
            )
        assert existing_calls.count(existing_args) == 1

        # A target attestation older than five minutes fails before remote access.
        stale_calls, stale_args, stale_reader = _observation_reader(
            fixture=fixture,
            task=task,
            identity=identity,
            staged=staged,
            index_payload=index_payload,
            completed=completed,
            attestation=attestation,
        )
        with patch.object(fixture["git_runner"], "run", side_effect=stale_reader):
            _reject(
                lambda: state._observe_verified_pilot_exact_task_remote_publication_state(
                    target_attestation=attestation,
                    now_provider=lambda: "2026-09-15T06:25:01Z",
                )
            )
        assert stale_args not in stale_calls

        for field in (
            "target_attestation_verified",
            "fresh_local_commit_revalidated",
            "remote_state_observed",
            "remote_destination_ref_absent",
            "expected_old_remote_sha_bound",
            "create_only_remote_ref_required",
            "https_only_remote_read",
            "redirects_forbidden",
            "credential_helpers_disabled",
            "interactive_auth_disabled",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        ):
            changed = observation.to_dict()
            changed[field] = False
            _reject(
                lambda changed=changed: state.PilotExactTaskRemotePublicationStateObservation.from_mapping(
                    changed
                )
            )
        for field in (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        ):
            changed = observation.to_dict()
            changed[field] = True
            _reject(
                lambda changed=changed: state.PilotExactTaskRemotePublicationStateObservation.from_mapping(
                    changed
                )
            )
        changed_old = observation.to_dict()
        changed_old["expected_old_remote_sha"] = "1" * 40
        _reject(
            lambda: state.PilotExactTaskRemotePublicationStateObservation.from_mapping(
                changed_old
            )
        )

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(observation.to_dict())
        assert set(schema["required"]) == set(observation.to_dict())
        assert schema["properties"]["remote_destination_ref_absent"]["const"] is True
        assert schema["properties"]["expected_old_remote_sha"]["const"] == "0" * 40
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False

        public_parameters = inspect.signature(
            state.observe_pilot_exact_task_remote_publication_state
        ).parameters
        assert tuple(public_parameters) == ("target_attestation",)

        source = inspect.getsource(state)
        assert '"ls-remote"' in source
        assert '"protocol.https.allow=always"' in source
        assert '"http.followRedirects=false"' in source
        assert '"credential.helper="' in source
        for forbidden in (
            '("push",',
            '("fetch",',
            '("update-ref",',
            "create_pull_request",
            "merge_pull_request",
            "shell=True",
        ):
            assert forbidden not in source

        runner_source = inspect.getsource(trusted_git_runtime_runner)
        assert '"GIT_TERMINAL_PROMPT": "0"' in runner_source
        assert '"GCM_INTERACTIVE": "Never"' in runner_source
        assert '"GIT_CONFIG_NOSYSTEM": "1"' in runner_source
        assert '"protocol.allow=never"' in runner_source
    finally:
        transaction_temp.cleanup()
        source_reservation_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()

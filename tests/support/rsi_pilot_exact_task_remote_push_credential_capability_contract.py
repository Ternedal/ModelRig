"""Adversarial contract for ADR-DC-055 opaque GitHub push credential capability."""
from __future__ import annotations

import inspect
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from kaliv_dev_control import improvement_pilot_exact_task_remote_push_capability_requirements as push_requirements  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_remote_push_credential_capability as credential  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_remote_push_credential_capability_impl as credential_impl  # noqa: E402
from kaliv_dev_control import _improvement_pilot_exact_task_remote_push_credential_capability_production_boundary as credential_prod  # noqa: E402
from rsi_pilot_exact_task_remote_push_capability_requirements_contract import _live_consumption  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-remote-push-credential-capability-v1.schema.json"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-055 unexpectedly materialized unsafe credential capability")


def _provider(*, repository: str, canonical_remote_url: str):
    return credential.GithubPushCredentialProviderAttestation(
        provider_instance_id="modelrig-github-push-provider-primary",
        provider_epoch=7,
        credential_slot_sha256=__import__("hashlib").sha256(b"opaque-provider-slot-055").hexdigest(),
        repository=repository,
        canonical_remote_url=canonical_remote_url,
        attested_at_utc="2026-09-15T05:36:00Z",
        expires_at_utc="2026-09-15T05:40:00Z",
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    values = _live_consumption()
    (
        source_temp, admission_ledger_temp, capability_temp, reservation_temp,
        execution_temp, local_admission_temp, local_consume_temp, object_ledger_temp,
        ref_ledger_temp, ref_receipt, identity, task, fixture, base_reader,
        requirements, remote_observation, claim, signature, supplied, fresh_proof,
        remote_admission_temp, remote_admission, consume_temp, consume_receipt,
    ) = values
    try:
        push_req = push_requirements._materialize_verified_pilot_exact_task_remote_push_capability_requirements(
            write_consumption_receipt=consume_receipt,
            now_provider=lambda: "2026-09-15T05:36:16Z",
        )
        assert push_req.requirements_authenticated is True

        provider = _provider(repository=task.repository, canonical_remote_url=push_req.canonical_remote_url)
        capability = credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:17Z",
        )

        assert capability.capability_authenticated is True
        assert capability.push_capability_requirements_sha256 == push_req.sha256
        assert capability.write_consumption_receipt_sha256 == consume_receipt.sha256
        assert capability.repository == task.repository
        assert capability.local_commit_sha == identity.predicted_commit_sha
        assert capability.destination_ref == push_req.destination_ref
        assert capability.canonical_remote_url == push_req.canonical_remote_url
        assert capability.push_refspec == push_req.push_refspec
        assert capability.remote_publication_nonce_sha256 == consume_receipt.remote_publication_nonce_sha256
        assert capability.provider_attestation == provider
        assert capability.provider_attestation_sha256 == provider.sha256
        assert capability.provider_instance_id == provider.provider_instance_id
        assert capability.provider_epoch == provider.provider_epoch
        assert capability.credential_slot_sha256 == provider.credential_slot_sha256
        assert capability.provider_attestation_host_controlled is True
        assert capability.provider_enabled is True
        assert capability.opaque_credential_handle_bound is True
        assert capability.raw_credential_material_present is False
        assert capability.credential_export_authorized is False
        assert capability.credential_read_authorized is False
        assert capability.remote_write_authorized is False
        assert capability.push_authorized is False
        assert capability.push_started is False
        assert capability.push_completed is False
        assert capability.pr_mutation_authorized is False
        assert capability.production_activation_authorized is False
        assert capability.capability_materialized_at_utc == "2026-09-15T05:36:17Z"
        assert capability.capability_expires_at_utc == "2026-09-15T05:36:47Z"

        reloaded = credential.PilotExactTaskRemotePushCredentialCapability.from_mapping(capability.to_dict())
        assert reloaded == capability
        assert reloaded.sha256 == capability.sha256
        assert reloaded.capability_authenticated is False

        reloaded_requirements = push_requirements.PilotExactTaskRemotePushCapabilityRequirements.from_mapping(push_req.to_dict())
        assert reloaded_requirements.requirements_authenticated is False
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=reloaded_requirements,
            provider_attestation=provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:18Z",
        ))
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=provider,
            provider_attestation_host_controlled=False,
            now_provider=lambda: "2026-09-15T05:36:18Z",
        ))
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=replace(provider, repository="Other/Repo"),
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:18Z",
        ))
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=replace(provider, canonical_remote_url="https://github.com/Other/Repo.git"),
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:18Z",
        ))
        _reject(lambda: credential.GithubPushCredentialProviderAttestation.from_mapping(
            {**provider.to_dict(), "raw_credential_material_present": True}
        ))
        _reject(lambda: credential.GithubPushCredentialProviderAttestation.from_mapping(
            {**provider.to_dict(), "credential_export_allowed": True}
        ))
        _reject(lambda: credential.GithubPushCredentialProviderAttestation.from_mapping(
            {**provider.to_dict(), "provider_interface": "caller-selected-provider/v1"}
        ))

        expired_provider = replace(
            provider,
            attested_at_utc="2026-09-15T05:35:00Z",
            expires_at_utc="2026-09-15T05:36:17Z",
        )
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=expired_provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:17Z",
        ))
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: "2026-09-15T05:36:00Z",
        ))
        _reject(lambda: credential._materialize_verified_pilot_exact_task_remote_push_credential_capability(
            push_capability_requirements=push_req,
            provider_attestation=provider,
            provider_attestation_host_controlled=True,
            now_provider=lambda: push_req.capability_expires_at_utc,
        ))

        for field, value in (
            ("provider_attestation_host_controlled", False),
            ("provider_enabled", False),
            ("provider_repository_scope_matched", False),
            ("provider_remote_url_scope_matched", False),
            ("provider_transport_scope_matched", False),
            ("opaque_credential_handle_bound", False),
            ("raw_credential_material_present", True),
            ("credential_export_authorized", True),
            ("credential_read_authorized", True),
            ("caller_supplied_credential_forbidden", False),
            ("inherited_git_credential_helpers_forbidden", False),
            ("interactive_credential_prompt_forbidden", False),
            ("exact_push_refspec_bound", False),
            ("fresh_remote_head_revalidation_at_push_required", False),
            ("remote_publication_authorization_consumed", False),
            ("remote_write_authorized", True),
            ("push_authorized", True),
            ("push_started", True),
            ("push_completed", True),
            ("pr_mutation_authorized", True),
            ("production_activation_authorized", True),
            ("credential_slot_sha256", "a" * 64),
            ("provider_attestation_sha256", "a" * 64),
            ("capability_expires_at_utc", "2026-09-15T05:37:17Z"),
        ):
            _reject(lambda field=field, value=value: credential.PilotExactTaskRemotePushCredentialCapability.from_mapping(
                {**capability.to_dict(), field: value}
            ))

        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        assert set(schema["properties"]) == set(capability.to_dict())
        assert set(schema["required"]) == set(capability.to_dict())
        assert schema["properties"]["raw_credential_material_present"]["const"] is False
        assert schema["properties"]["credential_export_authorized"]["const"] is False
        assert schema["properties"]["remote_write_authorized"]["const"] is False
        assert schema["properties"]["push_authorized"]["const"] is False

        public_api = inspect.signature(credential.materialize_pilot_exact_task_remote_push_credential_capability).parameters
        assert tuple(public_api) == ("push_capability_requirements",)

        runtime_source = inspect.getsource(credential_impl)
        production_source = inspect.getsource(credential_prod)
        combined = runtime_source + production_source
        assert "subprocess" not in combined
        assert "shell=True" not in combined
        assert ".run(" not in runtime_source
        assert '"ls-remote"' not in combined
        assert '("push",' not in combined
        assert "Ed25519PrivateKey" not in combined
        assert "credential_slot_sha256" in combined
    finally:
        consume_temp.cleanup()
        remote_admission_temp.cleanup()
        ref_ledger_temp.cleanup()
        object_ledger_temp.cleanup()
        local_consume_temp.cleanup()
        local_admission_temp.cleanup()
        execution_temp.cleanup()
        reservation_temp.cleanup()
        capability_temp.cleanup()
        admission_ledger_temp.cleanup()
        source_temp.cleanup()


if __name__ == "__main__":
    run_contract()

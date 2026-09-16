"""Adversarial contract for ADR-DC-083 functional staging runtime verification."""
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
    improvement_pilot_exact_task_staging_runtime_verification as runtime_verify,
)
import rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract as post_status_contract  # noqa: E402

SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-staging-runtime-verification-v1.schema.json"
SOURCE = ROOT / "devcontrol" / "src" / "kaliv_dev_control" / "improvement_pilot_exact_task_staging_runtime_verification.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-083 unexpectedly accepted unsafe runtime evidence")


def _live_source(*, recovered_upstream=False, recovered_status=False):
    if recovered_status:
        context, _plan, _observation, authorization, auth_temp, tx_temp, _tx_ledger, completion, recovery_temp, recovery_root = post_status_contract._recovered_completion(recovered=recovered_upstream)
    else:
        context, _plan, _observation, authorization, auth_temp, tx_temp, _tx_ledger, completion, recovery_temp, recovery_root = post_status_contract._normal_completion(recovered=recovered_upstream)
    transport = post_status_contract.recovery_contract._Transport(
        authorization,
        status_id=completion.deployment_status_id,
        node_hash=completion.deployment_status_node_id_sha256,
    )
    receipt = post_status_contract._attest(authorization, auth_temp, tx_temp, recovery_root, transport)
    assert receipt.attestation_authenticated is True
    return context, auth_temp, tx_temp, recovery_temp, receipt


def _cleanup(bundle) -> None:
    context, auth_temp, tx_temp, recovery_temp, _source = bundle
    post_status_contract._cleanup(context, auth_temp, tx_temp, recovery_temp)


def _config(source, *, origin="http://127.0.0.1:8080"):
    return runtime_verify.PilotExactTaskStagingRuntimeVerificationConfig(
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment="staging",
        runtime_origin=origin,
    )


def _credential():
    return runtime_verify.PilotExactTaskStagingRuntimeProbeCredential(token="1" * 64)


class _VersionObserver:
    def __init__(self, source, *, versions=None, blob_sha="a" * 40):
        self.credential_config_sha256 = source.publisher_credential_config_sha256
        self.credential_path_sha256 = source.publisher_credential_path_sha256
        self.source = source
        self.versions = list(versions or ["2.0.13", "2.0.13"])
        self.blob_sha = blob_sha
        self.calls = 0

    def observe(self, source):
        self.calls += 1
        assert source.sha256 == self.source.sha256
        version = self.versions.pop(0) if self.versions else "2.0.13"
        return runtime_verify._ExactVersionEvidence(
            repository=source.repository,
            repository_id=source.repository_id,
            merge_commit_sha=source.merge_commit_sha,
            version=version,
            version_blob_sha1=self.blob_sha,
        )


class _RuntimeProbe:
    def __init__(self, config, credential, path, *, versions=None, deep_ok=True, ollama_ok=True, models=3, worker_ok=True, embed_dims=768):
        origin, transport_class = runtime_verify._runtime_origin(config.runtime_origin)
        self.origin_sha256 = hashlib.sha256(origin.encode("utf-8")).hexdigest()
        self.transport_class = transport_class
        self.credential_sha256 = credential.sha256
        self.credential_path_sha256 = runtime_verify._path_sha256(path)
        self.versions = list(versions or ["2.0.13", "2.0.13"])
        self.deep_ok = deep_ok
        self.ollama_ok = ollama_ok
        self.models = models
        self.worker_ok = worker_ok
        self.embed_dims = embed_dims
        self.calls = 0

    def observe(self):
        self.calls += 1
        version = self.versions.pop(0) if self.versions else "2.0.13"
        return runtime_verify._RuntimeProbeEvidence(
            runtime_origin_sha256=self.origin_sha256,
            runtime_transport_class=self.transport_class,
            health_service="modelrig-server",
            health_status="ok",
            health_version=version,
            deep_health_ok=self.deep_ok,
            ollama_ok=self.ollama_ok,
            ollama_model_count=self.models,
            worker_ok=self.worker_ok,
            worker_embed_dims=self.embed_dims,
        )


def _verify(source, config, credential, path, version_observer, runtime_probe, *, now="2026-09-15T09:50:40Z"):
    return runtime_verify._verify_pilot_exact_task_staging_runtime(
        post_status_attestation=source,
        config=config,
        config_sha256=config.sha256,
        probe_credential=credential,
        probe_credential_sha256=credential.sha256,
        probe_credential_path=path,
        version_observer=version_observer,
        runtime_probe=runtime_probe,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle = _live_source()
    source = bundle[-1]
    path = Path("/tmp/modelrig-adr083-probe-credential.json")
    config = _config(source)
    credential = _credential()
    try:
        version_observer = _VersionObserver(source)
        runtime_probe = _RuntimeProbe(config, credential, path)
        receipt = _verify(source, config, credential, path, version_observer, runtime_probe)
        assert version_observer.calls == 2
        assert runtime_probe.calls == 2
        assert receipt.verification_authenticated is True
        assert receipt.post_staging_deployment_status_attestation_sha256 == source.sha256
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.deployment_status_id == source.deployment_status_id
        assert receipt.deployment_status_node_id_sha256 == source.deployment_status_node_id_sha256
        assert receipt.deployment_status_state == "in_progress"
        assert receipt.exact_source_version == "2.0.13"
        assert receipt.health_version == "2.0.13"
        assert receipt.health_service == "modelrig-server"
        assert receipt.ollama_model_count == 3
        assert receipt.worker_embed_dims == 768
        assert receipt.functional_staging_runtime_verified is True
        assert receipt.runtime_commit_identity_observable is False
        assert receipt.runtime_commit_identity_verified is False
        assert receipt.success_deployment_status_authorized is False
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = runtime_verify.PilotExactTaskStagingRuntimeVerificationReceipt.from_mapping(receipt.to_dict())
        assert serialized == receipt
        assert serialized.verification_authenticated is False

        replayed_source = post_status_contract.post_status.PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.from_mapping(source.to_dict())
        assert replayed_source.attestation_authenticated is False
        replay_version = _VersionObserver(source)
        replay_probe = _RuntimeProbe(config, credential, path)
        _reject(lambda: _verify(replayed_source, config, credential, path, replay_version, replay_probe))
        assert replay_version.calls == 0
        assert replay_probe.calls == 0

        bad_config = runtime_verify.PilotExactTaskStagingRuntimeVerificationConfig(
            repository=source.repository,
            repository_id="999",
            deployment_environment="staging",
            runtime_origin="http://127.0.0.1:8080",
        )
        _reject(lambda: _verify(source, bad_config, credential, path, _VersionObserver(source), _RuntimeProbe(bad_config, credential, path)))

        _reject(lambda: runtime_verify.PilotExactTaskStagingRuntimeVerificationConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            deployment_environment="staging",
            runtime_origin="http://192.168.1.21:8080",
        ))
        _reject(lambda: runtime_verify.PilotExactTaskStagingRuntimeVerificationConfig(
            repository=source.repository,
            repository_id=source.repository_id,
            deployment_environment="staging",
            runtime_origin="https://example.com:443",
        ))

        drift_version = _VersionObserver(source, versions=["2.0.13", "2.0.14"])
        drift_probe = _RuntimeProbe(config, credential, path)
        _reject(lambda: _verify(source, config, credential, path, drift_version, drift_probe))
        assert drift_version.calls == 2
        assert drift_probe.calls == 0

        wrong_runtime_version = _RuntimeProbe(config, credential, path, versions=["2.0.14", "2.0.14"])
        _reject(lambda: _verify(source, config, credential, path, _VersionObserver(source), wrong_runtime_version))

        deep_fail = _RuntimeProbe(config, credential, path, deep_ok=False)
        _reject(lambda: _verify(source, config, credential, path, _VersionObserver(source), deep_fail))

        no_models = _RuntimeProbe(config, credential, path, models=0)
        _reject(lambda: _verify(source, config, credential, path, _VersionObserver(source), no_models))

        no_embed = _RuntimeProbe(config, credential, path, embed_dims=0)
        _reject(lambda: _verify(source, config, credential, path, _VersionObserver(source), no_embed))

        runtime_drift = _RuntimeProbe(config, credential, path, versions=["2.0.13", "2.0.14"])
        _reject(lambda: _verify(source, config, credential, path, _VersionObserver(source), runtime_drift))

        bad_credential = runtime_verify.PilotExactTaskStagingRuntimeProbeCredential(token="2" * 64)
        credential_bound_probe = _RuntimeProbe(config, credential, path)
        _reject(lambda: _verify(source, config, bad_credential, path, _VersionObserver(source), credential_bound_probe))
        assert credential_bound_probe.calls == 0

        _reject(lambda: _verify(
            source,
            config,
            credential,
            path,
            _VersionObserver(source),
            _RuntimeProbe(config, credential, path),
            now="2026-09-15T09:50:29Z",
        ))

        for field in (
            "post_status_attestation_authenticated", "exact_deployment_status_verified",
            "staging_runtime_config_host_pinned", "runtime_probe_credential_host_pinned",
            "exact_source_version_observed", "runtime_health_verified", "runtime_deep_health_verified",
            "ollama_runtime_verified", "worker_runtime_verified", "model_inventory_nonempty",
            "embedding_round_trip_verified", "runtime_version_matches_exact_source",
            "double_source_version_observation_matched", "double_runtime_observation_matched",
            "functional_staging_runtime_verified",
        ):
            value = receipt.to_dict()
            value[field] = False
            _reject(lambda value=value: runtime_verify.PilotExactTaskStagingRuntimeVerificationReceipt.from_mapping(value))

        for field in (
            "runtime_commit_identity_observable", "runtime_commit_identity_verified",
            "success_deployment_status_authorized", "deployment_status_mutation_authorized",
            "deployment_mutation_authorized", "deploy_authorized", "remote_write_authorized",
            "release_authorized", "production_activation_authorized", "nonce_reusable",
        ):
            value = receipt.to_dict()
            value[field] = True
            _reject(lambda value=value: runtime_verify.PilotExactTaskStagingRuntimeVerificationReceipt.from_mapping(value))
    finally:
        _cleanup(bundle)

    recovered_bundle = _live_source(recovered_upstream=True, recovered_status=True)
    recovered_source = recovered_bundle[-1]
    recovered_path = Path("/tmp/modelrig-adr083-recovered-probe-credential.json")
    recovered_config = _config(recovered_source)
    recovered_credential = _credential()
    try:
        recovered_receipt = _verify(
            recovered_source,
            recovered_config,
            recovered_credential,
            recovered_path,
            _VersionObserver(recovered_source),
            _RuntimeProbe(recovered_config, recovered_credential, recovered_path),
        )
        assert recovered_receipt.verification_authenticated is True
        assert recovered_receipt.status_completion_source == "recovery"
        assert recovered_receipt.status_recovery_lock_sha256 is not None
        assert recovered_receipt.functional_staging_runtime_verified is True
        assert recovered_receipt.success_deployment_status_authorized is False
    finally:
        _cleanup(recovered_bundle)

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    fields = set(runtime_verify.PilotExactTaskStagingRuntimeVerificationReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 85

    signature = inspect.signature(runtime_verify.verify_pilot_exact_task_staging_runtime)
    assert list(signature.parameters) == ["post_staging_deployment_status_attestation"]

    source_text = SOURCE.read_text(encoding="utf-8")
    for forbidden in (
        'method="POST"', "method='POST'", 'method="PUT"', "method='PUT'",
        'method="PATCH"', "method='PATCH'", 'method="DELETE"', "method='DELETE'",
        "create_deployment_status(", "create_once_file",
    ):
        assert forbidden not in source_text
    assert 'method="GET"' in source_text
    assert "ProxyHandler({})" in source_text
    assert "UrllibReadOnlyTransport" in source_text
    assert "runtime_commit_identity_verified: bool = False" in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text


if __name__ == "__main__":
    run_contract()

"""Adversarial contract for ADR-DC-084 exact staging runtime build identity."""
from __future__ import annotations

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
from source_code import code_of  # noqa: E402

from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_runtime_build_identity as build_identity,
)
from kaliv_dev_control import (  # noqa: E402
    improvement_pilot_exact_task_staging_runtime_verification as runtime_verify,
)
import rsi_pilot_exact_task_staging_runtime_verification_contract as runtime_contract  # noqa: E402

SCHEMA = (
    ROOT / "devcontrol" / "schemas"
    / "rsi-pilot-exact-task-staging-runtime-build-identity-v1.schema.json"
)
SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_staging_runtime_build_identity.py"
)
SERVER_BUILD_SOURCE = ROOT / "backend" / "internal" / "httpapi" / "build_identity.go"
SYSTEM_STATUS_SOURCE = ROOT / "backend" / "internal" / "httpapi" / "system_status.go"
WORKER_BUILD_SOURCE = ROOT / "worker" / "app" / "build_identity.py"
STAMP_SOURCE = ROOT / "scripts" / "stamp_build_identity.py"


def _reject(fn) -> None:
    try:
        fn()
    except (ValueError, TypeError):
        return
    raise AssertionError("ADR-DC-084 unexpectedly accepted unsafe build identity")


def _runtime_receipt(*, recovered=False):
    bundle = runtime_contract._live_source(
        recovered_upstream=recovered,
        recovered_status=recovered,
    )
    source = bundle[-1]
    path = Path(
        "/tmp/modelrig-adr084-recovered-probe.json"
        if recovered
        else "/tmp/modelrig-adr084-probe.json"
    )
    config = runtime_contract._config(source)
    credential = runtime_contract._credential()
    receipt = runtime_contract._verify(
        source,
        config,
        credential,
        path,
        runtime_contract._VersionObserver(source),
        runtime_contract._RuntimeProbe(config, credential, path),
    )
    assert receipt.verification_authenticated is True
    return bundle, config, credential, path, receipt


class _BuildProbe:
    def __init__(
        self,
        source,
        *,
        server_commit=None,
        worker_commit=None,
        server_version=None,
        worker_version=None,
        server_observable=True,
        server_modified=False,
        worker_frozen=True,
        server_artifact="b" * 64,
        worker_code="c" * 64,
        worker_artifact="d" * 64,
        scripted=None,
    ):
        self.source = source
        self.credential_sha256 = source.runtime_probe_credential_sha256
        self.credential_path_sha256 = source.runtime_probe_credential_path_sha256
        self.origin_sha256 = source.runtime_origin_sha256
        self.server_commit = server_commit or source.merge_commit_sha
        self.worker_commit = worker_commit or source.merge_commit_sha
        self.server_version = server_version or source.exact_source_version
        self.worker_version = worker_version or source.exact_source_version
        self.server_observable = server_observable
        self.server_modified = server_modified
        self.worker_frozen = worker_frozen
        self.server_artifact = server_artifact
        self.worker_code = worker_code
        self.worker_artifact = worker_artifact
        self.scripted = list(scripted or ())
        self.calls = 0

    def _evidence(self, overrides=None):
        values = {
            "runtime_origin_sha256": self.source.runtime_origin_sha256,
            "runtime_transport_class": self.source.runtime_transport_class,
            "server_version": self.server_version,
            "server_commit_sha": self.server_commit,
            "server_commit_observable": self.server_observable,
            "server_vcs_modified": self.server_modified,
            "server_executable_sha256": self.server_artifact,
            "server_go_version": "go1.25.1",
            "server_module_path": "modelrig",
            "worker_version": self.worker_version,
            "worker_commit_sha": self.worker_commit,
            "worker_code_sha256": self.worker_code,
            "worker_artifact_sha256": self.worker_artifact,
            "worker_frozen": self.worker_frozen,
        }
        if overrides:
            values.update(overrides)
        return build_identity._RuntimeBuildIdentityEvidence(**values)

    def observe(self):
        self.calls += 1
        overrides = self.scripted.pop(0) if self.scripted else None
        return self._evidence(overrides)


def _verify(source, probe, *, now="2026-09-15T09:50:50Z"):
    return build_identity._verify_pilot_exact_task_staging_runtime_build_identity(
        staging_runtime_verification=source,
        probe=probe,
        now_provider=lambda: now,
    )


def run_contract() -> None:
    if os.name == "nt":
        return

    bundle, _config, _credential, _path, source = _runtime_receipt()
    try:
        probe = _BuildProbe(source)
        receipt = _verify(source, probe)
        assert probe.calls == 2
        assert receipt.verification_authenticated is True
        assert receipt.staging_runtime_verification_sha256 == source.sha256
        assert receipt.repository == source.repository
        assert receipt.repository_id == source.repository_id
        assert receipt.merge_commit_sha == source.merge_commit_sha
        assert receipt.server_commit_sha == source.merge_commit_sha
        assert receipt.worker_commit_sha == source.merge_commit_sha
        assert receipt.server_version == source.exact_source_version
        assert receipt.worker_version == source.exact_source_version
        assert receipt.server_executable_sha256 == "b" * 64
        assert receipt.worker_code_sha256 == "c" * 64
        assert receipt.worker_artifact_sha256 == "d" * 64
        assert receipt.functional_staging_runtime_verified is True
        assert receipt.server_commit_identity_observable is True
        assert receipt.server_commit_identity_verified is True
        assert receipt.server_clean_build_verified is True
        assert receipt.server_artifact_identity_verified is True
        assert receipt.worker_frozen_build_verified is True
        assert receipt.worker_commit_identity_verified is True
        assert receipt.worker_source_identity_verified is True
        assert receipt.worker_artifact_identity_verified is True
        assert receipt.server_worker_commit_matched is True
        assert receipt.runtime_commit_identity_observable is True
        assert receipt.runtime_commit_identity_verified is True
        assert receipt.runtime_artifact_identity_verified is True
        assert receipt.staging_runtime_build_identity_verified is True
        assert receipt.success_deployment_status_ready is True
        assert receipt.success_deployment_status_authorized is False
        assert receipt.deployment_status_mutation_authorized is False
        assert receipt.remote_write_authorized is False
        assert receipt.production_activation_authorized is False
        assert receipt.nonce_reusable is False

        serialized = (
            build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(
                receipt.to_dict()
            )
        )
        assert serialized == receipt
        assert serialized.verification_authenticated is False

        serialized_source = (
            runtime_verify.PilotExactTaskStagingRuntimeVerificationReceipt.from_mapping(
                source.to_dict()
            )
        )
        assert serialized_source.verification_authenticated is False
        stale_probe = _BuildProbe(source)
        _reject(lambda: _verify(serialized_source, stale_probe))
        assert stale_probe.calls == 0

        wrong_server = _BuildProbe(source, server_commit="1" * 40)
        _reject(lambda: _verify(source, wrong_server))
        assert wrong_server.calls == 2

        wrong_worker = _BuildProbe(source, worker_commit="2" * 40)
        _reject(lambda: _verify(source, wrong_worker))

        not_observable = _BuildProbe(source, server_observable=False)
        _reject(lambda: _verify(source, not_observable))

        dirty = _BuildProbe(source, server_modified=True)
        _reject(lambda: _verify(source, dirty))

        source_worker = _BuildProbe(source, worker_frozen=False)
        _reject(lambda: _verify(source, source_worker))

        wrong_server_version = _BuildProbe(source, server_version="2.0.14")
        _reject(lambda: _verify(source, wrong_server_version))

        wrong_worker_version = _BuildProbe(source, worker_version="2.0.14")
        _reject(lambda: _verify(source, wrong_worker_version))

        drift = _BuildProbe(
            source,
            scripted=[{}, {"worker_artifact_sha256": "e" * 64}],
        )
        _reject(lambda: _verify(source, drift))
        assert drift.calls == 2

        bad_credential = _BuildProbe(source)
        bad_credential.credential_sha256 = "8" * 64
        _reject(lambda: _verify(source, bad_credential))
        assert bad_credential.calls == 0

        bad_path = _BuildProbe(source)
        bad_path.credential_path_sha256 = "9" * 64
        _reject(lambda: _verify(source, bad_path))
        assert bad_path.calls == 0

        bad_origin = _BuildProbe(source)
        bad_origin.origin_sha256 = "a" * 64
        _reject(lambda: _verify(source, bad_origin))
        assert bad_origin.calls == 0

        _reject(
            lambda: _verify(
                source,
                _BuildProbe(source),
                now="2026-09-15T09:50:39Z",
            )
        )

        for field in (
            "staging_runtime_verification_authenticated",
            "functional_staging_runtime_verified",
            "server_commit_identity_observable",
            "server_commit_identity_verified",
            "server_clean_build_verified",
            "server_artifact_identity_verified",
            "worker_frozen_build_verified",
            "worker_commit_identity_verified",
            "worker_source_identity_verified",
            "worker_artifact_identity_verified",
            "server_worker_commit_matched",
            "double_build_identity_observation_matched",
            "runtime_commit_identity_observable",
            "runtime_commit_identity_verified",
            "runtime_artifact_identity_verified",
            "staging_runtime_build_identity_verified",
            "success_deployment_status_ready",
        ):
            value = receipt.to_dict()
            value[field] = False
            _reject(
                lambda value=value: build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(value)
            )

        for field in (
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        ):
            value = receipt.to_dict()
            value[field] = True
            _reject(
                lambda value=value: build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.from_mapping(value)
            )
    finally:
        runtime_contract._cleanup(bundle)

    recovered_bundle, _config, _credential, _path, recovered_source = _runtime_receipt(recovered=True)
    try:
        recovered = _verify(recovered_source, _BuildProbe(recovered_source))
        assert recovered.verification_authenticated is True
        assert recovered.status_completion_source == "recovery"
        assert recovered.status_recovery_lock_sha256 is not None
        assert recovered.staging_runtime_build_identity_verified is True
        assert recovered.success_deployment_status_ready is True
        assert recovered.success_deployment_status_authorized is False
    finally:
        runtime_contract._cleanup(recovered_bundle)

    schema = json.loads(code_of(SCHEMA))
    fields = set(build_identity.PilotExactTaskStagingRuntimeBuildIdentityReceipt.__dataclass_fields__)
    assert set(schema["required"]) == fields
    assert set(schema["properties"]) == fields
    assert len(fields) == 85

    signature = inspect.signature(build_identity.verify_pilot_exact_task_staging_runtime_build_identity)
    assert list(signature.parameters) == ["staging_runtime_verification"]

    source_text = code_of(SOURCE)
    for forbidden in (
        'method="POST"', "method='POST'", 'method="PUT"', "method='PUT'",
        'method="PATCH"', "method='PATCH'", 'method="DELETE"', "method='DELETE'",
        "create_deployment_status(", "create_once_file",
    ):
        assert forbidden not in source_text
    assert 'method="GET"' in source_text
    assert "ProxyHandler({})" in source_text
    assert "success_deployment_status_ready: bool = True" in source_text
    assert "success_deployment_status_authorized: bool = False" in source_text

    server_source = code_of(SERVER_BUILD_SOURCE)
    assert "debug.ReadBuildInfo()" in server_source
    assert "vcs.revision" in server_source
    assert "vcs.modified" in server_source
    assert "os.Executable()" in server_source
    assert "sha256.New()" in server_source

    system_source = code_of(SYSTEM_STATUS_SOURCE)
    assert '"build":          build' in system_source
    assert "currentServerBuildIdentity()" in system_source

    worker_source = code_of(WORKER_BUILD_SOURCE)
    assert "COMMIT_SHA" in worker_source
    assert "artifact_fingerprint()" in worker_source
    assert '"commit_sha": commit_identity()' in worker_source
    assert '"artifact_sha256": artifact_fingerprint()' in worker_source

    stamp_source = code_of(STAMP_SOURCE)
    assert 'COMMIT_SHA = "{commit}"' in stamp_source
    assert '["git", "rev-parse", "HEAD"]' in stamp_source


if __name__ == "__main__":
    run_contract()

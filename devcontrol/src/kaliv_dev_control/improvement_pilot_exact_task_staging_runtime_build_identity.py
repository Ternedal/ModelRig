"""ADR-DC-084 read-only exact staging runtime build identity verification.

Consumes one fresh live ADR-DC-083 functional staging runtime verification and
re-observes the host-pinned runtime through existing authenticated GET-only
surfaces.  The server must expose its embedded Go VCS revision and executable
SHA-256 through /api/v1/system/status; the packed worker must expose the commit
stamped before PyInstaller plus its running executable SHA-256 through
/api/v1/health/full.

This boundary proves exact commit/artifact identity only.  It grants no
Deployment Status mutation, Deployment mutation, production activation or other
remote-write authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import improvement_pilot_exact_task_staging_runtime_verification as runtime_boundary
from .improvement_pilot_exact_task_staging_runtime_verification import (
    PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_AUTHORITY,
    PilotExactTaskStagingRuntimeProbeCredential,
    PilotExactTaskStagingRuntimeVerificationConfig,
    PilotExactTaskStagingRuntimeVerificationReceipt,
)

PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-staging-runtime-build-identity-receipt/v1"
)
PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_AUTHORITY = (
    "host-verified-one-dc-l16-exact-staging-runtime-build-identity-only"
)
PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCOPE = (
    "read-only-exact-staging-runtime-build-and-artifact-identity-v1"
)

_SYSTEM_STATUS_PATH = "/api/v1/system/status"
_HEALTH_FULL_PATH = "/api/v1/health/full"
_MAX_RESPONSE_BYTES = 1024 * 1024
_TIMEOUT_SECONDS = 10.0
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PilotExactTaskStagingRuntimeBuildIdentityError(ValueError):
    """Exact staging runtime build identity is stale, weak, or inconsistent."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "staging runtime build evidence is not canonical JSON"
        ) from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_live_runtime_verification(
    value: Any,
) -> PilotExactTaskStagingRuntimeVerificationReceipt:
    if type(value) is not PilotExactTaskStagingRuntimeVerificationReceipt:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "exact live ADR-DC-083 staging runtime verification is required"
        )
    try:
        replayed = PilotExactTaskStagingRuntimeVerificationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "ADR-DC-083 replay validation failed"
        ) from exc
    required_true = (
        "post_status_attestation_authenticated",
        "exact_deployment_status_verified",
        "staging_runtime_config_host_pinned",
        "runtime_probe_credential_host_pinned",
        "exact_source_version_observed",
        "runtime_health_verified",
        "runtime_deep_health_verified",
        "ollama_runtime_verified",
        "worker_runtime_verified",
        "model_inventory_nonempty",
        "embedding_round_trip_verified",
        "runtime_version_matches_exact_source",
        "double_source_version_observation_matched",
        "double_runtime_observation_matched",
        "functional_staging_runtime_verified",
    )
    required_false = (
        "runtime_commit_identity_observable",
        "runtime_commit_identity_verified",
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
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_AUTHORITY
        or value.verification_authenticated is not True
        or value.deployment_environment != "staging"
        or value.deployment_status_state != "in_progress"
        or value.deployment_status_environment != "staging"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in required_false)
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "ADR-DC-084 requires one fresh inert ADR-DC-083 verification"
        )
    live = runtime_boundary._get_live_staging_runtime_verification_inputs(value)
    if (
        live is None
        or live.get("staging_runtime_verification_config_sha256")
        != value.staging_runtime_verification_config_sha256
        or live.get("source_version_observation_sha256")
        != value.source_version_observation_sha256
        or live.get("runtime_observation_sha256")
        != value.runtime_observation_sha256
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "ADR-DC-083 live provenance is unavailable"
        )
    post_status = live.get("post_staging_deployment_status_attestation")
    if (
        post_status is None
        or post_status.sha256
        != value.post_staging_deployment_status_attestation_sha256
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "ADR-DC-083 live source differs from its receipt"
        )
    return value


@dataclass(frozen=True, slots=True)
class _RuntimeBuildIdentityEvidence:
    runtime_origin_sha256: str
    runtime_transport_class: str
    server_version: str
    server_commit_sha: str
    server_commit_observable: bool
    server_vcs_modified: bool
    server_executable_sha256: str
    server_go_version: str
    server_module_path: str
    worker_version: str
    worker_commit_sha: str
    worker_code_sha256: str
    worker_artifact_sha256: str
    worker_frozen: bool

    def __post_init__(self) -> None:
        _hex64(self.runtime_origin_sha256, name="runtime_origin_sha256")
        _hex40(self.server_commit_sha, name="server_commit_sha")
        _hex64(self.server_executable_sha256, name="server_executable_sha256")
        _hex40(self.worker_commit_sha, name="worker_commit_sha")
        _hex64(self.worker_code_sha256, name="worker_code_sha256")
        _hex64(self.worker_artifact_sha256, name="worker_artifact_sha256")
        if self.runtime_transport_class not in {"loopback-http", "private-https"}:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime transport class is invalid"
            )
        if (
            _VERSION.fullmatch(self.server_version) is None
            or _VERSION.fullmatch(self.worker_version) is None
            or self.server_commit_observable is not True
            or self.server_vcs_modified is not False
            or self.worker_frozen is not True
            or not isinstance(self.server_go_version, str)
            or not self.server_go_version.startswith("go1.")
            or len(self.server_go_version) > 64
            or self.server_module_path != "modelrig"
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build identity projection is invalid"
            )

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical(self.to_dict()))


class _StagingRuntimeBuildIdentityProbe:
    """GET-only build observer on the same host-pinned ADR-083 origin."""

    def __init__(
        self,
        *,
        config: PilotExactTaskStagingRuntimeVerificationConfig,
        credential: PilotExactTaskStagingRuntimeProbeCredential,
        credential_sha256: str,
        credential_path: Path,
        opener: Any | None = None,
    ) -> None:
        if (
            type(config) is not PilotExactTaskStagingRuntimeVerificationConfig
            or type(credential) is not PilotExactTaskStagingRuntimeProbeCredential
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "exact ADR-083 runtime config/credential is required"
            )
        self.config = config
        self.credential = credential
        self.credential_sha256 = _hex64(
            credential_sha256,
            name="runtime_probe_credential_sha256",
        )
        if credential.sha256 != self.credential_sha256:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime probe credential digest mismatch"
            )
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute():
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime probe credential path is unsafe"
            )
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self.origin, self.transport_class = runtime_boundary._runtime_origin(
            config.runtime_origin
        )
        self.origin_sha256 = _sha256_text(self.origin)
        self._opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            runtime_boundary._NoRedirect(),
        )

    def _get_json(self, path: str) -> Mapping[str, Any]:
        if path not in {_SYSTEM_STATUS_PATH, _HEALTH_FULL_PATH}:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build probe path is outside fixed read-only scope"
            )
        url = self.origin + path
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.credential.token}",
                "User-Agent": "ModelRig-DevControl-ExactStagingRuntimeBuild/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                f"runtime build GET failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build GET failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingRuntimeBuildIdentityError(
                    "runtime build response identity/status is unexpected"
                )
            content_type = response.headers.get_content_type()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if (
            content_type != "application/json"
            or not raw
            or len(raw) > _MAX_RESPONSE_BYTES
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build response media/size is invalid"
            )
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build response is invalid JSON"
            ) from exc
        if not isinstance(value, Mapping):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "runtime build response must be one JSON object"
            )
        return value

    def observe(self) -> _RuntimeBuildIdentityEvidence:
        system = self._get_json(_SYSTEM_STATUS_PATH)
        if system.get("schema") != "kaliv-system-status/v1":
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "system status schema is unexpected"
            )
        server = system.get("build")
        if not isinstance(server, Mapping):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "system status lacks server build identity"
            )
        server_fields = {
            "version",
            "commit_sha",
            "commit_observable",
            "vcs_modified",
            "executable_sha256",
            "go_version",
            "module_path",
        }
        if set(server) != server_fields:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "server build identity fields differ from fixed ADR-084 contract"
            )
        full = self._get_json(_HEALTH_FULL_PATH)
        worker_build = full.get("build")
        checks = full.get("checks")
        if (
            not isinstance(worker_build, Mapping)
            or not isinstance(checks, Mapping)
            or not isinstance(checks.get("worker"), Mapping)
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "health/full lacks worker build identity"
            )
        required_worker = {
            "code_sha256",
            "commit_sha",
            "artifact_sha256",
            "frozen",
        }
        if not required_worker.issubset(worker_build):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "worker build identity is incomplete"
            )
        return _RuntimeBuildIdentityEvidence(
            runtime_origin_sha256=self.origin_sha256,
            runtime_transport_class=self.transport_class,
            server_version=server.get("version"),
            server_commit_sha=server.get("commit_sha"),
            server_commit_observable=server.get("commit_observable"),
            server_vcs_modified=server.get("vcs_modified"),
            server_executable_sha256=server.get("executable_sha256"),
            server_go_version=server.get("go_version"),
            server_module_path=server.get("module_path"),
            worker_version=checks["worker"].get("version"),
            worker_commit_sha=worker_build.get("commit_sha"),
            worker_code_sha256=worker_build.get("code_sha256"),
            worker_artifact_sha256=worker_build.get("artifact_sha256"),
            worker_frozen=worker_build.get("frozen"),
        )


def _double_observe_build_identity(
    probe: Any,
    *,
    source: PilotExactTaskStagingRuntimeVerificationReceipt,
) -> _RuntimeBuildIdentityEvidence:
    if probe is None or not callable(getattr(probe, "observe", None)):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "staging runtime build identity probe is required"
        )
    if (
        getattr(probe, "credential_sha256", None)
        != source.runtime_probe_credential_sha256
        or getattr(probe, "credential_path_sha256", None)
        != source.runtime_probe_credential_path_sha256
        or getattr(probe, "origin_sha256", None) != source.runtime_origin_sha256
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "runtime build probe identity differs from ADR-DC-083"
        )
    first = probe.observe()
    second = probe.observe()
    if (
        type(first) is not _RuntimeBuildIdentityEvidence
        or type(second) is not _RuntimeBuildIdentityEvidence
        or first != second
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "runtime build identity changed between observations"
        )
    if (
        first.runtime_transport_class != source.runtime_transport_class
        or first.server_version != source.exact_source_version
        or first.worker_version != source.exact_source_version
        or first.server_commit_sha != source.merge_commit_sha
        or first.worker_commit_sha != source.merge_commit_sha
        or first.server_commit_sha != first.worker_commit_sha
        or first.server_commit_observable is not True
        or first.server_vcs_modified is not False
        or first.worker_frozen is not True
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "runtime build identity does not match exact staged deployment"
        )
    return first


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskStagingRuntimeVerificationReceipt,
        observation_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            observation_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, observation_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.verification_authenticated is not True
            or source.sha256 != receipt.staging_runtime_verification_sha256
            or receipt.runtime_build_identity_observation_sha256
            != observation_sha
        ):
            return None
        return MappingProxyType(
            {
                "staging_runtime_verification": source,
                "runtime_build_identity_observation_sha256": observation_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_staging_runtime_build_identity_authenticated,
    _get_live_staging_runtime_build_identity_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingRuntimeBuildIdentityReceipt:
    staging_runtime_verification_sha256: str
    post_staging_deployment_status_attestation_sha256: str
    status_completion_source_receipt_sha256: str
    deployment_status_authorization_sha256: str
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    deployment_authorization_sha256: str
    deployment_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    deployment_status_intent_sha256: str
    status_transaction_lock_sha256: str
    status_recovery_lock_sha256: str | None
    publisher_credential_config_sha256: str
    publisher_credential_path_sha256: str
    repository: str
    repository_id: str
    deployment_environment: str
    merge_commit_sha: str
    deployment_id: int
    deployment_node_id_sha256: str
    deployment_status_id: int
    deployment_status_node_id_sha256: str
    deployment_status_state: str
    deployment_status_environment: str
    status_completion_source: str
    status_source_action: str
    status_source_remote_write_performed: bool
    staging_runtime_verification_config_sha256: str
    runtime_probe_credential_sha256: str
    runtime_probe_credential_path_sha256: str
    runtime_origin_sha256: str
    runtime_transport_class: str
    exact_source_version: str
    source_runtime_observation_sha256: str
    runtime_build_identity_observation_sha256: str
    server_version: str
    server_commit_sha: str
    server_executable_sha256: str
    server_go_version: str
    server_module_path: str
    worker_version: str
    worker_commit_sha: str
    worker_code_sha256: str
    worker_artifact_sha256: str
    source_verified_at_utc: str
    verified_at_utc: str
    staging_runtime_verification_authenticated: bool = True
    functional_staging_runtime_verified: bool = True
    server_commit_identity_observable: bool = True
    server_commit_identity_verified: bool = True
    server_clean_build_verified: bool = True
    server_artifact_identity_verified: bool = True
    worker_frozen_build_verified: bool = True
    worker_commit_identity_verified: bool = True
    worker_source_identity_verified: bool = True
    worker_artifact_identity_verified: bool = True
    server_worker_commit_matched: bool = True
    double_build_identity_observation_matched: bool = True
    runtime_commit_identity_observable: bool = True
    runtime_commit_identity_verified: bool = True
    runtime_artifact_identity_verified: bool = True
    staging_runtime_build_identity_verified: bool = True
    success_deployment_status_ready: bool = True
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    verification_scope: str = PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_AUTHORITY
            or self.verification_scope
            != PILOT_EXACT_TASK_STAGING_RUNTIME_BUILD_IDENTITY_SCOPE
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity receipt identity is unsupported"
            )
        hex64_fields = (
            "staging_runtime_verification_sha256",
            "post_staging_deployment_status_attestation_sha256",
            "status_completion_source_receipt_sha256",
            "deployment_status_authorization_sha256",
            "staging_deployment_status_plan_sha256",
            "post_staging_deployment_attestation_sha256",
            "deployment_authorization_sha256",
            "deployment_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "deployment_status_intent_sha256",
            "status_transaction_lock_sha256",
            "publisher_credential_config_sha256",
            "publisher_credential_path_sha256",
            "deployment_node_id_sha256",
            "deployment_status_node_id_sha256",
            "staging_runtime_verification_config_sha256",
            "runtime_probe_credential_sha256",
            "runtime_probe_credential_path_sha256",
            "runtime_origin_sha256",
            "source_runtime_observation_sha256",
            "runtime_build_identity_observation_sha256",
            "server_executable_sha256",
            "worker_code_sha256",
            "worker_artifact_sha256",
        )
        for name in hex64_fields:
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(
                self.status_recovery_lock_sha256,
                name="status_recovery_lock_sha256",
            )
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.server_commit_sha, name="server_commit_sha")
        _hex40(self.worker_commit_sha, name="worker_commit_sha")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_status_state != "in_progress"
            or self.deployment_status_environment != "staging"
            or self.status_completion_source not in {"transaction", "recovery"}
            or self.status_source_action
            not in {
                "execute_exact_first_staging_deployment_status",
                "finalize_existing_state",
            }
            or not isinstance(self.status_source_remote_write_performed, bool)
            or isinstance(self.deployment_id, bool)
            or not isinstance(self.deployment_id, int)
            or self.deployment_id < 1
            or isinstance(self.deployment_status_id, bool)
            or not isinstance(self.deployment_status_id, int)
            or self.deployment_status_id < 1
            or _VERSION.fullmatch(self.exact_source_version) is None
            or self.server_version != self.exact_source_version
            or self.worker_version != self.exact_source_version
            or self.server_commit_sha != self.merge_commit_sha
            or self.worker_commit_sha != self.merge_commit_sha
            or self.server_commit_sha != self.worker_commit_sha
            or self.runtime_transport_class
            not in {"loopback-http", "private-https"}
            or not self.server_go_version.startswith("go1.")
            or self.server_module_path != "modelrig"
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity projection is invalid"
            )
        if self.status_completion_source == "transaction":
            if (
                self.status_source_action
                != "execute_exact_first_staging_deployment_status"
                or self.status_source_remote_write_performed is not True
                or self.status_recovery_lock_sha256 is not None
            ):
                raise PilotExactTaskStagingRuntimeBuildIdentityError(
                    "normal first-status completion source is inconsistent"
                )
        elif (
            self.status_source_action != "finalize_existing_state"
            or self.status_source_remote_write_performed is not False
            or self.status_recovery_lock_sha256 is None
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "recovered first-status completion source is inconsistent"
            )
        if _utc(self.verified_at_utc, name="verified_at_utc") < _utc(
            self.source_verified_at_utc,
            name="source_verified_at_utc",
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "build identity verification predates ADR-DC-083"
            )
        required_true = (
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
        )
        forced_false = (
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
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def verification_authenticated(self) -> bool:
        return _get_live_staging_runtime_build_identity_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _verify_pilot_exact_task_staging_runtime_build_identity(
    *,
    staging_runtime_verification: PilotExactTaskStagingRuntimeVerificationReceipt,
    probe: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingRuntimeBuildIdentityReceipt:
    source = _require_live_runtime_verification(staging_runtime_verification)
    observation = _double_observe_build_identity(probe, source=source)
    verified_at = now_provider()
    if _utc(verified_at, name="verified_at_utc") < _utc(
        source.verified_at_utc,
        name="source_verified_at_utc",
    ):
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "system clock moved backwards before build identity verification"
        )
    receipt = PilotExactTaskStagingRuntimeBuildIdentityReceipt(
        staging_runtime_verification_sha256=source.sha256,
        post_staging_deployment_status_attestation_sha256=(
            source.post_staging_deployment_status_attestation_sha256
        ),
        status_completion_source_receipt_sha256=(
            source.status_completion_source_receipt_sha256
        ),
        deployment_status_authorization_sha256=(
            source.deployment_status_authorization_sha256
        ),
        staging_deployment_status_plan_sha256=(
            source.staging_deployment_status_plan_sha256
        ),
        post_staging_deployment_attestation_sha256=(
            source.post_staging_deployment_attestation_sha256
        ),
        deployment_authorization_sha256=source.deployment_authorization_sha256,
        deployment_intent_sha256=source.deployment_intent_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        deployment_status_intent_sha256=source.deployment_status_intent_sha256,
        status_transaction_lock_sha256=source.status_transaction_lock_sha256,
        status_recovery_lock_sha256=source.status_recovery_lock_sha256,
        publisher_credential_config_sha256=(
            source.publisher_credential_config_sha256
        ),
        publisher_credential_path_sha256=source.publisher_credential_path_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        deployment_environment=source.deployment_environment,
        merge_commit_sha=source.merge_commit_sha,
        deployment_id=source.deployment_id,
        deployment_node_id_sha256=source.deployment_node_id_sha256,
        deployment_status_id=source.deployment_status_id,
        deployment_status_node_id_sha256=source.deployment_status_node_id_sha256,
        deployment_status_state=source.deployment_status_state,
        deployment_status_environment=source.deployment_status_environment,
        status_completion_source=source.status_completion_source,
        status_source_action=source.status_source_action,
        status_source_remote_write_performed=(
            source.status_source_remote_write_performed
        ),
        staging_runtime_verification_config_sha256=(
            source.staging_runtime_verification_config_sha256
        ),
        runtime_probe_credential_sha256=source.runtime_probe_credential_sha256,
        runtime_probe_credential_path_sha256=(
            source.runtime_probe_credential_path_sha256
        ),
        runtime_origin_sha256=source.runtime_origin_sha256,
        runtime_transport_class=source.runtime_transport_class,
        exact_source_version=source.exact_source_version,
        source_runtime_observation_sha256=source.runtime_observation_sha256,
        runtime_build_identity_observation_sha256=observation.sha256,
        server_version=observation.server_version,
        server_commit_sha=observation.server_commit_sha,
        server_executable_sha256=observation.server_executable_sha256,
        server_go_version=observation.server_go_version,
        server_module_path=observation.server_module_path,
        worker_version=observation.worker_version,
        worker_commit_sha=observation.worker_commit_sha,
        worker_code_sha256=observation.worker_code_sha256,
        worker_artifact_sha256=observation.worker_artifact_sha256,
        source_verified_at_utc=source.verified_at_utc,
        verified_at_utc=verified_at,
    )
    _mark_staging_runtime_build_identity_authenticated(
        receipt,
        source=source,
        observation_sha256=observation.sha256,
    )
    if receipt.verification_authenticated is not True:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "staging runtime build identity lost live provenance"
        )
    return receipt


def _canonical_probe(
    source: PilotExactTaskStagingRuntimeVerificationReceipt,
) -> _StagingRuntimeBuildIdentityProbe:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            config_path = runtime_boundary._POSIX_CONFIG
            credential_path = runtime_boundary._POSIX_PROBE_CREDENTIAL
        elif os.name == "nt":
            config_path = runtime_boundary._WINDOWS_CONFIG
            credential_path = runtime_boundary._WINDOWS_PROBE_CREDENTIAL
        else:
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "staging runtime build identity platform is unsupported"
            )
        config_payload = runtime_boundary._read_host_file(
            config_path,
            name="staging runtime verification config",
        )
        config = runtime_boundary._parse_config(config_payload)
        config_sha = hashlib.sha256(config_payload).hexdigest()
        credential_payload = runtime_boundary._read_host_file(
            credential_path,
            name="staging runtime probe credential",
        )
        credential = runtime_boundary._parse_probe_credential(credential_payload)
        credential_sha = hashlib.sha256(credential_payload).hexdigest()
        if (
            config_sha != source.staging_runtime_verification_config_sha256
            or config.sha256 != config_sha
            or credential_sha != source.runtime_probe_credential_sha256
            or credential.sha256 != credential_sha
            or _path_sha256(credential_path)
            != source.runtime_probe_credential_path_sha256
            or _sha256_text(runtime_boundary._runtime_origin(config.runtime_origin)[0])
            != source.runtime_origin_sha256
        ):
            raise PilotExactTaskStagingRuntimeBuildIdentityError(
                "host-pinned runtime build inputs differ from ADR-DC-083"
            )
        return _StagingRuntimeBuildIdentityProbe(
            config=config,
            credential=credential,
            credential_sha256=credential_sha,
            credential_path=credential_path,
        )
    except PilotExactTaskStagingRuntimeBuildIdentityError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskStagingRuntimeBuildIdentityError(
            "staging runtime build identity runtime is not host-admin controlled"
        ) from exc


def verify_pilot_exact_task_staging_runtime_build_identity(
    staging_runtime_verification: PilotExactTaskStagingRuntimeVerificationReceipt,
) -> PilotExactTaskStagingRuntimeBuildIdentityReceipt:
    """Verify exact staging commit/artifact identity without write authority."""
    source = _require_live_runtime_verification(staging_runtime_verification)
    probe = _canonical_probe(source)
    return _verify_pilot_exact_task_staging_runtime_build_identity(
        staging_runtime_verification=source,
        probe=probe,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []

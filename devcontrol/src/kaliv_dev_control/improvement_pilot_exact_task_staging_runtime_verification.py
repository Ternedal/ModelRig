"""ADR-DC-083 read-only functional staging runtime verification.

Consumes one fresh live ADR-DC-082 post-Deployment-Status attestation plus
host-admin-pinned runtime probe configuration/credential.  It verifies the
VERSION file at the exact deployed merge SHA and performs two stable GET-only
runtime observations against ModelRig's existing /healthz and authenticated
/api/v1/health/deep contract.

V1 deliberately proves functional staging runtime plus exact source VERSION
matching.  It does not claim runtime byte/commit identity because the current
runtime endpoints do not expose an immutable build commit.  No Deployment
Status, Deployment, release, production, or other remote mutation is performed
or authorized.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from ._improvement_pilot_start_consumption_impl import _path_sha256
from . import github_read as github_read_boundary
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_remote_publication_transaction as publication_tx_boundary
from . import improvement_pilot_exact_task_post_staging_deployment_status_attestation as post_status_boundary
from .improvement_pilot_exact_task_post_staging_deployment_status_attestation import (
    PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_AUTHORITY,
    PilotExactTaskPostStagingDeploymentStatusAttestationReceipt,
)
from .improvement_pilot_exact_task_remote_publication_transaction import PilotExactTaskGitHubPublisherCredential

PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCHEMA = "kaliv-rsi-dc-l16-exact-task-staging-runtime-verification-receipt/v1"
PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_AUTHORITY = "host-verified-one-dc-l16-functional-staging-runtime-only"
PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCOPE = "read-only-functional-staging-runtime-and-exact-version-verification-v1"
PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_CONFIG_SCHEMA = "kaliv-rsi-dc-l16-exact-task-staging-runtime-verification-config/v1"
PILOT_EXACT_TASK_STAGING_RUNTIME_PROBE_CREDENTIAL_SCHEMA = "kaliv-rsi-dc-l16-exact-task-staging-runtime-probe-credential/v1"

_GITHUB_API_ROOT = "https://api.github.com"
_HEALTH_PATH = "/healthz"
_DEEP_HEALTH_PATH = "/api/v1/health/deep"
_HEALTH_SERVICE = "modelrig-server"
_TIMEOUT_SECONDS = 10.0
_MAX_RESPONSE_BYTES = 1024 * 1024
_MAX_FILE_BYTES = 1024 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_VERSION = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_SHARED_V4 = ipaddress.ip_network("100.64.0.0/10")

_POSIX_CONFIG = Path("/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-staging-runtime-verification-config-v1.json")
_WINDOWS_CONFIG = Path(r"C:\Program Files\ModelRig\DevControl\authority") / "rsi-pilot-exact-task-staging-runtime-verification-config-v1.json"
_POSIX_PROBE_CREDENTIAL = Path("/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-staging-runtime-probe-credential-v1.json")
_WINDOWS_PROBE_CREDENTIAL = Path(r"C:\Program Files\ModelRig\DevControl\authority") / "rsi-pilot-exact-task-staging-runtime-probe-credential-v1.json"


class PilotExactTaskStagingRuntimeVerificationError(ValueError):
    """Staging runtime evidence is stale, ambiguous, weak, or over-broad."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime evidence is not canonical JSON") from exc


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _runtime_origin(value: Any) -> tuple[str, str]:
    if not isinstance(value, str) or value.strip() != value:
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin is invalid")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin port is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or not parsed.hostname
        or port is None
        or not 1 <= port <= 65535
    ):
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin must be one exact IP-literal origin with explicit port")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin hostname must be an IP literal") from exc
    shared = isinstance(address, ipaddress.IPv4Address) and address in _SHARED_V4
    if address.is_unspecified or address.is_multicast or not (address.is_loopback or address.is_private or shared):
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin must stay on loopback/private/shared staging address space")
    if parsed.scheme == "http" and not address.is_loopback:
        raise PilotExactTaskStagingRuntimeVerificationError("plaintext staging runtime probing is restricted to loopback")
    host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    canonical = f"{parsed.scheme}://{host}:{port}"
    if value != canonical:
        raise PilotExactTaskStagingRuntimeVerificationError("runtime_origin is not canonical")
    return canonical, "loopback-http" if parsed.scheme == "http" else "private-https"


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingRuntimeVerificationConfig:
    repository: str
    repository_id: str
    deployment_environment: str
    runtime_origin: str
    health_path: str = _HEALTH_PATH
    deep_health_path: str = _DEEP_HEALTH_PATH
    health_service: str = _HEALTH_SERVICE
    require_exact_source_version: bool = True
    require_deep_health: bool = True
    require_ollama_ok: bool = True
    require_worker_ok: bool = True
    require_nonempty_model_inventory: bool = True
    require_embedding_round_trip: bool = True
    allow_runtime_commit_identity_claim: bool = False
    schema: str = PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_CONFIG_SCHEMA:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config schema is unsupported")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None or self.deployment_environment != "staging":
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config repository/environment is invalid")
        _runtime_origin(self.runtime_origin)
        if (
            self.health_path != _HEALTH_PATH
            or self.deep_health_path != _DEEP_HEALTH_PATH
            or self.health_service != _HEALTH_SERVICE
            or self.require_exact_source_version is not True
            or self.require_deep_health is not True
            or self.require_ollama_ok is not True
            or self.require_worker_ok is not True
            or self.require_nonempty_model_inventory is not True
            or self.require_embedding_round_trip is not True
            or self.allow_runtime_commit_identity_claim is not False
        ):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config weakens fixed v1 verification requirements")

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


@dataclass(frozen=True, slots=True)
class PilotExactTaskStagingRuntimeProbeCredential:
    token: str
    schema: str = PILOT_EXACT_TASK_STAGING_RUNTIME_PROBE_CREDENTIAL_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_RUNTIME_PROBE_CREDENTIAL_SCHEMA or not isinstance(self.token, str) or _HEX64.fullmatch(self.token) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential is invalid")

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def to_dict(self) -> dict[str, Any]:
        return {"token": self.token, "schema": self.schema}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != {"token", "schema"}:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskStagingRuntimeVerificationConfig:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config JSON is invalid") from exc
    config = PilotExactTaskStagingRuntimeVerificationConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config is not canonical JSON")
    return config


def _parse_probe_credential(payload: bytes) -> PilotExactTaskStagingRuntimeProbeCredential:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_FILE_BYTES:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential payload is invalid")
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential JSON is invalid") from exc
    credential = PilotExactTaskStagingRuntimeProbeCredential.from_mapping(raw)
    if credential.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential is not canonical JSON")
    return credential


def _read_host_file(path: Path, *, name: str) -> bytes:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is not host-admin controlled") from exc
    if first != second:
        raise PilotExactTaskStagingRuntimeVerificationError(f"{name} changed while being read")
    return second


def _require_live_post_status(value: Any) -> PilotExactTaskPostStagingDeploymentStatusAttestationReceipt:
    if type(value) is not PilotExactTaskPostStagingDeploymentStatusAttestationReceipt:
        raise PilotExactTaskStagingRuntimeVerificationError("exact live ADR-DC-082 post-status attestation is required")
    try:
        replayed = PilotExactTaskPostStagingDeploymentStatusAttestationReceipt.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("ADR-DC-082 replay validation failed") from exc
    required_true = (
        "durable_completion_verified", "exact_parent_deployment_verified", "exact_remote_deployment_status_verified",
        "exact_status_identity_verified", "exact_status_state_verified", "exact_status_environment_verified",
        "exact_status_description_verified", "status_urls_absent_verified", "double_observation_matched",
        "post_staging_deployment_status_verified",
    )
    forced_false = (
        "deployment_status_mutation_authorized", "deployment_mutation_authorized", "deploy_authorized",
        "remote_write_authorized", "release_authorized", "tag_write_authorized", "release_mutation_authorized",
        "merge_authorized", "push_authorized", "pr_mutation_authorized", "review_submission_authorized",
        "review_thread_mutation_authorized", "production_activation_authorized", "product_pilot_started", "nonce_reusable",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_POST_STAGING_DEPLOYMENT_STATUS_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or value.deployment_environment != "staging"
        or value.deployment_status_state != "in_progress"
        or value.deployment_status_environment != "staging"
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskStagingRuntimeVerificationError("ADR-DC-083 requires one fresh inert ADR-DC-082 attestation")
    live = post_status_boundary._get_live_post_staging_deployment_status_attestation_inputs(value)
    if (
        live is None
        or live.get("status_completion_source") != value.status_completion_source
        or live.get("status_completion_source_receipt_sha256") != value.status_completion_source_receipt_sha256
        or live.get("remote_status_observation_sha256") != value.remote_status_observation_sha256
    ):
        raise PilotExactTaskStagingRuntimeVerificationError("ADR-DC-082 live provenance is unavailable")
    return value


@dataclass(frozen=True, slots=True)
class _ExactVersionEvidence:
    repository: str
    repository_id: str
    merge_commit_sha: str
    version: str
    version_blob_sha1: str

    def __post_init__(self) -> None:
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("exact source VERSION repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None or not isinstance(self.version, str) or _VERSION.fullmatch(self.version) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("exact source VERSION evidence is invalid")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.version_blob_sha1, name="version_blob_sha1")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical(self.to_dict()))


@dataclass(frozen=True, slots=True)
class _RuntimeProbeEvidence:
    runtime_origin_sha256: str
    runtime_transport_class: str
    health_service: str
    health_status: str
    health_version: str
    deep_health_ok: bool
    ollama_ok: bool
    ollama_model_count: int
    worker_ok: bool
    worker_embed_dims: int

    def __post_init__(self) -> None:
        _hex64(self.runtime_origin_sha256, name="runtime_origin_sha256")
        if self.runtime_transport_class not in {"loopback-http", "private-https"}:
            raise PilotExactTaskStagingRuntimeVerificationError("runtime transport class is invalid")
        if not isinstance(self.health_service, str) or not self.health_service or not isinstance(self.health_status, str) or not self.health_status:
            raise PilotExactTaskStagingRuntimeVerificationError("runtime health identity is invalid")
        if not isinstance(self.health_version, str) or _VERSION.fullmatch(self.health_version) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("runtime health version is invalid")
        for name in ("deep_health_ok", "ollama_ok", "worker_ok"):
            if not isinstance(getattr(self, name), bool):
                raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is invalid")
        for name in ("ollama_model_count", "worker_embed_dims"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PilotExactTaskStagingRuntimeVerificationError(f"{name} is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @property
    def sha256(self) -> str:
        return _sha256_text(_canonical(self.to_dict()))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _GitHubExactVersionObserver:
    """Credential-bound exact VERSION reader over the hardened GitHub GET transport."""

    def __init__(self, *, credential: PilotExactTaskGitHubPublisherCredential, credential_config_sha256: str, credential_path: Path, transport: Any | None = None) -> None:
        if type(credential) is not PilotExactTaskGitHubPublisherCredential:
            raise PilotExactTaskStagingRuntimeVerificationError("exact publisher credential is required")
        self.credential = credential
        self.credential_config_sha256 = _hex64(credential_config_sha256, name="publisher_credential_config_sha256")
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute():
            raise PilotExactTaskStagingRuntimeVerificationError("publisher credential path is unsafe")
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        try:
            self._transport = github_read_boundary.UrllibReadOnlyTransport() if transport is None else transport
        except Exception as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("hardened GitHub VERSION transport is unavailable") from exc

    def observe(self, source: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt) -> _ExactVersionEvidence:
        if self.credential.repository != source.repository or self.credential.repository_id != source.repository_id:
            raise PilotExactTaskStagingRuntimeVerificationError("publisher credential is not bound to exact source repository")
        owner, repo = source.repository.split("/", 1)
        path = "/repos/{}/{}/contents/VERSION?{}".format(
            urllib.parse.quote(owner, safe=""), urllib.parse.quote(repo, safe=""), urllib.parse.urlencode({"ref": source.merge_commit_sha})
        )
        url = _GITHUB_API_ROOT + path
        try:
            response = self._transport.get(
                url,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {self.credential.token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                    "User-Agent": "ModelRig-DevControl-ExactStagingRuntimeVersion/1",
                },
                timeout_seconds=10,
                max_bytes=_MAX_RESPONSE_BYTES,
            )
        except Exception as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION GET failed closed") from exc
        if type(response) is not github_read_boundary.HttpResponse or response.status != 200 or "location" in response.headers:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION response identity/status is unexpected")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"application/json", "application/vnd.github+json"} or not response.body or len(response.body) > _MAX_RESPONSE_BYTES:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION response media/size is invalid")
        try:
            item = json.loads(response.body.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION response is invalid JSON") from exc
        if (
            not isinstance(item, Mapping)
            or item.get("type") != "file"
            or item.get("name") != "VERSION"
            or item.get("path") != "VERSION"
            or item.get("encoding") != "base64"
            or not isinstance(item.get("content"), str)
            or isinstance(item.get("size"), bool)
            or not isinstance(item.get("size"), int)
            or not 0 <= item["size"] <= 4096
        ):
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION response shape is invalid")
        content = item["content"]
        if any(char.isspace() and char not in "\r\n" for char in content):
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION base64 contains unsupported whitespace")
        try:
            payload = base64.b64decode(content.replace("\r", "").replace("\n", ""), validate=True)
        except (ValueError, binascii.Error) as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION content is invalid base64") from exc
        if len(payload) != item["size"]:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION size differs from payload")
        try:
            blob_sha = github_read_boundary._git_blob_sha(payload)
        except Exception as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION blob identity could not be computed") from exc
        if item.get("sha") != blob_sha:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION blob identity mismatch")
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION is not UTF-8") from exc
        if not text.endswith("\n") or text.count("\n") != 1 or _VERSION.fullmatch(text[:-1]) is None:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub exact VERSION file is not canonical")
        return _ExactVersionEvidence(source.repository, source.repository_id, source.merge_commit_sha, text[:-1], blob_sha)


class _StagingRuntimeProbe:
    """Pinned-origin GET-only observer for ModelRig health and deep health."""

    def __init__(self, *, config: PilotExactTaskStagingRuntimeVerificationConfig, credential: PilotExactTaskStagingRuntimeProbeCredential, credential_sha256: str, credential_path: Path) -> None:
        if type(config) is not PilotExactTaskStagingRuntimeVerificationConfig or type(credential) is not PilotExactTaskStagingRuntimeProbeCredential:
            raise PilotExactTaskStagingRuntimeVerificationError("exact staging runtime config/credential is required")
        self.config = config
        self.credential = credential
        self.credential_sha256 = _hex64(credential_sha256, name="runtime_probe_credential_sha256")
        if credential.sha256 != self.credential_sha256:
            raise PilotExactTaskStagingRuntimeVerificationError("runtime probe credential digest mismatch")
        self.credential_path = Path(credential_path)
        if not self.credential_path.is_absolute():
            raise PilotExactTaskStagingRuntimeVerificationError("runtime probe credential path is unsafe")
        self.credential_path_sha256 = _path_sha256(self.credential_path)
        self.origin, self.transport_class = _runtime_origin(config.runtime_origin)
        self.origin_sha256 = _sha256_text(self.origin)
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())

    def _get_json(self, path: str, *, authenticated: bool) -> Mapping[str, Any]:
        if path not in {_HEALTH_PATH, _DEEP_HEALTH_PATH}:
            raise PilotExactTaskStagingRuntimeVerificationError("runtime probe path is outside fixed health scope")
        url = self.origin + path
        headers = {"Accept": "application/json", "User-Agent": "ModelRig-DevControl-ExactStagingRuntimeProbe/1"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self.credential.token}"
        request = urllib.request.Request(url, method="GET", headers=headers)
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            raise PilotExactTaskStagingRuntimeVerificationError(f"staging runtime GET failed with HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime GET failed") from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskStagingRuntimeVerificationError("staging runtime response identity/status is unexpected")
            content_type = response.headers.get_content_type()
            raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if content_type != "application/json" or not raw or len(raw) > _MAX_RESPONSE_BYTES:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime response media/size is invalid")
        try:
            value = json.loads(raw.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime response is invalid JSON") from exc
        if not isinstance(value, Mapping):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime response must be a JSON object")
        return value

    def observe(self) -> _RuntimeProbeEvidence:
        health = self._get_json(_HEALTH_PATH, authenticated=False)
        if set(health) != {"status", "service", "version"}:
            raise PilotExactTaskStagingRuntimeVerificationError("staging /healthz response fields differ from fixed contract")
        deep = self._get_json(_DEEP_HEALTH_PATH, authenticated=True)
        if set(deep) != {"ok", "checks"} or not isinstance(deep.get("checks"), Mapping):
            raise PilotExactTaskStagingRuntimeVerificationError("staging deep-health response fields differ from fixed contract")
        checks = deep["checks"]
        if set(checks) != {"ollama", "worker"} or not isinstance(checks["ollama"], Mapping) or not isinstance(checks["worker"], Mapping):
            raise PilotExactTaskStagingRuntimeVerificationError("staging deep-health check set is invalid")
        ollama, worker = checks["ollama"], checks["worker"]
        if not {"ok", "latency_ms", "models"}.issubset(ollama) or not {"ok", "latency_ms", "embed_dims"}.issubset(worker):
            raise PilotExactTaskStagingRuntimeVerificationError("staging deep-health evidence is incomplete")
        for check, name in ((ollama, "ollama"), (worker, "worker")):
            latency = check.get("latency_ms")
            if isinstance(latency, bool) or not isinstance(latency, int) or latency < 0:
                raise PilotExactTaskStagingRuntimeVerificationError(f"{name} deep-health latency is invalid")
        models, embed_dims = ollama.get("models"), worker.get("embed_dims")
        if isinstance(models, bool) or not isinstance(models, int) or models < 0 or isinstance(embed_dims, bool) or not isinstance(embed_dims, int) or embed_dims < 0:
            raise PilotExactTaskStagingRuntimeVerificationError("deep-health model/embed metrics are invalid")
        return _RuntimeProbeEvidence(
            self.origin_sha256,
            self.transport_class,
            health.get("service"),
            health.get("status"),
            health.get("version"),
            deep.get("ok") is True,
            ollama.get("ok") is True,
            models,
            worker.get("ok") is True,
            embed_dims,
        )


def _double_observe_version(observer: Any, source: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt) -> _ExactVersionEvidence:
    if observer is None or not callable(getattr(observer, "observe", None)):
        raise PilotExactTaskStagingRuntimeVerificationError("exact source VERSION observer is required")
    if getattr(observer, "credential_config_sha256", None) != source.publisher_credential_config_sha256 or getattr(observer, "credential_path_sha256", None) != source.publisher_credential_path_sha256:
        raise PilotExactTaskStagingRuntimeVerificationError("source VERSION observer credential differs from ADR-DC-082")
    first, second = observer.observe(source), observer.observe(source)
    if type(first) is not _ExactVersionEvidence or type(second) is not _ExactVersionEvidence or first != second:
        raise PilotExactTaskStagingRuntimeVerificationError("exact source VERSION changed or returned invalid evidence")
    if first.repository != source.repository or first.repository_id != source.repository_id or first.merge_commit_sha != source.merge_commit_sha:
        raise PilotExactTaskStagingRuntimeVerificationError("exact source VERSION evidence differs from deployment identity")
    return first


def _double_observe_runtime(probe: Any, *, config: PilotExactTaskStagingRuntimeVerificationConfig, credential_sha256: str, credential_path_sha256: str) -> _RuntimeProbeEvidence:
    if probe is None or not callable(getattr(probe, "observe", None)):
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe is required")
    if (
        getattr(probe, "credential_sha256", None) != credential_sha256
        or getattr(probe, "credential_path_sha256", None) != credential_path_sha256
        or getattr(probe, "origin_sha256", None) != _sha256_text(_runtime_origin(config.runtime_origin)[0])
    ):
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe identity differs from host-pinned config")
    first, second = probe.observe(), probe.observe()
    if type(first) is not _RuntimeProbeEvidence or type(second) is not _RuntimeProbeEvidence or first != second:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime normalized evidence changed or is invalid")
    return first


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(receipt: Any, *, source: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt, config_sha256: str, source_version_sha256: str, runtime_observation_sha256: str) -> None:
        key = id(receipt)
        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)
        records[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup), weakref.ref(source), config_sha256, source_version_sha256, runtime_observation_sha256)

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, config_sha, version_sha, runtime_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.attestation_authenticated is not True
            or source.sha256 != receipt.post_staging_deployment_status_attestation_sha256
            or receipt.staging_runtime_verification_config_sha256 != config_sha
            or receipt.source_version_observation_sha256 != version_sha
            or receipt.runtime_observation_sha256 != runtime_sha
        ):
            return None
        return MappingProxyType({
            "post_staging_deployment_status_attestation": source,
            "staging_runtime_verification_config_sha256": config_sha,
            "source_version_observation_sha256": version_sha,
            "runtime_observation_sha256": runtime_sha,
        })

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_staging_runtime_verification_authenticated, _get_live_staging_runtime_verification_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskStagingRuntimeVerificationReceipt:
    post_staging_deployment_status_attestation_sha256: str
    status_completion_source_receipt_sha256: str
    deployment_status_authorization_sha256: str
    deployment_status_state_observation_sha256: str
    staging_deployment_status_plan_sha256: str
    post_staging_deployment_attestation_sha256: str
    upstream_completion_source_receipt_sha256: str
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
    deployment_status_description_sha256: str
    deployment_status_body_sha256: str
    status_completion_source: str
    status_source_action: str
    status_source_remote_write_performed: bool
    source_attested_at_utc: str
    staging_runtime_verification_config_sha256: str
    runtime_probe_credential_sha256: str
    runtime_probe_credential_path_sha256: str
    runtime_origin_sha256: str
    runtime_transport_class: str
    exact_source_version: str
    exact_source_version_blob_sha1: str
    source_version_observation_sha256: str
    runtime_observation_sha256: str
    health_service: str
    health_status: str
    health_version: str
    ollama_model_count: int
    worker_embed_dims: int
    verified_at_utc: str
    post_status_attestation_authenticated: bool = True
    exact_deployment_status_verified: bool = True
    staging_runtime_config_host_pinned: bool = True
    runtime_probe_credential_host_pinned: bool = True
    exact_source_version_observed: bool = True
    runtime_health_verified: bool = True
    runtime_deep_health_verified: bool = True
    ollama_runtime_verified: bool = True
    worker_runtime_verified: bool = True
    model_inventory_nonempty: bool = True
    embedding_round_trip_verified: bool = True
    runtime_version_matches_exact_source: bool = True
    double_source_version_observation_matched: bool = True
    double_runtime_observation_matched: bool = True
    functional_staging_runtime_verified: bool = True
    runtime_commit_identity_observable: bool = False
    runtime_commit_identity_verified: bool = False
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
    verification_scope: str = PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCOPE
    authority: str = PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCHEMA or self.authority != PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_AUTHORITY or self.verification_scope != PILOT_EXACT_TASK_STAGING_RUNTIME_VERIFICATION_SCOPE:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification identity is unsupported")
        hex64_fields = (
            "post_staging_deployment_status_attestation_sha256", "status_completion_source_receipt_sha256",
            "deployment_status_authorization_sha256", "deployment_status_state_observation_sha256",
            "staging_deployment_status_plan_sha256", "post_staging_deployment_attestation_sha256",
            "upstream_completion_source_receipt_sha256", "deployment_authorization_sha256", "deployment_intent_sha256",
            "execution_nonce_sha256", "development_task_sha256", "candidate_patch_sha256", "pr_intent_sha256",
            "deployment_status_intent_sha256", "status_transaction_lock_sha256", "publisher_credential_config_sha256",
            "publisher_credential_path_sha256", "deployment_node_id_sha256", "deployment_status_node_id_sha256",
            "deployment_status_description_sha256", "deployment_status_body_sha256", "staging_runtime_verification_config_sha256",
            "runtime_probe_credential_sha256", "runtime_probe_credential_path_sha256", "runtime_origin_sha256",
            "source_version_observation_sha256", "runtime_observation_sha256",
        )
        for name in hex64_fields:
            _hex64(getattr(self, name), name=name)
        if self.status_recovery_lock_sha256 is not None:
            _hex64(self.status_recovery_lock_sha256, name="status_recovery_lock_sha256")
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.exact_source_version_blob_sha1, name="exact_source_version_blob_sha1")
        if (
            not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None
            or self.deployment_environment != "staging"
            or self.deployment_status_state != "in_progress"
            or self.deployment_status_environment != "staging"
            or isinstance(self.deployment_id, bool) or not isinstance(self.deployment_id, int) or self.deployment_id < 1
            or isinstance(self.deployment_status_id, bool) or not isinstance(self.deployment_status_id, int) or self.deployment_status_id < 1
            or self.status_completion_source not in {"transaction", "recovery"}
            or self.status_source_action not in {"execute_exact_first_staging_deployment_status", "finalize_existing_state"}
            or not isinstance(self.status_source_remote_write_performed, bool)
            or _VERSION.fullmatch(self.exact_source_version) is None
            or self.health_service != _HEALTH_SERVICE or self.health_status != "ok" or self.health_version != self.exact_source_version
            or self.runtime_transport_class not in {"loopback-http", "private-https"}
            or isinstance(self.ollama_model_count, bool) or not isinstance(self.ollama_model_count, int) or self.ollama_model_count < 1
            or isinstance(self.worker_embed_dims, bool) or not isinstance(self.worker_embed_dims, int) or self.worker_embed_dims < 1
        ):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification projection is invalid")
        if self.status_completion_source == "transaction":
            if self.status_source_action != "execute_exact_first_staging_deployment_status" or self.status_source_remote_write_performed is not True or self.status_recovery_lock_sha256 is not None:
                raise PilotExactTaskStagingRuntimeVerificationError("normal first-status completion source is inconsistent")
        elif self.status_source_action != "finalize_existing_state" or self.status_source_remote_write_performed is not False or self.status_recovery_lock_sha256 is None:
            raise PilotExactTaskStagingRuntimeVerificationError("recovered first-status completion source is inconsistent")
        if _utc(self.verified_at_utc, name="verified_at_utc") < _utc(self.source_attested_at_utc, name="source_attested_at_utc"):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification predates ADR-DC-082 attestation")
        required_true = (
            "post_status_attestation_authenticated", "exact_deployment_status_verified", "staging_runtime_config_host_pinned",
            "runtime_probe_credential_host_pinned", "exact_source_version_observed", "runtime_health_verified",
            "runtime_deep_health_verified", "ollama_runtime_verified", "worker_runtime_verified", "model_inventory_nonempty",
            "embedding_round_trip_verified", "runtime_version_matches_exact_source", "double_source_version_observation_matched",
            "double_runtime_observation_matched", "functional_staging_runtime_verified",
        )
        forced_false = (
            "runtime_commit_identity_observable", "runtime_commit_identity_verified", "success_deployment_status_authorized",
            "deployment_status_mutation_authorized", "deployment_mutation_authorized", "deploy_authorized", "remote_write_authorized",
            "release_authorized", "tag_write_authorized", "release_mutation_authorized", "merge_authorized", "push_authorized",
            "pr_mutation_authorized", "review_submission_authorized", "review_thread_mutation_authorized",
            "production_activation_authorized", "product_pilot_started", "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification evidence is incomplete")
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification retains forbidden authority/claims")

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    @property
    def verification_authenticated(self) -> bool:
        return _get_live_staging_runtime_verification_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification receipt fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _verify_pilot_exact_task_staging_runtime(
    *,
    post_status_attestation: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt,
    config: PilotExactTaskStagingRuntimeVerificationConfig,
    config_sha256: str,
    probe_credential: PilotExactTaskStagingRuntimeProbeCredential,
    probe_credential_sha256: str,
    probe_credential_path: Path,
    version_observer: Any,
    runtime_probe: Any,
    now_provider: Callable[[], str],
) -> PilotExactTaskStagingRuntimeVerificationReceipt:
    source = _require_live_post_status(post_status_attestation)
    if type(config) is not PilotExactTaskStagingRuntimeVerificationConfig:
        raise PilotExactTaskStagingRuntimeVerificationError("exact staging runtime config is required")
    config_digest = _hex64(config_sha256, name="staging_runtime_verification_config_sha256")
    credential_digest = _hex64(probe_credential_sha256, name="runtime_probe_credential_sha256")
    if config.sha256 != config_digest or type(probe_credential) is not PilotExactTaskStagingRuntimeProbeCredential or probe_credential.sha256 != credential_digest:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config/credential digest mismatch")
    probe_path = Path(probe_credential_path)
    if not probe_path.is_absolute():
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime probe credential path is unsafe")
    probe_path_sha = _path_sha256(probe_path)
    if config.repository != source.repository or config.repository_id != source.repository_id or config.deployment_environment != source.deployment_environment:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime config differs from exact deployed repository")
    source_version = _double_observe_version(version_observer, source)
    runtime = _double_observe_runtime(runtime_probe, config=config, credential_sha256=credential_digest, credential_path_sha256=probe_path_sha)
    if (
        runtime.health_service != _HEALTH_SERVICE
        or runtime.health_status != "ok"
        or runtime.deep_health_ok is not True
        or runtime.ollama_ok is not True
        or runtime.ollama_model_count < 1
        or runtime.worker_ok is not True
        or runtime.worker_embed_dims < 1
        or runtime.health_version != source_version.version
    ):
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime does not satisfy exact functional verification contract")
    verified_at = now_provider()
    if _utc(verified_at, name="verified_at_utc") < _utc(source.attested_at_utc, name="attested_at_utc"):
        raise PilotExactTaskStagingRuntimeVerificationError("system clock moved backwards before staging runtime verification")
    receipt = PilotExactTaskStagingRuntimeVerificationReceipt(
        post_staging_deployment_status_attestation_sha256=source.sha256,
        status_completion_source_receipt_sha256=source.status_completion_source_receipt_sha256,
        deployment_status_authorization_sha256=source.deployment_status_authorization_sha256,
        deployment_status_state_observation_sha256=source.deployment_status_state_observation_sha256,
        staging_deployment_status_plan_sha256=source.staging_deployment_status_plan_sha256,
        post_staging_deployment_attestation_sha256=source.post_staging_deployment_attestation_sha256,
        upstream_completion_source_receipt_sha256=source.upstream_completion_source_receipt_sha256,
        deployment_authorization_sha256=source.deployment_authorization_sha256,
        deployment_intent_sha256=source.deployment_intent_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        deployment_status_intent_sha256=source.deployment_status_intent_sha256,
        status_transaction_lock_sha256=source.status_transaction_lock_sha256,
        status_recovery_lock_sha256=source.status_recovery_lock_sha256,
        publisher_credential_config_sha256=source.publisher_credential_config_sha256,
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
        deployment_status_description_sha256=source.deployment_status_description_sha256,
        deployment_status_body_sha256=source.deployment_status_body_sha256,
        status_completion_source=source.status_completion_source,
        status_source_action=source.status_source_action,
        status_source_remote_write_performed=source.status_source_remote_write_performed,
        source_attested_at_utc=source.attested_at_utc,
        staging_runtime_verification_config_sha256=config_digest,
        runtime_probe_credential_sha256=credential_digest,
        runtime_probe_credential_path_sha256=probe_path_sha,
        runtime_origin_sha256=runtime.runtime_origin_sha256,
        runtime_transport_class=runtime.runtime_transport_class,
        exact_source_version=source_version.version,
        exact_source_version_blob_sha1=source_version.version_blob_sha1,
        source_version_observation_sha256=source_version.sha256,
        runtime_observation_sha256=runtime.sha256,
        health_service=runtime.health_service,
        health_status=runtime.health_status,
        health_version=runtime.health_version,
        ollama_model_count=runtime.ollama_model_count,
        worker_embed_dims=runtime.worker_embed_dims,
        verified_at_utc=verified_at,
    )
    _mark_staging_runtime_verification_authenticated(receipt, source=source, config_sha256=config_digest, source_version_sha256=source_version.sha256, runtime_observation_sha256=runtime.sha256)
    if receipt.verification_authenticated is not True:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification lost live provenance")
    return receipt


def _canonical_runtime(source: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt):
    try:
        _require_elevated_operator()
        if os.name == "posix":
            config_path, probe_credential_path = _POSIX_CONFIG, _POSIX_PROBE_CREDENTIAL
        elif os.name == "nt":
            config_path, probe_credential_path = _WINDOWS_CONFIG, _WINDOWS_PROBE_CREDENTIAL
        else:
            raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification platform is unsupported")
        config_payload = _read_host_file(config_path, name="staging runtime verification config")
        config = _parse_config(config_payload)
        config_sha = hashlib.sha256(config_payload).hexdigest()
        probe_payload = _read_host_file(probe_credential_path, name="staging runtime probe credential")
        probe_credential = _parse_probe_credential(probe_payload)
        probe_sha = hashlib.sha256(probe_payload).hexdigest()
        publisher_credential, publisher_sha, publisher_path = publication_tx_boundary._canonical_credential()
        if publisher_sha != source.publisher_credential_config_sha256 or _path_sha256(publisher_path) != source.publisher_credential_path_sha256:
            raise PilotExactTaskStagingRuntimeVerificationError("GitHub publisher credential differs from ADR-DC-082 provenance")
        version_observer = _GitHubExactVersionObserver(credential=publisher_credential, credential_config_sha256=publisher_sha, credential_path=publisher_path)
        runtime_probe = _StagingRuntimeProbe(config=config, credential=probe_credential, credential_sha256=probe_sha, credential_path=probe_credential_path)
        return config, config_sha, probe_credential, probe_sha, probe_credential_path, version_observer, runtime_probe
    except PilotExactTaskStagingRuntimeVerificationError:
        raise
    except (PhysicalHostStateError, ValueError, TypeError, OSError) as exc:
        raise PilotExactTaskStagingRuntimeVerificationError("staging runtime verification runtime is not host-admin controlled") from exc


def verify_pilot_exact_task_staging_runtime(
    post_staging_deployment_status_attestation: PilotExactTaskPostStagingDeploymentStatusAttestationReceipt,
) -> PilotExactTaskStagingRuntimeVerificationReceipt:
    """Verify functional staging runtime without granting success/write authority."""
    source = _require_live_post_status(post_staging_deployment_status_attestation)
    config, config_sha, probe_credential, probe_sha, probe_path, version_observer, runtime_probe = _canonical_runtime(source)
    return _verify_pilot_exact_task_staging_runtime(
        post_status_attestation=source,
        config=config,
        config_sha256=config_sha,
        probe_credential=probe_credential,
        probe_credential_sha256=probe_sha,
        probe_credential_path=probe_path,
        version_observer=version_observer,
        runtime_probe=runtime_probe,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []

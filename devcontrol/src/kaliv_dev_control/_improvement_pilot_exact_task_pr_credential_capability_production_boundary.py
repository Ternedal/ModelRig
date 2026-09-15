"""Host-pinned production boundary for ADR-DC-057 PR credential capability."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from .improvement_physical_authority_keyring import PhysicalRequestAuthorityKeyringError, _read_keyring_bytes, _require_host_control
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PR_CREDENTIAL_BROKER_POLICY_SCHEMA = "kaliv-rsi-pilot-exact-task-pr-credential-broker-policy/v1"
_MAX_BROKER_BYTES = 16 * 1024 * 1024
_POLICY_FIELDS = {
    "schema", "provider", "api_origin", "repository", "credential_protocol", "broker_version",
    "broker_executable_path", "broker_executable_sha256", "secret_source", "secret_transport",
    "pull_request_write_required", "repository_contents_write_forbidden", "administration_write_forbidden",
    "merge_write_forbidden", "release_write_forbidden",
}


class PilotExactTaskPrCredentialCapabilityProductionBoundaryError(ValueError):
    """Production PR credential-broker authority is unsafe or unavailable."""


def _canonical_policy_path() -> Path:
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\publication\rsi-pilot-exact-task-pr-credential-broker-policy-v1.json")
    if os.name == "posix":
        return Path("/etc/modelrig/devcontrol/publication/rsi-pilot-exact-task-pr-credential-broker-policy-v1.json")
    raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy platform is unsupported")


def _canonical_broker_path() -> Path:
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\bin\rsi-github-pr-broker-v1.exe")
    if os.name == "posix":
        return Path("/usr/local/libexec/modelrig/rsi-github-pr-broker-v1")
    raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable platform is unsupported")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy is not canonical JSON") from exc


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _parse_policy(payload: bytes, *, broker_path: Path) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy payload is missing")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy is invalid JSON") from exc
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy fields mismatch")
    expected = {
        "schema": PILOT_EXACT_TASK_PR_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": "https://api.github.com",
        "repository": "Ternedal/ModelRig",
        "credential_protocol": "github-rest-broker-v1",
        "broker_executable_path": os.fspath(broker_path),
        "secret_source": "host-secret-store-only",
        "secret_transport": "broker-owned-https-only",
        "pull_request_write_required": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "merge_write_forbidden": True,
        "release_write_forbidden": True,
    }
    mismatch = next((name for name, expected_value in expected.items() if value.get(name) != expected_value), None)
    if mismatch is not None:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError(f"PR credential-broker policy mismatch: {mismatch}")
    version = value.get("broker_version")
    digest = value.get("broker_executable_sha256")
    if (
        not isinstance(version, str) or not version or len(version) > 64 or any(character.isspace() for character in version)
        or not isinstance(digest, str) or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest) or digest == "0" * 64
    ):
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy version/hash is invalid")
    canonical = dict(value)
    if payload != _canonical_bytes(canonical):
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy is not byte-for-byte canonical")
    return canonical


def _read_broker_bytes(path: Path, *, require_host_control: bool) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable path is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable is missing or unreadable") from exc
    try:
        observed = os.fstat(descriptor)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1 or observed.st_size < 1 or observed.st_size > _MAX_BROKER_BYTES:
            raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable file is unsafe")
        if require_host_control:
            try:
                _require_host_control(candidate, observed)
            except PhysicalRequestAuthorityKeyringError as exc:
                raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable is not host-admin controlled") from exc
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable read was incomplete")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable changed while reading")
        after = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino, observed.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable identity changed during read")
        return b"".join(chunks)
    except OSError as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable could not be read safely") from exc
    finally:
        os.close(descriptor)


def _load_broker_descriptor_at(policy_path: Path, broker_path: Path, *, require_host_control: bool) -> Mapping[str, str]:
    try:
        payload = _read_keyring_bytes(Path(policy_path), require_host_control=require_host_control)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker policy could not be read safely") from exc
    policy = _parse_policy(payload, broker_path=Path(broker_path))
    broker_bytes = _read_broker_bytes(Path(broker_path), require_host_control=require_host_control)
    broker_sha256 = hashlib.sha256(broker_bytes).hexdigest()
    if broker_sha256 != policy["broker_executable_sha256"]:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential-broker executable hash does not match host policy")
    return {
        "broker_policy_sha256": hashlib.sha256(payload).hexdigest(),
        "broker_executable_path": os.fspath(Path(broker_path)),
        "broker_executable_path_sha256": _path_sha256(Path(broker_path)),
        "broker_executable_sha256": broker_sha256,
        "broker_version": str(policy["broker_version"]),
        "credential_protocol": str(policy["credential_protocol"]),
        "secret_source": str(policy["secret_source"]),
        "secret_transport": str(policy["secret_transport"]),
        "api_origin": str(policy["api_origin"]),
    }


def _canonical_broker_descriptor() -> Mapping[str, str]:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential capability requires an elevated host operator") from exc
    return _load_broker_descriptor_at(_canonical_policy_path(), _canonical_broker_path(), require_host_control=True)


def install_pilot_exact_task_pr_credential_capability_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PilotExactTaskPrCredentialCapabilityProductionBoundaryError("PR credential capability implementation is unavailable")
    marker = "_production_pilot_exact_task_pr_credential_capability_boundary_installed"
    if getattr(implementation, marker, False):
        return
    private_materialize = implementation._materialize_verified_pilot_exact_task_pr_credential_capability

    def materialize_pilot_exact_task_pr_credential_capability(pr_state_observation: Any) -> Any:
        try:
            descriptor = _canonical_broker_descriptor()
            return private_materialize(
                pr_state_observation=pr_state_observation,
                broker_descriptor=descriptor,
                now_provider=implementation._now_utc_seconds,
            )
        except implementation.PilotExactTaskPrCredentialCapabilityError:
            raise
        except (PilotExactTaskPrCredentialCapabilityProductionBoundaryError, ValueError, TypeError, AttributeError, OSError) as exc:
            raise implementation.PilotExactTaskPrCredentialCapabilityError("host-controlled PR credential capability failed closed") from exc

    implementation.materialize_pilot_exact_task_pr_credential_capability = materialize_pilot_exact_task_pr_credential_capability
    setattr(implementation, marker, True)


__all__: list[str] = []

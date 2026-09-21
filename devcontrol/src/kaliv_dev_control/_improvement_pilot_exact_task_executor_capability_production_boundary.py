"""Windows host-controlled production resolver for ADR-DC-036.

The public boundary accepts only the already-bound ADR-DC-035 artifact and the
same live ADR-DC-033 receipt.  Catalog, toolchain, isolation attestation,
physical verifier trust, runtime-closure trust, runtime roots, Trusted Git,
workspace and control-plane paths are resolved from host-admin-controlled state.
No caller-selected verifier/root/path/environment/process limit is authority.
"""
from __future__ import annotations

import json
import os
import re
from datetime import timedelta
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .catalog import (
    IsolationAttestation,
    TOOLCHAIN_SCHEMA,
    ToolBinding,
    Toolchain,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)
from .physical_isolation import WindowsPhysicalIsolationVerifier
from .runtime_closure_builder import (
    VERSION_CHECK_COMMAND_ID,
    modelrig_version_check_closure_catalog,
)
from .runtime_closure_model import SignedRuntimeClosureManifest
from .runtime_closure_verify import RuntimeClosureVerifier
from .trusted_git_runtime_runner import TrustedGitRunner
from .trusted_git_runtime_staging import TrustedGitRuntime

_EXECUTOR_PROFILE_SCHEMA = "kaliv-rsi-dc-l16-exact-task-executor-profile/v1"
_EXECUTOR_HMAC_KEYRING_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-executor-hmac-verification-keyring/v1"
)
_PHYSICAL_DOMAIN = "dc-l16-executor-physical-isolation"
_RUNTIME_DOMAIN = "dc-l16-executor-runtime-closure"
_MAX_PROFILE_BYTES = 256 * 1024
_MAX_KEYRING_BYTES = 256 * 1024
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_KEY_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")

_WINDOWS_AUTHORITY_ROOT = Path(r"C:\Program Files\ModelRig\DevControl\authority")
_WINDOWS_PROFILE = _WINDOWS_AUTHORITY_ROOT / "rsi-pilot-exact-task-executor-profile-v1.json"
_WINDOWS_PHYSICAL_KEYRING = (
    _WINDOWS_AUTHORITY_ROOT / "rsi-pilot-executor-physical-hmac-keyring-v1.json"
)
_WINDOWS_RUNTIME_KEYRING = (
    _WINDOWS_AUTHORITY_ROOT / "rsi-pilot-executor-runtime-closure-hmac-keyring-v1.json"
)


class PilotExactTaskExecutorCapabilityProductionBoundaryError(ValueError):
    """Canonical Windows executor capability state is unavailable or unsafe."""


def _canonical(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor authority file is not canonical JSON"
        ) from exc


def _require_windows_host() -> None:
    if os.name != "nt":
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "production exact-task executor capability requires native Windows"
        )
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "production exact-task executor capability requires an elevated host operator"
        ) from exc


def _read_host_controlled(path: Path, *, maximum: int) -> bytes:
    try:
        payload = _read_keyring_bytes(path, require_host_control=True)
    except (PhysicalRequestAuthorityKeyringError, OSError) as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor authority file is not host-admin controlled"
        ) from exc
    if not payload or len(payload) > maximum:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor authority file is empty or oversized"
        )
    return payload


def _parse_hmac_keyring(payload: bytes, *, expected_domain: str) -> dict[str, bytes]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_KEYRING_BYTES:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring bytes are invalid"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "authority_domain",
        "keys",
    }:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring fields mismatch"
        )
    if (
        value.get("schema") != _EXECUTOR_HMAC_KEYRING_SCHEMA
        or value.get("authority_domain") != expected_domain
    ):
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring domain/schema mismatch"
        )
    entries = value.get("keys")
    if not isinstance(entries, list) or not 1 <= len(entries) <= 32:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring entries are invalid"
        )
    result: dict[str, bytes] = {}
    previous: str | None = None
    canonical_entries: list[dict[str, str]] = []
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {"key_id", "secret_hex"}:
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                "executor HMAC keyring entry fields mismatch"
            )
        key_id = entry.get("key_id")
        secret_hex = entry.get("secret_hex")
        if (
            not isinstance(key_id, str)
            or _KEY_ID.fullmatch(key_id) is None
            or previous is not None
            and key_id <= previous
        ):
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                "executor HMAC key ids must be canonical, sorted and unique"
            )
        if (
            not isinstance(secret_hex, str)
            or len(secret_hex) % 2
            or not 64 <= len(secret_hex) <= 8192
            or re.fullmatch(r"[0-9a-f]+", secret_hex) is None
        ):
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                "executor HMAC secret encoding is invalid"
            )
        secret = bytes.fromhex(secret_hex)
        if not 32 <= len(secret) <= 4096:
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                "executor HMAC secret size is invalid"
            )
        previous = key_id
        result[key_id] = secret
        canonical_entries.append({"key_id": key_id, "secret_hex": secret_hex})
    canonical = {
        "schema": _EXECUTOR_HMAC_KEYRING_SCHEMA,
        "authority_domain": expected_domain,
        "keys": canonical_entries,
    }
    if payload != _canonical(canonical):
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor HMAC keyring is not canonical JSON"
        )
    return result


def _absolute_canonical_path(value: Any, *, name: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            f"executor profile {name} is invalid"
        )
    path = Path(value)
    if not path.is_absolute():
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            f"executor profile {name} must be absolute"
        )
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            f"executor profile {name} is unavailable"
        ) from exc
    if resolved != path:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            f"executor profile {name} must be canonical and link-free"
        )
    return path


def _parse_toolchain(value: Any) -> Toolchain:
    if not isinstance(value, Mapping) or set(value) != {"schema", "bindings"}:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile toolchain fields mismatch"
        )
    if value.get("schema") != TOOLCHAIN_SCHEMA:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile toolchain schema mismatch"
        )
    raw_bindings = value.get("bindings")
    if not isinstance(raw_bindings, list) or not raw_bindings:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile toolchain is empty"
        )
    bindings: list[ToolBinding] = []
    for raw in raw_bindings:
        if not isinstance(raw, Mapping) or set(raw) != {
            "tool_id",
            "executable",
            "executable_sha256",
        }:
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                "executor profile tool binding fields mismatch"
            )
        bindings.append(
            ToolBinding(
                raw["tool_id"],
                raw["executable"],
                raw["executable_sha256"],
            )
        )
    toolchain = Toolchain(tuple(bindings))
    if toolchain.to_dict() != value:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile toolchain is not canonical"
        )
    return toolchain


def _parse_profile(payload: bytes) -> dict[str, Any]:
    if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_PROFILE_BYTES:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile bytes are invalid"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile is invalid JSON"
        ) from exc
    fields = {
        "schema",
        "development_task_sha256",
        "fixed_command_id",
        "catalog_sha256",
        "toolchain",
        "isolation_attestation",
        "signed_runtime_closure",
        "physical_evidence_root",
        "trusted_runtime_root",
        "trusted_git_transaction_root",
        "trusted_git_operation_root",
        "workspace_root",
        "control_plane_root",
    }
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile fields mismatch"
        )
    if value.get("schema") != _EXECUTOR_PROFILE_SCHEMA:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile schema mismatch"
        )
    for name in ("development_task_sha256", "catalog_sha256"):
        item = value.get(name)
        if not isinstance(item, str) or _HEX64.fullmatch(item) is None or item == "0" * 64:
            raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
                f"executor profile {name} is invalid"
            )
    if value.get("fixed_command_id") != VERSION_CHECK_COMMAND_ID:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile command is not the reviewed version-check command"
        )
    catalog = modelrig_version_check_closure_catalog()
    if value.get("catalog_sha256") != catalog.sha256:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile catalog hash is not the reviewed catalog"
        )
    toolchain = _parse_toolchain(value.get("toolchain"))
    try:
        attestation = IsolationAttestation.from_mapping(value.get("isolation_attestation"))
        signed_closure = SignedRuntimeClosureManifest.from_mapping(
            value.get("signed_runtime_closure")
        )
    except Exception as exc:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile contains invalid Tier-A evidence"
        ) from exc
    paths = {
        name: _absolute_canonical_path(value.get(name), name=name)
        for name in (
            "physical_evidence_root",
            "trusted_runtime_root",
            "trusted_git_transaction_root",
            "trusted_git_operation_root",
            "workspace_root",
            "control_plane_root",
        )
    }
    canonical = {
        "schema": _EXECUTOR_PROFILE_SCHEMA,
        "development_task_sha256": value["development_task_sha256"],
        "fixed_command_id": VERSION_CHECK_COMMAND_ID,
        "catalog_sha256": catalog.sha256,
        "toolchain": toolchain.to_dict(),
        "isolation_attestation": attestation.to_dict(),
        "signed_runtime_closure": signed_closure.to_dict(),
        **{name: str(path) for name, path in paths.items()},
    }
    if payload != _canonical(canonical):
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile is not canonical JSON"
        )
    return {
        "catalog": catalog,
        "toolchain": toolchain,
        "attestation": attestation,
        "signed_closure": signed_closure,
        **paths,
        "development_task_sha256": value["development_task_sha256"],
    }


def _resolve_host_executor_materialization_inputs(
    *,
    development_task_sha256: str,
) -> dict[str, Any]:
    """Resolve the one canonical Windows Tier-A profile for an exact task hash."""
    _require_windows_host()
    profile = _parse_profile(
        _read_host_controlled(_WINDOWS_PROFILE, maximum=_MAX_PROFILE_BYTES)
    )
    if profile["development_task_sha256"] != development_task_sha256:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor profile is not pinned to the exact DevelopmentTask"
        )
    physical_keys = _parse_hmac_keyring(
        _read_host_controlled(
            _WINDOWS_PHYSICAL_KEYRING,
            maximum=_MAX_KEYRING_BYTES,
        ),
        expected_domain=_PHYSICAL_DOMAIN,
    )
    runtime_keys = _parse_hmac_keyring(
        _read_host_controlled(
            _WINDOWS_RUNTIME_KEYRING,
            maximum=_MAX_KEYRING_BYTES,
        ),
        expected_domain=_RUNTIME_DOMAIN,
    )
    physical_verifier = WindowsPhysicalIsolationVerifier(
        profile["physical_evidence_root"],
        physical_keys,
        max_age=timedelta(days=30),
    )
    runtime_verifier = RuntimeClosureVerifier(runtime_keys)
    trusted_git_runtime = TrustedGitRuntime(
        profile["trusted_git_transaction_root"]
    )
    git_runner = TrustedGitRunner(
        trusted_git_runtime,
        operation_root=profile["trusted_git_operation_root"],
    )
    return {
        "catalog": profile["catalog"],
        "toolchain": profile["toolchain"],
        "isolation_attestation": profile["attestation"],
        "physical_verifier": physical_verifier,
        "signed_runtime_closure": profile["signed_closure"],
        "runtime_closure_verifier": runtime_verifier,
        "trusted_runtime_root": profile["trusted_runtime_root"],
        "git_runner": git_runner,
        "workspace_root": profile["workspace_root"],
        "control_plane_root": profile["control_plane_root"],
    }


def install_pilot_exact_task_executor_capability_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskExecutorCapabilityProductionBoundaryError(
            "executor capability implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_executor_capability_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def materialize_pilot_exact_task_executor_capability(
        *,
        task_binding: Any,
        admission_receipt: Any,
    ) -> Any:
        try:
            substrate_inputs = _resolve_host_executor_materialization_inputs(
                development_task_sha256=task_binding.development_task_sha256,
            )
            return implementation._materialize_verified_executor_capability(
                task_binding=task_binding,
                admission_receipt=admission_receipt,
                **substrate_inputs,
            )
        except implementation.PilotExactTaskExecutorCapabilityError:
            raise
        except Exception as exc:
            raise implementation.PilotExactTaskExecutorCapabilityError(
                "host-controlled exact executor capability materialization failed closed"
            ) from exc

    implementation.materialize_pilot_exact_task_executor_capability = (
        materialize_pilot_exact_task_executor_capability
    )
    setattr(implementation, marker, True)


__all__: list[str] = []

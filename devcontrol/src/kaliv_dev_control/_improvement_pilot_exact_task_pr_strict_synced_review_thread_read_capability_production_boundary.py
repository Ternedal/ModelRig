"""Host-pinned production boundary for ADR-DC-089 review-thread read capability."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import PhysicalHostStateError, _require_elevated_operator
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
    _require_host_control,
)
from .trusted_git_runtime_model import _has_linkish_component

POLICY_SCHEMA = "kaliv-rsi-pilot-exact-task-pr-strict-synced-review-thread-read-broker-policy/v1"
_MAX_BROKER_BYTES = 16 * 1024 * 1024
_POLICY_FIELDS = {
    "schema", "provider", "graphql_endpoint", "repository", "credential_account",
    "credential_protocol", "operation", "broker_version", "broker_executable_path",
    "broker_executable_sha256", "secret_source", "secret_transport", "graphql_query_sha256",
    "strict_synced_preflight_required", "review_thread_requirements_required",
    "required_status_checks_passed_required", "strict_base_sync_passed_required",
    "graphql_query_only", "graphql_mutation_forbidden", "graphql_introspection_forbidden",
    "other_repository_reads_forbidden", "review_submission_write_forbidden",
    "review_dismissal_write_forbidden", "review_thread_mutation_forbidden",
    "reviewer_request_write_forbidden", "pull_request_write_forbidden",
    "label_write_forbidden", "merge_write_forbidden", "repository_contents_write_forbidden",
    "administration_write_forbidden", "release_write_forbidden", "deployment_write_forbidden",
    "redirect_following_forbidden",
}


class PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError(ValueError):
    pass


def _canonical_policy_path() -> Path:
    if os.name == "posix":
        return Path("/etc/modelrig/devcontrol/review/rsi-pilot-exact-task-pr-strict-synced-review-thread-read-broker-policy-v1.json")
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\review\rsi-pilot-exact-task-pr-strict-synced-review-thread-read-broker-policy-v1.json")
    raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("unsupported platform")


def _canonical_broker_path() -> Path:
    if os.name == "posix":
        return Path("/usr/local/libexec/modelrig/rsi-github-strict-synced-review-thread-read-broker-v1")
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\bin\rsi-github-strict-synced-review-thread-read-broker-v1.exe")
    raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("unsupported platform")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy is not canonical JSON") from exc


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _parse_policy(
    payload: bytes,
    *,
    broker_path: Path,
    implementation: Any,
    expected_operation: str,
    expected_query_sha256: str,
) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy missing")
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy invalid JSON") from exc
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy fields mismatch")
    expected = {
        "schema": POLICY_SCHEMA,
        "provider": "github",
        "graphql_endpoint": implementation.GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": implementation.CREDENTIAL_ACCOUNT,
        "credential_protocol": implementation.PROTOCOL,
        "operation": expected_operation,
        "broker_executable_path": os.fspath(broker_path),
        "secret_source": implementation.SECRET_SOURCE,
        "secret_transport": implementation.SECRET_TRANSPORT,
        "graphql_query_sha256": expected_query_sha256,
        "strict_synced_preflight_required": True,
        "review_thread_requirements_required": True,
        "required_status_checks_passed_required": True,
        "strict_base_sync_passed_required": True,
        "graphql_query_only": True,
        "graphql_mutation_forbidden": True,
        "graphql_introspection_forbidden": True,
        "other_repository_reads_forbidden": True,
        "review_submission_write_forbidden": True,
        "review_dismissal_write_forbidden": True,
        "review_thread_mutation_forbidden": True,
        "reviewer_request_write_forbidden": True,
        "pull_request_write_forbidden": True,
        "label_write_forbidden": True,
        "merge_write_forbidden": True,
        "repository_contents_write_forbidden": True,
        "administration_write_forbidden": True,
        "release_write_forbidden": True,
        "deployment_write_forbidden": True,
        "redirect_following_forbidden": True,
    }
    mismatch = next((name for name, expected_value in expected.items() if value.get(name) != expected_value), None)
    if mismatch is not None:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError(f"broker policy mismatch: {mismatch}")
    version = value.get("broker_version")
    digest = value.get("broker_executable_sha256")
    if (
        not isinstance(version, str) or not version or len(version) > 64 or any(ch.isspace() for ch in version)
        or not isinstance(digest, str) or len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest) or digest == "0" * 64
        or payload != _canonical_bytes(dict(value))
    ):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy version/hash/canonical form invalid")
    return dict(value)


def _read_broker_bytes(path: Path, *, require_host_control: bool) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker path unsafe")
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker unreadable") from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1 or observed.st_size < 1
            or observed.st_size > _MAX_BROKER_BYTES
            or (os.name == "posix" and not (observed.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)))
        ):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker file unsafe")
        if require_host_control:
            try:
                _require_host_control(candidate, observed)
            except PhysicalRequestAuthorityKeyringError as exc:
                raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker is not host-controlled") from exc
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker read incomplete")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker changed while reading")
        after = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino, observed.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker identity changed")
        return b"".join(chunks)
    except OSError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker read failed") from exc
    finally:
        os.close(descriptor)


def _load_broker_descriptor_at(
    policy_path: Path,
    broker_path: Path,
    *,
    require_host_control: bool,
    implementation: Any,
    expected_operation: str,
    expected_query_sha256: str,
) -> Mapping[str, str]:
    try:
        payload = _read_keyring_bytes(Path(policy_path), require_host_control=require_host_control)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker policy could not be read safely") from exc
    policy = _parse_policy(
        payload,
        broker_path=Path(broker_path),
        implementation=implementation,
        expected_operation=expected_operation,
        expected_query_sha256=expected_query_sha256,
    )
    broker_bytes = _read_broker_bytes(Path(broker_path), require_host_control=require_host_control)
    broker_sha256 = hashlib.sha256(broker_bytes).hexdigest()
    if broker_sha256 != policy["broker_executable_sha256"]:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("broker binary hash mismatch")
    return {
        "broker_policy_sha256": hashlib.sha256(payload).hexdigest(),
        "broker_executable_path": os.fspath(Path(broker_path)),
        "broker_executable_path_sha256": _path_sha256(Path(broker_path)),
        "broker_executable_sha256": broker_sha256,
        "broker_version": str(policy["broker_version"]),
        "credential_protocol": str(policy["credential_protocol"]),
        "graphql_operation": str(policy["operation"]),
        "secret_source": str(policy["secret_source"]),
        "secret_transport": str(policy["secret_transport"]),
        "graphql_endpoint": str(policy["graphql_endpoint"]),
        "credential_account": str(policy["credential_account"]),
        "graphql_query_sha256": str(policy["graphql_query_sha256"]),
    }


def _canonical_broker_descriptor(
    implementation: Any,
    *,
    expected_operation: str,
    expected_query_sha256: str,
) -> Mapping[str, str]:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("elevated host operator required") from exc
    return _load_broker_descriptor_at(
        _canonical_policy_path(),
        _canonical_broker_path(),
        require_host_control=True,
        implementation=implementation,
        expected_operation=expected_operation,
        expected_query_sha256=expected_query_sha256,
    )


def install_pilot_exact_task_pr_strict_synced_review_thread_read_capability_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError("implementation unavailable")
    marker = "_production_strict_synced_review_thread_read_capability_boundary_installed"
    if getattr(implementation, marker, False):
        return
    private_materialize = implementation._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_read_capability

    def materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability(strict_base_sync_preflight: Any) -> Any:
        try:
            live = implementation._require_live_strict_sync(strict_base_sync_preflight)
            req = live["review_thread_read_requirements"]
            descriptor = _canonical_broker_descriptor(
                implementation,
                expected_operation=req.graphql_operation,
                expected_query_sha256=strict_base_sync_preflight.review_thread_graphql_query_sha256,
            )
            return private_materialize(
                strict_base_sync_preflight=strict_base_sync_preflight,
                broker_descriptor=descriptor,
                now_provider=implementation._now_utc_seconds,
            )
        except implementation.PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError:
            raise
        except (
            PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityProductionBoundaryError,
            ValueError, TypeError, AttributeError, OSError,
        ) as exc:
            raise implementation.PilotExactTaskPrStrictSyncedReviewThreadReadCapabilityError("host-controlled read capability failed closed") from exc

    implementation.materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability = materialize_pilot_exact_task_pr_strict_synced_review_thread_read_capability
    setattr(implementation, marker, True)


__all__: list[str] = []

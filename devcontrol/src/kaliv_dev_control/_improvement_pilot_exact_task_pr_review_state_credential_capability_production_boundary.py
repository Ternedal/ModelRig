"""Host-pinned production boundary for ADR-DC-077 review-state read capability."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
    _require_host_control,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_BROKER_POLICY_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-review-state-credential-broker-policy/v1"
)
_MAX_BROKER_BYTES = 16 * 1024 * 1024
_POLICY_FIELDS = {
    "schema", "provider", "api_origin", "graphql_endpoint", "repository",
    "credential_account", "credential_protocol", "broker_version",
    "broker_executable_path", "broker_executable_sha256", "secret_source",
    "secret_transport", "allowed_operations", "reviews_path_template",
    "graphql_query_sha256", "reviews_read_only", "review_threads_read_only",
    "review_decision_read_only", "graphql_queries_only",
    "graphql_mutation_forbidden", "graphql_introspection_forbidden",
    "collaborator_permission_read_forbidden", "other_repository_reads_forbidden",
    "review_submission_write_forbidden", "review_dismissal_write_forbidden",
    "review_thread_mutation_forbidden", "reviewer_request_write_forbidden",
    "pull_request_create_forbidden", "pull_request_metadata_write_forbidden",
    "ready_for_review_write_forbidden", "label_write_forbidden",
    "merge_write_forbidden", "repository_contents_write_forbidden",
    "administration_write_forbidden", "release_write_forbidden",
    "deployment_write_forbidden", "redirect_following_forbidden",
}


class PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(ValueError):
    """Production review-state broker is unsafe or unavailable."""


def _canonical_policy_path() -> Path:
    if os.name == "posix":
        return Path("/etc/modelrig/devcontrol/review/rsi-pilot-exact-task-pr-review-state-credential-broker-policy-v1.json")
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\review\rsi-pilot-exact-task-pr-review-state-credential-broker-policy-v1.json")
    raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
        "review-state broker policy platform is unsupported"
    )


def _canonical_broker_path() -> Path:
    if os.name == "posix":
        return Path("/usr/local/libexec/modelrig/rsi-github-review-state-read-broker-v1")
    if os.name == "nt":
        return Path(r"C:\Program Files\ModelRig\DevControl\bin\rsi-github-review-state-read-broker-v1.exe")
    raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
        "review-state broker executable platform is unsupported"
    )


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy is not canonical JSON"
        ) from exc


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _parse_policy(payload: bytes, *, broker_path: Path, implementation: Any) -> Mapping[str, Any]:
    if not isinstance(payload, bytes) or not payload:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy payload is missing"
        )
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _POLICY_FIELDS:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy fields mismatch"
        )
    expected = {
        "schema": PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_BROKER_POLICY_SCHEMA,
        "provider": "github",
        "api_origin": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_API_ORIGIN,
        "graphql_endpoint": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_ENDPOINT,
        "repository": "Ternedal/ModelRig",
        "credential_account": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_ACCOUNT,
        "credential_protocol": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_CREDENTIAL_PROTOCOL,
        "broker_executable_path": os.fspath(broker_path),
        "secret_source": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_SOURCE,
        "secret_transport": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_SECRET_TRANSPORT,
        "allowed_operations": [
            implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_REST_OPERATION,
            implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_OPERATION,
        ],
        "reviews_path_template": implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_REVIEWS_PATH_TEMPLATE,
        "graphql_query_sha256": hashlib.sha256(
            implementation.PILOT_EXACT_TASK_PR_REVIEW_STATE_GRAPHQL_QUERY.encode("utf-8")
        ).hexdigest(),
        "reviews_read_only": True,
        "review_threads_read_only": True,
        "review_decision_read_only": True,
        "graphql_queries_only": True,
        "graphql_mutation_forbidden": True,
        "graphql_introspection_forbidden": True,
        "collaborator_permission_read_forbidden": True,
        "other_repository_reads_forbidden": True,
        "review_submission_write_forbidden": True,
        "review_dismissal_write_forbidden": True,
        "review_thread_mutation_forbidden": True,
        "reviewer_request_write_forbidden": True,
        "pull_request_create_forbidden": True,
        "pull_request_metadata_write_forbidden": True,
        "ready_for_review_write_forbidden": True,
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
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            f"review-state broker policy mismatch: {mismatch}"
        )
    version = value.get("broker_version")
    digest = value.get("broker_executable_sha256")
    if (
        not isinstance(version, str) or not version or len(version) > 64
        or any(character.isspace() for character in version)
        or not isinstance(digest, str) or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        or digest == "0" * 64
    ):
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy version/hash is invalid"
        )
    if payload != _canonical_bytes(dict(value)):
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy is not byte-for-byte canonical"
        )
    return dict(value)


def _read_broker_bytes(path: Path, *, require_host_control: bool) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker executable path is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker executable is missing or unreadable"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1
            or observed.st_size < 1 or observed.st_size > _MAX_BROKER_BYTES
            or (os.name == "posix" and not (observed.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)))
        ):
            raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
                "review-state broker executable file is unsafe"
            )
        if require_host_control:
            try:
                _require_host_control(candidate, observed)
            except PhysicalRequestAuthorityKeyringError as exc:
                raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
                    "review-state broker executable is not host-admin controlled"
                ) from exc
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
                    "review-state broker executable read was incomplete"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
                "review-state broker executable changed while reading"
            )
        after = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino, observed.st_size) != (after.st_dev, after.st_ino, after.st_size):
            raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
                "review-state broker executable identity changed during read"
            )
        return b"".join(chunks)
    except OSError as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker executable could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)


def _load_broker_descriptor_at(policy_path: Path, broker_path: Path, *, require_host_control: bool, implementation: Any) -> Mapping[str, str]:
    try:
        payload = _read_keyring_bytes(Path(policy_path), require_host_control=require_host_control)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker policy could not be read safely"
        ) from exc
    policy = _parse_policy(payload, broker_path=Path(broker_path), implementation=implementation)
    broker_bytes = _read_broker_bytes(Path(broker_path), require_host_control=require_host_control)
    broker_sha256 = hashlib.sha256(broker_bytes).hexdigest()
    if broker_sha256 != policy["broker_executable_sha256"]:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state broker executable hash does not match host policy"
        )
    return {
        "broker_policy_sha256": hashlib.sha256(payload).hexdigest(),
        "broker_executable_path": os.fspath(Path(broker_path)),
        "broker_executable_path_sha256": _path_sha256(Path(broker_path)),
        "broker_executable_sha256": broker_sha256,
        "broker_version": str(policy["broker_version"]),
        "credential_protocol": str(policy["credential_protocol"]),
        "rest_operation": str(policy["allowed_operations"][0]),
        "graphql_operation": str(policy["allowed_operations"][1]),
        "secret_source": str(policy["secret_source"]),
        "secret_transport": str(policy["secret_transport"]),
        "api_origin": str(policy["api_origin"]),
        "graphql_endpoint": str(policy["graphql_endpoint"]),
        "credential_account": str(policy["credential_account"]),
        "reviews_path_template": str(policy["reviews_path_template"]),
        "graphql_query_sha256": str(policy["graphql_query_sha256"]),
    }


def _canonical_broker_descriptor(implementation: Any) -> Mapping[str, str]:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state capability requires an elevated host operator"
        ) from exc
    return _load_broker_descriptor_at(
        _canonical_policy_path(), _canonical_broker_path(),
        require_host_control=True, implementation=implementation,
    )


def install_pilot_exact_task_pr_review_state_credential_capability_production_boundary(implementation: Any) -> None:
    if implementation is None:
        raise PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError(
            "review-state capability implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_pr_review_state_credential_capability_boundary_installed"
    if getattr(implementation, marker, False):
        return
    private_materialize = implementation._materialize_verified_pilot_exact_task_pr_review_state_credential_capability

    def materialize_pilot_exact_task_pr_review_state_credential_capability(reviewer_request_attestation: Any) -> Any:
        try:
            descriptor = _canonical_broker_descriptor(implementation)
            return private_materialize(
                reviewer_request_attestation=reviewer_request_attestation,
                broker_descriptor=descriptor,
                now_provider=implementation._now_utc_seconds,
            )
        except implementation.PilotExactTaskPrReviewStateCredentialCapabilityError:
            raise
        except (
            PilotExactTaskPrReviewStateCredentialCapabilityProductionBoundaryError,
            ValueError, TypeError, AttributeError, OSError,
        ) as exc:
            raise implementation.PilotExactTaskPrReviewStateCredentialCapabilityError(
                "host-controlled review-state capability failed closed"
            ) from exc

    implementation.materialize_pilot_exact_task_pr_review_state_credential_capability = materialize_pilot_exact_task_pr_review_state_credential_capability
    setattr(implementation, marker, True)


__all__: list[str] = []

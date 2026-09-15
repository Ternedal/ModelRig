"""Host-pinned production verification for ADR-DC-068 reviewer-request authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)

PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-pr-reviewer-request-authorization-keyring/v1"
)
PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY_DOMAIN = (
    "rsi-dc-l16-exact-pr-reviewer-request-human-authorization"
)
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(ValueError):
    """Production human reviewer-request authority is unsafe or unavailable."""


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
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring is not canonical JSON"
        ) from exc


def _canonical_pilot_exact_task_pr_reviewer_request_authorization_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-pr-reviewer-request-authorization-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/"
            "rsi-pilot-exact-task-pr-reviewer-request-authorization-keyring-v1.json"
        )
    raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
        "reviewer-request authority keyring is unsupported on this platform"
    )


def _load_pilot_exact_task_pr_reviewer_request_authorization_verifier_at(
    path: Path,
    *,
    issuer_system_id: str,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    try:
        payload = _read_keyring_bytes(
            Path(path),
            require_host_control=require_host_control,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring fields mismatch"
        )
    if value.get("schema") != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_KEYRING_SCHEMA:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY_DOMAIN:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring belongs to another domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if isinstance(minimum_epoch, bool) or not isinstance(minimum_epoch, int) or minimum_epoch < 1:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring must contain public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
                    "reviewer-request authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
                    "reviewer-request authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_KEYRING_SCHEMA,
        "authority_domain": PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authority keyring is not canonical"
        )
    return verifier


def _canonical_pilot_exact_task_pr_reviewer_request_authorization_verifier(
    *, issuer_system_id: str
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authorization verification requires an elevated host operator"
        ) from exc
    return _load_pilot_exact_task_pr_reviewer_request_authorization_verifier_at(
        _canonical_pilot_exact_task_pr_reviewer_request_authorization_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def install_pilot_exact_task_pr_reviewer_request_authorization_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError(
            "reviewer-request authorization implementation is unavailable"
        )
    marker = "_production_pilot_exact_task_pr_reviewer_request_authorization_boundary_installed"
    if getattr(implementation, marker, False):
        return
    private_verify = implementation._verify_pilot_exact_task_pr_reviewer_request_authorization

    def verify_pilot_exact_task_pr_reviewer_request_authorization(
        *,
        reviewer_target_attestation: Any,
        authorization: Any,
        signature: Any,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.PilotExactTaskPrReviewerRequestAuthorizationError(
                "caller-selected reviewer-request verifier is not production authority"
            )
        try:
            host_verifier = (
                _canonical_pilot_exact_task_pr_reviewer_request_authorization_verifier(
                    issuer_system_id=(
                        implementation.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_AUTHORIZATION_ISSUER_SYSTEM_ID
                    )
                )
            )
        except PilotExactTaskPrReviewerRequestAuthorizationProductionBoundaryError as exc:
            raise implementation.PilotExactTaskPrReviewerRequestAuthorizationError(
                "host-controlled human reviewer-request authority is unavailable"
            ) from exc
        verification_now = implementation._now_utc_seconds()
        return private_verify(
            reviewer_target_attestation=reviewer_target_attestation,
            authorization=authorization,
            signature=signature,
            verifier=host_verifier,
            now_provider=lambda: verification_now,
        )

    implementation.verify_pilot_exact_task_pr_reviewer_request_authorization = (
        verify_pilot_exact_task_pr_reviewer_request_authorization
    )
    setattr(implementation, marker, True)


__all__: list[str] = []

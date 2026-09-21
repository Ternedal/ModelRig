"""Host-pinned production verification for ADR-DC-030 human task authority."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from . import _improvement_pilot_execution_admission_attestation_impl as _admission_impl
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from ._improvement_pilot_execution_admission_attestation_production_boundary import (
    PilotExecutionAdmissionAttestationProductionBoundaryError,
    _canonical_pilot_execution_admission_attestation_verifier,
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

PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_KEYRING_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-execution-authorization-keyring/v1"
)
PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY_DOMAIN = (
    "rsi-dc-l16-exact-task-execution-human-authorization"
)
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PilotExactTaskExecutionAuthorizationProductionBoundaryError(ValueError):
    """Production human execution authority state is unsafe or unavailable."""


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
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring is not canonical JSON"
        ) from exc


def _canonical_pilot_exact_task_execution_authorization_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-execution-authorization-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-execution-authorization-keyring-v1.json"
        )
    raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
        "execution-authority keyring is unsupported on this platform"
    )


def _load_pilot_exact_task_execution_authorization_verifier_at(
    path: Path,
    *,
    issuer_system_id: str,
    require_host_control: bool = True,
) -> Ed25519AuthorityVerifier:
    try:
        payload = _read_keyring_bytes(
            Path(path), require_host_control=require_host_control
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring fields mismatch"
        )
    if value.get("schema") != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_KEYRING_SCHEMA:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring schema is unsupported"
        )
    if value.get("authority_domain") != PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY_DOMAIN:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring must contain trusted public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
                    "execution-authority key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
                    "execution-authority keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PilotExactTaskExecutionAuthorizationProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_KEYRING_SCHEMA,
        "authority_domain": PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_AUTHORITY_DOMAIN,
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority keyring is not canonical"
        )
    return verifier


def _canonical_pilot_exact_task_execution_authorization_verifier(
    *, issuer_system_id: str
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority verification requires an elevated host operator"
        ) from exc
    return _load_pilot_exact_task_execution_authorization_verifier_at(
        _canonical_pilot_exact_task_execution_authorization_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def _verify_admission_attestation_provenance(
    *,
    proof: Any,
    signature: Any,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> None:
    if type(proof) is not _admission_impl.PilotExecutionAdmissionAttestationProof:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "exact ADR-DC-028 admission-attestation proof is required"
        )
    if signature is None:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "detached ADR-DC-028 admission-attestation signature is required"
        )
    try:
        reverified = _admission_impl._verify_pilot_execution_admission_attestation(
            attestation=proof.attestation,
            signature=signature,
            verifier=verifier,
            now_provider=now_provider,
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "ADR-DC-028 admission-attestation provenance verification failed"
        ) from exc
    if getattr(signature, "sha256", None) != proof.signature_sha256:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "ADR-DC-028 detached signature does not match supplied proof"
        )
    for field in (
        "attestation_sha256",
        "signature_sha256",
        "key_id",
        "issuer_actor_id",
        "issuer_system_id",
        "packet_sha256",
        "start_receipt_sha256",
        "host_attestation_verified",
        "execution_admission_observed",
        "execution_admission_satisfied",
        "task_execution_authorized",
        "integration_ready",
        "product_pilot_started",
        "local_commit_authorized",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
        "authority",
    ):
        if getattr(reverified, field) != getattr(proof, field):
            raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
                f"ADR-DC-028 fresh provenance mismatch: {field}"
            )


def install_pilot_exact_task_execution_authorization_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskExecutionAuthorizationProductionBoundaryError(
            "execution-authority implementation is unavailable"
        )
    if getattr(
        implementation,
        "_production_pilot_exact_task_execution_authorization_boundary_installed",
        False,
    ):
        return
    private_verify = implementation._verify_pilot_exact_task_execution_authorization

    def verify_pilot_exact_task_execution_authorization(
        *,
        execution_requirements: Any,
        authorization: Any,
        signature: Any,
        admission_attestation_signature: Any = None,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.PilotExactTaskExecutionAuthorizationError(
                "caller-selected execution-authority verifier is not production authority"
            )
        if admission_attestation_signature is None:
            raise implementation.PilotExactTaskExecutionAuthorizationError(
                "detached ADR-DC-028 admission-attestation signature is required"
            )
        verification_now = implementation._now_utc_seconds()
        try:
            requirements = implementation._require_requirements(execution_requirements)
            proof = requirements.admission_attestation_proof
            admission_verifier = (
                _canonical_pilot_execution_admission_attestation_verifier(
                    issuer_system_id=(
                        _admission_impl.PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID
                    )
                )
            )
            _verify_admission_attestation_provenance(
                proof=proof,
                signature=admission_attestation_signature,
                verifier=admission_verifier,
                now_provider=lambda: verification_now,
            )
        except (
            PilotExecutionAdmissionAttestationProductionBoundaryError,
            PilotExactTaskExecutionAuthorizationProductionBoundaryError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise implementation.PilotExactTaskExecutionAuthorizationError(
                "host-controlled ADR-DC-028 provenance is unavailable or invalid"
            ) from exc
        try:
            host_verifier = _canonical_pilot_exact_task_execution_authorization_verifier(
                issuer_system_id=(
                    implementation.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID
                )
            )
        except PilotExactTaskExecutionAuthorizationProductionBoundaryError as exc:
            raise implementation.PilotExactTaskExecutionAuthorizationError(
                "host-controlled human execution-authority state is unavailable"
            ) from exc
        return private_verify(
            execution_requirements=execution_requirements,
            authorization=authorization,
            signature=signature,
            verifier=host_verifier,
            now_provider=lambda: verification_now,
        )

    implementation.verify_pilot_exact_task_execution_authorization = (
        verify_pilot_exact_task_execution_authorization
    )
    implementation._production_pilot_exact_task_execution_authorization_boundary_installed = True


__all__: list[str] = []

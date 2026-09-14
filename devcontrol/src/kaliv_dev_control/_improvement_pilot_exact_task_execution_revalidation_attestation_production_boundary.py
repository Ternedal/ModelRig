"""Host-pinned production verification for ADR-DC-032 revalidation attestation."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable, Mapping

from . import _improvement_pilot_execution_admission_attestation_impl as _admission_impl
from . import _improvement_pilot_exact_task_execution_authorization_impl as _auth_impl
from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
)
from ._improvement_pilot_execution_admission_attestation_production_boundary import (
    PilotExecutionAdmissionAttestationProductionBoundaryError,
    _canonical_pilot_execution_admission_attestation_verifier,
)
from ._improvement_pilot_exact_task_execution_authorization_production_boundary import (
    PilotExactTaskExecutionAuthorizationProductionBoundaryError,
    _canonical_pilot_exact_task_execution_authorization_verifier,
    _verify_admission_attestation_provenance,
)
from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
    TrustedEd25519AuthorityKey,
)
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _read_keyring_bytes,
)

PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_KEYRING_SCHEMA = (
    "kaliv-rsi-pilot-exact-task-execution-revalidation-attestation-keyring/v1"
)
PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY_DOMAIN = (
    "rsi-dc-l16-exact-task-execution-revalidation-attestation"
)
_KEYRING_FIELDS = {
    "schema",
    "authority_domain",
    "minimum_keyring_epoch",
    "trusted_keys",
}


class PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
    ValueError
):
    """Production exact-task revalidation trust state is unsafe or unavailable."""


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
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring is not canonical JSON"
        ) from exc


def _canonical_pilot_exact_task_execution_revalidation_attestation_keyring_path() -> Path:
    if os.name == "nt":
        return Path(
            r"C:\Program Files\ModelRig\DevControl\authority\rsi-pilot-exact-task-execution-revalidation-attestation-keyring-v1.json"
        )
    if os.name == "posix":
        return Path(
            "/etc/modelrig/devcontrol/authority/rsi-pilot-exact-task-execution-revalidation-attestation-keyring-v1.json"
        )
    raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
        "revalidation-attestation keyring is unsupported on this platform"
    )


def _load_pilot_exact_task_execution_revalidation_attestation_verifier_at(
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
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring could not be read safely"
        ) from exc
    try:
        value = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring is invalid JSON"
        ) from exc
    if not isinstance(value, Mapping) or set(value) != _KEYRING_FIELDS:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring fields mismatch"
        )
    if (
        value.get("schema")
        != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_KEYRING_SCHEMA
    ):
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring schema is unsupported"
        )
    if (
        value.get("authority_domain")
        != PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY_DOMAIN
    ):
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring belongs to another authority domain"
        )
    minimum_epoch = value.get("minimum_keyring_epoch")
    if (
        not isinstance(minimum_epoch, int)
        or isinstance(minimum_epoch, bool)
        or minimum_epoch < 1
    ):
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation minimum keyring epoch is invalid"
        )
    raw_keys = value.get("trusted_keys")
    if not isinstance(raw_keys, list) or not raw_keys:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring must contain trusted public keys"
        )
    trusted: dict[str, TrustedEd25519AuthorityKey] = {}
    canonical_keys: list[dict[str, Any]] = []
    previous_key_id: str | None = None
    try:
        for raw in raw_keys:
            key = TrustedEd25519AuthorityKey.from_mapping(raw)
            if key.issuer_system_id != issuer_system_id:
                raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
                    "revalidation-attestation key belongs to another issuer system"
                )
            if previous_key_id is not None and key.key_id <= previous_key_id:
                raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
                    "revalidation-attestation keys must be sorted and unique"
                )
            previous_key_id = key.key_id
            trusted[key.key_id] = key
            canonical_keys.append(key.to_dict())
        verifier = Ed25519AuthorityVerifier(
            trusted,
            minimum_keyring_epoch=minimum_epoch,
        )
    except PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError:
        raise
    except (AsymmetricAuthorityError, AttributeError, TypeError, ValueError) as exc:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring contains invalid public-key evidence"
        ) from exc
    canonical_mapping = {
        "schema": PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_KEYRING_SCHEMA,
        "authority_domain": (
            PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_AUTHORITY_DOMAIN
        ),
        "minimum_keyring_epoch": minimum_epoch,
        "trusted_keys": canonical_keys,
    }
    if payload != _canonical(canonical_mapping):
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation keyring is not canonical"
        )
    return verifier


def _canonical_pilot_exact_task_execution_revalidation_attestation_verifier(
    *, issuer_system_id: str
) -> Ed25519AuthorityVerifier:
    try:
        _require_elevated_operator()
    except PhysicalHostStateError as exc:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation verification requires an elevated host operator"
        ) from exc
    return _load_pilot_exact_task_execution_revalidation_attestation_verifier_at(
        _canonical_pilot_exact_task_execution_revalidation_attestation_keyring_path(),
        issuer_system_id=issuer_system_id,
        require_host_control=True,
    )


def _stable_execution_authorization_proof_fields(proof: Any) -> dict[str, Any]:
    if type(proof) is not _auth_impl.PilotExactTaskExecutionAuthorizationProof:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "exact ADR-DC-030 execution-authorization proof is required"
        )
    try:
        replayed = _auth_impl.PilotExactTaskExecutionAuthorizationProof.from_mapping(
            proof.to_dict()
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "ADR-DC-030 execution-authorization proof replay failed"
        ) from exc
    if replayed != proof or replayed.sha256 != proof.sha256:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "ADR-DC-030 execution-authorization proof identity mismatch"
        )
    return {
        "authorization_sha256": proof.authorization_sha256,
        "signature_sha256": proof.signature_sha256,
        "key_id": proof.key_id,
        "issuer_actor_id": proof.issuer_actor_id,
        "issuer_system_id": proof.issuer_system_id,
        "authorization": proof.authorization,
        "execution_requirements_sha256": proof.execution_requirements_sha256,
        "admission_attestation_proof_sha256": proof.admission_attestation_proof_sha256,
        "admission_attestation_signature_sha256": (
            proof.admission_attestation_signature_sha256
        ),
        "start_receipt_sha256": proof.start_receipt_sha256,
        "execution_nonce_sha256": proof.execution_nonce_sha256,
        "one_shot_execution_required": proof.one_shot_execution_required,
        "execution_authorization_consumed": proof.execution_authorization_consumed,
        "human_task_execution_authorization_verified": (
            proof.human_task_execution_authorization_verified
        ),
        "task_execution_admission_observed": proof.task_execution_admission_observed,
        "task_execution_authorized": proof.task_execution_authorized,
        "task_execution_started": proof.task_execution_started,
        "integration_ready": proof.integration_ready,
        "product_pilot_started": proof.product_pilot_started,
        "local_commit_authorized": proof.local_commit_authorized,
        "remote_write_authorized": proof.remote_write_authorized,
        "push_authorized": proof.push_authorized,
        "pr_mutation_authorized": proof.pr_mutation_authorized,
        "merge_authorized": proof.merge_authorized,
        "release_authorized": proof.release_authorized,
        "deploy_authorized": proof.deploy_authorized,
        "production_activation_authorized": proof.production_activation_authorized,
        "authority": proof.authority,
    }


def _verify_execution_authorization_provenance(
    *,
    proof: Any,
    execution_authorization_signature: Any,
    admission_attestation_signature: Any,
    admission_verifier: Ed25519AuthorityVerifier,
    human_verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> None:
    stable = _stable_execution_authorization_proof_fields(proof)
    if type(execution_authorization_signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "detached ADR-DC-030 execution-authorization signature is required"
        )
    if (
        execution_authorization_signature.sha256 != proof.signature_sha256
        or execution_authorization_signature.issuer_actor_id != proof.issuer_actor_id
        or execution_authorization_signature.issuer_system_id != proof.issuer_system_id
    ):
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "ADR-DC-030 detached signature does not match supplied proof"
        )
    requirements = proof.authorization.execution_requirements
    admission_proof = requirements.admission_attestation_proof
    _verify_admission_attestation_provenance(
        proof=admission_proof,
        signature=admission_attestation_signature,
        verifier=admission_verifier,
        now_provider=now_provider,
    )
    try:
        fresh = _auth_impl._verify_pilot_exact_task_execution_authorization(
            execution_requirements=requirements,
            authorization=proof.authorization,
            signature=execution_authorization_signature,
            verifier=human_verifier,
            now_provider=now_provider,
        )
    except (ValueError, TypeError, AttributeError) as exc:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "ADR-DC-030 execution-authorization provenance verification failed"
        ) from exc
    fresh_stable = _stable_execution_authorization_proof_fields(fresh)
    if fresh_stable != stable:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "ADR-DC-030 fresh provenance does not match supplied proof"
        )


def install_pilot_exact_task_execution_revalidation_attestation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError(
            "revalidation-attestation implementation is unavailable"
        )
    marker = (
        "_production_pilot_exact_task_execution_revalidation_attestation_boundary_installed"
    )
    if getattr(implementation, marker, False):
        return
    private_verify = (
        implementation._verify_pilot_exact_task_execution_revalidation_attestation
    )

    def verify_pilot_exact_task_execution_revalidation_attestation(
        *,
        attestation: Any,
        signature: Any,
        execution_authorization_signature: Any = None,
        admission_attestation_signature: Any = None,
        verifier: Ed25519AuthorityVerifier | None = None,
    ) -> Any:
        if verifier is not None:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "caller-selected revalidation-attestation verifier is not production authority"
            )
        if execution_authorization_signature is None:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "detached ADR-DC-030 execution-authorization signature is required"
            )
        if admission_attestation_signature is None:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "detached ADR-DC-028 admission-attestation signature is required"
            )
        try:
            exact_attestation = implementation.PilotExactTaskExecutionRevalidationAttestation.from_mapping(
                attestation.to_dict()
            )
            proof = exact_attestation.packet.execution_authorization_proof
        except (ValueError, TypeError, AttributeError) as exc:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "exact ADR-DC-032 attestation input is invalid"
            ) from exc
        verification_now = implementation._now_utc_seconds()
        try:
            admission_verifier = (
                _canonical_pilot_execution_admission_attestation_verifier(
                    issuer_system_id=(
                        _admission_impl.PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID
                    )
                )
            )
            human_verifier = (
                _canonical_pilot_exact_task_execution_authorization_verifier(
                    issuer_system_id=(
                        _auth_impl.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID
                    )
                )
            )
            _verify_execution_authorization_provenance(
                proof=proof,
                execution_authorization_signature=execution_authorization_signature,
                admission_attestation_signature=admission_attestation_signature,
                admission_verifier=admission_verifier,
                human_verifier=human_verifier,
                now_provider=lambda: verification_now,
            )
        except (
            PilotExecutionAdmissionAttestationProductionBoundaryError,
            PilotExactTaskExecutionAuthorizationProductionBoundaryError,
            PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError,
            ValueError,
            TypeError,
            AttributeError,
        ) as exc:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "fresh ADR-DC-028/030 provenance is unavailable or invalid"
            ) from exc
        try:
            host_verifier = (
                _canonical_pilot_exact_task_execution_revalidation_attestation_verifier(
                    issuer_system_id=(
                        implementation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
                    )
                )
            )
        except PilotExactTaskExecutionRevalidationAttestationProductionBoundaryError as exc:
            raise implementation.PilotExactTaskExecutionRevalidationAttestationError(
                "host-controlled revalidation-attestation authority state is unavailable"
            ) from exc
        return private_verify(
            attestation=attestation,
            signature=signature,
            verifier=host_verifier,
            now_provider=lambda: verification_now,
        )

    implementation.verify_pilot_exact_task_execution_revalidation_attestation = (
        verify_pilot_exact_task_execution_revalidation_attestation
    )
    setattr(implementation, marker, True)


__all__: list[str] = []

"""Host-pinned production verification for ADR-DC-098 lineage attestation."""
from __future__ import annotations

import json
from typing import Any

from . import _improvement_pilot_exact_task_product_pilot_lineage_attestation_impl as _impl
from . import _improvement_human_pilot_decision_impl as _human
from . import _improvement_pilot_integration_human_selection_impl as _selection
from . import _improvement_pilot_runtime_preflight_attestation_impl as _preflight
from . import _improvement_pilot_start_authorization_impl as _start_auth
from . import _improvement_pilot_start_consumption_impl as _start_consume
from . import _improvement_pilot_execution_admission_attestation_impl as _admission
from . import _improvement_pilot_exact_task_execution_authorization_impl as _exec_auth
from . import _improvement_pilot_exact_task_execution_revalidation_attestation_impl as _revalidation
from . import _improvement_pilot_exact_task_execution_admission_impl as _exec_admission
from .asymmetric_authority import DetachedEd25519AuthoritySignature
from ._improvement_human_pilot_decision_production_boundary import (
    _canonical_human_pilot_decision_verifier,
)
from ._improvement_pilot_integration_human_selection_production_boundary import (
    _canonical_pilot_integration_human_selection_verifier,
)
from ._improvement_pilot_runtime_preflight_attestation_production_boundary import (
    _canonical_pilot_runtime_preflight_attestation_verifier,
)
from ._improvement_pilot_start_authorization_production_boundary import (
    _canonical_pilot_start_authorization_verifier,
)
from ._improvement_pilot_start_consumption_production_boundary import (
    _canonical_ledger_root as _canonical_start_ledger_root,
)
from ._improvement_pilot_execution_admission_attestation_production_boundary import (
    _canonical_pilot_execution_admission_attestation_verifier,
)
from ._improvement_pilot_exact_task_execution_authorization_production_boundary import (
    _canonical_pilot_exact_task_execution_authorization_verifier,
)
from ._improvement_pilot_exact_task_execution_revalidation_attestation_production_boundary import (
    _canonical_pilot_exact_task_execution_revalidation_attestation_verifier,
)
from ._improvement_pilot_exact_task_execution_admission_production_boundary import (
    _canonical_ledger_root as _canonical_execution_ledger_root,
)


class PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(ValueError):
    """Canonical lineage trust state is unavailable or inconsistent."""


def _snapshot_signature(value: Any, *, name: str) -> DetachedEd25519AuthoritySignature:
    if type(value) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            f"exact detached {name} signature is required"
        )
    try:
        return DetachedEd25519AuthoritySignature.from_mapping(
            json.loads(value.canonical_json())
        )
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            f"{name} signature could not be snapshotted"
        ) from exc


def _decision_from_proof(
    proof: _human.HumanPilotDecisionProof,
) -> _human.HumanPilotDecision:
    return _human.HumanPilotDecision(
        decision_id=proof.decision_id,
        completion_proof_sha256=proof.completion_proof_sha256,
        campaign_id=proof.campaign_id,
        task_id=proof.task_id,
        task_sha256=proof.task_sha256,
        repository=proof.repository,
        base_sha=proof.base_sha,
        requested_main_sha=proof.requested_main_sha,
        decision_maker_actor_id=proof.decision_maker_actor_id,
        decision=proof.decision,
        operator_surface=proof.operator_surface,
        allowed_task_ids=proof.allowed_task_ids,
        workspace_root_path_sha256=proof.workspace_root_path_sha256,
        local_commits_allowed=proof.local_commits_allowed,
        notes=proof.notes,
        decided_at_utc=proof.decided_at_utc,
    )


def _load_execution_receipt(
    proof: _revalidation.PilotExactTaskExecutionRevalidationAttestationProof,
) -> _exec_admission.PilotExactTaskExecutionAdmissionReceipt:
    exact = _exec_admission._require_satisfied_revalidation_proof(proof)
    key = _exec_admission._admission_key(exact)
    scope = _exec_admission._scope(exact)
    root = _canonical_execution_ledger_root()
    ledger = _exec_admission._PilotExactTaskExecutionAdmissionLedger(root)
    final_path, pending_path, lock_path = ledger._paths(key)
    if pending_path.exists() or pending_path.is_symlink():
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "ADR-DC-033 execution admission has unresolved pending state"
        )
    final_payload = _exec_admission._read_bound_file(final_path)
    lock_payload = _exec_admission._read_bound_file(lock_path)
    if final_payload is None or lock_payload is None:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-033 execution admission evidence is missing"
        )
    try:
        receipt = _exec_admission.PilotExactTaskExecutionAdmissionReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8", errors="strict"))
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-033 execution receipt is invalid"
        ) from exc
    if (
        receipt.admission_key_sha256 != key
        or receipt.revalidation_attestation_proof != exact
        or receipt.revalidation_attestation_proof_sha256 != exact.sha256
        or receipt.execution_nonce_sha256 != exact.execution_nonce_sha256
        or receipt.ledger_root_path_sha256 != ledger.root_sha256
        or receipt.canonical_json().encode("utf-8") != final_payload
    ):
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-033 execution receipt binding mismatch"
        )
    expected_lock = _exec_admission._canonical(
        {
            "schema": "kaliv-rsi-dc-l16-exact-task-execution-admission-lock/v1",
            "ledger_scope": _exec_admission.PILOT_EXACT_TASK_EXECUTION_ADMISSION_LEDGER_SCOPE,
            "ledger_root_path_sha256": ledger.root_sha256,
            "admission_key_sha256": key,
            "execution_authorization_proof_sha256": scope[
                "execution_authorization_proof_sha256"
            ],
            "start_receipt_sha256": scope["start_receipt_sha256"],
            "execution_nonce_sha256": scope["execution_nonce_sha256"],
            "selected_pilot_task_id": scope["selected_pilot_task_id"],
            "workspace_root_path_sha256": scope["workspace_root_path_sha256"],
        }
    ).encode("utf-8")
    if lock_payload != expected_lock:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-033 execution lock binding mismatch"
        )
    return receipt

def _nested_start_receipt(
    execution_receipt: _exec_admission.PilotExactTaskExecutionAdmissionReceipt,
) -> _start_consume.PilotStartConsumptionReceipt:
    try:
        return (
            execution_receipt.revalidation_attestation_proof.attestation.packet
            .execution_authorization_proof.authorization.execution_requirements
            .admission_attestation_proof.attestation.packet.admission_requirements
            .start_receipt
        )
    except AttributeError as exc:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "ADR-DC-033 receipt lacks nested ADR-DC-025 provenance"
        ) from exc


def _load_start_receipt(
    expected: _start_consume.PilotStartConsumptionReceipt,
) -> _start_consume.PilotStartConsumptionReceipt:
    root = _canonical_start_ledger_root()
    ledger = _start_consume._PilotStartConsumptionLedger(root)
    final_path, pending_path, lock_path = ledger._paths(expected.start_nonce_sha256)
    if pending_path.exists() or pending_path.is_symlink():
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "ADR-DC-025 start consumption has unresolved pending state"
        )
    final_payload = _start_consume._read_bound_file(final_path)
    lock_payload = _start_consume._read_bound_file(lock_path)
    if final_payload is None or lock_payload is None:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-025 start-consumption evidence is missing"
        )
    try:
        receipt = _start_consume.PilotStartConsumptionReceipt.from_mapping(
            json.loads(final_payload.decode("utf-8", errors="strict"))
        )
    except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-025 start-consumption receipt is invalid"
        ) from exc
    if (
        receipt != expected
        or receipt.sha256 != expected.sha256
        or receipt.ledger_root_path_sha256 != ledger.root_sha256
        or receipt.canonical_json().encode("utf-8") != final_payload
    ):
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-025 start-consumption binding mismatch"
        )
    expected_lock = ledger._lock_payload(
        nonce=receipt.start_nonce_sha256,
        authorization_sha256=receipt.authorization_sha256,
        signature_sha256=receipt.authorization_signature_sha256,
    )
    if lock_payload != expected_lock:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "canonical ADR-DC-025 start-consumption lock mismatch"
        )
    return receipt


def _historically_verify_authorities(
    *,
    human_decision_proof: _human.HumanPilotDecisionProof,
    completion_proof: Any,
    human_decision_signature: DetachedEd25519AuthoritySignature,
    human_selection_signature: DetachedEd25519AuthoritySignature,
    preflight_signature: DetachedEd25519AuthoritySignature,
    start_authorization_signature: DetachedEd25519AuthoritySignature,
    admission_attestation_signature: DetachedEd25519AuthoritySignature,
    execution_authorization_signature: DetachedEd25519AuthoritySignature,
    revalidation_attestation_signature: DetachedEd25519AuthoritySignature,
    execution_receipt: _exec_admission.PilotExactTaskExecutionAdmissionReceipt,
) -> tuple[str, str, str, str]:
    chain = _impl._historical_chain(execution_receipt)
    selection_proof = chain["selection"]
    preflight_proof = chain["preflight"]
    start_proof = chain["start_authorization"]
    admission_proof = chain["admission"]
    execution_proof = chain["execution_authorization"]
    revalidation_proof = chain["revalidation"]

    decision = _decision_from_proof(human_decision_proof)
    if decision.sha256 != human_decision_proof.decision_sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "ADR-DC-015 decision reconstruction does not match supplied proof"
        )

    human_verifier = _canonical_human_pilot_decision_verifier(
        issuer_system_id=_human.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID
    )
    verified_human = _human._verify_human_pilot_decision(
        completion_proof=completion_proof,
        decision=decision,
        signature=human_decision_signature,
        verifier=human_verifier,
        now_provider=lambda: human_decision_proof.verified_at_utc,
    )
    if verified_human != human_decision_proof or verified_human.sha256 != human_decision_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-015 authority verification changed proof identity"
        )

    selection_verifier = _canonical_pilot_integration_human_selection_verifier(
        issuer_system_id=_selection.PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID
    )
    verified_selection = _selection._verify_pilot_integration_human_selection(
        candidate_proof=selection_proof.selection.candidate_proof,
        selection=selection_proof.selection,
        signature=human_selection_signature,
        verifier=selection_verifier,
        now_provider=lambda: selection_proof.verified_at_utc,
    )
    if verified_selection != selection_proof or verified_selection.sha256 != selection_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-021 authority verification changed proof identity"
        )

    preflight_verifier = _canonical_pilot_runtime_preflight_attestation_verifier(
        issuer_system_id=_preflight.PILOT_RUNTIME_PREFLIGHT_ATTESTATION_ISSUER_SYSTEM_ID
    )
    verified_preflight = _preflight._verify_pilot_runtime_preflight_attestation(
        attestation=preflight_proof.attestation,
        signature=preflight_signature,
        verifier=preflight_verifier,
        now_provider=lambda: preflight_proof.verified_at_utc,
    )
    if verified_preflight != preflight_proof or verified_preflight.sha256 != preflight_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-023 authority verification changed proof identity"
        )

    start_verifier = _canonical_pilot_start_authorization_verifier(
        issuer_system_id=_start_auth.PILOT_START_AUTHORIZATION_ISSUER_SYSTEM_ID
    )
    verified_start = _start_auth._verify_pilot_start_authorization(
        preflight_proof=start_proof.authorization.preflight_proof,
        authorization=start_proof.authorization,
        signature=start_authorization_signature,
        verifier=start_verifier,
        now_provider=lambda: start_proof.verified_at_utc,
    )
    if verified_start != start_proof or verified_start.sha256 != start_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-024 authority verification changed proof identity"
        )

    admission_verifier = _canonical_pilot_execution_admission_attestation_verifier(
        issuer_system_id=_admission.PILOT_EXECUTION_ADMISSION_ATTESTATION_ISSUER_SYSTEM_ID
    )
    verified_admission = _admission._verify_pilot_execution_admission_attestation(
        attestation=admission_proof.attestation,
        signature=admission_attestation_signature,
        verifier=admission_verifier,
        now_provider=lambda: admission_proof.verified_at_utc,
    )
    if verified_admission != admission_proof or verified_admission.sha256 != admission_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-028 authority verification changed proof identity"
        )

    execution_verifier = _canonical_pilot_exact_task_execution_authorization_verifier(
        issuer_system_id=_exec_auth.PILOT_EXACT_TASK_EXECUTION_AUTHORIZATION_ISSUER_SYSTEM_ID
    )
    verified_execution = _exec_auth._verify_pilot_exact_task_execution_authorization(
        execution_requirements=execution_proof.authorization.execution_requirements,
        authorization=execution_proof.authorization,
        signature=execution_authorization_signature,
        verifier=execution_verifier,
        now_provider=lambda: execution_proof.verified_at_utc,
    )
    if verified_execution != execution_proof or verified_execution.sha256 != execution_proof.sha256:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-030 authority verification changed proof identity"
        )

    revalidation_verifier = (
        _canonical_pilot_exact_task_execution_revalidation_attestation_verifier(
            issuer_system_id=(
                _revalidation.PILOT_EXACT_TASK_EXECUTION_REVALIDATION_ATTESTATION_ISSUER_SYSTEM_ID
            )
        )
    )
    verified_revalidation = (
        _revalidation._verify_pilot_exact_task_execution_revalidation_attestation(
            attestation=revalidation_proof.attestation,
            signature=revalidation_attestation_signature,
            verifier=revalidation_verifier,
            now_provider=lambda: revalidation_proof.verified_at_utc,
        )
    )
    if (
        verified_revalidation != revalidation_proof
        or verified_revalidation.sha256 != revalidation_proof.sha256
    ):
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "historical ADR-DC-032 authority verification changed proof identity"
        )

    return (
        verified_human.sha256,
        verified_selection.sha256,
        verified_preflight.sha256,
        verified_revalidation.sha256,
    )


def install_pilot_exact_task_product_pilot_lineage_attestation_production_boundary(
    implementation: Any,
) -> None:
    if implementation is None:
        raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
            "lineage attestation implementation is unavailable"
        )
    marker = "_production_product_pilot_lineage_attestation_boundary_installed"
    if getattr(implementation, marker, False):
        return

    def attest_pilot_exact_task_product_pilot_lineage(
        *,
        human_decision_proof: Any,
        completion_proof: Any,
        human_decision_signature: Any,
        human_selection_signature: Any,
        preflight_signature: Any,
        start_authorization_signature: Any,
        admission_attestation_signature: Any,
        execution_authorization_signature: Any,
        execution_revalidation_proof: Any,
        revalidation_attestation_signature: Any,
        staging_runtime_build_identity: Any,
        production_activation_readiness: Any,
        post_production_activation_attestation: Any,
    ) -> Any:
        if type(human_decision_proof) is not _human.HumanPilotDecisionProof:
            raise implementation.PilotExactTaskProductPilotLineageAttestationError(
                "exact ADR-DC-015 human decision proof is required"
            )
        try:
            supplied_human = _human.HumanPilotDecisionProof.from_mapping(
                human_decision_proof.to_dict()
            )
            human_sig = _snapshot_signature(
                human_decision_signature,
                name="ADR-DC-015 human decision",
            )
            selection_sig = _snapshot_signature(
                human_selection_signature,
                name="ADR-DC-021 human selection",
            )
            preflight_sig = _snapshot_signature(
                preflight_signature,
                name="ADR-DC-023 preflight",
            )
            start_sig = _snapshot_signature(
                start_authorization_signature,
                name="ADR-DC-024 start authorization",
            )
            admission_sig = _snapshot_signature(
                admission_attestation_signature,
                name="ADR-DC-028 admission attestation",
            )
            execution_sig = _snapshot_signature(
                execution_authorization_signature,
                name="ADR-DC-030 execution authorization",
            )
            revalidation_sig = _snapshot_signature(
                revalidation_attestation_signature,
                name="ADR-DC-032 revalidation attestation",
            )

            if (
                type(execution_revalidation_proof)
                is not _revalidation.PilotExactTaskExecutionRevalidationAttestationProof
            ):
                raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
                    "exact ADR-DC-032 revalidation proof is required"
                )
            supplied_revalidation = (
                _revalidation.PilotExactTaskExecutionRevalidationAttestationProof.from_mapping(
                    execution_revalidation_proof.to_dict()
                )
            )
            if (
                supplied_revalidation != execution_revalidation_proof
                or supplied_revalidation.sha256 != execution_revalidation_proof.sha256
                or staging_runtime_build_identity.execution_nonce_sha256
                != supplied_revalidation.execution_nonce_sha256
            ):
                raise PilotExactTaskProductPilotLineageAttestationProductionBoundaryError(
                    "ADR-DC-032 proof does not match staging runtime execution nonce"
                )
            execution_receipt = _load_execution_receipt(supplied_revalidation)
            expected_start = _nested_start_receipt(execution_receipt)
            start_receipt = _load_start_receipt(expected_start)

            (
                human_sha,
                selection_sha,
                preflight_sha,
                revalidation_sha,
            ) = _historically_verify_authorities(
                human_decision_proof=supplied_human,
                completion_proof=completion_proof,
                human_decision_signature=human_sig,
                human_selection_signature=selection_sig,
                preflight_signature=preflight_sig,
                start_authorization_signature=start_sig,
                admission_attestation_signature=admission_sig,
                execution_authorization_signature=execution_sig,
                revalidation_attestation_signature=revalidation_sig,
                execution_receipt=execution_receipt,
            )

            return implementation._attest_verified_pilot_exact_task_product_pilot_lineage(
                verified_human_decision_proof_sha256=human_sha,
                verified_human_selection_proof_sha256=selection_sha,
                verified_preflight_proof_sha256=preflight_sha,
                durable_start_receipt=start_receipt,
                verified_execution_revalidation_proof_sha256=revalidation_sha,
                durable_execution_admission_receipt=execution_receipt,
                staging_runtime_build_identity=staging_runtime_build_identity,
                production_activation_readiness=production_activation_readiness,
                post_production_activation_attestation=post_production_activation_attestation,
                now_provider=implementation._now_utc_seconds,
            )
        except (
            PilotExactTaskProductPilotLineageAttestationProductionBoundaryError,
            ValueError,
            TypeError,
            AttributeError,
            OSError,
        ) as exc:
            if isinstance(
                exc, implementation.PilotExactTaskProductPilotLineageAttestationError
            ):
                raise
            raise implementation.PilotExactTaskProductPilotLineageAttestationError(
                "host-controlled product-pilot lineage verification failed closed"
            ) from exc

    implementation.attest_pilot_exact_task_product_pilot_lineage = (
        attest_pilot_exact_task_product_pilot_lineage
    )
    setattr(implementation, marker, True)


__all__: list[str] = []

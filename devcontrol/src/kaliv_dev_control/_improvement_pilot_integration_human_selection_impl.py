"""Human-signed selection of one exact ADR-DC-020 integration candidate.

ADR-DC-021 records and verifies only the human choice of an already validated
candidate. It does not make the choice, integrate product code, observe runtime,
satisfy preflight, start a pilot, mutate Git/GitHub or authorize production.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .improvement_pilot_integration_selection_candidate import (
    PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY,
    PilotIntegrationSelectionCandidateProof,
)

PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA = (
    "kaliv-rsi-dc-l16-product-integration-human-selection/v1"
)
PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-product-integration-human-selection-proof/v1"
)
PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY = (
    "human-dc-l16-product-integration-selection-claim-only"
)
PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY = (
    "verified-human-dc-l16-product-integration-selection-only"
)
PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID = (
    "kaliv-rsi-dc-l16-product-integration-selection-authority-v1"
)
PILOT_INTEGRATION_HUMAN_SELECTION_INTENT = "select-exact-candidate"

_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_NOTES = 32

_SELECTION_FIELDS = {
    "schema", "selection_id", "candidate_proof", "candidate_proof_sha256",
    "selection_maker_actor_id", "selected_at_utc", "notes",
    "human_selection_intent", "human_selection_recorded", "integration_ready",
    "preflight_observed", "preflight_satisfied", "pilot_start_authorized",
    "product_pilot_started", "remote_write_authorized", "push_authorized",
    "pr_mutation_authorized", "merge_authorized", "release_authorized",
    "deploy_authorized", "production_activation_authorized", "authority",
}

_PROOF_FIELDS = {
    "schema", "selection_sha256", "signature_sha256", "key_id",
    "issuer_actor_id", "issuer_system_id", "selection", "candidate_proof_sha256",
    "verified_at_utc", "human_selection_recorded", "candidate_selection_verified",
    "integration_ready", "preflight_observed", "preflight_satisfied",
    "pilot_start_authorized", "product_pilot_started", "remote_write_authorized",
    "push_authorized", "pr_mutation_authorized", "merge_authorized",
    "release_authorized", "deploy_authorized", "production_activation_authorized",
    "authority",
}


class PilotIntegrationHumanSelectionError(ValueError):
    """Human integration-selection evidence is malformed or over-authorizing."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotIntegrationHumanSelectionError(
            "human integration selection is not canonical JSON"
        ) from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PilotIntegrationHumanSelectionError(f"{name} fields mismatch")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PilotIntegrationHumanSelectionError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotIntegrationHumanSelectionError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None:
        raise PilotIntegrationHumanSelectionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotIntegrationHumanSelectionError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotIntegrationHumanSelectionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PilotIntegrationHumanSelectionError("selection notes must be an array")
    items = tuple(value)
    if len(items) > _MAX_NOTES:
        raise PilotIntegrationHumanSelectionError("selection has too many notes")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise PilotIntegrationHumanSelectionError("selection note is invalid")
    if len(items) != len(set(items)):
        raise PilotIntegrationHumanSelectionError(
            "selection notes must not contain duplicates"
        )
    return items


def _require_candidate(value: Any) -> PilotIntegrationSelectionCandidateProof:
    if type(value) is not PilotIntegrationSelectionCandidateProof:
        raise PilotIntegrationHumanSelectionError(
            "exact PilotIntegrationSelectionCandidateProof is required"
        )
    false_fields = (
        value.human_selection_recorded,
        value.integration_ready,
        value.preflight_observed,
        value.preflight_satisfied,
        value.pilot_start_authorized,
        value.product_pilot_started,
        value.remote_write_authorized,
        value.push_authorized,
        value.pr_mutation_authorized,
        value.merge_authorized,
        value.release_authorized,
        value.deploy_authorized,
        value.production_activation_authorized,
    )
    if (
        value.authority != PILOT_INTEGRATION_SELECTION_CANDIDATE_AUTHORITY
        or value.human_pilot_go_verified is not True
        or value.pilot_scope_verified is not True
        or value.source_inventory_verified is not True
        or value.selection_requirements_verified is not True
        or value.design_candidate_validated is not True
        or any(item is not False for item in false_fields)
    ):
        raise PilotIntegrationHumanSelectionError(
            "integration candidate is not inert verified evidence"
        )
    try:
        replayed = PilotIntegrationSelectionCandidateProof.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotIntegrationHumanSelectionError(
            "integration candidate replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotIntegrationHumanSelectionError(
            "integration candidate replay identity mismatch"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotIntegrationHumanSelection:
    selection_id: str
    candidate_proof: PilotIntegrationSelectionCandidateProof
    candidate_proof_sha256: str
    selection_maker_actor_id: str
    selected_at_utc: str
    notes: tuple[str, ...]
    human_selection_intent: str = PILOT_INTEGRATION_HUMAN_SELECTION_INTENT
    human_selection_recorded: bool = False
    integration_ready: bool = False
    preflight_observed: bool = False
    preflight_satisfied: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY
    schema: str = PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA:
            raise PilotIntegrationHumanSelectionError(
                "human integration selection schema is unsupported"
            )
        _identifier(self.selection_id, name="selection_id")
        candidate = _require_candidate(self.candidate_proof)
        _hex64(self.candidate_proof_sha256, name="candidate_proof_sha256")
        if self.candidate_proof_sha256 != candidate.sha256:
            raise PilotIntegrationHumanSelectionError(
                "human selection candidate proof hash mismatch"
            )
        _actor(self.selection_maker_actor_id, name="selection_maker_actor_id")
        _utc(self.selected_at_utc, name="selected_at_utc")
        _notes(self.notes)
        if self.human_selection_intent != PILOT_INTEGRATION_HUMAN_SELECTION_INTENT:
            raise PilotIntegrationHumanSelectionError(
                "human selection intent is unsupported"
            )
        if (
            self.human_selection_recorded is not False
            or self.integration_ready is not False
            or self.preflight_observed is not False
            or self.preflight_satisfied is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY
        ):
            raise PilotIntegrationHumanSelectionError(
                "human selection claim authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotIntegrationHumanSelection":
        data = dict(
            _strict(
                value,
                fields=_SELECTION_FIELDS,
                name="human integration selection",
            )
        )
        if not isinstance(data.get("candidate_proof"), Mapping):
            raise PilotIntegrationHumanSelectionError(
                "human selection candidate proof is invalid"
            )
        if not isinstance(data.get("notes"), list):
            raise PilotIntegrationHumanSelectionError(
                "human selection notes are invalid"
            )
        data["candidate_proof"] = PilotIntegrationSelectionCandidateProof.from_mapping(
            data["candidate_proof"]
        )
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "selection_id": self.selection_id,
            "candidate_proof": self.candidate_proof.to_dict(),
            "candidate_proof_sha256": self.candidate_proof_sha256,
            "selection_maker_actor_id": self.selection_maker_actor_id,
            "selected_at_utc": self.selected_at_utc,
            "notes": list(self.notes),
            "human_selection_intent": self.human_selection_intent,
            "human_selection_recorded": self.human_selection_recorded,
            "integration_ready": self.integration_ready,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "pilot_start_authorized": self.pilot_start_authorized,
            "product_pilot_started": self.product_pilot_started,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PilotIntegrationHumanSelectionProof:
    selection_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    selection: PilotIntegrationHumanSelection
    candidate_proof_sha256: str
    verified_at_utc: str
    human_selection_recorded: bool = True
    candidate_selection_verified: bool = True
    integration_ready: bool = False
    preflight_observed: bool = False
    preflight_satisfied: bool = False
    pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY
    schema: str = PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA:
            raise PilotIntegrationHumanSelectionError(
                "human integration selection proof schema is unsupported"
            )
        _hex64(self.selection_sha256, name="selection_sha256")
        _hex64(self.signature_sha256, name="signature_sha256")
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if self.issuer_system_id != PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID:
            raise PilotIntegrationHumanSelectionError(
                "human selection proof issuer system is invalid"
            )
        if type(self.selection) is not PilotIntegrationHumanSelection:
            raise PilotIntegrationHumanSelectionError(
                "exact PilotIntegrationHumanSelection is required"
            )
        if self.selection_sha256 != self.selection.sha256:
            raise PilotIntegrationHumanSelectionError(
                "human selection proof payload hash mismatch"
            )
        _hex64(self.candidate_proof_sha256, name="candidate_proof_sha256")
        if self.candidate_proof_sha256 != self.selection.candidate_proof_sha256:
            raise PilotIntegrationHumanSelectionError(
                "human selection proof candidate hash mismatch"
            )
        if self.issuer_actor_id != self.selection.selection_maker_actor_id:
            raise PilotIntegrationHumanSelectionError(
                "human selection proof signer mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        selected = _utc(self.selection.selected_at_utc, name="selected_at_utc")
        if verified < selected:
            raise PilotIntegrationHumanSelectionError(
                "human selection proof timing is invalid"
            )
        if (
            self.human_selection_recorded is not True
            or self.candidate_selection_verified is not True
            or self.integration_ready is not False
            or self.preflight_observed is not False
            or self.preflight_satisfied is not False
            or self.pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.remote_write_authorized is not False
            or self.push_authorized is not False
            or self.pr_mutation_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY
        ):
            raise PilotIntegrationHumanSelectionError(
                "human selection proof authority boundary is invalid"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotIntegrationHumanSelectionProof":
        data = dict(
            _strict(
                value,
                fields=_PROOF_FIELDS,
                name="human integration selection proof",
            )
        )
        if not isinstance(data.get("selection"), Mapping):
            raise PilotIntegrationHumanSelectionError(
                "human selection proof selection is invalid"
            )
        data["selection"] = PilotIntegrationHumanSelection.from_mapping(
            data["selection"]
        )
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "selection_sha256": self.selection_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "selection": self.selection.to_dict(),
            "candidate_proof_sha256": self.candidate_proof_sha256,
            "verified_at_utc": self.verified_at_utc,
            "human_selection_recorded": self.human_selection_recorded,
            "candidate_selection_verified": self.candidate_selection_verified,
            "integration_ready": self.integration_ready,
            "preflight_observed": self.preflight_observed,
            "preflight_satisfied": self.preflight_satisfied,
            "pilot_start_authorized": self.pilot_start_authorized,
            "product_pilot_started": self.product_pilot_started,
            "remote_write_authorized": self.remote_write_authorized,
            "push_authorized": self.push_authorized,
            "pr_mutation_authorized": self.pr_mutation_authorized,
            "merge_authorized": self.merge_authorized,
            "release_authorized": self.release_authorized,
            "deploy_authorized": self.deploy_authorized,
            "production_activation_authorized": self.production_activation_authorized,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


def build_pilot_integration_human_selection(
    *,
    candidate_proof: PilotIntegrationSelectionCandidateProof,
    selection_id: str,
    selection_maker_actor_id: str,
    selected_at_utc: str,
    notes: Sequence[str] = (),
) -> PilotIntegrationHumanSelection:
    """Build exact bytes for external human signing; this selects nothing by itself."""
    candidate = _require_candidate(candidate_proof)
    return PilotIntegrationHumanSelection(
        selection_id=selection_id,
        candidate_proof=candidate,
        candidate_proof_sha256=candidate.sha256,
        selection_maker_actor_id=selection_maker_actor_id,
        selected_at_utc=selected_at_utc,
        notes=_notes(notes),
    )


def _verify_pilot_integration_human_selection(
    *,
    candidate_proof: PilotIntegrationSelectionCandidateProof,
    selection: PilotIntegrationHumanSelection,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotIntegrationHumanSelectionProof:
    candidate = _require_candidate(candidate_proof)
    if type(selection) is not PilotIntegrationHumanSelection:
        raise PilotIntegrationHumanSelectionError(
            "exact PilotIntegrationHumanSelection is required"
        )
    if (
        selection.candidate_proof_sha256 != candidate.sha256
        or selection.candidate_proof != candidate
    ):
        raise PilotIntegrationHumanSelectionError(
            "human selection is not exactly bound to the supplied candidate"
        )
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise PilotIntegrationHumanSelectionError(
            "detached Ed25519 human selection signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotIntegrationHumanSelectionError(
            "Ed25519 human selection verifier is required"
        )
    if (
        signature.issuer_system_id
        != PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID
    ):
        raise PilotIntegrationHumanSelectionError(
            "human selection signature belongs to another issuer system"
        )
    if signature.issuer_actor_id != selection.selection_maker_actor_id:
        raise PilotIntegrationHumanSelectionError(
            "human selection signer must be the selection maker"
        )
    if signature.signed_at_utc != selection.selected_at_utc:
        raise PilotIntegrationHumanSelectionError(
            "human selection signature time does not match the claim"
        )
    verified_at = now_provider()
    if _utc(
        verified_at, name="human selection verification time"
    ) < _utc(selection.selected_at_utc, name="selected_at_utc"):
        raise PilotIntegrationHumanSelectionError(
            "human selection verification predates the selection"
        )
    try:
        verified_payload_sha256 = verifier.verify(
            payload=selection.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotIntegrationHumanSelectionError(
            "human integration selection authority verification failed"
        ) from exc
    if verified_payload_sha256 != selection.sha256:
        raise PilotIntegrationHumanSelectionError(
            "human selection verified payload hash mismatch"
        )
    return PilotIntegrationHumanSelectionProof(
        selection_sha256=selection.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        selection=selection,
        candidate_proof_sha256=candidate.sha256,
        verified_at_utc=verified_at,
    )


def verify_pilot_integration_human_selection(
    *,
    candidate_proof: PilotIntegrationSelectionCandidateProof,
    selection: PilotIntegrationHumanSelection,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotIntegrationHumanSelectionProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise PilotIntegrationHumanSelectionError(
            "human selection verifier is unavailable outside production facade"
        )
    return _verify_pilot_integration_human_selection(
        candidate_proof=candidate_proof,
        selection=selection,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_INTEGRATION_HUMAN_SELECTION_SCHEMA",
    "PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_SCHEMA",
    "PILOT_INTEGRATION_HUMAN_SELECTION_AUTHORITY",
    "PILOT_INTEGRATION_HUMAN_SELECTION_PROOF_AUTHORITY",
    "PILOT_INTEGRATION_HUMAN_SELECTION_ISSUER_SYSTEM_ID",
    "PILOT_INTEGRATION_HUMAN_SELECTION_INTENT",
    "PilotIntegrationHumanSelectionError",
    "PilotIntegrationHumanSelection",
    "PilotIntegrationHumanSelectionProof",
    "build_pilot_integration_human_selection",
    "verify_pilot_integration_human_selection",
]

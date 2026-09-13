"""Human-signed pilot GO/NO-GO decision over one completed DC-L15 chain.

ADR-DC-015 closes only the terminal human pilot-decision gate. It does not start
a product pilot, expose a Kaliv entrypoint, enable a feature flag, mutate Git or
GitHub, or authorize production activation. The decision itself carries the
exact local pilot scope and immutable default-deny invariants.
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
from .improvement_physical_campaign_independent_verdict import (
    PhysicalCampaignIndependentHumanVerdictProof,
)

HUMAN_PILOT_DECISION_SCHEMA = "kaliv-rsi-human-pilot-decision/v1"
HUMAN_PILOT_DECISION_PROOF_SCHEMA = "kaliv-rsi-human-pilot-decision-proof/v1"
HUMAN_PILOT_DECISION_AUTHORITY = "human-dc-l16-pilot-decision-claim-only"
HUMAN_PILOT_DECISION_PROOF_AUTHORITY = "verified-human-dc-l16-pilot-decision-only"
HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID = "kaliv-rsi-dc-l16-human-pilot-decision-authority-v1"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DECISIONS = {"go", "no_go", "go_with_conditions"}
_MAX_TASKS = 8
_MAX_NOTES = 32


class HumanPilotDecisionError(ValueError):
    """Pilot-decision evidence is malformed, untrusted or over-authorizing."""


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
        raise HumanPilotDecisionError("human pilot decision is not canonical JSON") from exc


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise HumanPilotDecisionError(f"{name} fields mismatch")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise HumanPilotDecisionError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise HumanPilotDecisionError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise HumanPilotDecisionError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise HumanPilotDecisionError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HumanPilotDecisionError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _task_ids(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise HumanPilotDecisionError("allowed task IDs must be an array")
    items = tuple(value)
    if not 1 <= len(items) <= _MAX_TASKS:
        raise HumanPilotDecisionError("pilot scope must contain one through eight task IDs")
    for item in items:
        _identifier(item, name="allowed task ID")
    if tuple(sorted(set(items))) != items:
        raise HumanPilotDecisionError("allowed task IDs must be sorted and unique")
    return items


def _notes(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise HumanPilotDecisionError("pilot decision notes must be an array")
    items = tuple(value)
    if len(items) > _MAX_NOTES:
        raise HumanPilotDecisionError("pilot decision has too many notes")
    for item in items:
        if (
            not isinstance(item, str)
            or not item
            or item.strip() != item
            or "\x00" in item
            or len(item.encode("utf-8")) > 2_048
        ):
            raise HumanPilotDecisionError("pilot decision note is invalid")
    if len(items) != len(set(items)):
        raise HumanPilotDecisionError("pilot decision notes must not contain duplicates")
    return items


_DECISION_FIELDS = {
    "schema",
    "decision_id",
    "completion_proof_sha256",
    "campaign_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "decision_maker_actor_id",
    "decision",
    "operator_surface",
    "allowed_task_ids",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "notes",
    "decided_at_utc",
    "feature_flag_default_off",
    "local_only_scope_confirmed",
    "kill_switch_required",
    "restart_revoke_required",
    "unattended_cadence_allowed",
    "remote_write_allowed",
    "push_allowed",
    "pr_mutation_allowed",
    "merge_allowed",
    "release_allowed",
    "deploy_allowed",
    "production_activation_allowed",
    "authority",
}


@dataclass(frozen=True, slots=True)
class HumanPilotDecision:
    decision_id: str
    completion_proof_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    decision_maker_actor_id: str
    decision: str
    operator_surface: str
    allowed_task_ids: tuple[str, ...]
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    notes: tuple[str, ...]
    decided_at_utc: str
    feature_flag_default_off: bool = True
    local_only_scope_confirmed: bool = True
    kill_switch_required: bool = True
    restart_revoke_required: bool = True
    unattended_cadence_allowed: bool = False
    remote_write_allowed: bool = False
    push_allowed: bool = False
    pr_mutation_allowed: bool = False
    merge_allowed: bool = False
    release_allowed: bool = False
    deploy_allowed: bool = False
    production_activation_allowed: bool = False
    authority: str = HUMAN_PILOT_DECISION_AUTHORITY
    schema: str = HUMAN_PILOT_DECISION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != HUMAN_PILOT_DECISION_SCHEMA:
            raise HumanPilotDecisionError("human pilot decision schema is unsupported")
        _identifier(self.decision_id, name="decision_id")
        _hex(self.completion_proof_sha256, name="completion_proof_sha256", pattern=_HEX64)
        _identifier(self.campaign_id, name="campaign_id")
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise HumanPilotDecisionError("task_id is invalid")
        _hex(self.task_sha256, name="task_sha256", pattern=_HEX64)
        if self.repository != "Ternedal/ModelRig":
            raise HumanPilotDecisionError("repository is unsupported")
        _hex(self.base_sha, name="base_sha", pattern=_HEX40)
        _hex(self.requested_main_sha, name="requested_main_sha", pattern=_HEX40)
        _actor(self.decision_maker_actor_id, name="decision_maker_actor_id")
        if self.decision not in _DECISIONS:
            raise HumanPilotDecisionError("human pilot decision is unsupported")
        _identifier(self.operator_surface, name="operator_surface")
        _task_ids(self.allowed_task_ids)
        _hex(self.workspace_root_path_sha256, name="workspace_root_path_sha256", pattern=_HEX64)
        if type(self.local_commits_allowed) is not bool:
            raise HumanPilotDecisionError("local_commits_allowed must be boolean")
        notes = _notes(self.notes)
        if self.decision in {"no_go", "go_with_conditions"} and not notes:
            raise HumanPilotDecisionError("NO-GO and conditional GO require explicit notes")
        _utc(self.decided_at_utc, name="decided_at_utc")
        if (
            self.feature_flag_default_off is not True
            or self.local_only_scope_confirmed is not True
            or self.kill_switch_required is not True
            or self.restart_revoke_required is not True
            or self.unattended_cadence_allowed is not False
            or self.remote_write_allowed is not False
            or self.push_allowed is not False
            or self.pr_mutation_allowed is not False
            or self.merge_allowed is not False
            or self.release_allowed is not False
            or self.deploy_allowed is not False
            or self.production_activation_allowed is not False
            or self.authority != HUMAN_PILOT_DECISION_AUTHORITY
        ):
            raise HumanPilotDecisionError("human pilot decision authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "HumanPilotDecision":
        data = dict(_strict(value, fields=_DECISION_FIELDS, name="human pilot decision"))
        if not isinstance(data.get("allowed_task_ids"), list) or not isinstance(data.get("notes"), list):
            raise HumanPilotDecisionError("human pilot decision arrays are invalid")
        data["allowed_task_ids"] = tuple(data["allowed_task_ids"])
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision_id": self.decision_id,
            "completion_proof_sha256": self.completion_proof_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "decision_maker_actor_id": self.decision_maker_actor_id,
            "decision": self.decision,
            "operator_surface": self.operator_surface,
            "allowed_task_ids": list(self.allowed_task_ids),
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "notes": list(self.notes),
            "decided_at_utc": self.decided_at_utc,
            "feature_flag_default_off": self.feature_flag_default_off,
            "local_only_scope_confirmed": self.local_only_scope_confirmed,
            "kill_switch_required": self.kill_switch_required,
            "restart_revoke_required": self.restart_revoke_required,
            "unattended_cadence_allowed": self.unattended_cadence_allowed,
            "remote_write_allowed": self.remote_write_allowed,
            "push_allowed": self.push_allowed,
            "pr_mutation_allowed": self.pr_mutation_allowed,
            "merge_allowed": self.merge_allowed,
            "release_allowed": self.release_allowed,
            "deploy_allowed": self.deploy_allowed,
            "production_activation_allowed": self.production_activation_allowed,
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


_PROOF_FIELDS = {
    "schema",
    "decision_sha256",
    "signature_sha256",
    "key_id",
    "issuer_actor_id",
    "issuer_system_id",
    "completion_proof_sha256",
    "campaign_id",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "decision_id",
    "decision_maker_actor_id",
    "decision",
    "operator_surface",
    "allowed_task_ids",
    "workspace_root_path_sha256",
    "local_commits_allowed",
    "notes",
    "decided_at_utc",
    "verified_at_utc",
    "human_pilot_decision_recorded",
    "pilot_go_authorized",
    "product_pilot_started",
    "feature_flag_default_off",
    "remote_write_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
    "authority",
}


@dataclass(frozen=True, slots=True)
class HumanPilotDecisionProof:
    decision_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    completion_proof_sha256: str
    campaign_id: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    decision_id: str
    decision_maker_actor_id: str
    decision: str
    operator_surface: str
    allowed_task_ids: tuple[str, ...]
    workspace_root_path_sha256: str
    local_commits_allowed: bool
    notes: tuple[str, ...]
    decided_at_utc: str
    verified_at_utc: str
    human_pilot_decision_recorded: bool = True
    pilot_go_authorized: bool = False
    product_pilot_started: bool = False
    feature_flag_default_off: bool = True
    remote_write_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = HUMAN_PILOT_DECISION_PROOF_AUTHORITY
    schema: str = HUMAN_PILOT_DECISION_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != HUMAN_PILOT_DECISION_PROOF_SCHEMA:
            raise HumanPilotDecisionError("human pilot decision proof schema is unsupported")
        for name, value, pattern in (
            ("decision_sha256", self.decision_sha256, _HEX64),
            ("signature_sha256", self.signature_sha256, _HEX64),
            ("completion_proof_sha256", self.completion_proof_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("workspace_root_path_sha256", self.workspace_root_path_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        _identifier(self.campaign_id, name="campaign_id")
        _identifier(self.decision_id, name="decision_id")
        _actor(self.decision_maker_actor_id, name="decision_maker_actor_id")
        _identifier(self.operator_surface, name="operator_surface")
        _task_ids(self.allowed_task_ids)
        _notes(self.notes)
        if not isinstance(self.task_id, str) or not 1 <= len(self.task_id) <= 64:
            raise HumanPilotDecisionError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise HumanPilotDecisionError("repository is unsupported")
        if self.issuer_system_id != HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID:
            raise HumanPilotDecisionError("human pilot decision proof issuer system is invalid")
        if self.issuer_actor_id != self.decision_maker_actor_id:
            raise HumanPilotDecisionError("human pilot decision proof signer mismatch")
        if self.decision not in _DECISIONS:
            raise HumanPilotDecisionError("human pilot decision proof decision is unsupported")
        if type(self.local_commits_allowed) is not bool:
            raise HumanPilotDecisionError("local_commits_allowed must be boolean")
        decided = _utc(self.decided_at_utc, name="decided_at_utc")
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        expected_go = self.decision in {"go", "go_with_conditions"}
        if verified < decided:
            raise HumanPilotDecisionError("human pilot decision proof timing is invalid")
        if (
            self.human_pilot_decision_recorded is not True
            or self.pilot_go_authorized is not expected_go
            or self.product_pilot_started is not False
            or self.feature_flag_default_off is not True
            or self.remote_write_authorized is not False
            or self.merge_authorized is not False
            or self.release_authorized is not False
            or self.deploy_authorized is not False
            or self.production_activation_authorized is not False
            or self.authority != HUMAN_PILOT_DECISION_PROOF_AUTHORITY
        ):
            raise HumanPilotDecisionError("human pilot decision proof authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "HumanPilotDecisionProof":
        data = dict(_strict(value, fields=_PROOF_FIELDS, name="human pilot decision proof"))
        if not isinstance(data.get("allowed_task_ids"), list) or not isinstance(data.get("notes"), list):
            raise HumanPilotDecisionError("human pilot decision proof arrays are invalid")
        data["allowed_task_ids"] = tuple(data["allowed_task_ids"])
        data["notes"] = tuple(data["notes"])
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "decision_sha256": self.decision_sha256,
            "signature_sha256": self.signature_sha256,
            "key_id": self.key_id,
            "issuer_actor_id": self.issuer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "completion_proof_sha256": self.completion_proof_sha256,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "decision_id": self.decision_id,
            "decision_maker_actor_id": self.decision_maker_actor_id,
            "decision": self.decision,
            "operator_surface": self.operator_surface,
            "allowed_task_ids": list(self.allowed_task_ids),
            "workspace_root_path_sha256": self.workspace_root_path_sha256,
            "local_commits_allowed": self.local_commits_allowed,
            "notes": list(self.notes),
            "decided_at_utc": self.decided_at_utc,
            "verified_at_utc": self.verified_at_utc,
            "human_pilot_decision_recorded": self.human_pilot_decision_recorded,
            "pilot_go_authorized": self.pilot_go_authorized,
            "product_pilot_started": self.product_pilot_started,
            "feature_flag_default_off": self.feature_flag_default_off,
            "remote_write_authorized": self.remote_write_authorized,
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


def _require_completion(value: Any) -> PhysicalCampaignIndependentHumanVerdictProof:
    if type(value) is not PhysicalCampaignIndependentHumanVerdictProof:
        raise HumanPilotDecisionError("exact PhysicalCampaignIndependentHumanVerdictProof is required")
    if (
        value.independent_human_verdict_verified is not True
        or value.runner_execution_binding_proven is not True
        or value.continuous_main_freeze_proven is not True
        or value.physical_campaign_completed is not True
        or value.dc_l15_complete is not True
        or value.dc_l14_independent_human_verdict_required is not False
        or value.human_pilot_go_required is not True
        or value.pilot_go_authorized is not False
        or value.activation_authorized is not False
        or value.remote_publication_authorized is not False
        or value.remaining_completion_gates != ("human_pilot_go_decision",)
    ):
        raise HumanPilotDecisionError("DC-L15 completion proof authority state is invalid")
    return value


def build_human_pilot_decision(
    *,
    completion_proof: PhysicalCampaignIndependentHumanVerdictProof,
    decision_id: str,
    decision_maker_actor_id: str,
    decision: str,
    operator_surface: str,
    allowed_task_ids: Sequence[str],
    workspace_root_path_sha256: str,
    local_commits_allowed: bool,
    notes: Sequence[str] = (),
    decided_at_utc: str,
) -> HumanPilotDecision:
    """Build exact bytes for external human signing; this starts no pilot."""
    completion = _require_completion(completion_proof)
    decided = _utc(decided_at_utc, name="decided_at_utc")
    completed = _utc(completion.verified_at_utc, name="completion verified_at_utc")
    if decided < completed:
        raise HumanPilotDecisionError("human pilot decision predates DC-L15 completion")
    return HumanPilotDecision(
        decision_id=decision_id,
        completion_proof_sha256=completion.sha256,
        campaign_id=completion.campaign_id,
        task_id=completion.task_id,
        task_sha256=completion.task_sha256,
        repository=completion.repository,
        base_sha=completion.base_sha,
        requested_main_sha=completion.requested_main_sha,
        decision_maker_actor_id=decision_maker_actor_id,
        decision=decision,
        operator_surface=operator_surface,
        allowed_task_ids=_task_ids(allowed_task_ids),
        workspace_root_path_sha256=workspace_root_path_sha256,
        local_commits_allowed=local_commits_allowed,
        notes=_notes(notes),
        decided_at_utc=decided_at_utc,
    )


def _decision_matches_completion(*, completion: PhysicalCampaignIndependentHumanVerdictProof, decision: HumanPilotDecision) -> bool:
    expected = {
        "completion_proof_sha256": completion.sha256,
        "campaign_id": completion.campaign_id,
        "task_id": completion.task_id,
        "task_sha256": completion.task_sha256,
        "repository": completion.repository,
        "base_sha": completion.base_sha,
        "requested_main_sha": completion.requested_main_sha,
    }
    return all(getattr(decision, name) == item for name, item in expected.items())


def _verify_human_pilot_decision(
    *,
    completion_proof: PhysicalCampaignIndependentHumanVerdictProof,
    decision: HumanPilotDecision,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> HumanPilotDecisionProof:
    completion = _require_completion(completion_proof)
    if type(decision) is not HumanPilotDecision:
        raise HumanPilotDecisionError("exact HumanPilotDecision is required")
    if not _decision_matches_completion(completion=completion, decision=decision):
        raise HumanPilotDecisionError("human pilot decision is not exactly bound to DC-L15 completion")
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise HumanPilotDecisionError("detached Ed25519 human pilot decision signature is required")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise HumanPilotDecisionError("Ed25519 human pilot decision verifier is required")
    if signature.issuer_system_id != HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID:
        raise HumanPilotDecisionError("human pilot decision signature belongs to another issuer system")
    if signature.issuer_actor_id != decision.decision_maker_actor_id:
        raise HumanPilotDecisionError("human pilot decision signer must be the decision maker")
    if signature.signed_at_utc != decision.decided_at_utc:
        raise HumanPilotDecisionError("human pilot decision signature time does not match the claim")
    verified_at = now_provider()
    if _utc(verified_at, name="human pilot decision verification time") < _utc(decision.decided_at_utc, name="decided_at_utc"):
        raise HumanPilotDecisionError("human pilot decision verification predates the decision")
    try:
        verified_payload_sha256 = verifier.verify(
            payload=decision.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise HumanPilotDecisionError("human pilot decision authority verification failed") from exc
    if verified_payload_sha256 != decision.sha256:
        raise HumanPilotDecisionError("human pilot decision verified payload hash mismatch")
    return HumanPilotDecisionProof(
        decision_sha256=decision.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        completion_proof_sha256=completion.sha256,
        campaign_id=completion.campaign_id,
        task_id=completion.task_id,
        task_sha256=completion.task_sha256,
        repository=completion.repository,
        base_sha=completion.base_sha,
        requested_main_sha=completion.requested_main_sha,
        decision_id=decision.decision_id,
        decision_maker_actor_id=decision.decision_maker_actor_id,
        decision=decision.decision,
        operator_surface=decision.operator_surface,
        allowed_task_ids=decision.allowed_task_ids,
        workspace_root_path_sha256=decision.workspace_root_path_sha256,
        local_commits_allowed=decision.local_commits_allowed,
        notes=decision.notes,
        decided_at_utc=decision.decided_at_utc,
        verified_at_utc=verified_at,
        pilot_go_authorized=decision.decision in {"go", "go_with_conditions"},
    )


def verify_human_pilot_decision(
    *,
    completion_proof: PhysicalCampaignIndependentHumanVerdictProof,
    decision: HumanPilotDecision,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier | None = None,
) -> HumanPilotDecisionProof:
    """Injectable compatibility surface replaced by the production facade."""
    if verifier is None:
        raise HumanPilotDecisionError("human pilot decision verifier is unavailable outside production facade")
    return _verify_human_pilot_decision(
        completion_proof=completion_proof,
        decision=decision,
        signature=signature,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "HUMAN_PILOT_DECISION_SCHEMA",
    "HUMAN_PILOT_DECISION_PROOF_SCHEMA",
    "HUMAN_PILOT_DECISION_AUTHORITY",
    "HUMAN_PILOT_DECISION_PROOF_AUTHORITY",
    "HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID",
    "HumanPilotDecisionError",
    "HumanPilotDecision",
    "HumanPilotDecisionProof",
    "build_human_pilot_decision",
    "verify_human_pilot_decision",
]

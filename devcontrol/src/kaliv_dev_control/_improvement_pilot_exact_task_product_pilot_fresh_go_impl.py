"""ADR-DC-099 fresh human product-pilot GO bound to exact qualified lineage.

The claim is built only from one inert ADR-DC-098 lineage attestation plus one
fresh live ADR-DC-095 post-production activation attestation. The corresponding
ADR-DC-096 requirements manifest is re-derived and its exact digest is signed by
one host-trusted human authority.

Verification produces only a fresh process-local GO proof for a later readiness
boundary. It does not make the product pilot ready, authorize start, start the
pilot, execute a task, mutate a repository, write remotely, deploy, restart, or
activate production.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from .asymmetric_authority import (
    AsymmetricAuthorityError,
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from . import improvement_human_pilot_decision as human_boundary
from . import improvement_pilot_exact_task_post_production_activation_attestation as post_boundary
from . import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage_boundary
from . import improvement_pilot_exact_task_product_pilot_start_requirements as requirements_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-fresh-go-claim/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-fresh-go-proof/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY = (
    "human-dc-l16-exact-product-pilot-fresh-go-claim-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY = (
    "verified-human-dc-l16-exact-product-pilot-fresh-go-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE = (
    "one-exact-lineage-qualified-product-pilot-go-only-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID = (
    human_boundary.HUMAN_PILOT_DECISION_ISSUER_SYSTEM_ID
)
PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS = 300

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotFreshGoError(ValueError):
    """Fresh product-pilot human GO is malformed, stale, or over-authorizing."""


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
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot fresh GO is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotFreshGoError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotFreshGoError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    return _utc(value, name=name).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _replay(value: Any, cls: type, *, name: str) -> Any:
    if type(value) is not cls:
        raise PilotExactTaskProductPilotFreshGoError(f"exact {name} is required")
    try:
        replayed = cls.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductPilotFreshGoError(
            f"{name} replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotFreshGoError(
            f"{name} replay identity mismatch"
        )
    return value


@dataclass(frozen=True, slots=True)
class PilotExactTaskProductPilotFreshGoClaim:
    product_pilot_lineage_attestation_sha256: str
    product_pilot_start_requirements_sha256: str
    post_production_activation_attestation_sha256: str
    historical_human_go_proof_sha256: str
    production_activation_candidate_sha256: str
    execution_nonce_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    operator_surface: str
    selected_pilot_task_id: str
    workspace_root_path_sha256: str
    feature_flag_name: str
    product_route: str
    decision_id: str
    decision_maker_actor_id: str
    decided_at_utc: str
    expires_at_utc: str
    decision: str = "go"
    local_commits_allowed: bool = False
    remote_write_allowed: bool = False
    unattended_cadence_allowed: bool = False
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    go_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY
            or self.go_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO claim identity is unsupported"
            )
        for name in (
            "product_pilot_lineage_attestation_sha256",
            "product_pilot_start_requirements_sha256",
            "post_production_activation_attestation_sha256",
            "historical_human_go_proof_sha256",
            "production_activation_candidate_sha256",
            "execution_nonce_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO repository is unsupported"
            )
        if (
            not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO repository_id is invalid"
            )
        for name in (
            "operator_surface",
            "selected_pilot_task_id",
            "feature_flag_name",
            "decision_id",
        ):
            _identifier(getattr(self, name), name=name)
        _actor(self.decision_maker_actor_id, name="decision_maker_actor_id")
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO product_route is invalid"
            )
        decided = _utc(self.decided_at_utc, name="decided_at_utc")
        expires = _utc(self.expires_at_utc, name="expires_at_utc")
        lifetime = int((expires - decided).total_seconds())
        if (
            expires <= decided
            or lifetime != (expires - decided).total_seconds()
            or lifetime > PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO authorization window is invalid"
            )
        if (
            self.decision != "go"
            or self.local_commits_allowed is not False
            or self.remote_write_allowed is not False
            or self.unattended_cadence_allowed is not False
            or self.product_pilot_start_ready is not False
            or self.product_pilot_start_authorized is not False
            or self.product_pilot_started is not False
            or self.nonce_reusable is not False
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO claim exceeds inert exact-start scope"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskProductPilotFreshGoClaim":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO claim fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


_LIVE_PROOFS: dict[
    int, tuple[int, str, weakref.ReferenceType[Any]]
] = {}


def _mark_live(proof: "PilotExactTaskProductPilotFreshGoProof") -> None:
    key = id(proof)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _LIVE_PROOFS.pop(key, None)

    _LIVE_PROOFS[key] = (
        os.getpid(),
        proof.sha256,
        weakref.ref(proof, cleanup),
    )


def _is_live(proof: Any) -> bool:
    entry = _LIVE_PROOFS.get(id(proof))
    if entry is None:
        return False
    pid, digest, ref = entry
    return pid == os.getpid() and ref() is proof and digest == proof.sha256


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotFreshGoProof:
    claim: PilotExactTaskProductPilotFreshGoClaim
    claim_sha256: str
    signature_sha256: str
    key_id: str
    issuer_actor_id: str
    issuer_system_id: str
    verified_at_utc: str
    fresh_product_pilot_go_verified: bool = True
    exact_lineage_bound: bool = True
    exact_requirements_bound: bool = True
    exact_pilot_scope_bound: bool = True
    product_pilot_start_ready: bool = False
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_readiness_required: bool = True
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO proof identity is unsupported"
            )
        if type(self.claim) is not PilotExactTaskProductPilotFreshGoClaim:
            raise PilotExactTaskProductPilotFreshGoError(
                "exact product-pilot GO claim is required"
            )
        _hex64(self.claim_sha256, name="claim_sha256")
        _hex64(self.signature_sha256, name="signature_sha256")
        if self.claim_sha256 != self.claim.sha256:
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO claim digest mismatch"
            )
        _identifier(self.key_id, name="key_id")
        _actor(self.issuer_actor_id, name="issuer_actor_id")
        _identifier(self.issuer_system_id, name="issuer_system_id")
        if (
            self.issuer_system_id
            != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID
            or self.issuer_actor_id != self.claim.decision_maker_actor_id
        ):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO signer identity mismatch"
            )
        verified = _utc(self.verified_at_utc, name="verified_at_utc")
        decided = _utc(self.claim.decided_at_utc, name="decided_at_utc")
        expires = _utc(self.claim.expires_at_utc, name="expires_at_utc")
        if verified < decided or verified > expires:
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO verification is outside the signed window"
            )
        required_true = (
            "fresh_product_pilot_go_verified",
            "exact_lineage_bound",
            "exact_requirements_bound",
            "exact_pilot_scope_bound",
            "next_boundary_readiness_required",
        )
        forced_false = (
            "product_pilot_start_ready",
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO proof lacks required positive evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO proof grants forbidden authority"
            )

    @property
    def go_authenticated(self) -> bool:
        return _is_live(self)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            **{
                name: getattr(self, name)
                for name in self.__dataclass_fields__
                if name != "claim"
            },
            "claim": self.claim.to_dict(),
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskProductPilotFreshGoProof":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO proof fields mismatch"
            )
        data = dict(value)
        if not isinstance(data.get("claim"), Mapping):
            raise PilotExactTaskProductPilotFreshGoError(
                "product-pilot GO proof claim is invalid"
            )
        data["claim"] = PilotExactTaskProductPilotFreshGoClaim.from_mapping(
            data["claim"]
        )
        return cls(**data)

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _qualified_material(
    *,
    product_pilot_lineage_attestation: (
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
    ),
    post_production_activation_attestation: (
        post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
) -> tuple[
    lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
    post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
    requirements_boundary.PilotExactTaskProductPilotStartRequirements,
]:
    lineage = _replay(
        product_pilot_lineage_attestation,
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
        name="ADR-DC-098 product-pilot lineage attestation",
    )
    post = post_production_activation_attestation
    requirements = (
        requirements_boundary.build_pilot_exact_task_product_pilot_start_requirements(
            post
        )
    )
    if (
        lineage.historical_human_go_verified is not True
        or lineage.historical_human_selection_verified is not True
        or lineage.historical_preflight_verified is not True
        or lineage.durable_start_consumption_verified is not True
        or lineage.historical_execution_revalidation_verified is not True
        or lineage.durable_execution_admission_verified is not True
        or lineage.execution_nonce_runtime_binding_verified is not True
        or lineage.runtime_production_candidate_binding_verified is not True
        or lineage.live_post_production_activation_verified is not True
        or lineage.product_pilot_start_ready is not False
        or lineage.product_pilot_start_authorized is not False
        or lineage.product_pilot_started is not False
        or lineage.nonce_reusable is not False
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "ADR-DC-098 lineage is not exact inert qualified evidence"
        )
    if (
        requirements.post_production_activation_attestation_sha256
        != lineage.post_production_activation_attestation_sha256
        or requirements.post_production_activation_attestation_sha256 != post.sha256
        or requirements.production_activation_candidate_sha256
        != lineage.production_activation_candidate_sha256
        or requirements.production_activation_candidate_sha256
        != post.production_activation_candidate_sha256
        or requirements.repository != lineage.repository
        or requirements.repository != post.repository
        or requirements.merge_commit_sha != lineage.merge_commit_sha
        or requirements.merge_commit_sha != post.merge_commit_sha
        or requirements.promotion_git_sha != post.promotion_git_sha
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "lineage, requirements, and live production state do not bind one candidate"
        )
    return lineage, post, requirements


def build_pilot_exact_task_product_pilot_fresh_go_claim(
    *,
    product_pilot_lineage_attestation: (
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
    ),
    post_production_activation_attestation: (
        post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    decision_id: str,
    decision_maker_actor_id: str,
    decided_at_utc: str,
    expires_at_utc: str,
) -> PilotExactTaskProductPilotFreshGoClaim:
    lineage, post, requirements = _qualified_material(
        product_pilot_lineage_attestation=product_pilot_lineage_attestation,
        post_production_activation_attestation=post_production_activation_attestation,
    )
    decided = _utc(decided_at_utc, name="decided_at_utc")
    if (
        decided < _utc(lineage.attested_at_utc, name="lineage attested_at_utc")
        or decided
        < _utc(
            post.second_observed_at_utc,
            name="post-production second_observed_at_utc",
        )
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "fresh product-pilot GO predates qualified production lineage"
        )
    return PilotExactTaskProductPilotFreshGoClaim(
        product_pilot_lineage_attestation_sha256=lineage.sha256,
        product_pilot_start_requirements_sha256=requirements.sha256,
        post_production_activation_attestation_sha256=post.sha256,
        historical_human_go_proof_sha256=lineage.human_decision_proof_sha256,
        production_activation_candidate_sha256=lineage.production_activation_candidate_sha256,
        execution_nonce_sha256=lineage.execution_nonce_sha256,
        repository=lineage.repository,
        repository_id=requirements.repository_id,
        merge_commit_sha=lineage.merge_commit_sha,
        promotion_git_sha=requirements.promotion_git_sha,
        operator_surface=lineage.operator_surface,
        selected_pilot_task_id=lineage.selected_pilot_task_id,
        workspace_root_path_sha256=lineage.workspace_root_path_sha256,
        feature_flag_name=lineage.feature_flag_name,
        product_route=lineage.product_route,
        decision_id=decision_id,
        decision_maker_actor_id=decision_maker_actor_id,
        decided_at_utc=_utc_seconds(decided_at_utc, name="decided_at_utc"),
        expires_at_utc=_utc_seconds(expires_at_utc, name="expires_at_utc"),
    )


def _verify_pilot_exact_task_product_pilot_fresh_go(
    *,
    claim: PilotExactTaskProductPilotFreshGoClaim,
    signature: DetachedEd25519AuthoritySignature,
    product_pilot_lineage_attestation: (
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
    ),
    post_production_activation_attestation: (
        post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    verifier: Ed25519AuthorityVerifier,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotFreshGoProof:
    if type(claim) is not PilotExactTaskProductPilotFreshGoClaim:
        raise PilotExactTaskProductPilotFreshGoError(
            "exact product-pilot fresh GO claim is required"
        )
    if type(signature) is not DetachedEd25519AuthoritySignature:
        raise PilotExactTaskProductPilotFreshGoError(
            "detached Ed25519 product-pilot GO signature is required"
        )
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise PilotExactTaskProductPilotFreshGoError(
            "Ed25519 product-pilot GO verifier is required"
        )

    lineage, post, requirements = _qualified_material(
        product_pilot_lineage_attestation=product_pilot_lineage_attestation,
        post_production_activation_attestation=post_production_activation_attestation,
    )
    expected = build_pilot_exact_task_product_pilot_fresh_go_claim(
        product_pilot_lineage_attestation=lineage,
        post_production_activation_attestation=post,
        decision_id=claim.decision_id,
        decision_maker_actor_id=claim.decision_maker_actor_id,
        decided_at_utc=claim.decided_at_utc,
        expires_at_utc=claim.expires_at_utc,
    )
    if expected != claim or expected.sha256 != claim.sha256:
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO claim does not match exact qualified material"
        )
    if (
        claim.product_pilot_start_requirements_sha256 != requirements.sha256
        or claim.product_pilot_lineage_attestation_sha256 != lineage.sha256
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO claim qualified-material digest mismatch"
        )
    if (
        signature.issuer_system_id
        != PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID
        or signature.issuer_actor_id != claim.decision_maker_actor_id
        or signature.signed_at_utc != claim.decided_at_utc
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO signature identity does not match claim"
        )
    verified_at = _utc_seconds(
        now_provider(),
        name="product-pilot GO verified_at_utc",
    )
    verified = _utc(verified_at, name="verified_at_utc")
    if (
        verified < _utc(claim.decided_at_utc, name="decided_at_utc")
        or verified > _utc(claim.expires_at_utc, name="expires_at_utc")
    ):
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO signature is outside the signed window"
        )
    try:
        digest = verifier.verify(
            payload=claim.canonical_json().encode("utf-8"),
            signature=signature,
            at_utc=verified_at,
        )
    except AsymmetricAuthorityError as exc:
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO authority verification failed"
        ) from exc
    if digest != claim.sha256:
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO verified payload hash mismatch"
        )

    proof = PilotExactTaskProductPilotFreshGoProof(
        claim=claim,
        claim_sha256=claim.sha256,
        signature_sha256=signature.sha256,
        key_id=signature.key_id,
        issuer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        verified_at_utc=verified_at,
    )
    _mark_live(proof)
    return proof


def verify_pilot_exact_task_product_pilot_fresh_go(
    *,
    claim: PilotExactTaskProductPilotFreshGoClaim,
    signature: DetachedEd25519AuthoritySignature,
    product_pilot_lineage_attestation: (
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
    ),
    post_production_activation_attestation: (
        post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    verifier: Ed25519AuthorityVerifier | None = None,
) -> PilotExactTaskProductPilotFreshGoProof:
    if verifier is None:
        raise PilotExactTaskProductPilotFreshGoError(
            "product-pilot GO verifier is unavailable outside production facade"
        )
    return _verify_pilot_exact_task_product_pilot_fresh_go(
        claim=claim,
        signature=signature,
        product_pilot_lineage_attestation=product_pilot_lineage_attestation,
        post_production_activation_attestation=post_production_activation_attestation,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_CLAIM_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_PROOF_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_ISSUER_SYSTEM_ID",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_FRESH_GO_MAX_AGE_SECONDS",
    "PilotExactTaskProductPilotFreshGoError",
    "PilotExactTaskProductPilotFreshGoClaim",
    "PilotExactTaskProductPilotFreshGoProof",
    "build_pilot_exact_task_product_pilot_fresh_go_claim",
    "verify_pilot_exact_task_product_pilot_fresh_go",
]

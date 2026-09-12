"""Signed, non-executing promotion from RSI proposal to DevelopmentTask.

The model-authored ImprovementProposal deliberately carries no execution authority.
This module is the separate authority boundary: a complete DevelopmentTask authority
payload must be supplied independently and verified with ModelRig's existing
verification-only Ed25519 authority primitives before a task can be materialized.

There is no private-key loader, signer, filesystem write, subprocess, network call,
campaign start, Git mutation, publication, merge, release or deployment path here.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from .asymmetric_authority import (
    DetachedEd25519AuthoritySignature,
    Ed25519AuthorityVerifier,
)
from .contract import DevelopmentTask, Risk
from .improvement_proposal import ImprovementProposal

PROMOTION_AUTHORIZATION_SCHEMA = "kaliv-rsi-promotion-authorization/v1"
PROMOTION_RECEIPT_SCHEMA = "kaliv-rsi-promotion-receipt/v1"
PROMOTION_ISSUER_SYSTEM_ID = "modelrig-rsi-human-review"
PROMOTION_AUTHORITY = "human-signed-promotion"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ACTOR_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_RISK_ORDER = {
    Risk.TRIVIAL: 0,
    Risk.LOW: 1,
    Risk.MEDIUM: 2,
    Risk.HIGH: 3,
}
_AUTHORIZATION_FIELDS = {
    "schema",
    "proposal_id",
    "proposal_sha256",
    "repository",
    "base_sha",
    "task",
    "required_evals",
    "authority",
}
_RECEIPT_FIELDS = {
    "schema",
    "proposal_id",
    "proposal_sha256",
    "authorization_sha256",
    "authorization_signature_sha256",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "reviewer_actor_id",
    "issuer_system_id",
    "verified_at_utc",
    "required_evals",
    "authority",
}


class ImprovementPromotionError(ValueError):
    """RSI proposal promotion is malformed, unbound or unauthorized."""


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ImprovementPromotionError(f"{name} must be an object")
    return value


def _strict(value: Any, *, name: str, fields: set[str]) -> Mapping[str, Any]:
    data = _mapping(value, name=name)
    unknown = sorted(set(data) - fields)
    missing = sorted(fields - set(data))
    if unknown or missing:
        raise ImprovementPromotionError(
            f"{name} fields mismatch"
            + (f"; unknown={unknown}" if unknown else "")
            + (f"; missing={missing}" if missing else "")
        )
    return data


def _string(value: Any, *, name: str, maximum: int = 4096) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or "\x00" in value
        or len(value.encode("utf-8")) > maximum
    ):
        raise ImprovementPromotionError(f"{name} is invalid")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    text = _string(value, name=name, maximum=pattern.pattern.__len__() + 128)
    if pattern.fullmatch(text) is None:
        raise ImprovementPromotionError(f"{name} is invalid")
    return text


def _strings(
    value: Any,
    *,
    name: str,
    minimum: int = 1,
    maximum_items: int = 128,
    maximum_bytes: int = 1024,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum_items:
        raise ImprovementPromotionError(
            f"{name} must contain {minimum}..{maximum_items} items"
        )
    result = tuple(
        _string(item, name=f"{name}[{index}]", maximum=maximum_bytes)
        for index, item in enumerate(value)
    )
    if len(result) != len(set(result)):
        raise ImprovementPromotionError(f"{name} must not contain duplicates")
    return result


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
        raise ImprovementPromotionError("promotion value is not canonical JSON") from exc


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def proposal_sha256(proposal: ImprovementProposal) -> str:
    if not isinstance(proposal, ImprovementProposal):
        raise ImprovementPromotionError("promotion requires an ImprovementProposal")
    return _sha256_text(proposal.canonical_json())


@dataclass(frozen=True, slots=True)
class PromotionAuthorization:
    """Externally signed authority payload for one exact proposal and task.

    Every execution-authorizing DevelopmentTask field lives in ``task`` and must
    therefore be present in the signed payload. Nothing is defaulted from the
    model proposal's suggested paths/tests.
    """

    proposal_id: str
    proposal_sha256: str
    repository: str
    base_sha: str
    task: DevelopmentTask
    required_evals: tuple[str, ...]
    authority: str = PROMOTION_AUTHORITY
    schema: str = PROMOTION_AUTHORIZATION_SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "PromotionAuthorization":
        data = _strict(
            value,
            name="promotion authorization",
            fields=_AUTHORIZATION_FIELDS,
        )
        if data["schema"] != PROMOTION_AUTHORIZATION_SCHEMA:
            raise ImprovementPromotionError("promotion authorization schema is unsupported")
        if data["authority"] != PROMOTION_AUTHORITY:
            raise ImprovementPromotionError("promotion authority must remain human-signed")
        proposal_id = _string(data["proposal_id"], name="proposal_id", maximum=64)
        proposal_hash = _hex(
            data["proposal_sha256"], name="proposal_sha256", pattern=_HEX64
        )
        repository = _string(data["repository"], name="repository", maximum=200)
        parts = repository.split("/")
        if len(parts) != 2 or not all(part and part.strip() == part for part in parts):
            raise ImprovementPromotionError("repository must be owner/name")
        base_sha = _hex(data["base_sha"], name="base_sha", pattern=_HEX40)
        try:
            task = DevelopmentTask.from_mapping(data["task"])
        except ValueError as exc:
            raise ImprovementPromotionError(f"promotion task is invalid: {exc}") from exc
        required_evals = _strings(
            data["required_evals"],
            name="required_evals",
            maximum_items=64,
            maximum_bytes=1024,
        )
        if task.repository != repository or task.base_sha != base_sha:
            raise ImprovementPromotionError(
                "promotion task repository/base_sha is not bound to authorization"
            )
        return cls(
            proposal_id=proposal_id,
            proposal_sha256=proposal_hash,
            repository=repository,
            base_sha=base_sha,
            task=task,
            required_evals=required_evals,
        )

    @classmethod
    def from_json(cls, text: str) -> "PromotionAuthorization":
        try:
            value = json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ImprovementPromotionError("promotion authorization JSON is invalid") from exc
        return cls.from_mapping(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "task": self.task.to_dict(),
            "required_evals": list(self.required_evals),
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())

    def verify_proposal(self, proposal: ImprovementProposal) -> None:
        expected_hash = proposal_sha256(proposal)
        if self.proposal_id != proposal.proposal_id:
            raise ImprovementPromotionError("authorization proposal_id is not bound")
        if self.proposal_sha256 != expected_hash:
            raise ImprovementPromotionError("authorization proposal_sha256 is not bound")
        if self.repository != proposal.repository:
            raise ImprovementPromotionError("authorization repository is not bound")
        if self.base_sha != proposal.base_sha:
            raise ImprovementPromotionError("authorization base_sha is not bound")
        if self.required_evals != proposal.required_evals:
            raise ImprovementPromotionError(
                "authorization must acknowledge the proposal required_evals exactly"
            )
        missing_criteria = sorted(
            set(proposal.acceptance_criteria) - set(self.task.acceptance_criteria)
        )
        if missing_criteria:
            raise ImprovementPromotionError(
                "promotion task dropped proposal acceptance criteria: "
                + ", ".join(missing_criteria)
            )
        proposal_risk = Risk(proposal.risk.value)
        if _RISK_ORDER[self.task.risk] < _RISK_ORDER[proposal_risk]:
            raise ImprovementPromotionError(
                "promotion task may not silently downgrade proposal risk"
            )


@dataclass(frozen=True, slots=True)
class PromotionReceipt:
    proposal_id: str
    proposal_sha256: str
    authorization_sha256: str
    authorization_signature_sha256: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    reviewer_actor_id: str
    issuer_system_id: str
    verified_at_utc: str
    required_evals: tuple[str, ...]
    authority: str = PROMOTION_AUTHORITY
    schema: str = PROMOTION_RECEIPT_SCHEMA

    @classmethod
    def from_mapping(cls, value: Any) -> "PromotionReceipt":
        data = _strict(value, name="promotion receipt", fields=_RECEIPT_FIELDS)
        if data["schema"] != PROMOTION_RECEIPT_SCHEMA:
            raise ImprovementPromotionError("promotion receipt schema is unsupported")
        if data["authority"] != PROMOTION_AUTHORITY:
            raise ImprovementPromotionError("promotion receipt authority is unsupported")
        for name in (
            "proposal_sha256",
            "authorization_sha256",
            "authorization_signature_sha256",
            "task_sha256",
        ):
            _hex(data[name], name=name, pattern=_HEX64)
        _hex(data["base_sha"], name="base_sha", pattern=_HEX40)
        actor = _string(data["reviewer_actor_id"], name="reviewer_actor_id", maximum=128)
        if _ACTOR_ID.fullmatch(actor) is None:
            raise ImprovementPromotionError("reviewer_actor_id is invalid")
        return cls(
            proposal_id=_string(data["proposal_id"], name="proposal_id", maximum=64),
            proposal_sha256=data["proposal_sha256"],
            authorization_sha256=data["authorization_sha256"],
            authorization_signature_sha256=data["authorization_signature_sha256"],
            task_id=_string(data["task_id"], name="task_id", maximum=64),
            task_sha256=data["task_sha256"],
            repository=_string(data["repository"], name="repository", maximum=200),
            base_sha=data["base_sha"],
            reviewer_actor_id=actor,
            issuer_system_id=_string(
                data["issuer_system_id"], name="issuer_system_id", maximum=128
            ),
            verified_at_utc=_string(
                data["verified_at_utc"], name="verified_at_utc", maximum=32
            ),
            required_evals=_strings(
                data["required_evals"], name="required_evals", maximum_items=64
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "proposal_id": self.proposal_id,
            "proposal_sha256": self.proposal_sha256,
            "authorization_sha256": self.authorization_sha256,
            "authorization_signature_sha256": self.authorization_signature_sha256,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "reviewer_actor_id": self.reviewer_actor_id,
            "issuer_system_id": self.issuer_system_id,
            "verified_at_utc": self.verified_at_utc,
            "required_evals": list(self.required_evals),
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def promote_improvement_proposal(
    *,
    proposal: ImprovementProposal,
    authorization: PromotionAuthorization,
    signature: DetachedEd25519AuthoritySignature,
    verifier: Ed25519AuthorityVerifier,
    verified_at_utc: str,
) -> tuple[DevelopmentTask, PromotionReceipt]:
    """Verify external human authority and materialize one bounded task.

    This function does not start, persist or execute the returned task.
    """

    if not isinstance(authorization, PromotionAuthorization):
        raise ImprovementPromotionError("promotion requires PromotionAuthorization")
    if not isinstance(signature, DetachedEd25519AuthoritySignature):
        raise ImprovementPromotionError("promotion requires detached Ed25519 signature")
    if not isinstance(verifier, Ed25519AuthorityVerifier):
        raise ImprovementPromotionError("promotion requires Ed25519AuthorityVerifier")
    if signature.issuer_system_id != PROMOTION_ISSUER_SYSTEM_ID:
        raise ImprovementPromotionError(
            "promotion signature is not from the RSI human-review authority system"
        )

    authorization.verify_proposal(proposal)
    payload = authorization.canonical_json().encode("utf-8")
    try:
        verifier.verify(payload=payload, signature=signature, at_utc=verified_at_utc)
    except ValueError as exc:
        raise ImprovementPromotionError(f"promotion signature is not trusted: {exc}") from exc

    task = authorization.task
    receipt = PromotionReceipt(
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal_sha256(proposal),
        authorization_sha256=authorization.sha256,
        authorization_signature_sha256=signature.sha256,
        task_id=task.task_id,
        task_sha256=_sha256_text(task.canonical_json()),
        repository=task.repository,
        base_sha=task.base_sha,
        reviewer_actor_id=signature.issuer_actor_id,
        issuer_system_id=signature.issuer_system_id,
        verified_at_utc=verified_at_utc,
        required_evals=authorization.required_evals,
    )
    return task, receipt

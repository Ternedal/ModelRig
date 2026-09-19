"""ADR-DC-096 inert product-pilot start readiness evaluation.

Consumes exactly one fresh live authenticated ADR-DC-095 post-production
activation attestation and derives an evidence-only readiness receipt for the
next product-pilot start authorization boundary.

This boundary performs no network I/O, subprocess execution, durable write,
production mutation, restart, GitHub/deployment/release mutation, or product
pilot start. All reusable mutation authority remains false.
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

from . import improvement_pilot_exact_task_post_production_activation_attestation as attestation_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-readiness-receipt/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY = (
    "host-evaluated-one-dc-l16-exact-product-pilot-start-readiness-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE = (
    "inert-exact-product-pilot-start-readiness-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_MAX_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotStartReadinessError(ValueError):
    """Post-production evidence is not safe to promote into pilot readiness."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskProductPilotStartReadinessError(
            "product-pilot readiness evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartReadinessError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} is invalid"
        ) from exc
    if parsed.tzinfo is None:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} lacks timezone"
        )
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    parsed = _utc(value, name=name)
    if parsed.microsecond:
        raise PilotExactTaskProductPilotStartReadinessError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _seconds_between(*, earlier: str, later: str) -> int:
    delta = _utc(later, name="evaluated_at_utc") - _utc(
        earlier, name="post_production_attested_at_utc"
    )
    seconds = int(delta.total_seconds())
    if seconds < 0 or delta.total_seconds() != seconds:
        raise PilotExactTaskProductPilotStartReadinessError(
            "product-pilot readiness clock is invalid"
        )
    return seconds


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartReadinessReceipt:
    post_production_activation_attestation_sha256: str
    production_activation_candidate_sha256: str
    production_activation_completion_source: str
    production_activation_source_receipt_sha256: str
    production_activation_transaction_lock_sha256: str
    environment_after_sha256: str
    output_state_sha256: str
    production_preflight_sha256: str
    machine_production_receipt_sha256: str
    repository: str
    repository_id: str
    merge_commit_sha: str
    promotion_git_sha: str
    post_production_attested_at_utc: str
    evaluated_at_utc: str
    attestation_age_seconds: int
    production_activation: bool = True
    production_activation_attested: bool = True
    post_production_state_verified: bool = True
    product_pilot_start_ready: bool = True
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    manual_intervention_required: bool = False
    promotion_gate_execution_authorized: bool = False
    production_env_mutation_authorized: bool = False
    appliance_restart_authorized: bool = False
    production_receipt_write_authorized: bool = False
    production_activation_authorized: bool = False
    success_deployment_status_authorized: bool = False
    deployment_status_mutation_authorized: bool = False
    deployment_mutation_authorized: bool = False
    deploy_authorized: bool = False
    remote_write_authorized: bool = False
    release_authorized: bool = False
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    merge_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    nonce_reusable: bool = False
    next_boundary_authorization_required: bool = True
    readiness_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_AUTHORITY
            or self.readiness_scope
            != PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_SCOPE
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness identity is unsupported"
            )
        for name in (
            "post_production_activation_attestation_sha256",
            "production_activation_candidate_sha256",
            "production_activation_source_receipt_sha256",
            "production_activation_transaction_lock_sha256",
            "environment_after_sha256",
            "output_state_sha256",
            "production_preflight_sha256",
            "machine_production_receipt_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if self.production_activation_completion_source not in {
            "transaction",
            "recovery",
        }:
            raise PilotExactTaskProductPilotStartReadinessError(
                "production activation completion source is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness repository identity is invalid"
            )
        _utc_seconds(
            self.post_production_attested_at_utc,
            name="post_production_attested_at_utc",
        )
        _utc_seconds(self.evaluated_at_utc, name="evaluated_at_utc")
        expected_age = _seconds_between(
            earlier=self.post_production_attested_at_utc,
            later=self.evaluated_at_utc,
        )
        if (
            type(self.attestation_age_seconds) is not int
            or self.attestation_age_seconds != expected_age
            or not 0 <= self.attestation_age_seconds
            <= PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_MAX_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotStartReadinessError(
                "post-production attestation is outside the readiness freshness window"
            )

        required_true = (
            "production_activation",
            "production_activation_attested",
            "post_production_state_verified",
            "product_pilot_start_ready",
            "next_boundary_authorization_required",
        )
        forced_false = (
            "product_pilot_start_authorized",
            "product_pilot_started",
            "manual_intervention_required",
            "promotion_gate_execution_authorized",
            "production_env_mutation_authorized",
            "appliance_restart_authorized",
            "production_receipt_write_authorized",
            "production_activation_authorized",
            "success_deployment_status_authorized",
            "deployment_status_mutation_authorized",
            "deployment_mutation_authorized",
            "deploy_authorized",
            "remote_write_authorized",
            "release_authorized",
            "tag_write_authorized",
            "release_mutation_authorized",
            "merge_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness lacks required positive evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness retains forbidden mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def readiness_authenticated(self) -> bool:
        return _get_live_readiness_source(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(cls, value: Any):
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartReadinessError(
                "product-pilot readiness fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _live_registry():
    records: dict[int, tuple[Any, ...]] = {}

    def mark(
        receipt: PilotExactTaskProductPilotStartReadinessReceipt,
        *,
        source: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            source.sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, source_digest = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or receipt.sha256 != digest
            or source is None
            or source.sha256 != source_digest
            or source.attestation_authenticated is not True
        ):
            return None
        return {"source": source}

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_readiness_authenticated, _get_live_readiness_source = _live_registry()


def _validate_source(
    source: attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt,
) -> None:
    if (
        type(source)
        is not attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
        or source.attestation_authenticated is not True
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "fresh live ADR-DC-095 attestation is required"
        )
    required_true = (
        "production_activation",
        "production_activation_attested",
        "durable_completion_verified",
        "transaction_lock_authenticated",
        "double_observation_matched",
        "preflight_receipt_verified",
        "machine_production_receipt_verified",
        "required_switches_active",
        "environment_matches_post_activation",
    )
    required_false = (
        "manual_intervention_required",
        "production_activation_authorized",
        "remote_write_authorized",
        "product_pilot_started",
        "nonce_reusable",
    )
    if (
        any(getattr(source, name) is not True for name in required_true)
        or any(getattr(source, name) is not False for name in required_false)
    ):
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-095 attestation is not inert exact production evidence"
        )


def _evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
    post_production_activation_attestation: (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    *,
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartReadinessReceipt:
    _validate_source(post_production_activation_attestation)
    evaluated_at = _utc_seconds(now_provider(), name="evaluated_at_utc")
    attested_at = _utc_seconds(
        post_production_activation_attestation.second_observed_at_utc,
        name="post_production_attested_at_utc",
    )
    age = _seconds_between(earlier=attested_at, later=evaluated_at)
    if age > PILOT_EXACT_TASK_PRODUCT_PILOT_START_READINESS_MAX_AGE_SECONDS:
        raise PilotExactTaskProductPilotStartReadinessError(
            "ADR-DC-095 attestation is stale for product-pilot readiness"
        )

    receipt = PilotExactTaskProductPilotStartReadinessReceipt(
        post_production_activation_attestation_sha256=(
            post_production_activation_attestation.sha256
        ),
        production_activation_candidate_sha256=(
            post_production_activation_attestation.production_activation_candidate_sha256
        ),
        production_activation_completion_source=(
            post_production_activation_attestation.production_activation_completion_source
        ),
        production_activation_source_receipt_sha256=(
            post_production_activation_attestation.production_activation_source_receipt_sha256
        ),
        production_activation_transaction_lock_sha256=(
            post_production_activation_attestation.production_activation_transaction_lock_sha256
        ),
        environment_after_sha256=(
            post_production_activation_attestation.environment_after_sha256
        ),
        output_state_sha256=post_production_activation_attestation.output_state_sha256,
        production_preflight_sha256=(
            post_production_activation_attestation.production_preflight_sha256
        ),
        machine_production_receipt_sha256=(
            post_production_activation_attestation.machine_production_receipt_sha256
        ),
        repository=post_production_activation_attestation.repository,
        repository_id=post_production_activation_attestation.repository_id,
        merge_commit_sha=post_production_activation_attestation.merge_commit_sha,
        promotion_git_sha=post_production_activation_attestation.promotion_git_sha,
        post_production_attested_at_utc=attested_at,
        evaluated_at_utc=evaluated_at,
        attestation_age_seconds=age,
    )
    _mark_readiness_authenticated(
        receipt,
        source=post_production_activation_attestation,
    )
    if receipt.readiness_authenticated is not True:
        raise PilotExactTaskProductPilotStartReadinessError(
            "product-pilot readiness lost live ADR-DC-095 provenance"
        )
    return receipt


def evaluate_pilot_exact_task_product_pilot_start_readiness(
    post_production_activation_attestation: (
        attestation_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
) -> PilotExactTaskProductPilotStartReadinessReceipt:
    """Evaluate fresh exact production evidence without starting the pilot."""
    return _evaluate_verified_pilot_exact_task_product_pilot_start_readiness(
        post_production_activation_attestation,
        now_provider=_now_utc_seconds,
    )


__all__: list[str] = []

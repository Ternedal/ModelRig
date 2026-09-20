"""ADR-DC-099 lineage-qualified product-pilot start readiness.

This boundary consumes one exact historical human GO proof already bound by
ADR-DC-098, one freshly human-signed GO over that same DC-L15 completion and
scope, the inert ADR-DC-098 lineage attestation, and one fresh live ADR-DC-095
post-production activation attestation.

It re-derives the ADR-DC-096 start requirements and may issue only inert
product-pilot start readiness. It never starts the pilot or grants repository,
network, release, deployment, restart, or production-mutation authority.
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

from . import improvement_human_pilot_decision as human_boundary
from . import improvement_pilot_exact_task_post_production_activation_attestation as post_boundary
from . import improvement_pilot_exact_task_product_pilot_lineage_attestation as lineage_boundary
from . import improvement_pilot_exact_task_product_pilot_start_requirements as requirements_boundary

PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-product-pilot-start-qualified-readiness/v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_AUTHORITY = (
    "host-evaluated-lineage-qualified-dc-l16-product-pilot-start-readiness-only"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCOPE = (
    "lineage-qualified-exact-product-pilot-start-readiness-v1"
)
PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_MAX_HUMAN_GO_AGE_SECONDS = 300

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")


class PilotExactTaskProductPilotStartQualifiedReadinessError(ValueError):
    """Qualified readiness evidence is stale, mismatched, or over-broad."""


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
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "qualified readiness is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str):
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(f"{name} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(f"{name} is invalid") from exc
    if parsed.tzinfo is None or parsed.microsecond:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            f"{name} must use whole UTC seconds"
        )
    return parsed.astimezone(timezone.utc)


def _utc_seconds(value: Any, *, name: str) -> str:
    return _utc(value, name=name).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _replay(value: Any, cls: type, *, name: str) -> Any:
    if type(value) is not cls:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            f"exact {name} is required"
        )
    try:
        replayed = cls.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            f"{name} replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            f"{name} replay identity mismatch"
        )
    return value


_LIVE_RECEIPTS: dict[int, tuple[int, str, weakref.ReferenceType[Any]]] = {}


def _mark_live(receipt: "PilotExactTaskProductPilotStartQualifiedReadinessReceipt") -> None:
    key = id(receipt)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _LIVE_RECEIPTS.pop(key, None)

    _LIVE_RECEIPTS[key] = (os.getpid(), receipt.sha256, weakref.ref(receipt, cleanup))


def _is_live(receipt: Any) -> bool:
    entry = _LIVE_RECEIPTS.get(id(receipt))
    if entry is None:
        return False
    pid, digest, ref = entry
    return pid == os.getpid() and ref() is receipt and digest == receipt.sha256


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskProductPilotStartQualifiedReadinessReceipt:
    product_pilot_start_requirements_sha256: str
    product_pilot_lineage_attestation_sha256: str
    historical_human_go_proof_sha256: str
    fresh_human_go_proof_sha256: str
    fresh_human_go_signature_sha256: str
    post_production_activation_attestation_sha256: str
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
    human_go_decided_at_utc: str
    human_go_verified_at_utc: str
    lineage_attested_at_utc: str
    evaluated_at_utc: str
    human_go_age_seconds: int
    production_activation: bool = True
    production_activation_attested: bool = True
    requirements_satisfied: bool = True
    lineage_verified: bool = True
    historical_human_go_lineage_verified: bool = True
    fresh_human_product_pilot_go_verified: bool = True
    explicit_pilot_scope_verified: bool = True
    product_integration_selection_reverified: bool = True
    runtime_preflight_reverified: bool = True
    feature_flag_default_off_verified: bool = True
    local_only_scope_verified: bool = True
    manual_operator_invocation_required: bool = True
    kill_switch_armed_required: bool = True
    revoke_not_asserted_required: bool = True
    restart_recovery_required: bool = True
    network_writes_blocked_required: bool = True
    credentials_absent_required: bool = True
    unattended_cadence_forbidden: bool = True
    general_shell_forbidden: bool = True
    model_defined_commands_forbidden: bool = True
    one_shot_start_authorization_required: bool = True
    host_local_replay_guard_required: bool = True
    start_receipt_required: bool = True
    product_pilot_start_ready: bool = True
    product_pilot_start_authorized: bool = False
    product_pilot_started: bool = False
    task_execution_authorized: bool = False
    local_commit_authorized: bool = False
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
    readiness_scope: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCOPE
    authority: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_AUTHORITY
            or self.readiness_scope != PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCOPE
        ):
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness identity is unsupported"
            )
        for name in (
            "product_pilot_start_requirements_sha256",
            "product_pilot_lineage_attestation_sha256",
            "historical_human_go_proof_sha256",
            "fresh_human_go_proof_sha256",
            "fresh_human_go_signature_sha256",
            "post_production_activation_attestation_sha256",
            "production_activation_candidate_sha256",
            "execution_nonce_sha256",
            "workspace_root_path_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.merge_commit_sha, name="merge_commit_sha")
        _hex40(self.promotion_git_sha, name="promotion_git_sha")
        if self.repository != "Ternedal/ModelRig":
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness repository is unsupported"
            )
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness repository_id is invalid"
            )
        for name in ("operator_surface", "selected_pilot_task_id", "feature_flag_name"):
            _identifier(getattr(self, name), name=name)
        if (
            not isinstance(self.product_route, str)
            or not self.product_route.startswith("/")
            or "\x00" in self.product_route
            or len(self.product_route.encode("utf-8")) > 512
        ):
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "product_route is invalid"
            )
        decided = _utc(self.human_go_decided_at_utc, name="human_go_decided_at_utc")
        verified = _utc(self.human_go_verified_at_utc, name="human_go_verified_at_utc")
        lineage_time = _utc(self.lineage_attested_at_utc, name="lineage_attested_at_utc")
        evaluated = _utc(self.evaluated_at_utc, name="evaluated_at_utc")
        if decided < lineage_time or verified < decided or evaluated < verified:
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness time ordering is invalid"
            )
        age = int((evaluated - verified).total_seconds())
        if (
            type(self.human_go_age_seconds) is not int
            or self.human_go_age_seconds != age
            or not 0 <= age <= PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_MAX_HUMAN_GO_AGE_SECONDS
        ):
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "fresh human product-pilot GO is outside the readiness window"
            )

        required_true = (
            "production_activation",
            "production_activation_attested",
            "requirements_satisfied",
            "lineage_verified",
            "historical_human_go_lineage_verified",
            "fresh_human_product_pilot_go_verified",
            "explicit_pilot_scope_verified",
            "product_integration_selection_reverified",
            "runtime_preflight_reverified",
            "feature_flag_default_off_verified",
            "local_only_scope_verified",
            "manual_operator_invocation_required",
            "kill_switch_armed_required",
            "revoke_not_asserted_required",
            "restart_recovery_required",
            "network_writes_blocked_required",
            "credentials_absent_required",
            "unattended_cadence_forbidden",
            "general_shell_forbidden",
            "model_defined_commands_forbidden",
            "one_shot_start_authorization_required",
            "host_local_replay_guard_required",
            "start_receipt_required",
            "product_pilot_start_ready",
            "next_boundary_authorization_required",
        )
        forced_false = (
            "product_pilot_start_authorized",
            "product_pilot_started",
            "task_execution_authorized",
            "local_commit_authorized",
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
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness lacks required positive evidence"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness grants forbidden mutation authority"
            )

    @property
    def readiness_authenticated(self) -> bool:
        return _is_live(self)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskProductPilotStartQualifiedReadinessReceipt":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskProductPilotStartQualifiedReadinessError(
                "qualified readiness fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _evaluate_verified_pilot_exact_task_product_pilot_start_qualified_readiness(
    *,
    fresh_human_go_proof: human_boundary.HumanPilotDecisionProof,
    product_pilot_lineage_attestation: (
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt
    ),
    post_production_activation_attestation: (
        post_boundary.PilotExactTaskPostProductionActivationAttestationReceipt
    ),
    now_provider: Callable[[], str],
) -> PilotExactTaskProductPilotStartQualifiedReadinessReceipt:
    fresh = _replay(
        fresh_human_go_proof,
        human_boundary.HumanPilotDecisionProof,
        name="fresh human product-pilot GO proof",
    )
    lineage = _replay(
        product_pilot_lineage_attestation,
        lineage_boundary.PilotExactTaskProductPilotLineageAttestationReceipt,
        name="ADR-DC-098 product-pilot lineage attestation",
    )
    post = post_production_activation_attestation
    requirements = (
        requirements_boundary.build_pilot_exact_task_product_pilot_start_requirements(post)
    )

    if (
        fresh.human_pilot_decision_recorded is not True
        or fresh.pilot_go_authorized is not True
        or fresh.product_pilot_started is not False
        or fresh.feature_flag_default_off is not True
        or fresh.local_commits_allowed is not False
        or fresh.remote_write_authorized is not False
        or fresh.merge_authorized is not False
        or fresh.release_authorized is not False
        or fresh.deploy_authorized is not False
        or fresh.production_activation_authorized is not False
    ):
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "fresh human decision is not an inert local-only product-pilot GO"
        )

    if (
        fresh.repository != lineage.repository
        or fresh.operator_surface != lineage.operator_surface
        or fresh.workspace_root_path_sha256 != lineage.workspace_root_path_sha256
        or fresh.allowed_task_ids != (lineage.selected_pilot_task_id,)
    ):
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "fresh human GO does not exactly match the attested product-pilot scope"
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
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "requirements, lineage and live production state do not bind one candidate"
        )

    required_requirements = (
        "fresh_human_product_pilot_go_required",
        "explicit_pilot_scope_required",
        "product_integration_selection_reverification_required",
        "runtime_preflight_reverification_required",
        "feature_flag_default_off_required",
        "local_only_scope_required",
        "manual_operator_invocation_required",
        "kill_switch_armed_required",
        "revoke_not_asserted_required",
        "restart_recovery_required",
        "network_writes_blocked_required",
        "credentials_absent_required",
        "unattended_cadence_forbidden",
        "general_shell_forbidden",
        "model_defined_commands_forbidden",
        "one_shot_start_authorization_required",
        "host_local_replay_guard_required",
        "start_receipt_required",
    )
    if any(getattr(requirements, name) is not True for name in required_requirements):
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "product-pilot start requirements were weakened"
        )

    decided = _utc(fresh.decided_at_utc, name="fresh human GO decided_at_utc")
    verified = _utc(fresh.verified_at_utc, name="fresh human GO verified_at_utc")
    lineage_time = _utc(lineage.attested_at_utc, name="lineage attested_at_utc")
    post_observed = _utc(
        post.second_observed_at_utc,
        name="post-production second_observed_at_utc",
    )
    evaluated_text = _utc_seconds(
        now_provider(),
        name="qualified readiness evaluated_at_utc",
    )
    evaluated = _utc(evaluated_text, name="qualified readiness evaluated_at_utc")
    if decided < lineage_time or decided < post_observed or verified < decided:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "fresh human GO predates the qualified production lineage"
        )
    if evaluated < verified:
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "qualified readiness evaluation predates human GO verification"
        )
    age = int((evaluated - verified).total_seconds())
    if not 0 <= age <= (
        PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_MAX_HUMAN_GO_AGE_SECONDS
    ):
        raise PilotExactTaskProductPilotStartQualifiedReadinessError(
            "fresh human product-pilot GO is stale"
        )

    receipt = PilotExactTaskProductPilotStartQualifiedReadinessReceipt(
        product_pilot_start_requirements_sha256=requirements.sha256,
        product_pilot_lineage_attestation_sha256=lineage.sha256,
        historical_human_go_proof_sha256=lineage.human_decision_proof_sha256,
        fresh_human_go_proof_sha256=fresh.sha256,
        fresh_human_go_signature_sha256=fresh.signature_sha256,
        post_production_activation_attestation_sha256=post.sha256,
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
        human_go_decided_at_utc=fresh.decided_at_utc,
        human_go_verified_at_utc=fresh.verified_at_utc,
        lineage_attested_at_utc=lineage.attested_at_utc,
        evaluated_at_utc=evaluated_text,
        human_go_age_seconds=age,
    )
    _mark_live(receipt)
    return receipt


def evaluate_pilot_exact_task_product_pilot_start_qualified_readiness(**kwargs):
    raise PilotExactTaskProductPilotStartQualifiedReadinessError(
        "qualified product-pilot readiness is unavailable outside production facade"
    )


__all__ = [
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCHEMA",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_AUTHORITY",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_SCOPE",
    "PILOT_EXACT_TASK_PRODUCT_PILOT_START_QUALIFIED_READINESS_MAX_HUMAN_GO_AGE_SECONDS",
    "PilotExactTaskProductPilotStartQualifiedReadinessError",
    "PilotExactTaskProductPilotStartQualifiedReadinessReceipt",
    "evaluate_pilot_exact_task_product_pilot_start_qualified_readiness",
]

"""Verified post-campaign evidence snapshot without DC-L15 completion authority.

This boundary consumes one live transaction-authenticated campaign admission,
verifies one existing signed Windows isolation report using the established
DC-L04 verifier trust material, and records a fresh trusted post-campaign local
``main`` observation.

The v1 physical report does not bind campaign_id or exact runner bytes.  This
module therefore refuses to infer runner execution, continuous main freeze,
DC-L15 completion, pilot GO, publication, merge, release, deployment or
activation authority from the report.  A later separately human-signed binding
must connect the exact admission/runner to this exact verified report.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .catalog import IsolationAttestation
from .durable_publication import DurablePublicationError, remove_tree_durable
from .improvement_physical_campaign_admission import (
    PhysicalCampaignAdmission,
    _snapshot_trusted_git_runtime,
)
from .improvement_physical_reservation import (
    _canonical_host_state_root,
    _canonical_repository_root,
    _ensure_link_free_directory,
    _now_utc_seconds,
    observe_local_main_head,
)
from .physical_isolation import (
    PhysicalIsolationError,
    SignedWindowsIsolationReport,
    WindowsPhysicalIsolationVerifier,
)
from .trusted_git_runtime_staging import TrustedGitRuntime

EVIDENCE_SNAPSHOT_SCHEMA = "kaliv-rsi-physical-campaign-evidence-snapshot/v1"
EVIDENCE_SNAPSHOT_AUTHORITY = "verified-physical-evidence-only"
_MAX_POST_CAMPAIGN_DELAY = timedelta(minutes=15)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
_ACTOR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{1,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MISSING_COMPLETION_GATES = (
    "exact_runner_execution_binding",
    "continuous_main_freeze_confirmation",
    "dc_l14_independent_human_verdict",
    "human_pilot_go_decision",
)


class PhysicalCampaignEvidenceError(ValueError):
    """Post-campaign evidence is malformed, untrusted, stale, or over-authorizing."""


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
        raise PhysicalCampaignEvidenceError(
            "physical campaign evidence is not canonical JSON"
        ) from exc


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _strict(value: Any, *, fields: set[str], name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != fields:
        raise PhysicalCampaignEvidenceError(f"{name} fields mismatch")
    return value


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PhysicalCampaignEvidenceError(f"{name} is invalid")
    return value


def _identifier(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
        raise PhysicalCampaignEvidenceError(f"{name} is invalid")
    return value


def _actor(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _ACTOR.fullmatch(value) is None:
        raise PhysicalCampaignEvidenceError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PhysicalCampaignEvidenceError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PhysicalCampaignEvidenceError(f"{name} is invalid") from exc


def _canonical_evidence_operation_root() -> Path:
    return _ensure_link_free_directory(
        _canonical_host_state_root() / "rsi-physical-campaign-evidence-git-operation-v1",
        name="canonical physical campaign evidence Git operation root",
    )


_EVIDENCE_FIELDS = {
    "schema",
    "admission_sha256",
    "campaign_id",
    "reservation_sha256",
    "request_sha256",
    "qualification_packet_sha256",
    "snapshot_receipt_sha256",
    "task_id",
    "task_sha256",
    "repository",
    "base_sha",
    "requested_main_sha",
    "runner_relative_path",
    "runner_sha256",
    "runner_bytes",
    "isolation_attestation_sha256",
    "signed_report_sha256",
    "physical_report_sha256",
    "report_id",
    "rig_id",
    "rig_fingerprint_sha256",
    "toolhost_sha256",
    "workspace_root_sha256",
    "collector_actor_id",
    "approver_actor_id",
    "report_started_at_utc",
    "report_completed_at_utc",
    "post_main_observation_sha256",
    "post_main_observed_sha",
    "post_main_observed_at_utc",
    "repository_root_path_sha256",
    "git_runtime_manifest_sha256",
    "git_executable_sha256",
    "physical_report_verified",
    "all_required_probes_passed",
    "collector_approver_separation_verified",
    "post_campaign_main_match_confirmed",
    "runner_execution_binding_proven",
    "continuous_main_freeze_proven",
    "physical_campaign_completed",
    "dc_l15_complete",
    "human_completion_binding_required",
    "dc_l14_independent_human_verdict_required",
    "human_pilot_go_required",
    "pilot_go_authorized",
    "activation_authorized",
    "remote_publication_authorized",
    "missing_completion_gates",
    "authority",
}


@dataclass(frozen=True, slots=True)
class PhysicalCampaignEvidenceSnapshot:
    admission_sha256: str
    campaign_id: str
    reservation_sha256: str
    request_sha256: str
    qualification_packet_sha256: str
    snapshot_receipt_sha256: str
    task_id: str
    task_sha256: str
    repository: str
    base_sha: str
    requested_main_sha: str
    runner_relative_path: str
    runner_sha256: str
    runner_bytes: int
    isolation_attestation_sha256: str
    signed_report_sha256: str
    physical_report_sha256: str
    report_id: str
    rig_id: str
    rig_fingerprint_sha256: str
    toolhost_sha256: str
    workspace_root_sha256: str
    collector_actor_id: str
    approver_actor_id: str
    report_started_at_utc: str
    report_completed_at_utc: str
    post_main_observation_sha256: str
    post_main_observed_sha: str
    post_main_observed_at_utc: str
    repository_root_path_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    physical_report_verified: bool = True
    all_required_probes_passed: bool = True
    collector_approver_separation_verified: bool = True
    post_campaign_main_match_confirmed: bool = True
    runner_execution_binding_proven: bool = False
    continuous_main_freeze_proven: bool = False
    physical_campaign_completed: bool = False
    dc_l15_complete: bool = False
    human_completion_binding_required: bool = True
    dc_l14_independent_human_verdict_required: bool = True
    human_pilot_go_required: bool = True
    pilot_go_authorized: bool = False
    activation_authorized: bool = False
    remote_publication_authorized: bool = False
    missing_completion_gates: tuple[str, ...] = MISSING_COMPLETION_GATES
    authority: str = EVIDENCE_SNAPSHOT_AUTHORITY
    schema: str = EVIDENCE_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EVIDENCE_SNAPSHOT_SCHEMA:
            raise PhysicalCampaignEvidenceError("physical evidence schema is unsupported")
        for name, value, pattern in (
            ("admission_sha256", self.admission_sha256, _HEX64),
            ("reservation_sha256", self.reservation_sha256, _HEX64),
            ("request_sha256", self.request_sha256, _HEX64),
            ("qualification_packet_sha256", self.qualification_packet_sha256, _HEX64),
            ("snapshot_receipt_sha256", self.snapshot_receipt_sha256, _HEX64),
            ("task_sha256", self.task_sha256, _HEX64),
            ("base_sha", self.base_sha, _HEX40),
            ("requested_main_sha", self.requested_main_sha, _HEX40),
            ("runner_sha256", self.runner_sha256, _HEX64),
            ("isolation_attestation_sha256", self.isolation_attestation_sha256, _HEX64),
            ("signed_report_sha256", self.signed_report_sha256, _HEX64),
            ("physical_report_sha256", self.physical_report_sha256, _HEX64),
            ("rig_fingerprint_sha256", self.rig_fingerprint_sha256, _HEX64),
            ("toolhost_sha256", self.toolhost_sha256, _HEX64),
            ("workspace_root_sha256", self.workspace_root_sha256, _HEX64),
            ("post_main_observation_sha256", self.post_main_observation_sha256, _HEX64),
            ("post_main_observed_sha", self.post_main_observed_sha, _HEX40),
            ("repository_root_path_sha256", self.repository_root_path_sha256, _HEX64),
            ("git_runtime_manifest_sha256", self.git_runtime_manifest_sha256, _HEX64),
            ("git_executable_sha256", self.git_executable_sha256, _HEX64),
        ):
            _hex(value, name=name, pattern=pattern)
        _identifier(self.campaign_id, name="campaign_id")
        _identifier(self.report_id, name="report_id")
        if not isinstance(self.task_id, str) or not self.task_id:
            raise PhysicalCampaignEvidenceError("task_id is invalid")
        if self.repository != "Ternedal/ModelRig":
            raise PhysicalCampaignEvidenceError("repository is unsupported")
        if not isinstance(self.runner_relative_path, str) or not self.runner_relative_path:
            raise PhysicalCampaignEvidenceError("runner_relative_path is invalid")
        if isinstance(self.runner_bytes, bool) or not isinstance(self.runner_bytes, int) or self.runner_bytes < 1:
            raise PhysicalCampaignEvidenceError("runner_bytes is invalid")
        if not isinstance(self.rig_id, str) or not self.rig_id:
            raise PhysicalCampaignEvidenceError("rig_id is invalid")
        collector = _actor(self.collector_actor_id, name="collector_actor_id")
        approver = _actor(self.approver_actor_id, name="approver_actor_id")
        if collector == approver:
            raise PhysicalCampaignEvidenceError("collector and approver must remain different")
        started = _utc(self.report_started_at_utc, name="report_started_at_utc")
        completed = _utc(self.report_completed_at_utc, name="report_completed_at_utc")
        observed = _utc(self.post_main_observed_at_utc, name="post_main_observed_at_utc")
        if completed <= started or observed < completed or observed - completed > _MAX_POST_CAMPAIGN_DELAY:
            raise PhysicalCampaignEvidenceError("physical report/post-main timing is invalid")
        if self.post_main_observed_sha != self.requested_main_sha:
            raise PhysicalCampaignEvidenceError("post-campaign main does not match requested main")
        if self.missing_completion_gates != MISSING_COMPLETION_GATES:
            raise PhysicalCampaignEvidenceError("missing completion gates are not exact")
        if (
            self.physical_report_verified is not True
            or self.all_required_probes_passed is not True
            or self.collector_approver_separation_verified is not True
            or self.post_campaign_main_match_confirmed is not True
            or self.runner_execution_binding_proven is not False
            or self.continuous_main_freeze_proven is not False
            or self.physical_campaign_completed is not False
            or self.dc_l15_complete is not False
            or self.human_completion_binding_required is not True
            or self.dc_l14_independent_human_verdict_required is not True
            or self.human_pilot_go_required is not True
            or self.pilot_go_authorized is not False
            or self.activation_authorized is not False
            or self.remote_publication_authorized is not False
            or self.authority != EVIDENCE_SNAPSHOT_AUTHORITY
        ):
            raise PhysicalCampaignEvidenceError("physical evidence authority boundary is invalid")

    @classmethod
    def from_mapping(cls, value: Any) -> "PhysicalCampaignEvidenceSnapshot":
        data = _strict(value, fields=_EVIDENCE_FIELDS, name="physical campaign evidence")
        gates = data["missing_completion_gates"]
        if not isinstance(gates, list):
            raise PhysicalCampaignEvidenceError("missing_completion_gates must be an array")
        kwargs = dict(data)
        kwargs["missing_completion_gates"] = tuple(gates)
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "admission_sha256": self.admission_sha256,
            "campaign_id": self.campaign_id,
            "reservation_sha256": self.reservation_sha256,
            "request_sha256": self.request_sha256,
            "qualification_packet_sha256": self.qualification_packet_sha256,
            "snapshot_receipt_sha256": self.snapshot_receipt_sha256,
            "task_id": self.task_id,
            "task_sha256": self.task_sha256,
            "repository": self.repository,
            "base_sha": self.base_sha,
            "requested_main_sha": self.requested_main_sha,
            "runner_relative_path": self.runner_relative_path,
            "runner_sha256": self.runner_sha256,
            "runner_bytes": self.runner_bytes,
            "isolation_attestation_sha256": self.isolation_attestation_sha256,
            "signed_report_sha256": self.signed_report_sha256,
            "physical_report_sha256": self.physical_report_sha256,
            "report_id": self.report_id,
            "rig_id": self.rig_id,
            "rig_fingerprint_sha256": self.rig_fingerprint_sha256,
            "toolhost_sha256": self.toolhost_sha256,
            "workspace_root_sha256": self.workspace_root_sha256,
            "collector_actor_id": self.collector_actor_id,
            "approver_actor_id": self.approver_actor_id,
            "report_started_at_utc": self.report_started_at_utc,
            "report_completed_at_utc": self.report_completed_at_utc,
            "post_main_observation_sha256": self.post_main_observation_sha256,
            "post_main_observed_sha": self.post_main_observed_sha,
            "post_main_observed_at_utc": self.post_main_observed_at_utc,
            "repository_root_path_sha256": self.repository_root_path_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "physical_report_verified": self.physical_report_verified,
            "all_required_probes_passed": self.all_required_probes_passed,
            "collector_approver_separation_verified": self.collector_approver_separation_verified,
            "post_campaign_main_match_confirmed": self.post_campaign_main_match_confirmed,
            "runner_execution_binding_proven": self.runner_execution_binding_proven,
            "continuous_main_freeze_proven": self.continuous_main_freeze_proven,
            "physical_campaign_completed": self.physical_campaign_completed,
            "dc_l15_complete": self.dc_l15_complete,
            "human_completion_binding_required": self.human_completion_binding_required,
            "dc_l14_independent_human_verdict_required": self.dc_l14_independent_human_verdict_required,
            "human_pilot_go_required": self.human_pilot_go_required,
            "pilot_go_authorized": self.pilot_go_authorized,
            "activation_authorized": self.activation_authorized,
            "remote_publication_authorized": self.remote_publication_authorized,
            "missing_completion_gates": list(self.missing_completion_gates),
            "authority": self.authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def _snapshot_attestation(attestation: IsolationAttestation) -> IsolationAttestation:
    if type(attestation) is not IsolationAttestation:
        raise PhysicalCampaignEvidenceError("evidence collection requires exact IsolationAttestation")
    try:
        return IsolationAttestation.from_mapping(attestation.to_dict())
    except Exception as exc:
        raise PhysicalCampaignEvidenceError("isolation attestation could not be snapshotted") from exc


def _snapshot_verifier(verifier: WindowsPhysicalIsolationVerifier) -> WindowsPhysicalIsolationVerifier:
    if type(verifier) is not WindowsPhysicalIsolationVerifier:
        raise PhysicalCampaignEvidenceError("evidence collection requires exact WindowsPhysicalIsolationVerifier")
    try:
        return WindowsPhysicalIsolationVerifier(
            Path(os.fspath(verifier.evidence_root)),
            dict(verifier.keyring),
            max_age=verifier.max_age,
            now=verifier.now,
            max_file_bytes=verifier.max_file_bytes,
        )
    except Exception as exc:
        raise PhysicalCampaignEvidenceError("physical verifier could not be snapshotted") from exc


def _verify_signed_report(
    *,
    attestation: IsolationAttestation,
    verifier: WindowsPhysicalIsolationVerifier,
) -> SignedWindowsIsolationReport:
    """Verify and snapshot the exact candidate bytes selected by the verifier root."""

    local = _snapshot_verifier(verifier)
    try:
        candidates = local._load_candidates(set(attestation.evidence_sha256))
    except PhysicalIsolationError as exc:
        raise PhysicalCampaignEvidenceError(f"physical evidence load failed: {exc}") from exc
    if len(candidates) != 1:
        raise PhysicalCampaignEvidenceError("expected exactly one trusted physical report")
    try:
        signed = SignedWindowsIsolationReport.from_mapping(
            json.loads(candidates[0].canonical_json())
        )
        secret = local.keyring[signed.key_id]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise PhysicalCampaignEvidenceError("physical report trust material is invalid") from exc
    expected = hmac.new(
        secret,
        signed.report.canonical_json().encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signed.signature_sha256):
        raise PhysicalCampaignEvidenceError("physical report signature is invalid")
    try:
        signed.report.bind_to_attestation(attestation)
    except PhysicalIsolationError as exc:
        raise PhysicalCampaignEvidenceError(f"physical report attestation binding failed: {exc}") from exc
    if not signed.report.all_probes_passed:
        raise PhysicalCampaignEvidenceError("physical isolation has one or more failed probes")
    current = local.now()
    if not isinstance(current, datetime) or current.tzinfo is None:
        raise PhysicalCampaignEvidenceError("physical verifier clock must be timezone-aware")
    current = current.astimezone(timezone.utc)
    completed = _utc(signed.report.completed_at, name="report.completed_at")
    if completed > current + timedelta(minutes=5):
        raise PhysicalCampaignEvidenceError("physical report completion time is in the future")
    if current - completed > local.max_age:
        raise PhysicalCampaignEvidenceError("physical isolation report is stale")
    return signed


def _require_live_admission(admission: PhysicalCampaignAdmission, expected_sha256: str | None = None) -> str:
    if type(admission) is not PhysicalCampaignAdmission or admission.transaction_authenticated is not True:
        raise PhysicalCampaignEvidenceError("evidence collection requires live transaction-authenticated admission")
    observed = admission.sha256
    if expected_sha256 is not None and observed != expected_sha256:
        raise PhysicalCampaignEvidenceError("campaign admission changed during evidence collection")
    return observed


def _require_report_binding(admission: PhysicalCampaignAdmission, signed: SignedWindowsIsolationReport) -> None:
    report = signed.report
    expected = {
        "task_id": admission.task_id,
        "task_sha256": admission.task_sha256,
        "repository": admission.repository,
        "base_sha": admission.base_sha,
        "collected_by": admission.required_operator_actor_id,
        "approved_by": admission.required_approver_actor_id,
    }
    actual = {name: getattr(report, name) for name in expected}
    if actual != expected:
        raise PhysicalCampaignEvidenceError("physical report is not bound to admission task/base/actors")
    admitted = _utc(admission.admitted_at_utc, name="admission.admitted_at_utc")
    started = _utc(report.started_at, name="report.started_at")
    if started < admitted:
        raise PhysicalCampaignEvidenceError("physical report started before campaign admission")


def _collect_physical_campaign_evidence(
    *,
    trusted_git: TrustedGitRuntime,
    repository_root: Path,
    operation_root: Path,
    admission: PhysicalCampaignAdmission,
    attestation: IsolationAttestation,
    verifier: WindowsPhysicalIsolationVerifier,
    now_provider: Callable[[], str],
) -> PhysicalCampaignEvidenceSnapshot:
    """Private injectable evidence-only transaction used by production and tests."""

    admission_sha256 = _require_live_admission(admission)
    attestation_snapshot = _snapshot_attestation(attestation)
    signed = _verify_signed_report(attestation=attestation_snapshot, verifier=verifier)
    _require_report_binding(admission, signed)
    _require_live_admission(admission, admission_sha256)

    try:
        trusted_runtime, runtime_snapshot_root = _snapshot_trusted_git_runtime(
            trusted_git,
            operation_root=operation_root,
        )
    except Exception as exc:
        raise PhysicalCampaignEvidenceError("trusted Git runtime could not be privately snapshotted") from exc
    try:
        observed_at = now_provider()
        observed_time = _utc(observed_at, name="post-campaign observation time")
        completed = _utc(signed.report.completed_at, name="report.completed_at")
        if observed_time < completed or observed_time - completed > _MAX_POST_CAMPAIGN_DELAY:
            raise PhysicalCampaignEvidenceError("post-campaign main observation is not fresh to report completion")
        observation = observe_local_main_head(
            trusted_git=trusted_runtime,
            repository_root=repository_root,
            operation_root=operation_root,
            observed_at_utc=observed_at,
            repository=admission.repository,
        )
        if observation.observed_sha != admission.requested_main_sha:
            raise PhysicalCampaignEvidenceError("post-campaign main does not match requested main")
        if observation.repository_root_path_sha256 != admission.repository_root_path_sha256:
            raise PhysicalCampaignEvidenceError("post-campaign observation belongs to another repository root")
        if (
            observation.git_runtime_manifest_sha256 != admission.git_runtime_manifest_sha256
            or observation.git_executable_sha256 != admission.git_executable_sha256
        ):
            raise PhysicalCampaignEvidenceError("post-campaign Trusted-Git identity changed")
        _require_live_admission(admission, admission_sha256)
        report = signed.report
        return PhysicalCampaignEvidenceSnapshot(
            admission_sha256=admission_sha256,
            campaign_id=admission.campaign_id,
            reservation_sha256=admission.reservation_sha256,
            request_sha256=admission.request_sha256,
            qualification_packet_sha256=admission.qualification_packet_sha256,
            snapshot_receipt_sha256=admission.snapshot_receipt_sha256,
            task_id=admission.task_id,
            task_sha256=admission.task_sha256,
            repository=admission.repository,
            base_sha=admission.base_sha,
            requested_main_sha=admission.requested_main_sha,
            runner_relative_path=admission.runner_relative_path,
            runner_sha256=admission.runner_sha256,
            runner_bytes=admission.runner_bytes,
            isolation_attestation_sha256=_sha256_text(attestation_snapshot.canonical_json()),
            signed_report_sha256=signed.sha256,
            physical_report_sha256=report.sha256,
            report_id=report.report_id,
            rig_id=report.rig_id,
            rig_fingerprint_sha256=report.rig_fingerprint_sha256,
            toolhost_sha256=report.toolhost_sha256,
            workspace_root_sha256=report.workspace_root_sha256,
            collector_actor_id=report.collected_by,
            approver_actor_id=report.approved_by,
            report_started_at_utc=report.started_at,
            report_completed_at_utc=report.completed_at,
            post_main_observation_sha256=observation.sha256,
            post_main_observed_sha=observation.observed_sha,
            post_main_observed_at_utc=observation.observed_at_utc,
            repository_root_path_sha256=observation.repository_root_path_sha256,
            git_runtime_manifest_sha256=observation.git_runtime_manifest_sha256,
            git_executable_sha256=observation.git_executable_sha256,
        )
    finally:
        try:
            remove_tree_durable(runtime_snapshot_root)
        except DurablePublicationError as exc:
            raise PhysicalCampaignEvidenceError(
                "physical evidence private Git runtime cleanup failed closed"
            ) from exc


def collect_physical_campaign_evidence(
    *,
    trusted_git: TrustedGitRuntime,
    admission: PhysicalCampaignAdmission,
    attestation: IsolationAttestation,
    verifier: WindowsPhysicalIsolationVerifier,
) -> PhysicalCampaignEvidenceSnapshot:
    """Verify existing physical evidence without running probes or completing DC-L15.

    Repository/operation roots and wall-clock time are derived internally.  The
    result deliberately leaves runner execution binding, continuous freeze,
    DC-L15 completion and pilot/activation authority false.
    """

    return _collect_physical_campaign_evidence(
        trusted_git=trusted_git,
        repository_root=_canonical_repository_root(),
        operation_root=_canonical_evidence_operation_root(),
        admission=admission,
        attestation=attestation,
        verifier=verifier,
        now_provider=_now_utc_seconds,
    )

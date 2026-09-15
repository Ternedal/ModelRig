"""ADR-DC-077 durable restart-safe checkpoint for later review observation.

Consumes one fresh live ADR-DC-076 post-reviewer-request attestation and commits
one create-once host-local checkpoint keyed by the attestation digest. The
checkpoint can later be re-authenticated from the canonical host-controlled
ledger after process restart without restoring write authority.

This boundary performs no GitHub/network mutation and grants authority only to
perform a later fresh read-only review-state observation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pr_reviewer_request_attestation as attestation_boundary
from .improvement_pilot_exact_task_pr_reviewer_request_attestation import (
    PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY,
    PilotExactTaskPrReviewerRequestAttestation,
)

PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-review-observation-checkpoint/v1"
)
PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY = (
    "host-checkpointed-one-dc-l16-exact-pr-review-observation-only"
)
PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_LEDGER_SCOPE = (
    "canonical-host-pr-review-observation-checkpoint-v1"
)
PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_MAX_SOURCE_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_LOGIN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024

_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pr-review-observation-checkpoint-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pr-review-observation-checkpoint-ledger-v1"
)


class PilotExactTaskPrReviewObservationCheckpointError(ValueError):
    """Review-observation checkpoint is stale, drifted, replayed, or unsafe."""


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
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskPrReviewObservationCheckpointError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskPrReviewObservationCheckpointError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _require_safe_ledger_root(path: Path) -> Path:
    candidate = Path(path)
    if not candidate.is_absolute() or not candidate.is_dir() or candidate.is_symlink():
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint ledger root is unsafe"
        )
    return candidate


def _canonical_ledger_root() -> Path:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            return _require_host_controlled_ledger_root(_POSIX_LEDGER)
        if os.name == "nt":
            return _require_host_controlled_ledger_root(_WINDOWS_LEDGER)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "canonical review-observation checkpoint ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPrReviewObservationCheckpointError(
        "review-observation checkpoint platform is unsupported"
    )


def _read_checkpoint_bytes(
    path: Path,
    *,
    require_host_control: bool,
) -> bytes:
    candidate = Path(path)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint path is unsafe"
        )
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint is missing or unreadable"
        ) from exc
    try:
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
            or observed.st_size < 1
            or observed.st_size > _MAX_ARTIFACT_BYTES
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint file is unsafe"
            )
        if require_host_control and os.name == "posix":
            if observed.st_uid != 0 or stat.S_IMODE(observed.st_mode) & 0o077:
                raise PilotExactTaskPrReviewObservationCheckpointError(
                    "review-observation checkpoint file is not root-private"
                )
        remaining = observed.st_size
        chunks: list[bytes] = []
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                raise PilotExactTaskPrReviewObservationCheckpointError(
                    "review-observation checkpoint read was incomplete"
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint changed while reading"
            )
        after = os.fstat(descriptor)
        if (
            observed.st_dev,
            observed.st_ino,
            observed.st_size,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint identity changed during read"
            )
        return b"".join(chunks)
    except OSError as exc:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint could not be read safely"
        ) from exc
    finally:
        os.close(descriptor)


def _require_live_attestation(
    value: Any,
) -> PilotExactTaskPrReviewerRequestAttestation:
    if type(value) is not PilotExactTaskPrReviewerRequestAttestation:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "exact live ADR-DC-076 reviewer-request attestation is required"
        )
    try:
        replayed = PilotExactTaskPrReviewerRequestAttestation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "ADR-DC-076 attestation replay validation failed"
        ) from exc
    required_true = (
        "reviewer_request_performed_verified",
        "exact_requested_reviewer_verified",
        "team_reviewers_absent_verified",
        "exact_pr_state_verified",
        "stable_double_observation_verified",
        "credential_free_reads",
        "redirects_forbidden",
        "response_bounded",
        "review_state_attestation_required",
    )
    forced_false = (
        "nonce_reusable",
        "reviewer_mutation_authorized",
        "review_submission_authorized",
        "review_thread_mutation_authorized",
        "merge_readiness_authorized",
        "label_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_ATTESTATION_AUTHORITY
        or value.attestation_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != "Ternedal/ModelRig"
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
        or _LOGIN.fullmatch(value.reviewer_login) is None
    ):
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "checkpoint requires one live inert ADR-DC-076 attestation"
        )
    live = attestation_boundary._get_live_pr_reviewer_request_attestation_inputs(
        value
    )
    transaction = None if live is None else live.get("reviewer_write_transaction")
    if (
        transaction is None
        or getattr(transaction, "transaction_authenticated", None) is not True
        or transaction.sha256 != value.reviewer_write_transaction_sha256
        or transaction.pull_request_number != value.pull_request_number
        or transaction.predicted_commit_sha != value.predicted_commit_sha
        or transaction.reviewer_login != value.reviewer_login
        or transaction.reviewer_user_id != value.reviewer_user_id
        or transaction.reviewer_user_node_id_sha256 != value.reviewer_user_node_id_sha256
        or transaction.reviewer_request_nonce_sha256 != value.reviewer_request_nonce_sha256
    ):
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "ADR-DC-076 lost live hardened ADR-DC-075 provenance"
        )
    return value


def _require_checkpoint_window(
    attestation: PilotExactTaskPrReviewerRequestAttestation,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="checkpointed_at_utc")
    source = _utc(
        attestation.second_observed_at_utc,
        name="ADR-DC-076 second_observed_at_utc",
    )
    if (
        at < source
        or (at - source).total_seconds()
        > PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_MAX_SOURCE_AGE_SECONDS
    ):
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "ADR-DC-076 attestation is too old for durable checkpointing"
        )


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrReviewObservationCheckpoint:
    ledger_root_path_sha256: str
    checkpoint_key_sha256: str
    source_reviewer_request_attestation_sha256: str
    reviewer_write_transaction_sha256: str
    transaction_start_sha256: str
    reviewer_write_credential_capability_sha256: str
    reviewer_request_preflight_sha256: str
    reviewer_requestability_precondition_sha256: str
    reviewer_request_reservation_sha256: str
    reviewer_target_attestation_sha256: str
    reviewer_handoff_requirements_sha256: str
    reviewer_request_nonce_sha256: str
    repository: str
    pull_request_number: int
    pull_request_api_url: str
    pull_request_html_url: str
    pull_request_node_id_sha256: str
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    reviewer_login: str
    reviewer_user_id: int
    reviewer_user_node_id_sha256: str
    pull_request_author_login: str
    pull_request_author_user_id: int
    requested_updated_at_utc: str
    source_first_response_body_sha256: str
    source_first_response_etag_sha256: str
    source_second_response_body_sha256: str
    source_second_response_etag_sha256: str
    source_second_observed_at_utc: str
    checkpointed_at_utc: str
    source_attestation_verified: bool = True
    durable_checkpoint_committed: bool = True
    restart_safe_reauthentication_supported: bool = True
    exact_pr_identity_bound: bool = True
    exact_head_sha_bound: bool = True
    exact_reviewer_identity_bound: bool = True
    reviewer_request_performed_verified: bool = True
    exact_requested_reviewer_verified: bool = True
    team_reviewers_absent_verified: bool = True
    future_review_observation_must_revalidate_exact_pr: bool = True
    submitted_reviews_read_only_observation_only: bool = True
    reviewer_request_nonce_consumed: bool = True
    observation_checkpoint_reusable: bool = True
    credential_material_in_artifact: bool = False
    reviewer_mutation_authorized: bool = False
    review_submission_authorized: bool = False
    review_thread_mutation_authorized: bool = False
    ready_for_review_authorized: bool = False
    label_mutation_authorized: bool = False
    merge_readiness_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_SCHEMA
            or self.authority
            != PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_LEDGER_SCOPE
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint schema/authority/scope unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "checkpoint_key_sha256",
            "source_reviewer_request_attestation_sha256",
            "reviewer_write_transaction_sha256",
            "transaction_start_sha256",
            "reviewer_write_credential_capability_sha256",
            "reviewer_request_preflight_sha256",
            "reviewer_requestability_precondition_sha256",
            "reviewer_request_reservation_sha256",
            "reviewer_target_attestation_sha256",
            "reviewer_handoff_requirements_sha256",
            "reviewer_request_nonce_sha256",
            "pull_request_node_id_sha256",
            "reviewer_user_node_id_sha256",
            "source_first_response_body_sha256",
            "source_first_response_etag_sha256",
            "source_second_response_body_sha256",
            "source_second_response_etag_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        source_at = _utc(
            self.source_second_observed_at_utc,
            name="source_second_observed_at_utc",
        )
        checkpointed = _utc(self.checkpointed_at_utc, name="checkpointed_at_utc")
        if checkpointed < source_at or (
            checkpointed - source_at
        ).total_seconds() > PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_MAX_SOURCE_AGE_SECONDS:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint timing is invalid"
            )
        if (
            self.checkpoint_key_sha256
            != self.source_reviewer_request_attestation_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.pull_request_api_url
            != f"https://api.github.com/repos/Ternedal/ModelRig/pulls/{self.pull_request_number}"
            or self.pull_request_html_url
            != f"https://github.com/Ternedal/ModelRig/pull/{self.pull_request_number}"
            or not isinstance(self.reviewer_login, str)
            or _LOGIN.fullmatch(self.reviewer_login) is None
            or isinstance(self.reviewer_user_id, bool)
            or not isinstance(self.reviewer_user_id, int)
            or self.reviewer_user_id < 1
            or not isinstance(self.pull_request_author_login, str)
            or _LOGIN.fullmatch(self.pull_request_author_login) is None
            or isinstance(self.pull_request_author_user_id, bool)
            or not isinstance(self.pull_request_author_user_id, int)
            or self.pull_request_author_user_id < 1
            or self.pull_request_author_user_id == self.reviewer_user_id
            or self.pull_request_author_login.lower() == self.reviewer_login.lower()
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint target binding is invalid"
            )
        required_true = (
            "source_attestation_verified",
            "durable_checkpoint_committed",
            "restart_safe_reauthentication_supported",
            "exact_pr_identity_bound",
            "exact_head_sha_bound",
            "exact_reviewer_identity_bound",
            "reviewer_request_performed_verified",
            "exact_requested_reviewer_verified",
            "team_reviewers_absent_verified",
            "future_review_observation_must_revalidate_exact_pr",
            "submitted_reviews_read_only_observation_only",
            "reviewer_request_nonce_consumed",
            "observation_checkpoint_reusable",
        )
        forced_false = (
            "credential_material_in_artifact",
            "reviewer_mutation_authorized",
            "review_submission_authorized",
            "review_thread_mutation_authorized",
            "ready_for_review_authorized",
            "label_mutation_authorized",
            "merge_readiness_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint cannot grant mutation authority"
            )

    @property
    def checkpoint_authenticated(self) -> bool:
        return _get_live_pr_review_observation_checkpoint_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskPrReviewObservationCheckpoint":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


_live_records: dict[
    int,
    tuple[int, str, weakref.ReferenceType[Any], Path, bytes, bool],
] = {}


def _mark_authenticated(
    checkpoint: PilotExactTaskPrReviewObservationCheckpoint,
    *,
    path: Path,
    payload: bytes,
    require_host_control: bool,
) -> None:
    key = id(checkpoint)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        checkpoint.sha256,
        weakref.ref(checkpoint, cleanup),
        path,
        payload,
        bool(require_host_control),
    )


def _get_live_pr_review_observation_checkpoint_inputs(
    checkpoint: Any,
) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(checkpoint))
    if entry is None:
        return None
    pid, digest, checkpoint_ref, path, payload, require_host_control = entry
    if (
        pid != os.getpid()
        or checkpoint_ref() is not checkpoint
        or checkpoint.sha256 != digest
        or _read_checkpoint_bytes(
            path,
            require_host_control=require_host_control,
        ) != payload
    ):
        return None
    return MappingProxyType(
        {
            "checkpoint_path": path,
            "checkpoint_payload_sha256": hashlib.sha256(payload).hexdigest(),
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


class _ReviewObservationCheckpointLedger:
    def __init__(
        self,
        root: Path,
        *,
        require_host_control: bool,
    ) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)
        self.require_host_control = bool(require_host_control)

    def _path(self, checkpoint_key_sha256: str) -> Path:
        key = _hex64(
            checkpoint_key_sha256,
            name="checkpoint_key_sha256",
        )
        return self.root / f"{key}.json"

    def commit(
        self,
        checkpoint: PilotExactTaskPrReviewObservationCheckpoint,
    ) -> tuple[Path, bytes]:
        if (
            type(checkpoint) is not PilotExactTaskPrReviewObservationCheckpoint
            or checkpoint.ledger_root_path_sha256 != self.root_sha256
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint does not belong to ledger"
            )
        path = self._path(checkpoint.checkpoint_key_sha256)
        payload = checkpoint.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "review-observation checkpoint already exists or ledger write failed"
            ) from exc
        observed = _read_checkpoint_bytes(
            path,
            require_host_control=self.require_host_control,
        )
        if observed != payload:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "durable review-observation checkpoint readback failed"
            )
        return path, payload

    def load(
        self,
        checkpoint_key_sha256: str,
    ) -> PilotExactTaskPrReviewObservationCheckpoint:
        path = self._path(checkpoint_key_sha256)
        payload = _read_checkpoint_bytes(
            path,
            require_host_control=self.require_host_control,
        )
        try:
            document = json.loads(payload.decode("utf-8", errors="strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "stored review-observation checkpoint is invalid JSON"
            ) from exc
        checkpoint = PilotExactTaskPrReviewObservationCheckpoint.from_mapping(document)
        if (
            checkpoint.checkpoint_key_sha256 != checkpoint_key_sha256
            or checkpoint.ledger_root_path_sha256 != self.root_sha256
            or checkpoint.canonical_json().encode("utf-8") != payload
        ):
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "stored review-observation checkpoint binding mismatch"
            )
        _mark_authenticated(
            checkpoint,
            path=path,
            payload=payload,
            require_host_control=self.require_host_control,
        )
        if checkpoint.checkpoint_authenticated is not True:
            raise PilotExactTaskPrReviewObservationCheckpointError(
                "stored review-observation checkpoint could not be re-authenticated"
            )
        return checkpoint


def _checkpoint_verified_pilot_exact_task_pr_review_observation(
    *,
    reviewer_request_attestation: PilotExactTaskPrReviewerRequestAttestation,
    ledger: _ReviewObservationCheckpointLedger,
    now_provider: Any,
) -> PilotExactTaskPrReviewObservationCheckpoint:
    source = _require_live_attestation(reviewer_request_attestation)
    checkpointed_at = now_provider()
    _require_checkpoint_window(source, at_utc=checkpointed_at)
    if not isinstance(ledger, _ReviewObservationCheckpointLedger):
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "exact review-observation checkpoint ledger is required"
        )

    checkpoint = PilotExactTaskPrReviewObservationCheckpoint(
        ledger_root_path_sha256=ledger.root_sha256,
        checkpoint_key_sha256=source.sha256,
        source_reviewer_request_attestation_sha256=source.sha256,
        reviewer_write_transaction_sha256=source.reviewer_write_transaction_sha256,
        transaction_start_sha256=source.transaction_start_sha256,
        reviewer_write_credential_capability_sha256=source.reviewer_write_credential_capability_sha256,
        reviewer_request_preflight_sha256=source.reviewer_request_preflight_sha256,
        reviewer_requestability_precondition_sha256=source.reviewer_requestability_precondition_sha256,
        reviewer_request_reservation_sha256=source.reviewer_request_reservation_sha256,
        reviewer_target_attestation_sha256=source.reviewer_target_attestation_sha256,
        reviewer_handoff_requirements_sha256=source.reviewer_handoff_requirements_sha256,
        reviewer_request_nonce_sha256=source.reviewer_request_nonce_sha256,
        repository=source.repository,
        pull_request_number=source.pull_request_number,
        pull_request_api_url=source.pull_request_api_url,
        pull_request_html_url=source.pull_request_html_url,
        pull_request_node_id_sha256=source.pull_request_node_id_sha256,
        base_branch=source.base_branch,
        head_branch=source.head_branch,
        predicted_commit_sha=source.predicted_commit_sha,
        reviewer_login=source.reviewer_login,
        reviewer_user_id=source.reviewer_user_id,
        reviewer_user_node_id_sha256=source.reviewer_user_node_id_sha256,
        pull_request_author_login=source.pull_request_author_login,
        pull_request_author_user_id=source.pull_request_author_user_id,
        requested_updated_at_utc=source.requested_updated_at_utc,
        source_first_response_body_sha256=source.first_response_body_sha256,
        source_first_response_etag_sha256=source.first_response_etag_sha256,
        source_second_response_body_sha256=source.second_response_body_sha256,
        source_second_response_etag_sha256=source.second_response_etag_sha256,
        source_second_observed_at_utc=source.second_observed_at_utc,
        checkpointed_at_utc=checkpointed_at,
    )
    path, payload = ledger.commit(checkpoint)
    _mark_authenticated(
        checkpoint,
        path=path,
        payload=payload,
        require_host_control=ledger.require_host_control,
    )
    if checkpoint.checkpoint_authenticated is not True:
        raise PilotExactTaskPrReviewObservationCheckpointError(
            "review-observation checkpoint lost durable provenance"
        )
    return checkpoint


def checkpoint_pilot_exact_task_pr_review_observation(
    reviewer_request_attestation: PilotExactTaskPrReviewerRequestAttestation,
) -> PilotExactTaskPrReviewObservationCheckpoint:
    """Durably checkpoint one exact post-reviewer-request state for later reads."""
    ledger = _ReviewObservationCheckpointLedger(
        _canonical_ledger_root(),
        require_host_control=True,
    )
    return _checkpoint_verified_pilot_exact_task_pr_review_observation(
        reviewer_request_attestation=reviewer_request_attestation,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


def load_pilot_exact_task_pr_review_observation_checkpoint(
    checkpoint_key_sha256: str,
) -> PilotExactTaskPrReviewObservationCheckpoint:
    """Re-authenticate one exact checkpoint from the canonical host ledger."""
    ledger = _ReviewObservationCheckpointLedger(
        _canonical_ledger_root(),
        require_host_control=True,
    )
    return ledger.load(checkpoint_key_sha256)


__all__ = [
    "PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_SCHEMA",
    "PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_AUTHORITY",
    "PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PR_REVIEW_OBSERVATION_CHECKPOINT_MAX_SOURCE_AGE_SECONDS",
    "PilotExactTaskPrReviewObservationCheckpointError",
    "PilotExactTaskPrReviewObservationCheckpoint",
    "checkpoint_pilot_exact_task_pr_review_observation",
    "load_pilot_exact_task_pr_review_observation_checkpoint",
]

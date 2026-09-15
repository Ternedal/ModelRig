"""ADR-DC-057 durable one-shot reservation for exact PR mutation intent.

Consumes one live ADR-DC-056 read-only PR-state observation, performs a fresh
equivalent observation, then durably burns the human-signed PR mutation nonce in
a create-once host ledger. The reservation consumes the human PR authorization
for replay purposes but still performs no GitHub write and grants no PR-create,
update, ready-for-review, merge, release, deploy or production authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from ._improvement_physical_state_host_control import (
    PhysicalHostStateError,
    _require_elevated_operator,
    _require_host_controlled_ledger_root,
)
from .durable_publication import DurablePublicationError, create_once_file
from . import improvement_pilot_exact_task_pull_request_state_observation as state_boundary
from .improvement_pilot_exact_task_pull_request_state_observation import (
    PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY,
    PilotExactTaskPullRequestStateObservation,
)
from .trusted_git_runtime_model import _has_linkish_component

PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pull-request-mutation-reservation/v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_AUTHORITY = (
    "host-reserved-one-dc-l16-exact-pull-request-mutation-slot-only"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_LEDGER_SCOPE = (
    "canonical-host-pull-request-mutation-v1"
)
PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_MAX_OBSERVATION_AGE_SECONDS = 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEAD_REF = re.compile(r"^refs/heads/agent/rsi/remote-candidate/[0-9a-f]{64}$")
_HEAD_BRANCH = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_ARTIFACT_BYTES = 2 * 1024 * 1024
_POSIX_LEDGER = Path(
    "/var/lib/modelrig/devcontrol/"
    "rsi-pilot-exact-task-pull-request-mutation-reservation-ledger-v1"
)
_WINDOWS_LEDGER = (
    Path(r"C:\Program Files\ModelRig\DevControl\state")
    / "rsi-pilot-exact-task-pull-request-mutation-reservation-ledger-v1"
)


class PilotExactTaskPullRequestMutationReservationError(ValueError):
    """The exact PR-mutation reservation is replayed, stale, drifted, or unsafe."""


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
        raise PilotExactTaskPullRequestMutationReservationError(
            "PR-mutation reservation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPullRequestMutationReservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPullRequestMutationReservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPullRequestMutationReservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPullRequestMutationReservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _path_sha256(path: Path) -> str:
    return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest()


def _read_bound_file(path: Path) -> bytes | None:
    candidate = Path(path)
    if not candidate.is_absolute() or _has_linkish_component(candidate):
        return None
    try:
        payload = candidate.read_bytes()
    except OSError:
        return None
    if not payload or len(payload) > _MAX_ARTIFACT_BYTES:
        return None
    return payload


def _require_safe_ledger_root(path: Path) -> Path:
    candidate = Path(path)
    if (
        not candidate.is_absolute()
        or not candidate.is_dir()
        or _has_linkish_component(candidate)
    ):
        raise PilotExactTaskPullRequestMutationReservationError(
            "PR-mutation reservation ledger root is unsafe"
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
        raise PilotExactTaskPullRequestMutationReservationError(
            "canonical PR-mutation reservation ledger is not host controlled"
        ) from exc
    raise PilotExactTaskPullRequestMutationReservationError(
        "PR-mutation reservation platform is unsupported"
    )


def _stable_observation_mapping(
    value: PilotExactTaskPullRequestStateObservation,
) -> dict[str, Any]:
    result = value.to_dict()
    for name in (
        "observed_at_utc",
        "head_response_sha256",
        "head_response_bytes",
        "pull_list_response_sha256",
        "pull_list_response_bytes",
    ):
        result.pop(name)
    return result


def _require_live_observation(
    value: Any,
) -> tuple[PilotExactTaskPullRequestStateObservation, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskPullRequestStateObservation:
        raise PilotExactTaskPullRequestMutationReservationError(
            "exact ADR-DC-056 PR-state observation is required"
        )
    try:
        replayed = PilotExactTaskPullRequestStateObservation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskPullRequestMutationReservationError(
            "ADR-DC-056 observation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskPullRequestMutationReservationError(
            "ADR-DC-056 observation identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_PULL_REQUEST_STATE_OBSERVATION_AUTHORITY
        or value.observation_authenticated is not True
        or value.human_pr_mutation_authorization_verified is not True
        or value.fresh_authorization_proof_reverified is not True
        or value.live_pr_requirements_verified is not True
        or value.remote_head_ref_observed is not True
        or value.remote_head_sha_matches_exact_candidate is not True
        or value.pull_request_state_observed is not True
        or value.existing_open_pull_request_absent is not True
        or value.same_repository_head_verified is not True
        or value.exact_base_ref_verified is not True
        or value.fixed_api_host_verified is not True
        or value.https_only_read is not True
        or value.get_only_read is not True
        or value.redirects_forbidden is not True
        or value.credentials_not_required is not True
        or value.response_bounded is not True
        or value.one_shot_pr_mutation_reservation_required is not True
        or value.host_pinned_pr_credential_capability_required is not True
        or value.merge_separately_authorized_required is not True
        or value.pr_mutation_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.pull_request_create_authorized is not False
        or value.pull_request_update_authorized is not False
        or value.ready_for_review_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.repository != "Ternedal/ModelRig"
        or value.api_host != "api.github.com"
        or value.base_ref != "main"
        or value.head_owner != "Ternedal"
        or _HEAD_REF.fullmatch(value.head_ref) is None
        or _HEAD_BRANCH.fullmatch(value.head_branch) is None
        or value.head_ref != f"refs/heads/{value.head_branch}"
    ):
        raise PilotExactTaskPullRequestMutationReservationError(
            "PR reservation requires one live inert ADR-DC-056 observation"
        )
    inputs = state_boundary._get_live_pull_request_state_observation_inputs(value)
    if inputs is None:
        raise PilotExactTaskPullRequestMutationReservationError(
            "ADR-DC-056 live observation provenance is unavailable"
        )
    proof = inputs.get("pull_request_mutation_authorization_proof")
    if (
        proof is None
        or getattr(proof, "sha256", None)
        != value.pull_request_mutation_authorization_proof_sha256
        or getattr(proof, "pr_mutation_nonce_sha256", None)
        != value.pr_mutation_nonce_sha256
        or getattr(proof, "predicted_commit_sha", None) != value.predicted_commit_sha
    ):
        raise PilotExactTaskPullRequestMutationReservationError(
            "ADR-DC-056 observation lost exact live ADR-DC-055 proof provenance"
        )
    return value, inputs


def _require_reservation_window(
    observation: PilotExactTaskPullRequestStateObservation,
    *,
    at_utc: str,
) -> datetime:
    at = _utc(at_utc, name="PR-mutation reservation time")
    observed = _utc(observation.observed_at_utc, name="ADR-DC-056 observed_at_utc")
    if at < observed:
        raise PilotExactTaskPullRequestMutationReservationError(
            "system clock moved backwards after ADR-DC-056 observation"
        )
    if (
        at - observed
    ).total_seconds() > PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_MAX_OBSERVATION_AGE_SECONDS:
        raise PilotExactTaskPullRequestMutationReservationError(
            "ADR-DC-056 observation is too old for PR-mutation reservation"
        )
    live = state_boundary._get_live_pull_request_state_observation_inputs(observation)
    proof = None if live is None else live.get(
        "pull_request_mutation_authorization_proof"
    )
    if proof is None:
        raise PilotExactTaskPullRequestMutationReservationError(
            "live human PR-mutation proof is unavailable"
        )
    authorized = _utc(
        proof.authorization.authorized_at_utc,
        name="PR authorization authorized_at_utc",
    )
    expires = _utc(
        proof.authorization.expires_at_utc,
        name="PR authorization expires_at_utc",
    )
    if at < authorized or at > expires:
        raise PilotExactTaskPullRequestMutationReservationError(
            "human PR-mutation authorization is not valid for reservation now"
        )
    return at


def _fresh_observation(
    supplied: PilotExactTaskPullRequestStateObservation,
    *,
    fresh_observer: Callable[[], PilotExactTaskPullRequestStateObservation],
) -> PilotExactTaskPullRequestStateObservation:
    if not callable(fresh_observer):
        raise PilotExactTaskPullRequestMutationReservationError(
            "fresh PR-state observer is unavailable"
        )
    try:
        fresh = fresh_observer()
    except Exception as exc:
        raise PilotExactTaskPullRequestMutationReservationError(
            "fresh ADR-DC-056 PR-state observation failed"
        ) from exc
    _require_live_observation(fresh)
    if _stable_observation_mapping(fresh) != _stable_observation_mapping(supplied):
        raise PilotExactTaskPullRequestMutationReservationError(
            "fresh PR-state semantics differ from supplied ADR-DC-056 observation"
        )
    return fresh


_REQUIRED_TRUE = (
    "host_replay_guard_committed",
    "fresh_pr_state_revalidated",
    "remote_head_sha_matches_exact_candidate",
    "existing_open_pull_request_absent",
    "pr_mutation_authorization_consumed",
    "pr_mutation_slot_reserved",
    "pr_mutation_transaction_required",
    "fresh_pr_state_revalidation_before_write_required",
    "draft_pull_request_required",
    "create_only_pull_request_required",
    "host_pinned_pr_credential_capability_required",
    "merge_separately_authorized_required",
)

_FORCED_FALSE = (
    "remote_write_authorized",
    "push_authorized",
    "pr_mutation_authorized",
    "pull_request_create_authorized",
    "pull_request_update_authorized",
    "ready_for_review_authorized",
    "merge_authorized",
    "release_authorized",
    "deploy_authorized",
    "production_activation_authorized",
)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPullRequestMutationReservationReceipt:
    ledger_root_path_sha256: str
    reservation_key_sha256: str
    state_observation_sha256: str
    fresh_state_observation_sha256: str
    pull_request_mutation_authorization_proof_sha256: str
    pull_request_mutation_requirements_sha256: str
    remote_publication_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    pr_mutation_nonce_sha256: str
    predicted_commit_sha: str
    repository: str
    api_host: str
    base_ref: str
    head_owner: str
    head_ref: str
    head_branch: str
    query_sha256: str
    supplied_observed_at_utc: str
    fresh_observed_at_utc: str
    reserved_at_utc: str
    host_replay_guard_committed: bool = True
    fresh_pr_state_revalidated: bool = True
    remote_head_sha_matches_exact_candidate: bool = True
    existing_open_pull_request_absent: bool = True
    pr_mutation_authorization_consumed: bool = True
    pr_mutation_slot_reserved: bool = True
    pr_mutation_transaction_required: bool = True
    fresh_pr_state_revalidation_before_write_required: bool = True
    draft_pull_request_required: bool = True
    create_only_pull_request_required: bool = True
    host_pinned_pr_credential_capability_required: bool = True
    merge_separately_authorized_required: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    pull_request_create_authorized: bool = False
    pull_request_update_authorized: bool = False
    ready_for_review_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_AUTHORITY
    ledger_scope: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_LEDGER_SCOPE
    schema: str = PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_SCHEMA:
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation schema is unsupported"
            )
        if (
            self.authority
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_AUTHORITY
            or self.ledger_scope
            != PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_LEDGER_SCOPE
        ):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation authority/scope is unsupported"
            )
        for name in (
            "ledger_root_path_sha256",
            "reservation_key_sha256",
            "state_observation_sha256",
            "fresh_state_observation_sha256",
            "pull_request_mutation_authorization_proof_sha256",
            "pull_request_mutation_requirements_sha256",
            "remote_publication_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "pr_mutation_nonce_sha256",
            "query_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        if (
            self.reservation_key_sha256 != self.pr_mutation_nonce_sha256
            or self.repository != "Ternedal/ModelRig"
            or self.api_host != "api.github.com"
            or self.base_ref != "main"
            or self.head_owner != "Ternedal"
            or _HEAD_REF.fullmatch(self.head_ref) is None
            or _HEAD_BRANCH.fullmatch(self.head_branch) is None
            or self.head_ref != f"refs/heads/{self.head_branch}"
            or not self.head_ref.endswith(self.remote_publication_nonce_sha256)
        ):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation target binding is invalid"
            )
        supplied = _utc(self.supplied_observed_at_utc, name="supplied_observed_at_utc")
        fresh = _utc(self.fresh_observed_at_utc, name="fresh_observed_at_utc")
        reserved = _utc(self.reserved_at_utc, name="reserved_at_utc")
        if fresh < supplied or reserved < fresh:
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation timestamps are not monotonic"
            )
        if (
            reserved - fresh
        ).total_seconds() > PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_MAX_OBSERVATION_AGE_SECONDS:
            raise PilotExactTaskPullRequestMutationReservationError(
                "fresh PR-state observation is too old for committed reservation"
            )
        if any(getattr(self, name) is not True for name in _REQUIRED_TRUE):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in _FORCED_FALSE):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation cannot grant mutation authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def reservation_authenticated(self) -> bool:
        return _get_live_pull_request_mutation_reservation_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(
        cls, value: Any
    ) -> "PilotExactTaskPullRequestMutationReservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation receipt fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


class _PilotExactTaskPullRequestMutationReservationLedger:
    def __init__(self, root: Path) -> None:
        self.root = _require_safe_ledger_root(Path(root))
        self.root_sha256 = _path_sha256(self.root)

    def _path(self, nonce_sha256: str) -> Path:
        nonce = _hex64(nonce_sha256, name="pr_mutation_nonce_sha256")
        return self.root / f"{nonce}.json"

    def reserve(
        self,
        receipt: PilotExactTaskPullRequestMutationReservationReceipt,
    ) -> tuple[Path, bytes]:
        if (
            type(receipt) is not PilotExactTaskPullRequestMutationReservationReceipt
            or receipt.ledger_root_path_sha256 != self.root_sha256
            or receipt.reservation_key_sha256 != receipt.pr_mutation_nonce_sha256
        ):
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation receipt does not belong to this ledger"
            )
        path = self._path(receipt.pr_mutation_nonce_sha256)
        payload = receipt.canonical_json().encode("utf-8")
        if len(payload) > _MAX_ARTIFACT_BYTES:
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation reservation receipt exceeds byte bound"
            )
        try:
            create_once_file(path, payload, mode=0o600)
        except (FileExistsError, DurablePublicationError, OSError) as exc:
            raise PilotExactTaskPullRequestMutationReservationError(
                "PR-mutation nonce is already reserved or ledger write failed"
            ) from exc
        if _read_bound_file(path) != payload:
            raise PilotExactTaskPullRequestMutationReservationError(
                "durable PR-mutation reservation could not be read back exactly"
            )
        return path, payload


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            PilotExactTaskPullRequestStateObservation,
            Path,
            bytes,
        ],
    ] = {}

    def mark(
        receipt: PilotExactTaskPullRequestMutationReservationReceipt,
        fresh_observation: PilotExactTaskPullRequestStateObservation,
        *,
        path: Path,
        payload: bytes,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            fresh_observation,
            path,
            payload,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, observation, path, payload = entry
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or observation.observation_authenticated is not True
            or receipt.sha256 != digest
            or observation.sha256 != receipt.fresh_state_observation_sha256
            or observation.pr_mutation_nonce_sha256 != receipt.pr_mutation_nonce_sha256
            or observation.predicted_commit_sha != receipt.predicted_commit_sha
            or observation.head_ref != receipt.head_ref
            or _read_bound_file(path) != payload
        ):
            return None
        return MappingProxyType({"pull_request_state_observation": observation})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_pull_request_mutation_reservation_authenticated,
    _get_live_pull_request_mutation_reservation_inputs,
) = _live_registry()


def _reserve_verified_pilot_exact_task_pull_request_mutation(
    *,
    state_observation: PilotExactTaskPullRequestStateObservation,
    fresh_observer: Callable[[], PilotExactTaskPullRequestStateObservation],
    ledger: _PilotExactTaskPullRequestMutationReservationLedger,
    now_provider: Callable[[], str],
) -> PilotExactTaskPullRequestMutationReservationReceipt:
    supplied, _inputs = _require_live_observation(state_observation)
    started_at = now_provider()
    _require_reservation_window(supplied, at_utc=started_at)

    fresh = _fresh_observation(supplied, fresh_observer=fresh_observer)
    reserved_at = now_provider()
    _require_reservation_window(fresh, at_utc=reserved_at)

    if not isinstance(ledger, _PilotExactTaskPullRequestMutationReservationLedger):
        raise PilotExactTaskPullRequestMutationReservationError(
            "exact PR-mutation reservation ledger is required"
        )

    receipt = PilotExactTaskPullRequestMutationReservationReceipt(
        ledger_root_path_sha256=ledger.root_sha256,
        reservation_key_sha256=fresh.pr_mutation_nonce_sha256,
        state_observation_sha256=supplied.sha256,
        fresh_state_observation_sha256=fresh.sha256,
        pull_request_mutation_authorization_proof_sha256=(
            fresh.pull_request_mutation_authorization_proof_sha256
        ),
        pull_request_mutation_requirements_sha256=(
            fresh.pull_request_mutation_requirements_sha256
        ),
        remote_publication_write_transaction_sha256=(
            fresh.remote_publication_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=fresh.remote_publication_nonce_sha256,
        pr_mutation_nonce_sha256=fresh.pr_mutation_nonce_sha256,
        predicted_commit_sha=fresh.predicted_commit_sha,
        repository=fresh.repository,
        api_host=fresh.api_host,
        base_ref=fresh.base_ref,
        head_owner=fresh.head_owner,
        head_ref=fresh.head_ref,
        head_branch=fresh.head_branch,
        query_sha256=fresh.query_sha256,
        supplied_observed_at_utc=supplied.observed_at_utc,
        fresh_observed_at_utc=fresh.observed_at_utc,
        reserved_at_utc=reserved_at,
    )
    path, payload = ledger.reserve(receipt)
    _mark_pull_request_mutation_reservation_authenticated(
        receipt,
        fresh,
        path=path,
        payload=payload,
    )
    if receipt.reservation_authenticated is not True:
        raise PilotExactTaskPullRequestMutationReservationError(
            "PR-mutation reservation lost durable live provenance"
        )
    return receipt


def reserve_pilot_exact_task_pull_request_mutation(
    state_observation: PilotExactTaskPullRequestStateObservation,
    *,
    authorization_signature: Any,
) -> PilotExactTaskPullRequestMutationReservationReceipt:
    """Durably consume one signed PR nonce without performing a GitHub write."""
    supplied, inputs = _require_live_observation(state_observation)
    proof = inputs.get("pull_request_mutation_authorization_proof")
    if proof is None:
        raise PilotExactTaskPullRequestMutationReservationError(
            "live ADR-DC-055 proof is unavailable for fresh reservation check"
        )
    root = _canonical_ledger_root()
    ledger = _PilotExactTaskPullRequestMutationReservationLedger(root)

    def observe_fresh() -> PilotExactTaskPullRequestStateObservation:
        return state_boundary.observe_pilot_exact_task_pull_request_state(
            authorization_proof=proof,
            authorization_signature=authorization_signature,
        )

    return _reserve_verified_pilot_exact_task_pull_request_mutation(
        state_observation=supplied,
        fresh_observer=observe_fresh,
        ledger=ledger,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_LEDGER_SCOPE",
    "PILOT_EXACT_TASK_PULL_REQUEST_MUTATION_RESERVATION_MAX_OBSERVATION_AGE_SECONDS",
    "PilotExactTaskPullRequestMutationReservationError",
    "PilotExactTaskPullRequestMutationReservationReceipt",
    "reserve_pilot_exact_task_pull_request_mutation",
]

"""ADR-DC-050 read-only observation of one exact remote publication ref.

The boundary accepts only a live ADR-DC-049 host-pinned target attestation,
freshly revalidates the local candidate, then performs one bounded noninteractive
HTTPS `git ls-remote` for the exact attested destination ref. Publication may
continue only when that ref is absent. No remote mutation authority is granted.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping

from . import improvement_pilot_exact_task_local_commit_publication_requirements as publication_boundary
from .improvement_pilot_exact_task_local_commit_publication_requirements import (
    PilotExactTaskLocalCommitPublicationRequirements,
)
from . import improvement_pilot_exact_task_remote_publication_target_attestation as target_boundary
from .improvement_pilot_exact_task_remote_publication_target_attestation import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY,
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL,
    PilotExactTaskRemotePublicationTargetAttestation,
)

PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-state-observation/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-remote-destination-absent-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCOPE = (
    "one-read-only-host-pinned-remote-destination-observation-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA = "0" * 40
PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_TARGET_ATTESTATION_AGE_SECONDS = 5 * 60

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_REMOTE_OUTPUT_BYTES = 4096


class PilotExactTaskRemotePublicationStateObservationError(ValueError):
    """The exact remote destination state cannot be observed safely."""


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
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote state observation is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationStateObservationError(
            f"{name} is invalid"
        )
    return value


def _hex40(value: Any, *, name: str, allow_zero: bool = False) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            f"{name} is invalid"
        )
    if not allow_zero and value == PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA:
        raise PilotExactTaskRemotePublicationStateObservationError(
            f"{name} must not be zero"
        )
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationStateObservationError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _stable_requirements_mapping(
    value: PilotExactTaskLocalCommitPublicationRequirements,
) -> dict[str, Any]:
    result = value.to_dict()
    result.pop("verified_at_utc")
    return result


def _require_live_target_attestation(
    value: Any,
) -> tuple[
    PilotExactTaskRemotePublicationTargetAttestation,
    Any,
    PilotExactTaskLocalCommitPublicationRequirements,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskRemotePublicationTargetAttestation:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "exact ADR-DC-049 target attestation is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationTargetAttestation.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-049 target attestation replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-049 target attestation identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_ATTESTATION_AUTHORITY
        or value.target_attestation_authenticated is not True
        or value.human_remote_publication_authorization_verified is not True
        or value.remote_target_host_pinned is not True
        or value.destination_ref_derived_from_signed_nonce is not True
        or value.remote_state_observation_required is not True
        or value.remote_write_reservation_required is not True
        or value.remote_branch_compare_and_swap_required is not True
        or value.expected_old_remote_sha_required is not True
        or value.no_force_push_required is not True
        or value.separate_pr_mutation_authorization_required is not True
        or value.remote_publication_authorization_consumed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.canonical_remote_url
        != PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL
    ):
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote state observation requires one inert live ADR-DC-049 attestation"
        )

    target_inputs = target_boundary._get_live_remote_publication_target_attestation_inputs(
        value
    )
    if target_inputs is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-049 live target provenance is unavailable"
        )
    proof = target_inputs.get("remote_publication_authorization_proof")
    if proof is None or getattr(proof, "sha256", None) != value.authorization_proof_sha256:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-049 target lost exact ADR-DC-048 proof provenance"
        )
    requirements = proof.authorization.local_commit_publication_requirements
    if (
        type(requirements) is not PilotExactTaskLocalCommitPublicationRequirements
        or requirements.verification_authenticated is not True
        or requirements.sha256 != value.local_commit_publication_requirements_sha256
        or requirements.predicted_commit_sha != value.predicted_commit_sha
        or proof.remote_publication_nonce_sha256 != value.remote_publication_nonce_sha256
    ):
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-049 target is not bound to live ADR-DC-047 requirements"
        )
    publication_inputs = (
        publication_boundary._get_live_local_commit_publication_requirements_inputs(
            requirements
        )
    )
    if publication_inputs is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "ADR-DC-047 live local candidate provenance is unavailable"
        )
    return value, proof, requirements, publication_inputs


def _fresh_local_candidate_revalidation(
    requirements: PilotExactTaskLocalCommitPublicationRequirements,
    publication_inputs: Mapping[str, Any],
) -> PilotExactTaskLocalCommitPublicationRequirements:
    transaction = publication_inputs.get("local_commit_write_transaction")
    if transaction is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "live publication requirements lost the local-write transaction"
        )
    try:
        fresh = (
            publication_boundary.materialize_pilot_exact_task_local_commit_publication_requirements(
                transaction
            )
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "fresh local candidate verification failed before remote observation"
        ) from exc
    if _stable_requirements_mapping(fresh) != _stable_requirements_mapping(requirements):
        raise PilotExactTaskRemotePublicationStateObservationError(
            "fresh local candidate semantics differ from ADR-DC-047"
        )
    return fresh


def _require_observation_window(
    *,
    attestation: PilotExactTaskRemotePublicationTargetAttestation,
    proof: Any,
    at_utc: str,
) -> datetime:
    at = _utc(at_utc, name="remote observation time")
    attested = _utc(attestation.attested_at_utc, name="target attested_at_utc")
    authorized = _utc(
        proof.authorization.authorized_at_utc,
        name="remote authorization authorized_at_utc",
    )
    expires = _utc(
        proof.authorization.expires_at_utc,
        name="remote authorization expires_at_utc",
    )
    if at < attested or at < authorized or at > expires:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote observation is outside the live human authorization window"
        )
    age = (at - attested).total_seconds()
    if age > PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_TARGET_ATTESTATION_AGE_SECONDS:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote target attestation is too old for fresh remote observation"
        )
    return at


def _observe_remote_destination_absent(
    *,
    attestation: PilotExactTaskRemotePublicationTargetAttestation,
    publication_inputs: Mapping[str, Any],
) -> None:
    runner = publication_inputs.get("git_runner")
    workspace = publication_inputs.get("workspace_root")
    if runner is None or workspace is None:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "trusted Git remote-read provenance is unavailable"
        )
    args = (
        "-c",
        "protocol.https.allow=always",
        "-c",
        "http.followRedirects=false",
        "-c",
        "credential.helper=",
        "ls-remote",
        "--refs",
        attestation.canonical_remote_url,
        attestation.destination_ref,
    )
    try:
        output = runner.run(
            args,
            cwd=workspace,
            maximum=_MAX_REMOTE_OUTPUT_BYTES,
            timeout_seconds=30,
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "host-pinned remote state could not be observed safely"
        ) from exc
    if not isinstance(output, bytes):
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote state observation returned non-bytes output"
        )
    if output != b"":
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote destination ref already exists; create-only publication fails closed"
        )


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            PilotExactTaskRemotePublicationTargetAttestation,
        ],
    ] = {}

    def mark(
        observation: Any,
        attestation: PilotExactTaskRemotePublicationTargetAttestation,
    ) -> None:
        key = id(observation)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            observation.sha256,
            weakref.ref(observation, cleanup),
            attestation,
        )

    def get(observation: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(observation))
        if entry is None:
            return None
        pid, digest, observation_ref, attestation = entry
        if (
            pid != os.getpid()
            or observation_ref() is not observation
            or observation.sha256 != digest
            or attestation.sha256 != observation.target_attestation_sha256
            or attestation.target_attestation_authenticated is not True
        ):
            return None
        return MappingProxyType({"remote_publication_target_attestation": attestation})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_state_observation_authenticated,
    _get_live_remote_publication_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationStateObservation:
    target_attestation_sha256: str
    authorization_proof_sha256: str
    local_commit_publication_requirements_sha256: str
    local_commit_write_transaction_sha256: str
    remote_publication_nonce_sha256: str
    predicted_commit_sha: str
    target_policy_sha256: str
    target_provider: str
    target_host: str
    target_repository: str
    canonical_remote_url: str
    destination_ref: str
    expected_old_remote_sha: str
    observed_at_utc: str
    target_attestation_verified: bool = True
    fresh_local_commit_revalidated: bool = True
    remote_state_observed: bool = True
    remote_destination_ref_absent: bool = True
    expected_old_remote_sha_bound: bool = True
    create_only_remote_ref_required: bool = True
    https_only_remote_read: bool = True
    redirects_forbidden: bool = True
    credential_helpers_disabled: bool = True
    interactive_auth_disabled: bool = True
    remote_write_reservation_required: bool = True
    remote_branch_compare_and_swap_required: bool = True
    no_force_push_required: bool = True
    separate_pr_mutation_authorization_required: bool = True
    remote_publication_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCHEMA:
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation schema is unsupported"
            )
        if self.observation_scope != PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCOPE:
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation scope is unsupported"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY:
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation authority is unsupported"
            )
        for name in (
            "target_attestation_sha256",
            "authorization_proof_sha256",
            "local_commit_publication_requirements_sha256",
            "local_commit_write_transaction_sha256",
            "remote_publication_nonce_sha256",
            "target_policy_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        _hex40(
            self.expected_old_remote_sha,
            name="expected_old_remote_sha",
            allow_zero=True,
        )
        if self.expected_old_remote_sha != PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA:
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation must remain create-only from an absent ref"
            )
        fixed = {
            "target_provider": "github",
            "target_host": "github.com",
            "target_repository": "Ternedal/ModelRig",
            "canonical_remote_url": PILOT_EXACT_TASK_REMOTE_PUBLICATION_TARGET_CANONICAL_URL,
        }
        mismatch = next(
            (name for name, expected in fixed.items() if getattr(self, name) != expected),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemotePublicationStateObservationError(
                f"remote state target identity mismatch: {mismatch}"
            )
        if not isinstance(self.destination_ref, str) or not self.destination_ref.startswith(
            "refs/heads/agent/rsi/remote-candidate/"
        ):
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote destination ref is outside the pinned namespace"
            )
        _utc(self.observed_at_utc, name="observed_at_utc")
        required_true = (
            "target_attestation_verified",
            "fresh_local_commit_revalidated",
            "remote_state_observed",
            "remote_destination_ref_absent",
            "expected_old_remote_sha_bound",
            "create_only_remote_ref_required",
            "https_only_remote_read",
            "redirects_forbidden",
            "credential_helpers_disabled",
            "interactive_auth_disabled",
            "remote_write_reservation_required",
            "remote_branch_compare_and_swap_required",
            "no_force_push_required",
            "separate_pr_mutation_authorization_required",
        )
        forced_false = (
            "remote_publication_authorization_consumed",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation cannot grant remote mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_remote_publication_state_observation_inputs(self) is not None

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
        cls, value: Any
    ) -> "PilotExactTaskRemotePublicationStateObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemotePublicationStateObservationError(
                "remote state observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_remote_publication_state(
    *,
    target_attestation: PilotExactTaskRemotePublicationTargetAttestation,
    now_provider: Callable[[], str],
) -> PilotExactTaskRemotePublicationStateObservation:
    attestation, proof, requirements, publication_inputs = (
        _require_live_target_attestation(target_attestation)
    )
    started_at = now_provider()
    _require_observation_window(
        attestation=attestation,
        proof=proof,
        at_utc=started_at,
    )
    _fresh_local_candidate_revalidation(requirements, publication_inputs)
    _observe_remote_destination_absent(
        attestation=attestation,
        publication_inputs=publication_inputs,
    )
    _fresh_local_candidate_revalidation(requirements, publication_inputs)
    observed_at = now_provider()
    started = _utc(started_at, name="observation started_at_utc")
    observed = _require_observation_window(
        attestation=attestation,
        proof=proof,
        at_utc=observed_at,
    )
    if observed < started:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "system clock moved backwards during remote state observation"
        )
    result = PilotExactTaskRemotePublicationStateObservation(
        target_attestation_sha256=attestation.sha256,
        authorization_proof_sha256=attestation.authorization_proof_sha256,
        local_commit_publication_requirements_sha256=(
            attestation.local_commit_publication_requirements_sha256
        ),
        local_commit_write_transaction_sha256=(
            attestation.local_commit_write_transaction_sha256
        ),
        remote_publication_nonce_sha256=attestation.remote_publication_nonce_sha256,
        predicted_commit_sha=attestation.predicted_commit_sha,
        target_policy_sha256=attestation.target_policy_sha256,
        target_provider=attestation.target_provider,
        target_host=attestation.target_host,
        target_repository=attestation.target_repository,
        canonical_remote_url=attestation.canonical_remote_url,
        destination_ref=attestation.destination_ref,
        expected_old_remote_sha=PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA,
        observed_at_utc=observed_at,
    )
    _mark_remote_publication_state_observation_authenticated(result, attestation)
    if result.observation_authenticated is not True:
        raise PilotExactTaskRemotePublicationStateObservationError(
            "remote state observation lost live target provenance"
        )
    return result


def observe_pilot_exact_task_remote_publication_state(
    target_attestation: PilotExactTaskRemotePublicationTargetAttestation,
) -> PilotExactTaskRemotePublicationStateObservation:
    """Observe one host-pinned destination ref without granting mutation authority."""
    return _observe_verified_pilot_exact_task_remote_publication_state(
        target_attestation=target_attestation,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_STATE_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_EXPECTED_ABSENT_SHA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_TARGET_ATTESTATION_AGE_SECONDS",
    "PilotExactTaskRemotePublicationStateObservationError",
    "PilotExactTaskRemotePublicationStateObservation",
    "observe_pilot_exact_task_remote_publication_state",
]

"""ADR-DC-050 read-only exact remote-head observation.

This boundary accepts only the exact live ADR-DC-049 remote-publication
requirements, revalidates the clean local commit and host-pinned remote
configuration, and performs two anonymous HTTPS ``git ls-remote --heads``
observations against the exact canonical GitHub repository/ref.

It never pushes, fetches objects, writes remote state, loads credentials,
mutates a PR, merges, releases, deploys, or activates production.
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
from typing import Any, Mapping

from . import improvement_pilot_exact_task_remote_publication_requirements as requirements_boundary
from .improvement_pilot_exact_task_remote_publication_requirements import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY,
    PilotExactTaskRemotePublicationRequirements,
)

PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-head-observation/v1"
)
PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-github-remote-head-read-only"
)
PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCOPE = (
    "anonymous-read-only-exact-github-remote-head-v1"
)
PILOT_EXACT_TASK_REMOTE_HEAD_TRANSPORT = "trusted-git-anonymous-https-ls-remote-v1"
PUBLICATION_MODE_FAST_FORWARD = "fast-forward-from-exact-base"
PUBLICATION_MODE_CREATE = "create-exact-branch-if-absent"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_REMOTE_OUTPUT_BYTES = 4096

_KEY_FIELDS = (
    "requirements_sha256",
    "requirements_key_sha256",
    "ref_update_receipt_sha256",
    "task_id",
    "repository",
    "base_sha",
    "local_commit_sha",
    "source_ref",
    "destination_ref",
    "canonical_remote_url",
    "remote_name",
    "remote_provider",
    "first_remote_observation_sha256",
    "second_remote_observation_sha256",
    "remote_head_present",
    "remote_head_sha",
    "publication_mode",
    "local_state_before_sha256",
    "local_state_after_sha256",
    "observation_started_at_utc",
    "observation_completed_at_utc",
    "transport",
)


class PilotExactTaskRemoteHeadObservationError(ValueError):
    """Exact remote-head observation is malformed, stale, or unsafe."""


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
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head observation is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX40.fullmatch(value) is None or value == "0" * 40:
        raise PilotExactTaskRemoteHeadObservationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if not isinstance(value, str) or _HEX64.fullmatch(value) is None or value == "0" * 64:
        raise PilotExactTaskRemoteHeadObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemoteHeadObservationError(f"{name} must be canonical UTC seconds")
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise PilotExactTaskRemoteHeadObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def _observation_key(value: Any) -> str:
    payload = {name: getattr(value, name) for name in _KEY_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _observation_key_from_mapping(value: Mapping[str, Any]) -> str:
    payload = {name: value[name] for name in _KEY_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _replay_requirements(value: Any) -> PilotExactTaskRemotePublicationRequirements:
    if type(value) is not PilotExactTaskRemotePublicationRequirements:
        raise PilotExactTaskRemoteHeadObservationError(
            "exact ADR-DC-049 remote-publication requirements are required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationRequirements.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-049 requirements replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemoteHeadObservationError("ADR-DC-049 requirements identity mismatch")
    required_true = (
        "source_ref_update_authenticated_at_materialization",
        "fresh_local_commit_state_matched",
        "remote_configuration_observed_locally",
        "local_commit_created",
        "fresh_human_remote_publication_authorization_required",
        "one_shot_remote_publication_nonce_required",
        "host_local_remote_authorization_replay_ledger_required",
        "host_local_remote_execution_ledger_required",
        "fresh_local_commit_revalidation_before_authorization_required",
        "fresh_remote_head_observation_before_authorization_required",
        "fresh_remote_head_revalidation_before_push_required",
        "exact_source_commit_required",
        "exact_destination_ref_required",
        "fast_forward_only_required",
        "force_push_forbidden",
        "remote_delete_forbidden",
        "tag_publication_forbidden",
        "pr_mutation_separate_authority_required",
        "manual_operator_invocation_required",
    )
    forced_false = (
        "network_access_performed",
        "credential_material_present",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY
        or value.requirements_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head observation requires exact live inert ADR-DC-049 requirements"
        )
    if (
        value.remote_name != "origin"
        or value.remote_provider != "github"
        or value.remote_repository.casefold() != value.repository.casefold()
        or value.source_ref != value.destination_ref
        or value.source_ref_sha != value.local_commit_sha
        or value.push_refspec != f"{value.local_commit_sha}:{value.destination_ref}"
        or value.canonical_remote_url
        != requirements_boundary._canonical_github_remote(
            value.observed_push_url,
            repository=value.repository,
        )
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-049 remote-publication binding is inconsistent"
        )
    return value


def _require_live_requirements(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationRequirements, Any, Mapping[str, Any]]:
    requirements = _replay_requirements(value)
    live = requirements_boundary._get_live_remote_publication_requirements_inputs(requirements)
    if live is None:
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-049 live requirements provenance is unavailable"
        )
    ref_update_receipt = live.get("ref_update_receipt")
    if ref_update_receipt is None:
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-048 live ref-update provenance is unavailable"
        )
    try:
        exact_ref, _object_write, _identity, inputs = requirements_boundary._require_live_ref_update(
            ref_update_receipt
        )
    except Exception as exc:
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-049 live local-commit binding is unavailable"
        ) from exc
    if (
        exact_ref.sha256 != requirements.ref_update_receipt_sha256
        or exact_ref.new_commit_sha != requirements.local_commit_sha
        or exact_ref.target_ref != requirements.destination_ref
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "ADR-DC-049 no longer matches its live local commit"
        )
    return requirements, ref_update_receipt, inputs


def _fresh_local_state(
    requirements: PilotExactTaskRemotePublicationRequirements,
    ref_update_receipt: Any,
    inputs: Mapping[str, Any],
):
    try:
        snapshot, local_ref, push_url, canonical = requirements_boundary._fresh_local_publication_state(
            ref_update_receipt,
            inputs,
        )
    except Exception as exc:
        raise PilotExactTaskRemoteHeadObservationError(
            "fresh ADR-DC-050 local publication revalidation failed"
        ) from exc
    if (
        snapshot.sha256 != requirements.post_ref_update_workspace_snapshot_sha256
        or local_ref != requirements.destination_ref
        or push_url != requirements.observed_push_url
        or hashlib.sha256(push_url.encode("utf-8")).hexdigest()
        != requirements.observed_push_url_sha256
        or canonical != requirements.canonical_remote_url
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "local commit/remote configuration drifted since ADR-DC-049"
        )
    return snapshot


def _parse_ls_remote(raw: bytes, *, destination_ref: str) -> tuple[bool, str | None]:
    if not isinstance(raw, bytes) or len(raw) > _MAX_REMOTE_OUTPUT_BYTES:
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head output exceeds its exact bound"
        )
    if raw == b"":
        return False, None
    if b"\x00" in raw or b"\r" in raw:
        raise PilotExactTaskRemoteHeadObservationError("remote-head output is non-canonical")
    lines = raw.splitlines()
    if len(lines) != 1 or not raw.endswith(b"\n"):
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head output must contain exactly one canonical record"
        )
    fields = lines[0].split(b"\t")
    if len(fields) != 2:
        raise PilotExactTaskRemoteHeadObservationError("remote-head record fields are invalid")
    try:
        sha = fields[0].decode("ascii", errors="strict")
        ref = fields[1].decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head record encoding is invalid"
        ) from exc
    _hex40(sha, name="remote head SHA")
    if ref != destination_ref:
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head record does not match the exact destination ref"
        )
    return True, sha


def _observe_remote_head_once(
    requirements: PilotExactTaskRemotePublicationRequirements,
    inputs: Mapping[str, Any],
) -> tuple[bytes, bool, str | None]:
    runner = inputs["git_runner"]
    args = (
        "-c",
        "protocol.allow=https",
        "-c",
        "protocol.version=2",
        "-c",
        "http.followRedirects=false",
        "ls-remote",
        "--heads",
        requirements.canonical_remote_url,
        requirements.destination_ref,
    )
    try:
        raw = runner.run(
            args,
            cwd=runner.operation_root,
            maximum=_MAX_REMOTE_OUTPUT_BYTES,
            timeout_seconds=30,
        )
    except Exception as exc:
        raise PilotExactTaskRemoteHeadObservationError(
            "anonymous exact GitHub remote-head observation failed"
        ) from exc
    present, sha = _parse_ls_remote(raw, destination_ref=requirements.destination_ref)
    return raw, present, sha


def _publication_mode(
    *,
    present: bool,
    remote_head_sha: str | None,
    base_sha: str,
    local_commit_sha: str,
) -> str:
    if not present:
        if remote_head_sha is not None:
            raise PilotExactTaskRemoteHeadObservationError("absent remote head cannot carry a SHA")
        return PUBLICATION_MODE_CREATE
    if remote_head_sha == base_sha:
        return PUBLICATION_MODE_FAST_FORWARD
    if remote_head_sha == local_commit_sha:
        raise PilotExactTaskRemoteHeadObservationError(
            "remote destination already contains the exact local commit"
        )
    raise PilotExactTaskRemoteHeadObservationError(
        "remote destination is not at the exact reviewed base SHA"
    )


def _live_registry():
    records: dict[int, tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]]] = {}

    def mark(observation: Any, requirements: PilotExactTaskRemotePublicationRequirements) -> None:
        key = id(observation)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            observation.sha256,
            weakref.ref(observation, cleanup),
            weakref.ref(requirements),
        )

    def get(observation: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(observation))
        if entry is None:
            return None
        pid, digest, observation_ref, requirements_ref = entry
        requirements = requirements_ref()
        if (
            pid != os.getpid()
            or observation_ref() is not observation
            or requirements is None
            or requirements.requirements_authenticated is not True
        ):
            return None
        try:
            if observation.sha256 != digest:
                return None
        except (AttributeError, TypeError, ValueError):
            return None
        return MappingProxyType({"requirements": requirements})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_remote_head_observation_authenticated, _get_live_remote_head_observation_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemoteHeadObservation:
    requirements: PilotExactTaskRemotePublicationRequirements
    requirements_sha256: str
    requirements_key_sha256: str
    ref_update_receipt_sha256: str
    task_id: str
    repository: str
    base_sha: str
    local_commit_sha: str
    source_ref: str
    destination_ref: str
    canonical_remote_url: str
    remote_name: str
    remote_provider: str
    first_remote_observation_sha256: str
    second_remote_observation_sha256: str
    remote_head_present: bool
    remote_head_sha: str | None
    publication_mode: str
    local_state_before_sha256: str
    local_state_after_sha256: str
    observation_started_at_utc: str
    observation_completed_at_utc: str
    observation_key_sha256: str
    network_access_performed: bool = True
    credential_material_present: bool = False
    remote_head_observed: bool = True
    remote_head_stable_across_double_observation: bool = True
    local_commit_state_matched: bool = True
    exact_remote_repository_matched: bool = True
    exact_destination_ref_matched: bool = True
    fast_forward_candidate: bool = True
    fresh_human_remote_publication_authorization_required: bool = True
    fresh_remote_head_revalidation_before_push_required: bool = True
    human_remote_publication_authorization_verified: bool = False
    remote_publication_authorization_consumed: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    observation_scope: str = PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCOPE
    transport: str = PILOT_EXACT_TASK_REMOTE_HEAD_TRANSPORT
    authority: str = PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCOPE
            or self.transport != PILOT_EXACT_TASK_REMOTE_HEAD_TRANSPORT
        ):
            raise PilotExactTaskRemoteHeadObservationError(
                "remote-head observation schema/scope/transport/authority is unsupported"
            )
        if type(self.requirements) is not PilotExactTaskRemotePublicationRequirements:
            raise PilotExactTaskRemoteHeadObservationError("exact ADR-DC-049 requirements are required")
        try:
            replayed = PilotExactTaskRemotePublicationRequirements.from_mapping(
                self.requirements.to_dict()
            )
        except Exception as exc:
            raise PilotExactTaskRemoteHeadObservationError(
                "embedded ADR-DC-049 requirements replay failed"
            ) from exc
        if (
            replayed != self.requirements
            or replayed.sha256 != self.requirements_sha256
            or self.requirements.requirements_key_sha256 != self.requirements_key_sha256
            or self.requirements.ref_update_receipt_sha256 != self.ref_update_receipt_sha256
        ):
            raise PilotExactTaskRemoteHeadObservationError(
                "embedded ADR-DC-049 requirements identity mismatch"
            )
        for name in (
            "requirements_sha256",
            "requirements_key_sha256",
            "ref_update_receipt_sha256",
            "first_remote_observation_sha256",
            "second_remote_observation_sha256",
            "local_state_before_sha256",
            "local_state_after_sha256",
            "observation_key_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "local_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if self.remote_head_sha is not None:
            _hex40(self.remote_head_sha, name="remote_head_sha")
        if not isinstance(self.remote_head_present, bool):
            raise PilotExactTaskRemoteHeadObservationError("remote_head_present is invalid")
        expected = {
            "task_id": self.requirements.task_id,
            "repository": self.requirements.repository,
            "base_sha": self.requirements.base_sha,
            "local_commit_sha": self.requirements.local_commit_sha,
            "source_ref": self.requirements.source_ref,
            "destination_ref": self.requirements.destination_ref,
            "canonical_remote_url": self.requirements.canonical_remote_url,
            "remote_name": self.requirements.remote_name,
            "remote_provider": self.requirements.remote_provider,
        }
        mismatch = next(
            (name for name, value in expected.items() if getattr(self, name) != value),
            None,
        )
        if mismatch is not None:
            raise PilotExactTaskRemoteHeadObservationError(
                f"remote-head observation binding mismatch: {mismatch}"
            )
        if self.first_remote_observation_sha256 != self.second_remote_observation_sha256:
            raise PilotExactTaskRemoteHeadObservationError(
                "double remote-head observations do not match"
            )
        mode = _publication_mode(
            present=self.remote_head_present,
            remote_head_sha=self.remote_head_sha,
            base_sha=self.base_sha,
            local_commit_sha=self.local_commit_sha,
        )
        if self.publication_mode != mode:
            raise PilotExactTaskRemoteHeadObservationError(
                "publication mode does not match observed remote head"
            )
        started = _utc(self.observation_started_at_utc, name="observation_started_at_utc")
        completed = _utc(self.observation_completed_at_utc, name="observation_completed_at_utc")
        source_time = _utc(
            self.requirements.requirements_materialized_at_utc,
            name="requirements_materialized_at_utc",
        )
        if not source_time <= started <= completed:
            raise PilotExactTaskRemoteHeadObservationError(
                "remote-head observation timestamps are not monotonic"
            )
        required_true = (
            "network_access_performed",
            "remote_head_observed",
            "remote_head_stable_across_double_observation",
            "local_commit_state_matched",
            "exact_remote_repository_matched",
            "exact_destination_ref_matched",
            "fast_forward_candidate",
            "fresh_human_remote_publication_authorization_required",
            "fresh_remote_head_revalidation_before_push_required",
        )
        forced_false = (
            "credential_material_present",
            "human_remote_publication_authorization_verified",
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
            raise PilotExactTaskRemoteHeadObservationError(
                "required read-only remote observation evidence is not satisfied"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemoteHeadObservationError(
                "remote-head observation cannot grant publication authority"
            )
        if self.observation_key_sha256 != _observation_key(self):
            raise PilotExactTaskRemoteHeadObservationError("remote-head observation key mismatch")

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemoteHeadObservation":
        if not isinstance(value, Mapping) or set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemoteHeadObservationError("remote-head observation fields mismatch")
        data = dict(value)
        embedded = data.get("requirements")
        if not isinstance(embedded, Mapping):
            raise PilotExactTaskRemoteHeadObservationError("requirements must be an object")
        data["requirements"] = PilotExactTaskRemotePublicationRequirements.from_mapping(embedded)
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return {
            name: self.requirements.to_dict() if name == "requirements" else getattr(self, name)
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_remote_head_observation_inputs(self) is not None


def _observe_verified_pilot_exact_task_remote_head(
    *,
    requirements: PilotExactTaskRemotePublicationRequirements,
    now_provider=_now_utc_seconds,
) -> PilotExactTaskRemoteHeadObservation:
    exact, ref_update_receipt, inputs = _require_live_requirements(requirements)
    before = _fresh_local_state(exact, ref_update_receipt, inputs)
    started_at = now_provider()
    if _utc(started_at, name="observation_started_at_utc") < _utc(
        exact.requirements_materialized_at_utc,
        name="requirements_materialized_at_utc",
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "remote-head observation predates ADR-DC-049 requirements"
        )
    raw1, present1, sha1 = _observe_remote_head_once(exact, inputs)
    middle = _fresh_local_state(exact, ref_update_receipt, inputs)
    if middle != before or middle.sha256 != before.sha256:
        raise PilotExactTaskRemoteHeadObservationError(
            "local commit state changed during remote-head observation"
        )
    raw2, present2, sha2 = _observe_remote_head_once(exact, inputs)
    after = _fresh_local_state(exact, ref_update_receipt, inputs)
    if after != before or after.sha256 != before.sha256:
        raise PilotExactTaskRemoteHeadObservationError(
            "local commit state changed after remote-head observation"
        )
    first_digest = hashlib.sha256(raw1).hexdigest()
    second_digest = hashlib.sha256(raw2).hexdigest()
    if raw1 != raw2 or first_digest != second_digest or present1 != present2 or sha1 != sha2:
        raise PilotExactTaskRemoteHeadObservationError(
            "remote destination changed across the double observation"
        )
    mode = _publication_mode(
        present=present1,
        remote_head_sha=sha1,
        base_sha=exact.base_sha,
        local_commit_sha=exact.local_commit_sha,
    )
    completed_at = now_provider()
    if _utc(completed_at, name="observation_completed_at_utc") < _utc(
        started_at,
        name="observation_started_at_utc",
    ):
        raise PilotExactTaskRemoteHeadObservationError(
            "system clock moved backwards during remote-head observation"
        )
    values = dict(
        requirements=exact,
        requirements_sha256=exact.sha256,
        requirements_key_sha256=exact.requirements_key_sha256,
        ref_update_receipt_sha256=exact.ref_update_receipt_sha256,
        task_id=exact.task_id,
        repository=exact.repository,
        base_sha=exact.base_sha,
        local_commit_sha=exact.local_commit_sha,
        source_ref=exact.source_ref,
        destination_ref=exact.destination_ref,
        canonical_remote_url=exact.canonical_remote_url,
        remote_name=exact.remote_name,
        remote_provider=exact.remote_provider,
        first_remote_observation_sha256=first_digest,
        second_remote_observation_sha256=second_digest,
        remote_head_present=present1,
        remote_head_sha=sha1,
        publication_mode=mode,
        local_state_before_sha256=before.sha256,
        local_state_after_sha256=after.sha256,
        observation_started_at_utc=started_at,
        observation_completed_at_utc=completed_at,
        observation_key_sha256="f" * 64,
        transport=PILOT_EXACT_TASK_REMOTE_HEAD_TRANSPORT,
    )
    values["observation_key_sha256"] = _observation_key_from_mapping(values)
    observation = PilotExactTaskRemoteHeadObservation(**values)
    _mark_remote_head_observation_authenticated(observation, exact)
    if observation.observation_authenticated is not True:
        raise PilotExactTaskRemoteHeadObservationError(
            "live remote-head observation provenance was not established"
        )
    return observation


def observe_pilot_exact_task_remote_head(
    requirements: PilotExactTaskRemotePublicationRequirements,
) -> PilotExactTaskRemoteHeadObservation:
    """Observe one exact remote branch read-only using live ADR-DC-049 requirements."""
    return _observe_verified_pilot_exact_task_remote_head(
        requirements=requirements,
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_HEAD_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_HEAD_TRANSPORT",
    "PilotExactTaskRemoteHeadObservationError",
    "PilotExactTaskRemoteHeadObservation",
    "observe_pilot_exact_task_remote_head",
]

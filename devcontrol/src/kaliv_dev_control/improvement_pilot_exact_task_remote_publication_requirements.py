"""ADR-DC-049 inert requirements for later exact remote publication.

This boundary accepts only the exact live ADR-DC-048 local-commit ref-update
receipt, fresh-revalidates the attached local commit and current branch twice,
reads only the host-pinned ``origin`` push URL through TrustedGit, and freezes
the exact evidence and safety requirements that a later human-signed one-shot
remote-publication authorization must bind.

It performs no network operation, loads no credentials, pushes nothing, mutates
no PR, and grants no remote/publication authority.
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
from typing import Any, Mapping
from urllib.parse import urlsplit

from . import improvement_pilot_exact_task_local_commit_ref_update as ref_update_boundary
from .improvement_pilot_exact_task_local_commit_ref_update import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY,
    PilotExactTaskLocalCommitRefUpdateReceipt,
)
from . import improvement_pilot_exact_task_local_commit_object_write as object_write_boundary
from . import _improvement_pilot_exact_task_local_commit_object_write_impl as _object_write_impl
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-publication-requirements/v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY = (
    "dc-l16-exact-task-remote-publication-authorization-requirements-only"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCOPE = (
    "remote-publication-human-authorization-requirements-only-v1"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT = (
    "authorize-one-exact-fast-forward-github-branch-publication"
)
PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS = 10 * 60
PILOT_EXACT_TASK_REMOTE_NAME = "origin"
PILOT_EXACT_TASK_REMOTE_PROVIDER = "github"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOCAL_REF = re.compile(r"^refs/heads/[A-Za-z0-9][A-Za-z0-9._/-]{0,1000}$")

_KEY_FIELDS = (
    "ref_update_receipt_sha256",
    "object_write_receipt_sha256",
    "write_consumption_receipt_sha256",
    "local_commit_object_identity_sha256",
    "local_commit_plan_sha256",
    "development_task_sha256",
    "task_id",
    "repository",
    "base_sha",
    "root_tree_sha",
    "local_commit_sha",
    "commit_payload_sha256",
    "commit_subject_sha256",
    "local_commit_nonce_sha256",
    "local_ref",
    "post_ref_update_workspace_snapshot_sha256",
    "source_ref",
    "destination_ref",
    "push_refspec",
    "remote_name",
    "remote_provider",
    "remote_repository",
    "observed_push_url",
    "observed_push_url_sha256",
    "canonical_remote_url",
    "source_ref_sha",
    "source_ref_update_completed_at_utc",
    "requirements_materialized_at_utc",
    "authorization_intent",
    "authorization_max_window_seconds",
)


class PilotExactTaskRemotePublicationRequirementsError(ValueError):
    """Exact remote-publication requirements are malformed or unsafe."""


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
        raise PilotExactTaskRemotePublicationRequirementsError(
            "remote-publication requirements are not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemotePublicationRequirementsError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemotePublicationRequirementsError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _requirements_key_from_values(value: Any) -> str:
    payload = {name: getattr(value, name) for name in _KEY_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _validate_local_ref(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _LOCAL_REF.fullmatch(value) is None
        or value.endswith("/")
        or value.endswith(".")
        or value.endswith(".lock")
        or "//" in value
        or ".." in value
        or "@{" in value
        or any(char in value for char in ("\\", ":", "?", "*", "[", "~", "^"))
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            f"{name} is not one canonical local branch ref"
        )
    return value


def _require_live_ref_update(
    value: Any,
) -> tuple[
    PilotExactTaskLocalCommitRefUpdateReceipt,
    Any,
    Any,
    Mapping[str, Any],
]:
    if type(value) is not PilotExactTaskLocalCommitRefUpdateReceipt:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "exact ADR-DC-048 local-commit ref-update receipt is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitRefUpdateReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-048 ref-update receipt replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-048 ref-update receipt identity mismatch"
        )
    required_true = (
        "host_ref_update_guard_committed",
        "object_write_authenticated_at_ref_update",
        "exact_commit_object_verified",
        "current_local_branch_ref_verified",
        "compare_and_swap_ref_update_executed",
        "local_ref_updated",
        "local_commit_created",
    )
    forced_false = (
        "git_object_write_authorized",
        "local_ref_update_authorized",
        "local_commit_authorized",
        "remote_write_authorized",
        "push_authorized",
        "pr_mutation_authorized",
        "merge_authorized",
        "release_authorized",
        "deploy_authorized",
        "production_activation_authorized",
    )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_REF_UPDATE_AUTHORITY
        or value.ref_update_authenticated is not True
        or any(getattr(value, name) is not True for name in required_true)
        or any(getattr(value, name) is not False for name in forced_false)
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "remote-publication planning requires the exact live inert ADR-DC-048 receipt"
        )

    live = ref_update_boundary._get_live_local_commit_ref_update_inputs(value)
    if live is None:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-048 live ref-update provenance is unavailable"
        )
    object_write = live.get("object_write_receipt")
    if object_write is None or getattr(object_write, "object_write_authenticated", False) is not True:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-047 live object-write provenance is unavailable"
        )
    object_live = object_write_boundary._get_live_local_commit_object_write_inputs(
        object_write
    )
    if object_live is None:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-047 live object-write inputs are unavailable"
        )
    consumption = object_live.get("write_consumption_receipt")
    try:
        _exact_consumption, identity, inputs = _object_write_impl._require_live_consumption(
            consumption
        )
    except Exception as exc:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "exact live ADR-DC-042 identity binding is unavailable"
        ) from exc

    if (
        value.object_write_receipt_sha256 != object_write.sha256
        or value.local_commit_object_identity_sha256 != identity.sha256
        or value.local_commit_plan_sha256 != identity.local_commit_plan_sha256
        or value.development_task_sha256 != identity.development_task_sha256
        or value.task_id != identity.task_id
        or value.repository != identity.repository
        or value.base_sha != identity.base_sha
        or value.root_tree_sha != identity.root_tree_sha
        or value.predicted_commit_sha != identity.predicted_commit_sha
        or value.new_commit_sha != identity.predicted_commit_sha
        or value.commit_payload_sha256 != identity.commit_payload_sha256
        or value.commit_subject_sha256 != identity.commit_subject_sha256
        or value.local_commit_nonce_sha256 != object_write.local_commit_nonce_sha256
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "ADR-DC-048 receipt is not bound to the exact live local commit identity"
        )
    return value, object_write, identity, inputs


def _canonical_github_remote(push_url: str, *, repository: str) -> str:
    if (
        not isinstance(push_url, str)
        or not push_url
        or push_url.strip() != push_url
        or "\x00" in push_url
        or "\n" in push_url
        or "\r" in push_url
        or len(push_url.encode("utf-8")) > 2048
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "origin push URL is malformed"
        )

    remote_repository: str | None = None
    if push_url.startswith("git@github.com:"):
        path = push_url[len("git@github.com:") :]
        remote_repository = path[:-4] if path.endswith(".git") else path
    else:
        parsed = urlsplit(push_url)
        if parsed.scheme == "https":
            if (
                parsed.hostname != "github.com"
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in (None, 443)
                or parsed.query
                or parsed.fragment
            ):
                raise PilotExactTaskRemotePublicationRequirementsError(
                    "origin HTTPS push URL is not credential-free canonical GitHub"
                )
            path = parsed.path.lstrip("/")
            remote_repository = path[:-4] if path.endswith(".git") else path
        elif parsed.scheme == "ssh":
            if (
                parsed.hostname != "github.com"
                or parsed.username != "git"
                or parsed.password is not None
                or parsed.port not in (None, 22)
                or parsed.query
                or parsed.fragment
            ):
                raise PilotExactTaskRemotePublicationRequirementsError(
                    "origin SSH push URL is not canonical GitHub"
                )
            path = parsed.path.lstrip("/")
            remote_repository = path[:-4] if path.endswith(".git") else path

    if (
        remote_repository is None
        or _REPOSITORY.fullmatch(remote_repository) is None
        or remote_repository.casefold() != repository.casefold()
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "origin push URL does not identify the exact reviewed GitHub repository"
        )
    return f"https://github.com/{repository}.git"


def _fresh_local_publication_state(
    receipt: PilotExactTaskLocalCommitRefUpdateReceipt,
    inputs: Mapping[str, Any],
) -> tuple[GitWorkspaceSnapshot, str, str, str]:
    workspace = Path(inputs["workspace_root"])
    runner = inputs["git_runner"]
    try:
        snapshot = _GitWorkspaceEvidence(
            workspace,
            inputs["task"],
            runner,
        ).snapshot()
        raw_ref = runner.run(
            ("symbolic-ref", "-q", "HEAD"),
            cwd=workspace,
            maximum=2048,
            timeout_seconds=120,
        )
        local_ref = _validate_local_ref(
            raw_ref.decode("utf-8", errors="strict").strip(),
            name="current local ref",
        )
        runner.run(
            ("check-ref-format", local_ref),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        )
        raw_ref_sha = runner.run(
            ("rev-parse", "--verify", local_ref),
            cwd=workspace,
            maximum=128,
            timeout_seconds=120,
        )
        ref_sha = raw_ref_sha.decode("ascii", errors="strict").strip()
        raw_push_url = runner.run(
            ("remote", "get-url", "--push", PILOT_EXACT_TASK_REMOTE_NAME),
            cwd=workspace,
            maximum=4096,
            timeout_seconds=120,
        )
        push_url_text = raw_push_url.decode("utf-8", errors="strict")
    except Exception as exc:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "fresh local publication evidence collection failed"
        ) from exc

    _hex40(ref_sha, name="current local ref SHA")
    lines = push_url_text.splitlines()
    if len(lines) != 1:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "origin must resolve to exactly one push URL"
        )
    push_url = lines[0]
    canonical_remote_url = _canonical_github_remote(
        push_url,
        repository=receipt.repository,
    )

    if (
        snapshot.head_sha != receipt.new_commit_sha
        or ref_sha != receipt.new_commit_sha
        or local_ref != receipt.target_ref
        or snapshot.sha256 != receipt.post_ref_update_workspace_snapshot_sha256
        or snapshot.staged_patch_bytes != 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "local commit state no longer matches exact ADR-DC-048 evidence"
        )
    return snapshot, local_ref, push_url, canonical_remote_url


def _live_registry():
    records: dict[
        int,
        tuple[
            int,
            str,
            weakref.ReferenceType[Any],
            weakref.ReferenceType[Any],
        ],
    ] = {}

    def mark(
        requirements: Any,
        ref_update_receipt: PilotExactTaskLocalCommitRefUpdateReceipt,
    ) -> None:
        key = id(requirements)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            requirements.sha256,
            weakref.ref(requirements, cleanup),
            weakref.ref(ref_update_receipt),
        )

    def get(requirements: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(requirements))
        if entry is None:
            return None
        pid, digest, requirements_ref, ref_update_ref = entry
        ref_update_receipt = ref_update_ref()
        if (
            pid != os.getpid()
            or requirements_ref() is not requirements
            or ref_update_receipt is None
            or ref_update_receipt.ref_update_authenticated is not True
            or requirements.sha256 != digest
            or requirements.ref_update_receipt_sha256 != ref_update_receipt.sha256
        ):
            return None
        return MappingProxyType({"ref_update_receipt": ref_update_receipt})

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_publication_requirements_authenticated,
    _get_live_remote_publication_requirements_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemotePublicationRequirements:
    ref_update_receipt_sha256: str
    object_write_receipt_sha256: str
    write_consumption_receipt_sha256: str
    local_commit_object_identity_sha256: str
    local_commit_plan_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    root_tree_sha: str
    local_commit_sha: str
    commit_payload_sha256: str
    commit_subject_sha256: str
    local_commit_nonce_sha256: str
    local_ref: str
    post_ref_update_workspace_snapshot_sha256: str
    source_ref: str
    destination_ref: str
    push_refspec: str
    remote_name: str
    remote_provider: str
    remote_repository: str
    observed_push_url: str
    observed_push_url_sha256: str
    canonical_remote_url: str
    source_ref_sha: str
    source_ref_update_completed_at_utc: str
    requirements_materialized_at_utc: str
    authorization_intent: str
    authorization_max_window_seconds: int
    requirements_key_sha256: str
    source_ref_update_authenticated_at_materialization: bool = True
    fresh_local_commit_state_matched: bool = True
    remote_configuration_observed_locally: bool = True
    local_commit_created: bool = True
    network_access_performed: bool = False
    credential_material_present: bool = False
    fresh_human_remote_publication_authorization_required: bool = True
    one_shot_remote_publication_nonce_required: bool = True
    host_local_remote_authorization_replay_ledger_required: bool = True
    host_local_remote_execution_ledger_required: bool = True
    fresh_local_commit_revalidation_before_authorization_required: bool = True
    fresh_remote_head_observation_before_authorization_required: bool = True
    fresh_remote_head_revalidation_before_push_required: bool = True
    exact_source_commit_required: bool = True
    exact_destination_ref_required: bool = True
    fast_forward_only_required: bool = True
    force_push_forbidden: bool = True
    remote_delete_forbidden: bool = True
    tag_publication_forbidden: bool = True
    pr_mutation_separate_authority_required: bool = True
    manual_operator_invocation_required: bool = True
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    requirements_scope: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCHEMA:
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements schema is unsupported"
            )
        if (
            self.requirements_scope
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCOPE
            or self.authority
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements scope/authority is unsupported"
            )
        for name in (
            "ref_update_receipt_sha256",
            "object_write_receipt_sha256",
            "write_consumption_receipt_sha256",
            "local_commit_object_identity_sha256",
            "local_commit_plan_sha256",
            "development_task_sha256",
            "commit_payload_sha256",
            "commit_subject_sha256",
            "local_commit_nonce_sha256",
            "post_ref_update_workspace_snapshot_sha256",
            "observed_push_url_sha256",
            "requirements_key_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in (
            "base_sha",
            "root_tree_sha",
            "local_commit_sha",
            "source_ref_sha",
        ):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskRemotePublicationRequirementsError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "repository is invalid"
            )
        _validate_local_ref(self.local_ref, name="local_ref")
        _validate_local_ref(self.source_ref, name="source_ref")
        _validate_local_ref(self.destination_ref, name="destination_ref")
        if (
            self.local_ref != self.source_ref
            or self.local_ref != self.destination_ref
            or self.source_ref_sha != self.local_commit_sha
            or self.push_refspec != f"{self.local_commit_sha}:{self.destination_ref}"
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "exact remote-publication refspec binding mismatch"
            )
        if (
            self.remote_name != PILOT_EXACT_TASK_REMOTE_NAME
            or self.remote_provider != PILOT_EXACT_TASK_REMOTE_PROVIDER
            or self.remote_repository != self.repository
            or self.canonical_remote_url
            != f"https://github.com/{self.repository}.git"
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote publication target is not the exact host-pinned GitHub repository"
            )
        if (
            hashlib.sha256(self.observed_push_url.encode("utf-8")).hexdigest()
            != self.observed_push_url_sha256
            or _canonical_github_remote(
                self.observed_push_url,
                repository=self.repository,
            )
            != self.canonical_remote_url
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "observed origin push URL audit binding mismatch"
            )
        source_completed = _utc(
            self.source_ref_update_completed_at_utc,
            name="source_ref_update_completed_at_utc",
        )
        materialized = _utc(
            self.requirements_materialized_at_utc,
            name="requirements_materialized_at_utc",
        )
        if materialized < source_completed:
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements predate the local commit"
            )
        if (
            self.authorization_intent != PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT
            or self.authorization_max_window_seconds
            != PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS
        ):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication authorization policy mismatch"
            )

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
        required_false = (
            "network_access_performed",
            "credential_material_present",
            "integration_ready",
            "product_pilot_started",
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "required remote-publication safety invariant is not satisfied"
            )
        if any(getattr(self, name) is not False for name in required_false):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "requirements cannot grant network/publication authority"
            )
        if self.requirements_key_sha256 != _requirements_key_from_values(self):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements key mismatch"
            )

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemotePublicationRequirements":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements must be an object"
            )
        if set(value) != set(cls.__dataclass_fields__):
            raise PilotExactTaskRemotePublicationRequirementsError(
                "remote-publication requirements fields mismatch"
            )
        return cls(**dict(value))

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def requirements_authenticated(self) -> bool:
        return _get_live_remote_publication_requirements_inputs(self) is not None


def _build_verified_pilot_exact_task_remote_publication_requirements(
    *,
    ref_update_receipt: PilotExactTaskLocalCommitRefUpdateReceipt,
    now_provider=_now_utc_seconds,
) -> PilotExactTaskRemotePublicationRequirements:
    receipt, object_write, identity, inputs = _require_live_ref_update(
        ref_update_receipt
    )
    (
        first_snapshot,
        first_local_ref,
        first_push_url,
        first_canonical_remote,
    ) = _fresh_local_publication_state(receipt, inputs)

    materialized_at = now_provider()
    if _utc(materialized_at, name="requirements_materialized_at_utc") < _utc(
        receipt.ref_update_completed_at_utc,
        name="ref_update_completed_at_utc",
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "remote-publication requirements clock moved backwards"
        )

    push_refspec = f"{receipt.new_commit_sha}:{receipt.target_ref}"
    values = dict(
        ref_update_receipt_sha256=receipt.sha256,
        object_write_receipt_sha256=receipt.object_write_receipt_sha256,
        write_consumption_receipt_sha256=receipt.write_consumption_receipt_sha256,
        local_commit_object_identity_sha256=receipt.local_commit_object_identity_sha256,
        local_commit_plan_sha256=receipt.local_commit_plan_sha256,
        development_task_sha256=receipt.development_task_sha256,
        task_id=receipt.task_id,
        repository=receipt.repository,
        base_sha=receipt.base_sha,
        root_tree_sha=receipt.root_tree_sha,
        local_commit_sha=receipt.new_commit_sha,
        commit_payload_sha256=receipt.commit_payload_sha256,
        commit_subject_sha256=receipt.commit_subject_sha256,
        local_commit_nonce_sha256=receipt.local_commit_nonce_sha256,
        local_ref=receipt.target_ref,
        post_ref_update_workspace_snapshot_sha256=receipt.post_ref_update_workspace_snapshot_sha256,
        source_ref=receipt.target_ref,
        destination_ref=receipt.target_ref,
        push_refspec=push_refspec,
        remote_name=PILOT_EXACT_TASK_REMOTE_NAME,
        remote_provider=PILOT_EXACT_TASK_REMOTE_PROVIDER,
        remote_repository=receipt.repository,
        observed_push_url=first_push_url,
        observed_push_url_sha256=hashlib.sha256(
            first_push_url.encode("utf-8")
        ).hexdigest(),
        canonical_remote_url=first_canonical_remote,
        source_ref_sha=receipt.new_commit_sha,
        source_ref_update_completed_at_utc=receipt.ref_update_completed_at_utc,
        requirements_materialized_at_utc=materialized_at,
        authorization_intent=PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT,
        authorization_max_window_seconds=PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS,
    )
    provisional = type("_RequirementsKeyValues", (), values)()
    requirements = PilotExactTaskRemotePublicationRequirements(
        **values,
        requirements_key_sha256=_requirements_key_from_values(provisional),
    )

    (
        second_snapshot,
        second_local_ref,
        second_push_url,
        second_canonical_remote,
    ) = _fresh_local_publication_state(receipt, inputs)
    if (
        second_snapshot != first_snapshot
        or second_snapshot.sha256 != first_snapshot.sha256
        or second_local_ref != first_local_ref
        or second_push_url != first_push_url
        or second_canonical_remote != first_canonical_remote
    ):
        raise PilotExactTaskRemotePublicationRequirementsError(
            "local commit or remote configuration changed while requirements were materialized"
        )

    _mark_remote_publication_requirements_authenticated(
        requirements,
        receipt,
    )
    if requirements.requirements_authenticated is not True:
        raise PilotExactTaskRemotePublicationRequirementsError(
            "live remote-publication requirements provenance was not established"
        )
    return requirements


def build_pilot_exact_task_remote_publication_requirements(
    ref_update_receipt: PilotExactTaskLocalCommitRefUpdateReceipt,
) -> PilotExactTaskRemotePublicationRequirements:
    """Build inert remote-publication authorization requirements from ADR-DC-048."""
    return _build_verified_pilot_exact_task_remote_publication_requirements(
        ref_update_receipt=ref_update_receipt,
    )


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_REQUIREMENTS_SCOPE",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_INTENT",
    "PILOT_EXACT_TASK_REMOTE_PUBLICATION_MAX_WINDOW_SECONDS",
    "PilotExactTaskRemotePublicationRequirementsError",
    "PilotExactTaskRemotePublicationRequirements",
    "build_pilot_exact_task_remote_publication_requirements",
]

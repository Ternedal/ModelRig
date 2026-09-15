"""ADR-DC-042 exact local commit object identity materialization.

This boundary accepts only the exact live ADR-DC-041 local-commit candidate plan,
fresh-rechecks the frozen staged candidate, reads the Git index through the
existing TrustedGitRunner, and reconstructs the exact SHA-1 root tree and commit
object identities in memory.

It does not write Git objects, create a commit, move a local ref, publish
remotely, or grant any write/publication authority.
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

from .contract import DevelopmentTask, normalize_repo_path
from . import improvement_pilot_exact_task_local_commit_plan as commit_plan_boundary
from .improvement_pilot_exact_task_local_commit_plan import (
    PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY,
    PilotExactTaskLocalCommitPlan,
)
from .tier_a_command_receipt import GitWorkspaceSnapshot, _GitWorkspaceEvidence

PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-local-commit-object-identity/v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY = (
    "host-materialized-one-dc-l16-exact-local-commit-object-identity-only"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCOPE = (
    "local-commit-object-identity-only-v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT = "sha1"
PILOT_EXACT_TASK_LOCAL_COMMIT_IDENTITY_POLICY = (
    "reviewed-development-control-identity-v1"
)
PILOT_EXACT_TASK_LOCAL_COMMIT_TIME_POLICY = "materialization-time-utc-v1"
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME = "ModelRig Development Control"
PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL = "devcontrol@modelrig.local"
PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE = "+0000"

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_MAX_INDEX_BYTES = 64 * 1024 * 1024
_MAX_INDEX_ENTRIES = 1_000_000
_ALLOWED_INDEX_MODES = {"100644", "100755", "120000", "160000"}


class PilotExactTaskLocalCommitObjectIdentityError(ValueError):
    """The exact local commit object identity cannot be materialized safely."""


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
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "local commit object identity is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _development_task_sha256(task: DevelopmentTask) -> str:
    return hashlib.sha256(task.canonical_json().encode("utf-8")).hexdigest()


def _require_live_local_commit_plan(
    value: Any,
) -> tuple[PilotExactTaskLocalCommitPlan, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskLocalCommitPlan:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "exact ADR-DC-041 local commit plan is required"
        )
    try:
        replayed = PilotExactTaskLocalCommitPlan.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "ADR-DC-041 local commit plan replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "ADR-DC-041 local commit plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.post_execution_evaluation_authenticated is not True
        or value.mechanical_evaluation_passed is not True
        or value.fresh_workspace_snapshot_matched is not True
        or value.candidate_patch_bound is not True
        or value.commit_plan_materialized is not True
        or value.git_object_write_authorized is not False
        or value.local_ref_update_authorized is not False
        or value.local_commit_authorized is not False
        or value.local_commit_created is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "object identity requires one live inert ADR-DC-041 plan"
        )

    inputs = commit_plan_boundary._get_live_local_commit_plan_inputs(value)
    if inputs is None:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "ADR-DC-041 live plan inputs are unavailable"
        )
    task = inputs.get("task")
    evaluation = inputs.get("post_execution_evaluation")
    if (
        type(task) is not DevelopmentTask
        or evaluation is None
        or _development_task_sha256(task) != value.development_task_sha256
        or getattr(evaluation, "sha256", None)
        != value.post_execution_evaluation_sha256
        or task.task_id != value.task_id
        or task.repository != value.repository
        or task.base_sha != value.base_sha
        or getattr(evaluation, "candidate_patch_sha256", None)
        != value.candidate_patch_sha256
        or getattr(evaluation, "candidate_patch_bytes", None)
        != value.candidate_patch_bytes
        or getattr(evaluation, "candidate_numstat_sha256", None)
        != value.candidate_numstat_sha256
        or getattr(evaluation, "scope_policy_sha256", None)
        != value.scope_policy_sha256
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "ADR-DC-041 plan is not bound to its exact live task/evaluation"
        )
    return value, inputs


def _fresh_workspace_snapshot(inputs: Mapping[str, Any]) -> GitWorkspaceSnapshot:
    try:
        evidence = _GitWorkspaceEvidence(
            Path(inputs["workspace_root"]),
            inputs["task"],
            inputs["git_runner"],
        )
        return evidence.snapshot()
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "fresh commit-object-identity Trusted-Git snapshot failed"
        ) from exc


def _require_snapshot_matches_plan(
    plan: PilotExactTaskLocalCommitPlan,
    snapshot: GitWorkspaceSnapshot,
) -> None:
    if (
        snapshot != plan.post_execution_workspace_snapshot
        or snapshot.sha256 != plan.post_execution_workspace_snapshot_sha256
        or snapshot.head_sha != plan.base_sha
        or snapshot.staged_patch_sha256 != plan.candidate_patch_sha256
        or snapshot.staged_patch_bytes != plan.candidate_patch_bytes
        or snapshot.staged_patch_bytes <= 0
        or snapshot.unstaged_patch_bytes != 0
        or snapshot.untracked_path_count != 0
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "fresh workspace no longer matches ADR-DC-041 candidate plan"
        )


def _read_object_format(inputs: Mapping[str, Any]) -> str:
    try:
        raw = inputs["git_runner"].run(
            ("rev-parse", "--show-object-format"),
            cwd=Path(inputs["workspace_root"]),
            maximum=128,
            timeout_seconds=120,
        )
        value = raw.decode("ascii", errors="strict").strip()
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git object format collection failed"
        ) from exc
    if value != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "only SHA-1 Git object repositories are supported by ADR-DC-042"
        )
    return value


def _read_index_manifest(inputs: Mapping[str, Any]) -> bytes:
    try:
        payload = inputs["git_runner"].run(
            ("ls-files", "--stage", "-z", "--"),
            cwd=Path(inputs["workspace_root"]),
            maximum=_MAX_INDEX_BYTES,
            timeout_seconds=120,
        )
    except Exception as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git index manifest collection failed"
        ) from exc
    if not isinstance(payload, bytes) or len(payload) > _MAX_INDEX_BYTES:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git index manifest is invalid or oversized"
        )
    return payload


def _parse_index_manifest(
    payload: bytes,
) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(payload, bytes):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git index manifest must be bytes"
        )
    if not payload:
        return ()
    if not payload.endswith(b"\0"):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git index manifest is not NUL-terminated"
        )
    raw_records = payload[:-1].split(b"\0")
    if len(raw_records) > _MAX_INDEX_ENTRIES:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "Git index manifest contains too many entries"
        )
    entries: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for record in raw_records:
        if not record or b"\t" not in record:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index entry is malformed"
            )
        metadata, path_raw = record.split(b"\t", 1)
        parts = metadata.split(b" ")
        if len(parts) != 3:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index metadata is malformed"
            )
        mode_raw, object_raw, stage_raw = parts
        try:
            mode = mode_raw.decode("ascii", errors="strict")
            object_sha = object_raw.decode("ascii", errors="strict")
            stage = stage_raw.decode("ascii", errors="strict")
            path = path_raw.decode("utf-8", errors="strict")
        except UnicodeError as exc:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index entry text is not canonical"
            ) from exc
        if mode not in _ALLOWED_INDEX_MODES:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index mode is unsupported"
            )
        _hex40(object_sha, name="Git index object SHA")
        if stage != "0":
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index contains unresolved staged conflict entries"
            )
        if (
            not path
            or path.strip() != path
            or any(ord(char) < 32 or ord(char) == 127 for char in path)
            or normalize_repo_path(path, name="Git index path") != path
            or path in seen
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index path is non-canonical or duplicated"
            )
        seen.add(path)
        entries.append((mode, object_sha, path))

    paths = sorted(seen)
    for path in paths:
        prefix = path + "/"
        if any(other.startswith(prefix) for other in paths):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index contains file/directory path collision"
            )
    return tuple(entries)


def _git_sha1(kind: str, payload: bytes) -> str:
    if kind not in {"tree", "commit"}:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "unsupported in-memory Git object kind"
        )
    header = f"{kind} {len(payload)}\0".encode("ascii")
    return hashlib.sha1(header + payload).hexdigest()


def _root_tree_sha(entries: tuple[tuple[str, str, str], ...]) -> str:
    root: dict[str, Any] = {}
    for mode, object_sha, path in entries:
        parts = path.split("/")
        node = root
        for component in parts[:-1]:
            existing = node.get(component)
            if existing is None:
                child: dict[str, Any] = {}
                node[component] = child
                node = child
            elif isinstance(existing, dict):
                node = existing
            else:
                raise PilotExactTaskLocalCommitObjectIdentityError(
                    "Git index tree contains path collision"
                )
        leaf = parts[-1]
        if leaf in node:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "Git index tree contains duplicate leaf"
            )
        node[leaf] = (mode, object_sha)

    def materialize(node: dict[str, Any]) -> str:
        records: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            name_raw = name.encode("utf-8")
            if isinstance(value, dict):
                object_sha = materialize(value)
                mode_raw = b"40000"
                sort_key = name_raw + b"/"
            else:
                mode, object_sha = value
                mode_raw = mode.encode("ascii")
                sort_key = name_raw
            record = (
                mode_raw
                + b" "
                + name_raw
                + b"\0"
                + bytes.fromhex(object_sha)
            )
            records.append((sort_key, record))
        payload = b"".join(
            record for _, record in sorted(records, key=lambda item: item[0])
        )
        return _git_sha1("tree", payload)

    return materialize(root)


def _commit_epoch(materialized_at_utc: str) -> int:
    instant = _utc(materialized_at_utc, name="materialized_at_utc")
    epoch = int(instant.timestamp())
    if epoch <= 0:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "commit identity epoch is invalid"
        )
    return epoch


def _commit_payload(
    *,
    tree_sha: str,
    parent_sha: str,
    subject: str,
    epoch_seconds: int,
) -> bytes:
    _hex40(tree_sha, name="root_tree_sha")
    _hex40(parent_sha, name="base_sha")
    if (
        not isinstance(subject, str)
        or not subject
        or subject.strip() != subject
        or "\n" in subject
        or "\r" in subject
        or "\x00" in subject
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "commit subject is invalid"
        )
    if (
        isinstance(epoch_seconds, bool)
        or not isinstance(epoch_seconds, int)
        or epoch_seconds <= 0
    ):
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "commit epoch is invalid"
        )
    identity = (
        f"{PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME} "
        f"<{PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL}> "
        f"{epoch_seconds} {PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE}"
    )
    text = (
        f"tree {tree_sha}\n"
        f"parent {parent_sha}\n"
        f"author {identity}\n"
        f"committer {identity}\n"
        "\n"
        f"{subject}\n"
    )
    return text.encode("utf-8")


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

    def mark(identity: Any, plan: PilotExactTaskLocalCommitPlan) -> None:
        key = id(identity)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            identity.sha256,
            weakref.ref(identity, cleanup),
            weakref.ref(plan),
        )

    def get(identity: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(identity))
        if entry is None:
            return None
        pid, digest, identity_ref, plan_ref = entry
        plan = plan_ref()
        if (
            pid != os.getpid()
            or identity_ref() is not identity
            or plan is None
            or plan.plan_authenticated is not True
            or identity.sha256 != digest
            or identity.local_commit_plan_sha256 != plan.sha256
        ):
            return None
        inputs = commit_plan_boundary._get_live_local_commit_plan_inputs(plan)
        if inputs is None:
            return None
        result = dict(inputs)
        result["local_commit_plan"] = plan
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_local_commit_object_identity_authenticated,
    _get_live_local_commit_object_identity_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskLocalCommitObjectIdentity:
    local_commit_plan_sha256: str
    post_execution_evaluation_sha256: str
    execution_transaction_sha256: str
    tier_a_receipt_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    task_id: str
    repository: str
    base_sha: str
    fixed_command_plan_sha256: str
    post_execution_workspace_snapshot_sha256: str
    candidate_patch_sha256: str
    candidate_patch_bytes: int
    candidate_numstat_sha256: str
    scope_policy_sha256: str
    changed_paths: tuple[str, ...]
    changed_file_count: int
    commit_operation: str
    commit_message_policy: str
    commit_subject: str
    commit_subject_sha256: str
    planned_at_utc: str
    materialized_at_utc: str
    object_format: str
    index_manifest_sha256: str
    index_entry_count: int
    root_tree_sha: str
    commit_identity_policy: str
    commit_time_policy: str
    author_name: str
    author_email: str
    committer_name: str
    committer_email: str
    commit_epoch_seconds: int
    commit_timezone: str
    commit_payload_sha256: str
    predicted_commit_sha: str
    local_commit_plan_authenticated: bool = True
    fresh_workspace_snapshot_matched: bool = True
    index_manifest_bound: bool = True
    root_tree_identity_materialized: bool = True
    commit_object_identity_materialized: bool = True
    git_object_write_authorized: bool = False
    local_ref_update_authorized: bool = False
    local_commit_authorized: bool = False
    local_commit_created: bool = False
    integration_ready: bool = False
    product_pilot_started: bool = False
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    identity_scope: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCOPE
    authority: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY
    schema: str = PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCHEMA:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity schema is unsupported"
            )
        if self.identity_scope != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCOPE:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity scope is unsupported"
            )
        for name in (
            "local_commit_plan_sha256",
            "post_execution_evaluation_sha256",
            "execution_transaction_sha256",
            "tier_a_receipt_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "fixed_command_plan_sha256",
            "post_execution_workspace_snapshot_sha256",
            "candidate_patch_sha256",
            "candidate_numstat_sha256",
            "scope_policy_sha256",
            "commit_subject_sha256",
            "index_manifest_sha256",
            "commit_payload_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("base_sha", "root_tree_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if (
            not isinstance(self.task_id, str)
            or _TASK_ID.fullmatch(self.task_id) is None
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError("task_id is invalid")
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError("repository is invalid")
        if (
            isinstance(self.candidate_patch_bytes, bool)
            or not isinstance(self.candidate_patch_bytes, int)
            or not 1 <= self.candidate_patch_bytes <= 32 * 1024 * 1024
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "candidate_patch_bytes is invalid"
            )
        if (
            not isinstance(self.changed_paths, tuple)
            or not self.changed_paths
            or len(self.changed_paths) != self.changed_file_count
            or len(set(self.changed_paths)) != len(self.changed_paths)
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "changed_paths is invalid"
            )
        for index, path in enumerate(self.changed_paths):
            if normalize_repo_path(path, name=f"changed_paths[{index}]") != path:
                raise PilotExactTaskLocalCommitObjectIdentityError(
                    "changed_paths are not canonical"
                )
        if (
            isinstance(self.changed_file_count, bool)
            or not isinstance(self.changed_file_count, int)
            or not 1 <= self.changed_file_count <= 200
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "changed_file_count is invalid"
            )
        if (
            self.object_format != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT
            or self.commit_identity_policy
            != PILOT_EXACT_TASK_LOCAL_COMMIT_IDENTITY_POLICY
            or self.commit_time_policy
            != PILOT_EXACT_TASK_LOCAL_COMMIT_TIME_POLICY
            or self.author_name != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME
            or self.author_email != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL
            or self.committer_name != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME
            or self.committer_email != PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL
            or self.commit_timezone != PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity policy is unsupported"
            )
        if (
            isinstance(self.index_entry_count, bool)
            or not isinstance(self.index_entry_count, int)
            or not 0 <= self.index_entry_count <= _MAX_INDEX_ENTRIES
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "index_entry_count is invalid"
            )
        planned = _utc(self.planned_at_utc, name="planned_at_utc")
        materialized = _utc(self.materialized_at_utc, name="materialized_at_utc")
        if materialized < planned:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "object identity timestamp precedes ADR-DC-041 plan"
            )
        if self.commit_epoch_seconds != _commit_epoch(self.materialized_at_utc):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "commit epoch does not match materialization time"
            )
        if (
            not isinstance(self.commit_operation, str)
            or not self.commit_operation
            or not isinstance(self.commit_message_policy, str)
            or not self.commit_message_policy
            or not isinstance(self.commit_subject, str)
            or not self.commit_subject
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "commit plan identity fields are invalid"
            )
        if (
            hashlib.sha256(self.commit_subject.encode("utf-8")).hexdigest()
            != self.commit_subject_sha256
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "commit subject digest mismatch"
            )
        payload = _commit_payload(
            tree_sha=self.root_tree_sha,
            parent_sha=self.base_sha,
            subject=self.commit_subject,
            epoch_seconds=self.commit_epoch_seconds,
        )
        if (
            hashlib.sha256(payload).hexdigest() != self.commit_payload_sha256
            or _git_sha1("commit", payload) != self.predicted_commit_sha
        ):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "predicted commit object identity is inconsistent"
            )

        required_true = (
            "local_commit_plan_authenticated",
            "fresh_workspace_snapshot_matched",
            "index_manifest_bound",
            "root_tree_identity_materialized",
            "commit_object_identity_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity evidence is incomplete"
            )
        forced_false = (
            "git_object_write_authorized",
            "local_ref_update_authorized",
            "local_commit_authorized",
            "local_commit_created",
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
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "object identity cannot grant write/publication authority"
            )
        if self.authority != PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity authority is unsupported"
            )

    @property
    def identity_authenticated(self) -> bool:
        return _get_live_local_commit_object_identity_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for name in self.__dataclass_fields__:  # type: ignore[attr-defined]
            value = getattr(self, name)
            result[name] = list(value) if name == "changed_paths" else value
        return result

    @classmethod
    def from_mapping(
        cls,
        value: Any,
    ) -> "PilotExactTaskLocalCommitObjectIdentity":
        if not isinstance(value, Mapping):
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity fields mismatch"
            )
        data = dict(value)
        try:
            data["changed_paths"] = tuple(data["changed_paths"])
        except Exception as exc:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity nested evidence is invalid"
            ) from exc
        return cls(**data)

    @classmethod
    def from_json(
        cls,
        text: str,
    ) -> "PilotExactTaskLocalCommitObjectIdentity":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskLocalCommitObjectIdentityError(
                "local commit object identity JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_local_commit_object_identity(
    *,
    local_commit_plan: PilotExactTaskLocalCommitPlan,
    now_provider,
) -> PilotExactTaskLocalCommitObjectIdentity:
    plan, inputs = _require_live_local_commit_plan(local_commit_plan)

    first = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_plan(plan, first)

    object_format = _read_object_format(inputs)
    index_payload = _read_index_manifest(inputs)
    index_entries = _parse_index_manifest(index_payload)
    tree_sha = _root_tree_sha(index_entries)

    materialized_at = now_provider()
    planned_time = _utc(plan.planned_at_utc, name="planned_at_utc")
    materialized_time = _utc(materialized_at, name="materialized_at_utc")
    if materialized_time < planned_time:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "system clock moved backwards after ADR-DC-041 planning"
        )
    epoch = _commit_epoch(materialized_at)
    commit_payload = _commit_payload(
        tree_sha=tree_sha,
        parent_sha=plan.base_sha,
        subject=plan.commit_subject,
        epoch_seconds=epoch,
    )

    second = _fresh_workspace_snapshot(inputs)
    _require_snapshot_matches_plan(plan, second)
    if second != first or second.sha256 != first.sha256:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "workspace changed while commit object identity was materialized"
        )

    identity = PilotExactTaskLocalCommitObjectIdentity(
        local_commit_plan_sha256=plan.sha256,
        post_execution_evaluation_sha256=plan.post_execution_evaluation_sha256,
        execution_transaction_sha256=plan.execution_transaction_sha256,
        tier_a_receipt_sha256=plan.tier_a_receipt_sha256,
        execution_nonce_sha256=plan.execution_nonce_sha256,
        development_task_sha256=plan.development_task_sha256,
        task_id=plan.task_id,
        repository=plan.repository,
        base_sha=plan.base_sha,
        fixed_command_plan_sha256=plan.fixed_command_plan_sha256,
        post_execution_workspace_snapshot_sha256=(
            plan.post_execution_workspace_snapshot_sha256
        ),
        candidate_patch_sha256=plan.candidate_patch_sha256,
        candidate_patch_bytes=plan.candidate_patch_bytes,
        candidate_numstat_sha256=plan.candidate_numstat_sha256,
        scope_policy_sha256=plan.scope_policy_sha256,
        changed_paths=plan.changed_paths,
        changed_file_count=plan.changed_file_count,
        commit_operation=plan.commit_operation,
        commit_message_policy=plan.commit_message_policy,
        commit_subject=plan.commit_subject,
        commit_subject_sha256=plan.commit_subject_sha256,
        planned_at_utc=plan.planned_at_utc,
        materialized_at_utc=materialized_at,
        object_format=object_format,
        index_manifest_sha256=hashlib.sha256(index_payload).hexdigest(),
        index_entry_count=len(index_entries),
        root_tree_sha=tree_sha,
        commit_identity_policy=PILOT_EXACT_TASK_LOCAL_COMMIT_IDENTITY_POLICY,
        commit_time_policy=PILOT_EXACT_TASK_LOCAL_COMMIT_TIME_POLICY,
        author_name=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME,
        author_email=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL,
        committer_name=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME,
        committer_email=PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL,
        commit_epoch_seconds=epoch,
        commit_timezone=PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE,
        commit_payload_sha256=hashlib.sha256(commit_payload).hexdigest(),
        predicted_commit_sha=_git_sha1("commit", commit_payload),
    )

    _mark_local_commit_object_identity_authenticated(identity, plan)
    if identity.identity_authenticated is not True:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "local commit object identity lost live provenance"
        )
    return identity


def materialize_pilot_exact_task_local_commit_object_identity(
    local_commit_plan: PilotExactTaskLocalCommitPlan,
) -> PilotExactTaskLocalCommitObjectIdentity:
    """Host-pinned ADR-DC-042 read-only object-identity entrypoint."""
    try:
        return _materialize_verified_pilot_exact_task_local_commit_object_identity(
            local_commit_plan=local_commit_plan,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskLocalCommitObjectIdentityError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskLocalCommitObjectIdentityError(
            "host-controlled local commit object identity failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCHEMA",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_AUTHORITY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_IDENTITY_SCOPE",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_OBJECT_FORMAT",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_IDENTITY_POLICY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_TIME_POLICY",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_NAME",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_AUTHOR_EMAIL",
    "PILOT_EXACT_TASK_LOCAL_COMMIT_TIMEZONE",
    "PilotExactTaskLocalCommitObjectIdentityError",
    "PilotExactTaskLocalCommitObjectIdentity",
    "materialize_pilot_exact_task_local_commit_object_identity",
]

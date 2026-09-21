"""ADR-DC-064 deterministic exact release intent plan.

This boundary accepts only one fresh live ADR-DC-063 release-readiness
evaluation with ``release_ready=True`` and one host-admin-pinned canonical
release-plan config. It freezes a content-addressed release version, tag,
GitHub Release name/body and conservative draft/prerelease intent around the
exact attested squash merge commit.

No tag, GitHub Release, deployment or other remote mutation is performed and
no release authority is granted.
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
)
from . import improvement_pilot_exact_task_pr_lifecycle_authorization as lifecycle_auth_boundary
from . import improvement_pilot_exact_task_release_readiness_evaluation as readiness_boundary
from .improvement_pilot_exact_task_release_readiness_evaluation import (
    PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY,
    PilotExactTaskReleaseReadinessEvaluationReceipt,
)

PILOT_EXACT_TASK_RELEASE_PLAN_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-plan-receipt/v1"
)
PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY = (
    "host-planned-one-dc-l16-exact-release-intent-only"
)
PILOT_EXACT_TASK_RELEASE_PLAN_SCOPE = (
    "deterministic-exact-release-intent-only-v1"
)
PILOT_EXACT_TASK_RELEASE_PLAN_CONFIG_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-release-plan-config/v1"
)

_MAX_FILE_BYTES = 1024 * 1024
_MAX_RELEASE_BODY_BYTES = 16 * 1024
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_TAG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")

_VERSION_SCHEME = "merge-sha40-v1"
_VERSION_PREFIX = "rsi-"
_TAG_PREFIX = "modelrig-rsi-"
_RELEASE_NAME_PREFIX = "ModelRig RSI "
_RELEASE_DRAFT = True
_RELEASE_PRERELEASE = True
_MAKE_LATEST = False

_POSIX_CONFIG = Path(
    "/etc/modelrig/devcontrol/authority/"
    "rsi-pilot-exact-task-release-plan-config-v1.json"
)
_WINDOWS_CONFIG = Path(
    r"C:\Program Files\ModelRig\DevControl\authority"
) / "rsi-pilot-exact-task-release-plan-config-v1.json"


class PilotExactTaskReleasePlanError(ValueError):
    """Release readiness/config or deterministic release intent is unsafe."""


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
        raise PilotExactTaskReleasePlanError(
            "release-plan evidence is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskReleasePlanError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskReleasePlanError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskReleasePlanError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskReleasePlanError(f"{name} is invalid") from exc


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskReleasePlanError(f"{name} is invalid")
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


@dataclass(frozen=True, slots=True)
class PilotExactTaskReleasePlanConfig:
    repository: str
    repository_id: str
    version_scheme: str = _VERSION_SCHEME
    version_prefix: str = _VERSION_PREFIX
    tag_prefix: str = _TAG_PREFIX
    release_name_prefix: str = _RELEASE_NAME_PREFIX
    release_draft: bool = _RELEASE_DRAFT
    release_prerelease: bool = _RELEASE_PRERELEASE
    make_latest: bool = _MAKE_LATEST
    schema: str = PILOT_EXACT_TASK_RELEASE_PLAN_CONFIG_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_RELEASE_PLAN_CONFIG_SCHEMA:
            raise PilotExactTaskReleasePlanError(
                "release-plan config schema is unsupported"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan repository identity is invalid"
            )
        if (
            self.version_scheme != _VERSION_SCHEME
            or self.version_prefix != _VERSION_PREFIX
            or self.tag_prefix != _TAG_PREFIX
            or self.release_name_prefix != _RELEASE_NAME_PREFIX
            or self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan config weakens fixed conservative intent"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "repository_id": self.repository_id,
            "version_scheme": self.version_scheme,
            "version_prefix": self.version_prefix,
            "tag_prefix": self.tag_prefix,
            "release_name_prefix": self.release_name_prefix,
            "release_draft": self.release_draft,
            "release_prerelease": self.release_prerelease,
            "make_latest": self.make_latest,
            "schema": self.schema,
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskReleasePlanConfig":
        expected = {
            "repository",
            "repository_id",
            "version_scheme",
            "version_prefix",
            "tag_prefix",
            "release_name_prefix",
            "release_draft",
            "release_prerelease",
            "make_latest",
            "schema",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise PilotExactTaskReleasePlanError(
                "release-plan config fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _parse_config(payload: bytes) -> PilotExactTaskReleasePlanConfig:
    if (
        not isinstance(payload, bytes)
        or not payload
        or len(payload) > _MAX_FILE_BYTES
    ):
        raise PilotExactTaskReleasePlanError(
            "release-plan config payload is invalid"
        )
    try:
        raw = json.loads(payload.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskReleasePlanError(
            "release-plan config JSON is invalid"
        ) from exc
    config = PilotExactTaskReleasePlanConfig.from_mapping(raw)
    if config.canonical_json().encode("utf-8") != payload:
        raise PilotExactTaskReleasePlanError(
            "release-plan config is not canonical JSON"
        )
    return config


def _read_host_config(path: Path) -> tuple[PilotExactTaskReleasePlanConfig, str]:
    try:
        first = lifecycle_auth_boundary._read_host_authority_file(Path(path))
        second = lifecycle_auth_boundary._read_host_authority_file(Path(path))
    except Exception as exc:
        raise PilotExactTaskReleasePlanError(
            "release-plan config is not host-admin controlled"
        ) from exc
    if first != second:
        raise PilotExactTaskReleasePlanError(
            "release-plan config changed while being read"
        )
    config = _parse_config(second)
    return config, hashlib.sha256(second).hexdigest()


def _require_live_readiness(
    value: Any,
) -> PilotExactTaskReleaseReadinessEvaluationReceipt:
    if type(value) is not PilotExactTaskReleaseReadinessEvaluationReceipt:
        raise PilotExactTaskReleasePlanError(
            "exact live ADR-DC-063 release-readiness evaluation is required"
        )
    try:
        replayed = PilotExactTaskReleaseReadinessEvaluationReceipt.from_mapping(
            value.to_dict()
        )
    except Exception as exc:
        raise PilotExactTaskReleasePlanError(
            "ADR-DC-063 replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskReleasePlanError(
            "ADR-DC-063 release-readiness identity mismatch"
        )
    if (
        value.authority
        != PILOT_EXACT_TASK_RELEASE_READINESS_EVALUATION_AUTHORITY
        or value.evaluation_authenticated is not True
        or value.post_merge_attestation_authenticated is not True
        or value.release_readiness_policy_host_pinned is not True
        or value.exact_merge_revalidated is not True
        or value.exact_authorized_parent_satisfied is not True
        or value.double_observation_matched is not True
        or value.release_readiness_evaluated is not True
        or value.release_ready is not True
        or value.blocker_codes != ()
        or value.current_base_sha != value.merge_commit_sha
        or value.base_branch_policy_satisfied is not True
        or value.merge_method_policy_satisfied is not True
        or value.completion_source_policy_satisfied is not True
        or value.current_base_head_satisfied is not True
        or value.release_readiness_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
        or value.remote_write_authorized is not False
        or value.merge_authorized is not False
        or value.nonce_reusable is not False
    ):
        raise PilotExactTaskReleasePlanError(
            "ADR-DC-064 requires positive read-only ADR-DC-063 readiness"
        )
    live = readiness_boundary._get_live_release_readiness_evaluation_inputs(value)
    if (
        live is None
        or live.get("release_readiness_policy_sha256")
        != value.release_readiness_policy_sha256
        or live.get("remote_observation_sha256")
        != value.remote_observation_sha256
    ):
        raise PilotExactTaskReleasePlanError(
            "ADR-DC-063 live provenance is unavailable"
        )
    return value


def _release_version(merge_commit_sha: str) -> str:
    return f"{_VERSION_PREFIX}{_hex40(merge_commit_sha, name='merge_commit_sha')}"


def _tag_name(merge_commit_sha: str) -> str:
    tag = f"{_TAG_PREFIX}{_hex40(merge_commit_sha, name='merge_commit_sha')}"
    if _TAG.fullmatch(tag) is None or tag.endswith(("/", ".", ".lock")) or ".." in tag:
        raise PilotExactTaskReleasePlanError("deterministic release tag is invalid")
    return tag


def _release_name(merge_commit_sha: str) -> str:
    value = f"{_RELEASE_NAME_PREFIX}{_hex40(merge_commit_sha, name='merge_commit_sha')[:12]}"
    if not 1 <= len(value) <= 200 or value.strip() != value:
        raise PilotExactTaskReleasePlanError("deterministic release name is invalid")
    return value


def _release_body_fields(
    *,
    repository: str,
    release_base_branch: str,
    merge_commit_sha: str,
    development_task_sha256: str,
    candidate_patch_sha256: str,
    release_readiness_evaluation_sha256: str,
) -> str:
    body = (
        "ModelRig exact RSI release candidate\n\n"
        f"- repository: `{repository}`\n"
        f"- release base: `{release_base_branch}`\n"
        f"- merge commit: `{merge_commit_sha}`\n"
        f"- development task: `{development_task_sha256}`\n"
        f"- candidate patch: `{candidate_patch_sha256}`\n"
        f"- release readiness: `{release_readiness_evaluation_sha256}`\n\n"
        "Boundary: deterministic draft/prerelease intent only; no tag, GitHub "
        "Release, deployment or production mutation has been authorized."
    )
    encoded = body.encode("utf-8")
    if not encoded or len(encoded) > _MAX_RELEASE_BODY_BYTES:
        raise PilotExactTaskReleasePlanError("deterministic release body is invalid")
    return body


def _release_body(source: PilotExactTaskReleaseReadinessEvaluationReceipt) -> str:
    return _release_body_fields(
        repository=source.repository,
        release_base_branch=source.release_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        release_readiness_evaluation_sha256=source.sha256,
    )


def _release_intent_sha256_fields(
    *,
    release_readiness_evaluation_sha256: str,
    post_merge_attestation_sha256: str,
    release_readiness_policy_sha256: str,
    release_plan_config_sha256: str,
    execution_nonce_sha256: str,
    development_task_sha256: str,
    candidate_patch_sha256: str,
    pr_intent_sha256: str,
    transaction_lock_sha256: str,
    repository: str,
    repository_id: str,
    release_base_branch: str,
    merge_commit_sha: str,
    release_version: str,
    tag_name: str,
    tag_target_sha: str,
    release_name: str,
    release_body: str,
) -> str:
    payload = {
        "release_readiness_evaluation_sha256": _hex64(
            release_readiness_evaluation_sha256,
            name="release_readiness_evaluation_sha256",
        ),
        "post_merge_attestation_sha256": _hex64(
            post_merge_attestation_sha256,
            name="post_merge_attestation_sha256",
        ),
        "release_readiness_policy_sha256": _hex64(
            release_readiness_policy_sha256,
            name="release_readiness_policy_sha256",
        ),
        "release_plan_config_sha256": _hex64(
            release_plan_config_sha256,
            name="release_plan_config_sha256",
        ),
        "execution_nonce_sha256": _hex64(
            execution_nonce_sha256, name="execution_nonce_sha256"
        ),
        "development_task_sha256": _hex64(
            development_task_sha256, name="development_task_sha256"
        ),
        "candidate_patch_sha256": _hex64(
            candidate_patch_sha256, name="candidate_patch_sha256"
        ),
        "pr_intent_sha256": _hex64(pr_intent_sha256, name="pr_intent_sha256"),
        "transaction_lock_sha256": _hex64(
            transaction_lock_sha256, name="transaction_lock_sha256"
        ),
        "repository": repository,
        "repository_id": repository_id,
        "release_base_branch": release_base_branch,
        "merge_commit_sha": _hex40(merge_commit_sha, name="merge_commit_sha"),
        "release_version": release_version,
        "tag_name": tag_name,
        "tag_target_sha": _hex40(tag_target_sha, name="tag_target_sha"),
        "release_name": release_name,
        "release_body": release_body,
        "release_draft": True,
        "release_prerelease": True,
        "make_latest": False,
    }
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _release_intent_sha256(
    *,
    source: PilotExactTaskReleaseReadinessEvaluationReceipt,
    config_sha256: str,
    release_version: str,
    tag_name: str,
    release_name: str,
    release_body: str,
) -> str:
    return _release_intent_sha256_fields(
        release_readiness_evaluation_sha256=source.sha256,
        post_merge_attestation_sha256=source.post_merge_attestation_sha256,
        release_readiness_policy_sha256=source.release_readiness_policy_sha256,
        release_plan_config_sha256=config_sha256,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        transaction_lock_sha256=source.transaction_lock_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        release_base_branch=source.release_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        release_version=release_version,
        tag_name=tag_name,
        tag_target_sha=source.merge_commit_sha,
        release_name=release_name,
        release_body=release_body,
    )


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any], str, str],
    ] = {}

    def mark(
        receipt: Any,
        *,
        source: PilotExactTaskReleaseReadinessEvaluationReceipt,
        config_sha256: str,
        intent_sha256: str,
    ) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(source),
            config_sha256,
            intent_sha256,
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, source_ref, config_sha, intent_sha = entry
        source = source_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or source is None
            or receipt.sha256 != digest
            or source.evaluation_authenticated is not True
            or source.sha256 != receipt.release_readiness_evaluation_sha256
            or receipt.release_plan_config_sha256 != config_sha
            or receipt.release_intent_sha256 != intent_sha
        ):
            return None
        return MappingProxyType(
            {
                "release_readiness_evaluation": source,
                "release_plan_config_sha256": config_sha,
                "release_intent_sha256": intent_sha,
            }
        )

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


_mark_release_plan_authenticated, _get_live_release_plan_inputs = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskReleasePlanReceipt:
    release_readiness_evaluation_sha256: str
    post_merge_attestation_sha256: str
    release_readiness_policy_sha256: str
    release_plan_config_sha256: str
    release_intent_sha256: str
    execution_nonce_sha256: str
    development_task_sha256: str
    candidate_patch_sha256: str
    pr_intent_sha256: str
    transaction_lock_sha256: str
    repository: str
    repository_id: str
    release_base_branch: str
    merge_commit_sha: str
    release_version: str
    tag_name: str
    tag_target_sha: str
    release_name: str
    release_body: str
    release_body_sha256: str
    release_draft: bool
    release_prerelease: bool
    make_latest: bool
    readiness_evaluated_at_utc: str
    planned_at_utc: str
    release_readiness_authenticated: bool = True
    release_ready: bool = True
    release_plan_config_host_pinned: bool = True
    release_intent_materialized: bool = True
    tag_creation_planned: bool = True
    github_release_creation_planned: bool = True
    tag_write_authorized: bool = False
    release_mutation_authorized: bool = False
    release_authorized: bool = False
    remote_write_authorized: bool = False
    merge_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    nonce_reusable: bool = False
    plan_scope: str = PILOT_EXACT_TASK_RELEASE_PLAN_SCOPE
    authority: str = PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY
    schema: str = PILOT_EXACT_TASK_RELEASE_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_RELEASE_PLAN_SCHEMA
            or self.authority != PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY
            or self.plan_scope != PILOT_EXACT_TASK_RELEASE_PLAN_SCOPE
        ):
            raise PilotExactTaskReleasePlanError("release-plan identity is unsupported")
        for name in (
            "release_readiness_evaluation_sha256",
            "post_merge_attestation_sha256",
            "release_readiness_policy_sha256",
            "release_plan_config_sha256",
            "release_intent_sha256",
            "execution_nonce_sha256",
            "development_task_sha256",
            "candidate_patch_sha256",
            "pr_intent_sha256",
            "transaction_lock_sha256",
            "release_body_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("merge_commit_sha", "tag_target_sha"):
            _hex40(getattr(self, name), name=name)
        if self.tag_target_sha != self.merge_commit_sha:
            raise PilotExactTaskReleasePlanError(
                "release tag target differs from exact merge commit"
            )
        if (
            not isinstance(self.repository, str)
            or _REPOSITORY.fullmatch(self.repository) is None
            or not isinstance(self.repository_id, str)
            or _REPOSITORY_ID.fullmatch(self.repository_id) is None
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan repository identity is invalid"
            )
        _branch(self.release_base_branch, name="release_base_branch")
        expected_version = _release_version(self.merge_commit_sha)
        expected_tag = _tag_name(self.merge_commit_sha)
        expected_name = _release_name(self.merge_commit_sha)
        if (
            self.release_version != expected_version
            or _RELEASE_ID.fullmatch(self.release_version) is None
            or self.tag_name != expected_tag
            or self.release_name != expected_name
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan deterministic naming is inconsistent"
            )
        if (
            not isinstance(self.release_body, str)
            or not self.release_body
            or len(self.release_body.encode("utf-8")) > _MAX_RELEASE_BODY_BYTES
            or hashlib.sha256(self.release_body.encode("utf-8")).hexdigest()
            != self.release_body_sha256
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan body identity is invalid"
            )
        expected_body = _release_body_fields(
            repository=self.repository,
            release_base_branch=self.release_base_branch,
            merge_commit_sha=self.merge_commit_sha,
            development_task_sha256=self.development_task_sha256,
            candidate_patch_sha256=self.candidate_patch_sha256,
            release_readiness_evaluation_sha256=self.release_readiness_evaluation_sha256,
        )
        if self.release_body != expected_body:
            raise PilotExactTaskReleasePlanError(
                "release-plan deterministic body is inconsistent"
            )
        expected_intent = _release_intent_sha256_fields(
            release_readiness_evaluation_sha256=self.release_readiness_evaluation_sha256,
            post_merge_attestation_sha256=self.post_merge_attestation_sha256,
            release_readiness_policy_sha256=self.release_readiness_policy_sha256,
            release_plan_config_sha256=self.release_plan_config_sha256,
            execution_nonce_sha256=self.execution_nonce_sha256,
            development_task_sha256=self.development_task_sha256,
            candidate_patch_sha256=self.candidate_patch_sha256,
            pr_intent_sha256=self.pr_intent_sha256,
            transaction_lock_sha256=self.transaction_lock_sha256,
            repository=self.repository,
            repository_id=self.repository_id,
            release_base_branch=self.release_base_branch,
            merge_commit_sha=self.merge_commit_sha,
            release_version=self.release_version,
            tag_name=self.tag_name,
            tag_target_sha=self.tag_target_sha,
            release_name=self.release_name,
            release_body=self.release_body,
        )
        if self.release_intent_sha256 != expected_intent:
            raise PilotExactTaskReleasePlanError(
                "release-plan intent hash is inconsistent"
            )
        if (
            self.release_draft is not True
            or self.release_prerelease is not True
            or self.make_latest is not False
        ):
            raise PilotExactTaskReleasePlanError(
                "release-plan conservative GitHub Release flags are invalid"
            )
        readiness_time = _utc(
            self.readiness_evaluated_at_utc, name="readiness_evaluated_at_utc"
        )
        planned = _utc(self.planned_at_utc, name="planned_at_utc")
        if planned < readiness_time:
            raise PilotExactTaskReleasePlanError(
                "release plan predates readiness evaluation"
            )
        required_true = (
            "release_readiness_authenticated",
            "release_ready",
            "release_plan_config_host_pinned",
            "release_intent_materialized",
            "tag_creation_planned",
            "github_release_creation_planned",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskReleasePlanError(
                "release-plan evidence is incomplete"
            )
        forced_false = (
            "tag_write_authorized",
            "release_mutation_authorized",
            "release_authorized",
            "remote_write_authorized",
            "merge_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
            "nonce_reusable",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskReleasePlanError(
                "inert release plan retains forbidden authority"
            )

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    @property
    def plan_authenticated(self) -> bool:
        return _get_live_release_plan_inputs(self) is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskReleasePlanReceipt":
        if (
            not isinstance(value, Mapping)
            or set(value) != set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        ):
            raise PilotExactTaskReleasePlanError("release-plan fields mismatch")
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _materialize_verified_pilot_exact_task_release_plan(
    *,
    release_readiness_evaluation: PilotExactTaskReleaseReadinessEvaluationReceipt,
    config: PilotExactTaskReleasePlanConfig,
    config_sha256: str,
    now_provider: Callable[[], str],
) -> PilotExactTaskReleasePlanReceipt:
    source = _require_live_readiness(release_readiness_evaluation)
    if type(config) is not PilotExactTaskReleasePlanConfig:
        raise PilotExactTaskReleasePlanError(
            "exact host release-plan config is required"
        )
    supplied_config_sha = _hex64(
        config_sha256, name="release_plan_config_sha256"
    )
    if config.sha256 != supplied_config_sha:
        raise PilotExactTaskReleasePlanError(
            "release-plan config digest mismatch"
        )
    if (
        config.repository != source.repository
        or config.repository_id != source.repository_id
    ):
        raise PilotExactTaskReleasePlanError(
            "release-plan config is not bound to exact repository"
        )
    version = _release_version(source.merge_commit_sha)
    tag = _tag_name(source.merge_commit_sha)
    name = _release_name(source.merge_commit_sha)
    body = _release_body(source)
    body_sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    intent_sha = _release_intent_sha256(
        source=source,
        config_sha256=supplied_config_sha,
        release_version=version,
        tag_name=tag,
        release_name=name,
        release_body=body,
    )
    planned_at = now_provider()
    if _utc(planned_at, name="planned_at_utc") < _utc(
        source.evaluated_at_utc, name="readiness_evaluated_at_utc"
    ):
        raise PilotExactTaskReleasePlanError(
            "system clock moved backwards after release readiness"
        )
    receipt = PilotExactTaskReleasePlanReceipt(
        release_readiness_evaluation_sha256=source.sha256,
        post_merge_attestation_sha256=source.post_merge_attestation_sha256,
        release_readiness_policy_sha256=source.release_readiness_policy_sha256,
        release_plan_config_sha256=supplied_config_sha,
        release_intent_sha256=intent_sha,
        execution_nonce_sha256=source.execution_nonce_sha256,
        development_task_sha256=source.development_task_sha256,
        candidate_patch_sha256=source.candidate_patch_sha256,
        pr_intent_sha256=source.pr_intent_sha256,
        transaction_lock_sha256=source.transaction_lock_sha256,
        repository=source.repository,
        repository_id=source.repository_id,
        release_base_branch=source.release_base_branch,
        merge_commit_sha=source.merge_commit_sha,
        release_version=version,
        tag_name=tag,
        tag_target_sha=source.merge_commit_sha,
        release_name=name,
        release_body=body,
        release_body_sha256=body_sha,
        release_draft=True,
        release_prerelease=True,
        make_latest=False,
        readiness_evaluated_at_utc=source.evaluated_at_utc,
        planned_at_utc=planned_at,
    )
    expected_intent = _release_intent_sha256(
        source=source,
        config_sha256=supplied_config_sha,
        release_version=receipt.release_version,
        tag_name=receipt.tag_name,
        release_name=receipt.release_name,
        release_body=receipt.release_body,
    )
    if receipt.release_intent_sha256 != expected_intent:
        raise PilotExactTaskReleasePlanError(
            "release intent changed while materializing plan"
        )
    _mark_release_plan_authenticated(
        receipt,
        source=source,
        config_sha256=supplied_config_sha,
        intent_sha256=intent_sha,
    )
    if receipt.plan_authenticated is not True:
        raise PilotExactTaskReleasePlanError(
            "release plan lost live provenance"
        )
    return receipt


def _canonical_config() -> tuple[PilotExactTaskReleasePlanConfig, str]:
    try:
        _require_elevated_operator()
        if os.name == "posix":
            path = _POSIX_CONFIG
        elif os.name == "nt":
            path = _WINDOWS_CONFIG
        else:
            raise PilotExactTaskReleasePlanError(
                "release-plan config platform is unsupported"
            )
        return _read_host_config(path)
    except PhysicalHostStateError as exc:
        raise PilotExactTaskReleasePlanError(
            "release-plan config requires an elevated host operator"
        ) from exc


def materialize_pilot_exact_task_release_plan(
    release_readiness_evaluation: PilotExactTaskReleaseReadinessEvaluationReceipt,
) -> PilotExactTaskReleasePlanReceipt:
    """Freeze one deterministic release intent without mutating GitHub."""
    try:
        config, digest = _canonical_config()
        return _materialize_verified_pilot_exact_task_release_plan(
            release_readiness_evaluation=release_readiness_evaluation,
            config=config,
            config_sha256=digest,
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskReleasePlanError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskReleasePlanError(
            "exact deterministic release planning failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_RELEASE_PLAN_SCHEMA",
    "PILOT_EXACT_TASK_RELEASE_PLAN_AUTHORITY",
    "PILOT_EXACT_TASK_RELEASE_PLAN_SCOPE",
    "PILOT_EXACT_TASK_RELEASE_PLAN_CONFIG_SCHEMA",
    "PilotExactTaskReleasePlanError",
    "PilotExactTaskReleasePlanConfig",
    "PilotExactTaskReleasePlanReceipt",
    "materialize_pilot_exact_task_release_plan",
]

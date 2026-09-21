"""ADR-DC-048 exact read-only GitHub remote-state observation.

This boundary accepts only one exact live ADR-DC-047 remote-publication plan,
revalidates the completed local commit, and then performs bounded unauthenticated
GET-only observation against the plan-pinned public GitHub repository.

A passing receipt proves that remote main still equals the exact DevelopmentTask
base, the deterministic head branch is absent, and no pull request (open or
closed) exists for the exact head/base pair. It performs no Git or GitHub
mutation and grants no push, pull-request, merge, release, deploy or activation
authority.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from . import improvement_pilot_exact_task_remote_publication_plan as plan_boundary
from .improvement_pilot_exact_task_remote_publication_plan import (
    PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY,
    PilotExactTaskRemotePublicationPlan,
)

PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-remote-state-observation/v1"
)
PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY = (
    "host-observed-one-dc-l16-exact-remote-state-only"
)
PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCOPE = (
    "read-only-exact-github-publication-lane-v1"
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_TASK_ID = re.compile(r"^[A-Z][A-Z0-9_-]{2,63}$")
_REPOSITORY = re.compile(r"^[^/\s]+/[^/\s]+$")
_REPOSITORY_ID = re.compile(r"^[1-9][0-9]{0,19}$")
_BRANCH = re.compile(r"^(?![./])(?!.*\.\.)(?!.*//)[A-Za-z0-9._/-]{1,200}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_GITHUB_API_ROOT = "https://api.github.com"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 15.0


class PilotExactTaskRemoteStateObservationError(ValueError):
    """Remote state is untrustworthy, ambiguous, stale, or mutation-bearing."""


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
        raise PilotExactTaskRemoteStateObservationError(
            "remote-state observation is not canonical JSON"
        ) from exc


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskRemoteStateObservationError(f"{name} is invalid")
    return value


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskRemoteStateObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskRemoteStateObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskRemoteStateObservationError(f"{name} is invalid") from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _branch(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or value.strip() != value
        or _BRANCH.fullmatch(value) is None
        or value.endswith(("/", ".", ".lock"))
        or "@{" in value
        or "\\" in value
    ):
        raise PilotExactTaskRemoteStateObservationError(
            f"{name} is not a canonical branch name"
        )
    return value


def _require_live_plan(
    value: Any,
) -> tuple[PilotExactTaskRemotePublicationPlan, Mapping[str, Any]]:
    if type(value) is not PilotExactTaskRemotePublicationPlan:
        raise PilotExactTaskRemoteStateObservationError(
            "exact ADR-DC-047 remote publication plan is required"
        )
    try:
        replayed = PilotExactTaskRemotePublicationPlan.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 plan replay validation failed"
        ) from exc
    if replayed != value or replayed.sha256 != value.sha256:
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 plan identity mismatch"
        )
    if (
        value.authority != PILOT_EXACT_TASK_REMOTE_PUBLICATION_PLAN_AUTHORITY
        or value.plan_authenticated is not True
        or value.integration_ready is not True
        or value.exact_local_commit_revalidated is not True
        or value.remote_target_host_pinned is not True
        or value.remote_publication_plan_materialized is not True
        or value.remote_branch_creation_planned is not True
        or value.exact_commit_push_planned is not True
        or value.draft_pr_creation_planned is not True
        or value.remote_state_observed is not False
        or value.remote_write_authorized is not False
        or value.push_authorized is not False
        or value.pr_mutation_authorized is not False
        or value.merge_authorized is not False
        or value.release_authorized is not False
        or value.deploy_authorized is not False
        or value.production_activation_authorized is not False
    ):
        raise PilotExactTaskRemoteStateObservationError(
            "remote observation requires one live inert ADR-DC-047 plan"
        )
    inputs = plan_boundary._get_live_remote_publication_plan_inputs(value)
    if inputs is None:
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 live plan inputs are unavailable"
        )
    readiness = inputs.get("integration_readiness")
    task = inputs.get("task")
    identity = inputs.get("local_commit_object_identity")
    if (
        readiness is None
        or task is None
        or identity is None
        or getattr(readiness, "sha256", None) != value.integration_readiness_sha256
        or getattr(task, "task_id", None) != value.task_id
        or getattr(task, "repository", None) != value.repository
        or getattr(task, "base_sha", None) != value.base_sha
        or getattr(identity, "predicted_commit_sha", None) != value.predicted_commit_sha
    ):
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 plan is not bound to exact live provenance"
        )
    return value, inputs


def _fresh_revalidate_local_commit(
    *, plan: PilotExactTaskRemotePublicationPlan, inputs: Mapping[str, Any]
) -> None:
    readiness = inputs.get("integration_readiness")
    if readiness is None:
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 plan lacks live readiness"
        )
    try:
        plan_boundary._fresh_revalidate_exact_local_commit(
            readiness=readiness,
            inputs=inputs,
        )
    except Exception as exc:
        raise PilotExactTaskRemoteStateObservationError(
            "exact local commit changed before remote-state observation"
        ) from exc
    live = plan_boundary._get_live_remote_publication_plan_inputs(plan)
    if live is None or live.get("integration_readiness") is not readiness:
        raise PilotExactTaskRemoteStateObservationError(
            "ADR-DC-047 live plan changed during remote-state observation"
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


class _GitHubReadOnlyObserver:
    """Unauthenticated GET-only observer pinned to api.github.com."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(_NoRedirect())

    def _get_json(
        self,
        *,
        path: str,
        query: Mapping[str, str] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        if not isinstance(path, str) or not path.startswith("/repos/") or ".." in path:
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub observation path is outside the repository API"
            )
        url = _GITHUB_API_ROOT + path
        if query:
            url += "?" + urllib.parse.urlencode(dict(query), safe=":/")
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "ModelRig-DevControl-RemoteStateObserver/1",
            },
        )
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            raise PilotExactTaskRemoteStateObservationError(
                f"GitHub read-only observation failed with HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub read-only observation failed"
            ) from exc
        with response:
            if response.status != 200 or response.geturl() != url:
                raise PilotExactTaskRemoteStateObservationError(
                    "GitHub observation response identity is unexpected"
                )
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
        if not payload or len(payload) > _MAX_RESPONSE_BYTES:
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub observation response size is invalid"
            )
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub observation response is not valid JSON"
            ) from exc

    def observe(self, plan: PilotExactTaskRemotePublicationPlan) -> Mapping[str, Any]:
        if type(plan) is not PilotExactTaskRemotePublicationPlan:
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub observer requires exact ADR-DC-047 plan"
            )
        owner, repo = plan.repository.split("/", 1)
        owner_q = urllib.parse.quote(owner, safe="")
        repo_q = urllib.parse.quote(repo, safe="")
        root = f"/repos/{owner_q}/{repo_q}"
        metadata = self._get_json(path=root)
        if not isinstance(metadata, Mapping):
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub repository metadata is invalid"
            )
        repository_id = metadata.get("id")
        full_name = metadata.get("full_name")
        default_branch = metadata.get("default_branch")
        if (
            str(repository_id) != plan.repository_id
            or full_name != plan.repository
            or default_branch != plan.base_branch
        ):
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub repository identity/default branch does not match plan"
            )

        base_q = urllib.parse.quote(plan.base_branch, safe="")
        base_ref = self._get_json(path=f"{root}/git/ref/heads/{base_q}")
        if not isinstance(base_ref, Mapping):
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub base ref response is invalid"
            )
        base_object = base_ref.get("object")
        if not isinstance(base_object, Mapping) or base_object.get("type") != "commit":
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub base ref is not a commit"
            )
        base_sha = _hex40(base_object.get("sha"), name="observed GitHub base SHA")

        head_q = urllib.parse.quote(plan.head_branch, safe="")
        head_ref = self._get_json(
            path=f"{root}/git/ref/heads/{head_q}",
            allow_not_found=True,
        )
        head_exists = head_ref is not None
        if head_exists and not isinstance(head_ref, Mapping):
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub head ref response is invalid"
            )

        pulls = self._get_json(
            path=f"{root}/pulls",
            query={
                "state": "all",
                "head": f"{owner}:{plan.head_branch}",
                "base": plan.base_branch,
                "per_page": "100",
            },
        )
        if not isinstance(pulls, list):
            raise PilotExactTaskRemoteStateObservationError(
                "GitHub pull-request observation is invalid"
            )
        return MappingProxyType(
            {
                "repository_id": str(repository_id),
                "repository": full_name,
                "default_branch": default_branch,
                "base_sha": base_sha,
                "head_exists": head_exists,
                "matching_pr_count": len(pulls),
            }
        )


def _validate_observation(
    plan: PilotExactTaskRemotePublicationPlan,
    value: Any,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "repository_id",
        "repository",
        "default_branch",
        "base_sha",
        "head_exists",
        "matching_pr_count",
    }:
        raise PilotExactTaskRemoteStateObservationError(
            "remote-state observer returned unexpected fields"
        )
    if (
        value["repository_id"] != plan.repository_id
        or value["repository"] != plan.repository
        or value["default_branch"] != plan.base_branch
    ):
        raise PilotExactTaskRemoteStateObservationError(
            "remote-state repository identity changed"
        )
    base_sha = _hex40(value["base_sha"], name="observed base SHA")
    if type(value["head_exists"]) is not bool:
        raise PilotExactTaskRemoteStateObservationError(
            "head branch existence observation is invalid"
        )
    count = value["matching_pr_count"]
    if isinstance(count, bool) or not isinstance(count, int) or count < 0 or count > 100:
        raise PilotExactTaskRemoteStateObservationError(
            "matching pull-request count is invalid"
        )
    return MappingProxyType(
        {
            "repository_id": plan.repository_id,
            "repository": plan.repository,
            "default_branch": plan.base_branch,
            "base_sha": base_sha,
            "head_exists": value["head_exists"],
            "matching_pr_count": count,
        }
    )


def _remote_observation_sha256(
    *, plan: PilotExactTaskRemotePublicationPlan, observation: Mapping[str, Any]
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "repository": plan.repository,
                "repository_id": plan.repository_id,
                "provider": plan.provider,
                "host": plan.host,
                "base_branch": plan.base_branch,
                "head_branch": plan.head_branch,
                "exact_task_base_sha": plan.base_sha,
                "predicted_commit_sha": plan.predicted_commit_sha,
                "observed_base_sha": observation["base_sha"],
                "head_exists": observation["head_exists"],
                "matching_pr_count": observation["matching_pr_count"],
            }
        ).encode("utf-8")
    ).hexdigest()


def _live_registry():
    records: dict[
        int,
        tuple[int, str, weakref.ReferenceType[Any], weakref.ReferenceType[Any]],
    ] = {}

    def mark(receipt: Any, plan: PilotExactTaskRemotePublicationPlan) -> None:
        key = id(receipt)

        def cleanup(_: weakref.ReferenceType[Any]) -> None:
            records.pop(key, None)

        records[key] = (
            os.getpid(),
            receipt.sha256,
            weakref.ref(receipt, cleanup),
            weakref.ref(plan),
        )

    def get(receipt: Any) -> Mapping[str, Any] | None:
        entry = records.get(id(receipt))
        if entry is None:
            return None
        pid, digest, receipt_ref, plan_ref = entry
        plan = plan_ref()
        if (
            pid != os.getpid()
            or receipt_ref() is not receipt
            or plan is None
            or plan.plan_authenticated is not True
            or receipt.sha256 != digest
            or receipt.remote_publication_plan_sha256 != plan.sha256
        ):
            return None
        inputs = plan_boundary._get_live_remote_publication_plan_inputs(plan)
        if inputs is None:
            return None
        result = dict(inputs)
        result["remote_publication_plan"] = plan
        return MappingProxyType(result)

    if hasattr(os, "register_at_fork"):
        os.register_at_fork(after_in_child=records.clear)
    return mark, get


(
    _mark_remote_state_observation_authenticated,
    _get_live_remote_state_observation_inputs,
) = _live_registry()


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskRemoteStateObservationReceipt:
    remote_publication_plan_sha256: str
    integration_readiness_sha256: str
    remote_target_config_sha256: str
    remote_repository_identity_sha256: str
    pr_intent_sha256: str
    remote_observation_sha256: str
    task_id: str
    repository: str
    repository_id: str
    provider: str
    host: str
    base_branch: str
    head_branch: str
    exact_task_base_sha: str
    observed_base_sha: str
    predicted_commit_sha: str
    observed_at_utc: str
    remote_publication_plan_authenticated: bool = True
    remote_repository_identity_verified: bool = True
    remote_default_branch_verified: bool = True
    base_branch_observed: bool = True
    base_branch_matches_exact_task_base: bool = True
    head_branch_observed: bool = True
    head_branch_exists: bool = False
    head_branch_absent: bool = True
    matching_prs_observed: bool = True
    matching_pr_count: int = 0
    matching_pr_absent: bool = True
    double_observation_matched: bool = True
    remote_state_observed: bool = True
    publication_lane_clear: bool = True
    integration_ready: bool = True
    remote_publication_plan_materialized: bool = True
    remote_write_authorized: bool = False
    push_authorized: bool = False
    pr_mutation_authorized: bool = False
    merge_authorized: bool = False
    release_authorized: bool = False
    deploy_authorized: bool = False
    production_activation_authorized: bool = False
    product_pilot_started: bool = False
    observation_scope: str = PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCOPE
    authority: str = PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY
    schema: str = PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCHEMA:
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation schema is unsupported"
            )
        if self.observation_scope != PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCOPE:
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation scope is unsupported"
            )
        for name in (
            "remote_publication_plan_sha256",
            "integration_readiness_sha256",
            "remote_target_config_sha256",
            "remote_repository_identity_sha256",
            "pr_intent_sha256",
            "remote_observation_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        for name in ("exact_task_base_sha", "observed_base_sha", "predicted_commit_sha"):
            _hex40(getattr(self, name), name=name)
        if not isinstance(self.task_id, str) or _TASK_ID.fullmatch(self.task_id) is None:
            raise PilotExactTaskRemoteStateObservationError("task_id is invalid")
        if not isinstance(self.repository, str) or _REPOSITORY.fullmatch(self.repository) is None:
            raise PilotExactTaskRemoteStateObservationError("repository is invalid")
        if not isinstance(self.repository_id, str) or _REPOSITORY_ID.fullmatch(self.repository_id) is None:
            raise PilotExactTaskRemoteStateObservationError("repository_id is invalid")
        if self.provider != "github" or self.host != "github.com":
            raise PilotExactTaskRemoteStateObservationError("provider/host is unsupported")
        if self.base_branch != "main":
            raise PilotExactTaskRemoteStateObservationError("base branch is unsupported")
        _branch(self.head_branch, name="head branch")
        _utc(self.observed_at_utc, name="observed_at_utc")
        required_true = (
            "remote_publication_plan_authenticated",
            "remote_repository_identity_verified",
            "remote_default_branch_verified",
            "base_branch_observed",
            "base_branch_matches_exact_task_base",
            "head_branch_observed",
            "head_branch_absent",
            "matching_prs_observed",
            "matching_pr_absent",
            "double_observation_matched",
            "remote_state_observed",
            "publication_lane_clear",
            "integration_ready",
            "remote_publication_plan_materialized",
        )
        if any(getattr(self, name) is not True for name in required_true):
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state publication-lane evidence is incomplete"
            )
        if self.head_branch_exists is not False or self.matching_pr_count != 0:
            raise PilotExactTaskRemoteStateObservationError(
                "publication lane is not empty"
            )
        forced_false = (
            "remote_write_authorized",
            "push_authorized",
            "pr_mutation_authorized",
            "merge_authorized",
            "release_authorized",
            "deploy_authorized",
            "production_activation_authorized",
            "product_pilot_started",
        )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation cannot grant mutation authority"
            )
        if self.observed_base_sha != self.exact_task_base_sha:
            raise PilotExactTaskRemoteStateObservationError(
                "observed remote base no longer equals exact task base"
            )
        if self.authority != PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY:
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation authority is unsupported"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_remote_state_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskRemoteStateObservationReceipt":
        if not isinstance(value, Mapping):
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation receipt must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation receipt fields mismatch"
            )
        return cls(**dict(value))

    @classmethod
    def from_json(cls, text: str) -> "PilotExactTaskRemoteStateObservationReceipt":
        try:
            return cls.from_mapping(json.loads(text))
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise PilotExactTaskRemoteStateObservationError(
                "remote-state observation JSON is invalid"
            ) from exc

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_remote_state(
    *,
    remote_publication_plan: PilotExactTaskRemotePublicationPlan,
    observer: Any,
    now_provider,
) -> PilotExactTaskRemoteStateObservationReceipt:
    plan, inputs = _require_live_plan(remote_publication_plan)
    if observer is None or not callable(getattr(observer, "observe", None)):
        raise PilotExactTaskRemoteStateObservationError(
            "read-only GitHub observer is required"
        )
    _fresh_revalidate_local_commit(plan=plan, inputs=inputs)

    first = _validate_observation(plan, observer.observe(plan))
    second = _validate_observation(plan, observer.observe(plan))
    if dict(first) != dict(second):
        raise PilotExactTaskRemoteStateObservationError(
            "GitHub remote state changed between read-only observations"
        )
    if second["base_sha"] != plan.base_sha:
        raise PilotExactTaskRemoteStateObservationError(
            "remote main advanced or rewound from exact DevelopmentTask base"
        )
    if second["head_exists"] is not False:
        raise PilotExactTaskRemoteStateObservationError(
            "deterministic remote head branch already exists"
        )
    if second["matching_pr_count"] != 0:
        raise PilotExactTaskRemoteStateObservationError(
            "a pull request already exists for deterministic head/base intent"
        )

    _fresh_revalidate_local_commit(plan=plan, inputs=inputs)
    live_again = plan_boundary._get_live_remote_publication_plan_inputs(plan)
    if live_again is None or live_again.get("integration_readiness") is not inputs.get(
        "integration_readiness"
    ):
        raise PilotExactTaskRemoteStateObservationError(
            "live publication plan changed during remote-state observation"
        )

    observed_at = now_provider()
    if _utc(observed_at, name="observed_at_utc") < _utc(
        plan.planned_at_utc, name="planned_at_utc"
    ):
        raise PilotExactTaskRemoteStateObservationError(
            "system clock moved backwards after ADR-DC-047 plan"
        )
    observation_sha = _remote_observation_sha256(plan=plan, observation=second)
    receipt = PilotExactTaskRemoteStateObservationReceipt(
        remote_publication_plan_sha256=plan.sha256,
        integration_readiness_sha256=plan.integration_readiness_sha256,
        remote_target_config_sha256=plan.remote_target_config_sha256,
        remote_repository_identity_sha256=plan.remote_repository_identity_sha256,
        pr_intent_sha256=plan.pr_intent_sha256,
        remote_observation_sha256=observation_sha,
        task_id=plan.task_id,
        repository=plan.repository,
        repository_id=plan.repository_id,
        provider=plan.provider,
        host=plan.host,
        base_branch=plan.base_branch,
        head_branch=plan.head_branch,
        exact_task_base_sha=plan.base_sha,
        observed_base_sha=second["base_sha"],
        predicted_commit_sha=plan.predicted_commit_sha,
        observed_at_utc=observed_at,
    )
    _mark_remote_state_observation_authenticated(receipt, plan)
    if receipt.observation_authenticated is not True:
        raise PilotExactTaskRemoteStateObservationError(
            "remote-state observation lost live provenance"
        )
    return receipt


def observe_pilot_exact_task_remote_state(
    remote_publication_plan: PilotExactTaskRemotePublicationPlan,
) -> PilotExactTaskRemoteStateObservationReceipt:
    """ADR-DC-048 public GitHub GET-only exact remote-state observation."""
    try:
        return _observe_verified_pilot_exact_task_remote_state(
            remote_publication_plan=remote_publication_plan,
            observer=_GitHubReadOnlyObserver(),
            now_provider=_now_utc_seconds,
        )
    except PilotExactTaskRemoteStateObservationError:
        raise
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        raise PilotExactTaskRemoteStateObservationError(
            "exact remote-state observation failed closed"
        ) from exc


__all__ = [
    "PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_REMOTE_STATE_OBSERVATION_SCOPE",
    "PilotExactTaskRemoteStateObservationError",
    "PilotExactTaskRemoteStateObservationReceipt",
    "observe_pilot_exact_task_remote_state",
]

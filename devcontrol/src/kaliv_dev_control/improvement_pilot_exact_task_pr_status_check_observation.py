"""ADR-DC-081 exact-head status-check observation.

Consumes one live authenticated ADR-DC-080 merge preflight and observes all
GitHub check-runs plus legacy commit statuses bound to its immutable predicted
head SHA. The observation is credential-free, fixed-origin, bounded, paginated,
and repeated in full. It records evidence only; it does not decide which checks
are required and grants no merge or mutation authority.
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

from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from . import improvement_pilot_exact_task_pr_merge_preflight as preflight_boundary
from .improvement_pilot_exact_task_pr_merge_preflight import (
    PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY,
    PilotExactTaskPrMergePreflight,
)

PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-status-check-observation/v1"
)
PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY = (
    "observed-one-dc-l16-exact-head-status-check-inventory-only"
)
PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCOPE = (
    "credential-free-stable-exact-head-check-inventory-v1"
)
PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_MAX_PREFLIGHT_AGE_SECONDS = 60

_REPOSITORY = "Ternedal/ModelRig"
_TIMEOUT_SECONDS = 20
_MAX_PAGE_BYTES = 512 * 1024
_PAGE_SIZE = 100
_MAX_PAGES = 10
_MAX_ROWS = _PAGE_SIZE * _MAX_PAGES
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_HEAD = re.compile(r"^agent/rsi/remote-candidate/[0-9a-f]{64}$")
_CHECK_STATUSES = frozenset({"queued", "in_progress", "completed", "requested", "waiting", "pending"})
_CHECK_CONCLUSIONS = frozenset({
    "NONE", "action_required", "cancelled", "failure", "neutral", "skipped",
    "stale", "startup_failure", "success", "timed_out",
})
_LEGACY_STATES = frozenset({"error", "failure", "pending", "success"})


class PilotExactTaskPrStatusCheckObservationError(ValueError):
    """Status-check evidence is stale, drifted, incomplete, or unsafe."""


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PilotExactTaskPrStatusCheckObservationError(
            "status-check evidence is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrStatusCheckObservationError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrStatusCheckObservationError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrStatusCheckObservationError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrStatusCheckObservationError(f"{name} is invalid") from exc


def _optional_utc(value: Any, *, name: str) -> str:
    if value is None:
        return ""
    _utc(value, name=name)
    return value


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _headers() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-081",
        }
    )


def _require_live_preflight(value: Any) -> PilotExactTaskPrMergePreflight:
    if type(value) is not PilotExactTaskPrMergePreflight:
        raise PilotExactTaskPrStatusCheckObservationError(
            "exact live ADR-DC-080 merge preflight is required"
        )
    try:
        replayed = PilotExactTaskPrMergePreflight.from_mapping(value.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrStatusCheckObservationError(
            "ADR-DC-080 merge preflight replay validation failed"
        ) from exc
    live = preflight_boundary._get_live_pr_merge_preflight_inputs(value)
    forced_false = (
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
    if (
        replayed != value
        or replayed.sha256 != value.sha256
        or value.authority != PILOT_EXACT_TASK_PR_MERGE_PREFLIGHT_AUTHORITY
        or value.preflight_authenticated is not True
        or live is None
        or value.metadata_and_review_preflight_passed is not True
        or value.required_status_checks_preflight_required is not True
        or value.review_threads_preflight_required is not True
        or value.branch_policy_preflight_required is not True
        or value.fresh_merge_transaction_revalidation_required is not True
        or any(getattr(value, name) is not False for name in forced_false)
        or value.repository != _REPOSITORY
        or value.base_branch != "main"
        or _HEAD.fullmatch(value.head_branch) is None
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "status observation requires one live inert ADR-DC-080 preflight"
        )
    return value


def _require_preflight_window(
    preflight: PilotExactTaskPrMergePreflight,
    *,
    at_utc: str,
) -> None:
    at = _utc(at_utc, name="status observation time")
    source = _utc(
        preflight.second_observed_at_utc,
        name="ADR-DC-080 second_observed_at_utc",
    )
    if (
        at < source
        or (at - source).total_seconds()
        > PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_MAX_PREFLIGHT_AGE_SECONDS
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "ADR-DC-080 merge preflight is too old for exact-head status observation"
        )


def _get(
    transport: ReadOnlyTransport,
    url: str,
) -> HttpResponse:
    try:
        response = transport.get(
            url,
            headers=_headers(),
            timeout_seconds=_TIMEOUT_SECONDS,
            max_bytes=_MAX_PAGE_BYTES,
        )
    except GitHubReadError as exc:
        raise PilotExactTaskPrStatusCheckObservationError(
            "credential-free fixed-origin GitHub status read failed"
        ) from exc
    if (
        type(response) is not HttpResponse
        or response.status != 200
        or len(response.body) > _MAX_PAGE_BYTES
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "GitHub status response status/size is unsafe"
        )
    content_type = str(response.headers.get("content-type", "")).lower()
    if content_type and not (
        content_type.startswith("application/json")
        or content_type.startswith("application/vnd.github+json")
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "GitHub status response content type is unsafe"
        )
    return response


def _json(response: HttpResponse, *, name: str) -> Any:
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrStatusCheckObservationError(
            f"{name} is not UTF-8 JSON"
        ) from exc


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if (
        not isinstance(etag, str)
        or len(etag) > 512
        or any(marker in etag for marker in ("\r", "\n", "\x00"))
    ):
        raise PilotExactTaskPrStatusCheckObservationError("GitHub ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _text(value: Any, *, name: str, maximum: int = 512) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value.strip() != value
        or len(value.encode("utf-8")) > maximum
        or any(marker in value for marker in ("\r", "\n", "\x00"))
    ):
        raise PilotExactTaskPrStatusCheckObservationError(f"{name} is invalid")
    return value


def _check_row(value: Any, *, head_sha: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrStatusCheckObservationError("check run row is not an object")
    run_id = value.get("id")
    node_id = value.get("node_id")
    name = value.get("name")
    status = value.get("status")
    conclusion = value.get("conclusion")
    app = value.get("app")
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or run_id < 1
        or not isinstance(node_id, str)
        or not node_id
        or value.get("head_sha") != head_sha
        or status not in _CHECK_STATUSES
        or (conclusion is not None and conclusion not in _CHECK_CONCLUSIONS)
        or (status == "completed" and conclusion is None)
        or (status != "completed" and conclusion is not None)
        or not isinstance(app, Mapping)
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "check run identity/state is invalid"
        )
    app_id = app.get("id")
    app_slug = app.get("slug")
    if (
        isinstance(app_id, bool)
        or not isinstance(app_id, int)
        or app_id < 1
    ):
        raise PilotExactTaskPrStatusCheckObservationError("check run app id is invalid")
    _text(name, name="check run name", maximum=512)
    _text(app_slug, name="check run app slug", maximum=256)
    started = _optional_utc(value.get("started_at"), name="check run started_at")
    completed = _optional_utc(value.get("completed_at"), name="check run completed_at")
    if status == "completed" and not completed:
        raise PilotExactTaskPrStatusCheckObservationError(
            "completed check run must have completed_at"
        )
    return MappingProxyType(
        {
            "id": run_id,
            "node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
            "name": name,
            "app_id": app_id,
            "app_slug": app_slug,
            "status": status,
            "conclusion": "NONE" if conclusion is None else conclusion,
            "started_at_utc": started,
            "completed_at_utc": completed,
        }
    )


def _legacy_row(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PilotExactTaskPrStatusCheckObservationError(
            "legacy commit status row is not an object"
        )
    status_id = value.get("id")
    node_id = value.get("node_id")
    state = value.get("state")
    context = value.get("context")
    creator = value.get("creator")
    if (
        isinstance(status_id, bool)
        or not isinstance(status_id, int)
        or status_id < 1
        or not isinstance(node_id, str)
        or not node_id
        or state not in _LEGACY_STATES
        or not isinstance(creator, Mapping)
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "legacy commit status identity/state is invalid"
        )
    creator_id = creator.get("id")
    if (
        isinstance(creator_id, bool)
        or not isinstance(creator_id, int)
        or creator_id < 1
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "legacy commit status creator id is invalid"
        )
    _text(context, name="legacy status context", maximum=512)
    created = _optional_utc(value.get("created_at"), name="legacy status created_at")
    updated = _optional_utc(value.get("updated_at"), name="legacy status updated_at")
    if not created or not updated:
        raise PilotExactTaskPrStatusCheckObservationError(
            "legacy commit status timestamps are required"
        )
    return MappingProxyType(
        {
            "id": status_id,
            "node_id_sha256": hashlib.sha256(node_id.encode("utf-8")).hexdigest(),
            "context": context,
            "state": state,
            "creator_id": creator_id,
            "created_at_utc": created,
            "updated_at_utc": updated,
        }
    )


def _check_runs_url(head_sha: str, page: int) -> str:
    return (
        f"https://api.github.com/repos/Ternedal/ModelRig/commits/{head_sha}/check-runs"
        f"?filter=all&per_page={_PAGE_SIZE}&page={page}"
    )


def _statuses_url(head_sha: str, page: int) -> str:
    return (
        f"https://api.github.com/repos/Ternedal/ModelRig/commits/{head_sha}/statuses"
        f"?per_page={_PAGE_SIZE}&page={page}"
    )


def _read_check_runs(
    *,
    head_sha: str,
    transport: ReadOnlyTransport,
) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    pages: list[Mapping[str, Any]] = []
    expected_total: int | None = None
    for page in range(1, _MAX_PAGES + 1):
        response = _get(transport, _check_runs_url(head_sha, page))
        raw = _json(response, name="check-runs response")
        if (
            not isinstance(raw, Mapping)
            or not {"total_count", "check_runs"}.issubset(raw)
            or isinstance(raw.get("total_count"), bool)
            or not isinstance(raw.get("total_count"), int)
            or raw["total_count"] < 0
            or not isinstance(raw.get("check_runs"), list)
            or len(raw["check_runs"]) > _PAGE_SIZE
        ):
            raise PilotExactTaskPrStatusCheckObservationError(
                "check-runs response shape is invalid"
            )
        total = raw["total_count"]
        if total > _MAX_ROWS:
            raise PilotExactTaskPrStatusCheckObservationError(
                "check-runs inventory exceeds bounded complete-observation limit"
            )
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise PilotExactTaskPrStatusCheckObservationError(
                "check-runs total_count drifted during pagination"
            )
        page_rows = tuple(_check_row(item, head_sha=head_sha) for item in raw["check_runs"])
        for row in page_rows:
            if row["id"] in seen:
                raise PilotExactTaskPrStatusCheckObservationError(
                    "duplicate check-run id across pagination"
                )
            seen.add(row["id"])
            rows.append(row)
        pages.append(
            MappingProxyType(
                {
                    "page": page,
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "etag_sha256": _etag_sha256(response.headers),
                    "row_count": len(page_rows),
                    "total_count": total,
                }
            )
        )
        if len(page_rows) < _PAGE_SIZE:
            break
        if page == _MAX_PAGES:
            raise PilotExactTaskPrStatusCheckObservationError(
                "check-runs inventory completeness is not provable within page bound"
            )
    if expected_total is None or len(rows) != expected_total:
        raise PilotExactTaskPrStatusCheckObservationError(
            "check-runs total_count does not match bounded inventory"
        )
    normalized = tuple(sorted(rows, key=lambda item: item["id"]))
    inventory_sha = hashlib.sha256(
        _canonical([dict(item) for item in normalized]).encode("utf-8")
    ).hexdigest()
    evidence_sha = hashlib.sha256(
        _canonical([dict(item) for item in pages]).encode("utf-8")
    ).hexdigest()
    return normalized, MappingProxyType(
        {
            "inventory_sha256": inventory_sha,
            "evidence_sha256": evidence_sha,
            "count": len(normalized),
            "pages": len(pages),
        }
    )


def _read_legacy_statuses(
    *,
    head_sha: str,
    transport: ReadOnlyTransport,
) -> tuple[tuple[Mapping[str, Any], ...], Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    seen: set[int] = set()
    pages: list[Mapping[str, Any]] = []
    for page in range(1, _MAX_PAGES + 1):
        response = _get(transport, _statuses_url(head_sha, page))
        raw = _json(response, name="legacy statuses response")
        if not isinstance(raw, list) or len(raw) > _PAGE_SIZE:
            raise PilotExactTaskPrStatusCheckObservationError(
                "legacy statuses response shape is invalid"
            )
        page_rows = tuple(_legacy_row(item) for item in raw)
        for row in page_rows:
            if row["id"] in seen:
                raise PilotExactTaskPrStatusCheckObservationError(
                    "duplicate legacy status id across pagination"
                )
            seen.add(row["id"])
            rows.append(row)
        pages.append(
            MappingProxyType(
                {
                    "page": page,
                    "body_sha256": hashlib.sha256(response.body).hexdigest(),
                    "etag_sha256": _etag_sha256(response.headers),
                    "row_count": len(page_rows),
                }
            )
        )
        if len(page_rows) < _PAGE_SIZE:
            break
        if page == _MAX_PAGES:
            raise PilotExactTaskPrStatusCheckObservationError(
                "legacy status inventory completeness is not provable within page bound"
            )
    normalized = tuple(sorted(rows, key=lambda item: item["id"]))
    inventory_sha = hashlib.sha256(
        _canonical([dict(item) for item in normalized]).encode("utf-8")
    ).hexdigest()
    evidence_sha = hashlib.sha256(
        _canonical([dict(item) for item in pages]).encode("utf-8")
    ).hexdigest()
    return normalized, MappingProxyType(
        {
            "inventory_sha256": inventory_sha,
            "evidence_sha256": evidence_sha,
            "count": len(normalized),
            "pages": len(pages),
        }
    )


def _snapshot(
    *,
    preflight: PilotExactTaskPrMergePreflight,
    transport: ReadOnlyTransport,
) -> Mapping[str, Any]:
    check_rows, checks = _read_check_runs(
        head_sha=preflight.predicted_commit_sha,
        transport=transport,
    )
    status_rows, statuses = _read_legacy_statuses(
        head_sha=preflight.predicted_commit_sha,
        transport=transport,
    )
    combined = hashlib.sha256(
        _canonical(
            {
                "check_runs_inventory_sha256": checks["inventory_sha256"],
                "legacy_statuses_inventory_sha256": statuses["inventory_sha256"],
                "check_runs_evidence_sha256": checks["evidence_sha256"],
                "legacy_statuses_evidence_sha256": statuses["evidence_sha256"],
            }
        ).encode("utf-8")
    ).hexdigest()
    return MappingProxyType(
        {
            "check_rows": check_rows,
            "status_rows": status_rows,
            "check_runs_inventory_sha256": checks["inventory_sha256"],
            "legacy_statuses_inventory_sha256": statuses["inventory_sha256"],
            "check_runs_evidence_sha256": checks["evidence_sha256"],
            "legacy_statuses_evidence_sha256": statuses["evidence_sha256"],
            "check_run_count": checks["count"],
            "legacy_status_count": statuses["count"],
            "check_run_page_count": checks["pages"],
            "legacy_status_page_count": statuses["pages"],
            "combined_evidence_sha256": combined,
        }
    )


_live_records: dict[
    int,
    tuple[
        int,
        str,
        weakref.ReferenceType[Any],
        weakref.ReferenceType[PilotExactTaskPrMergePreflight],
        tuple[Mapping[str, Any], ...],
        tuple[Mapping[str, Any], ...],
    ],
] = {}


def _mark_authenticated(
    result: Any,
    preflight: PilotExactTaskPrMergePreflight,
    check_rows: tuple[Mapping[str, Any], ...],
    status_rows: tuple[Mapping[str, Any], ...],
) -> None:
    key = id(result)

    def cleanup(_: weakref.ReferenceType[Any]) -> None:
        _live_records.pop(key, None)

    _live_records[key] = (
        os.getpid(),
        result.sha256,
        weakref.ref(result, cleanup),
        weakref.ref(preflight),
        check_rows,
        status_rows,
    )


def _get_live_pr_status_check_observation_inputs(result: Any) -> Mapping[str, Any] | None:
    entry = _live_records.get(id(result))
    if entry is None:
        return None
    pid, digest, result_ref, preflight_ref, check_rows, status_rows = entry
    preflight = preflight_ref()
    if (
        pid != os.getpid()
        or result_ref() is not result
        or preflight is None
        or preflight.preflight_authenticated is not True
        or preflight.sha256 != result.merge_preflight_sha256
        or hashlib.sha256(
            _canonical([dict(item) for item in check_rows]).encode("utf-8")
        ).hexdigest() != result.check_runs_inventory_sha256
        or hashlib.sha256(
            _canonical([dict(item) for item in status_rows]).encode("utf-8")
        ).hexdigest() != result.legacy_statuses_inventory_sha256
        or result.sha256 != digest
    ):
        return None
    return MappingProxyType(
        {
            "merge_preflight": preflight,
            "check_runs": check_rows,
            "legacy_statuses": status_rows,
        }
    )


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_live_records.clear)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class PilotExactTaskPrStatusCheckObservation:
    merge_preflight_sha256: str
    review_disposition_sha256: str
    submitted_review_observation_sha256: str
    review_observation_checkpoint_sha256: str
    reviewer_handoff_requirements_sha256: str
    repository: str
    pull_request_number: int
    base_branch: str
    head_branch: str
    predicted_commit_sha: str
    check_runs_endpoint_sha256: str
    statuses_endpoint_sha256: str
    first_check_runs_evidence_sha256: str
    second_check_runs_evidence_sha256: str
    first_statuses_evidence_sha256: str
    second_statuses_evidence_sha256: str
    check_runs_inventory_sha256: str
    legacy_statuses_inventory_sha256: str
    first_combined_evidence_sha256: str
    second_combined_evidence_sha256: str
    check_run_count: int
    legacy_status_count: int
    check_run_page_count: int
    legacy_status_page_count: int
    first_observed_at_utc: str
    second_observed_at_utc: str
    source_merge_preflight_verified: bool = True
    exact_head_sha_bound: bool = True
    check_runs_inventory_complete: bool = True
    legacy_status_inventory_complete: bool = True
    stable_double_observation_verified: bool = True
    credential_free_reads: bool = True
    fixed_origin_reads: bool = True
    redirects_forbidden: bool = True
    response_bounded: bool = True
    pagination_bounded: bool = True
    check_run_limit_not_exceeded: bool = True
    legacy_status_limit_not_exceeded: bool = True
    fresh_merge_preflight_age_verified: bool = True
    status_check_policy_required: bool = True
    required_status_checks_evaluated: bool = False
    status_policy_evaluated: bool = False
    fresh_review_reobservation_before_merge_required: bool = True
    review_threads_preflight_required: bool = True
    branch_policy_preflight_required: bool = True
    fresh_merge_transaction_revalidation_required: bool = True
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
    authority: str = PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY
    observation_scope: str = PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCOPE
    schema: str = PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCHEMA

    def __post_init__(self) -> None:
        if (
            self.schema != PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCHEMA
            or self.authority != PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY
            or self.observation_scope != PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCOPE
        ):
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation schema/authority/scope unsupported"
            )
        for name in (
            "merge_preflight_sha256",
            "review_disposition_sha256",
            "submitted_review_observation_sha256",
            "review_observation_checkpoint_sha256",
            "reviewer_handoff_requirements_sha256",
            "check_runs_endpoint_sha256",
            "statuses_endpoint_sha256",
            "first_check_runs_evidence_sha256",
            "second_check_runs_evidence_sha256",
            "first_statuses_evidence_sha256",
            "second_statuses_evidence_sha256",
            "check_runs_inventory_sha256",
            "legacy_statuses_inventory_sha256",
            "first_combined_evidence_sha256",
            "second_combined_evidence_sha256",
        ):
            _hex64(getattr(self, name), name=name)
        _hex40(self.predicted_commit_sha, name="predicted_commit_sha")
        first = _utc(self.first_observed_at_utc, name="first_observed_at_utc")
        second = _utc(self.second_observed_at_utc, name="second_observed_at_utc")
        if second < first:
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation clock moved backwards"
            )
        if (
            self.repository != _REPOSITORY
            or self.base_branch != "main"
            or _HEAD.fullmatch(self.head_branch) is None
            or isinstance(self.pull_request_number, bool)
            or not isinstance(self.pull_request_number, int)
            or self.pull_request_number < 1
            or self.first_check_runs_evidence_sha256 != self.second_check_runs_evidence_sha256
            or self.first_statuses_evidence_sha256 != self.second_statuses_evidence_sha256
            or self.first_combined_evidence_sha256 != self.second_combined_evidence_sha256
        ):
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation exact target/evidence binding is invalid"
            )
        for name in (
            "check_run_count",
            "legacy_status_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_ROWS:
                raise PilotExactTaskPrStatusCheckObservationError(
                    f"{name} is invalid"
                )
        for name in ("check_run_page_count", "legacy_status_page_count"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= _MAX_PAGES:
                raise PilotExactTaskPrStatusCheckObservationError(
                    f"{name} is invalid"
                )
        required_true = (
            "source_merge_preflight_verified",
            "exact_head_sha_bound",
            "check_runs_inventory_complete",
            "legacy_status_inventory_complete",
            "stable_double_observation_verified",
            "credential_free_reads",
            "fixed_origin_reads",
            "redirects_forbidden",
            "response_bounded",
            "pagination_bounded",
            "check_run_limit_not_exceeded",
            "legacy_status_limit_not_exceeded",
            "fresh_merge_preflight_age_verified",
            "status_check_policy_required",
            "fresh_review_reobservation_before_merge_required",
            "review_threads_preflight_required",
            "branch_policy_preflight_required",
            "fresh_merge_transaction_revalidation_required",
        )
        forced_false = (
            "required_status_checks_evaluated",
            "status_policy_evaluated",
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
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation evidence is incomplete"
            )
        if any(getattr(self, name) is not False for name in forced_false):
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation cannot evaluate policy or grant mutation authority"
            )

    @property
    def observation_authenticated(self) -> bool:
        return _get_live_pr_status_check_observation_inputs(self) is not None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__  # type: ignore[attr-defined]
        }

    @classmethod
    def from_mapping(cls, value: Any) -> "PilotExactTaskPrStatusCheckObservation":
        if not isinstance(value, Mapping):
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation must be an object"
            )
        expected = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
        if set(value) != expected:
            raise PilotExactTaskPrStatusCheckObservationError(
                "status-check observation fields mismatch"
            )
        return cls(**dict(value))

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())


def _observe_verified_pilot_exact_task_pr_status_checks(
    *,
    merge_preflight: PilotExactTaskPrMergePreflight,
    transport: ReadOnlyTransport,
    now_provider: Any,
) -> PilotExactTaskPrStatusCheckObservation:
    checked = _require_live_preflight(merge_preflight)

    first_at = now_provider()
    _require_preflight_window(checked, at_utc=first_at)
    first = _snapshot(preflight=checked, transport=transport)

    second_at = now_provider()
    _require_preflight_window(checked, at_utc=second_at)
    if _utc(second_at, name="second_observed_at_utc") < _utc(
        first_at, name="first_observed_at_utc"
    ):
        raise PilotExactTaskPrStatusCheckObservationError(
            "clock moved backwards during status-check observation"
        )
    second = _snapshot(preflight=checked, transport=transport)

    stable_keys = (
        "check_runs_inventory_sha256",
        "legacy_statuses_inventory_sha256",
        "check_runs_evidence_sha256",
        "legacy_statuses_evidence_sha256",
        "check_run_count",
        "legacy_status_count",
        "check_run_page_count",
        "legacy_status_page_count",
        "combined_evidence_sha256",
    )
    if any(first[key] != second[key] for key in stable_keys):
        raise PilotExactTaskPrStatusCheckObservationError(
            "exact-head status inventory changed between complete observations"
        )

    result = PilotExactTaskPrStatusCheckObservation(
        merge_preflight_sha256=checked.sha256,
        review_disposition_sha256=checked.review_disposition_sha256,
        submitted_review_observation_sha256=checked.submitted_review_observation_sha256,
        review_observation_checkpoint_sha256=checked.review_observation_checkpoint_sha256,
        reviewer_handoff_requirements_sha256=checked.reviewer_handoff_requirements_sha256,
        repository=checked.repository,
        pull_request_number=checked.pull_request_number,
        base_branch=checked.base_branch,
        head_branch=checked.head_branch,
        predicted_commit_sha=checked.predicted_commit_sha,
        check_runs_endpoint_sha256=hashlib.sha256(
            _check_runs_url(checked.predicted_commit_sha, 1).encode("utf-8")
        ).hexdigest(),
        statuses_endpoint_sha256=hashlib.sha256(
            _statuses_url(checked.predicted_commit_sha, 1).encode("utf-8")
        ).hexdigest(),
        first_check_runs_evidence_sha256=str(first["check_runs_evidence_sha256"]),
        second_check_runs_evidence_sha256=str(second["check_runs_evidence_sha256"]),
        first_statuses_evidence_sha256=str(first["legacy_statuses_evidence_sha256"]),
        second_statuses_evidence_sha256=str(second["legacy_statuses_evidence_sha256"]),
        check_runs_inventory_sha256=str(first["check_runs_inventory_sha256"]),
        legacy_statuses_inventory_sha256=str(first["legacy_statuses_inventory_sha256"]),
        first_combined_evidence_sha256=str(first["combined_evidence_sha256"]),
        second_combined_evidence_sha256=str(second["combined_evidence_sha256"]),
        check_run_count=int(first["check_run_count"]),
        legacy_status_count=int(first["legacy_status_count"]),
        check_run_page_count=int(first["check_run_page_count"]),
        legacy_status_page_count=int(first["legacy_status_page_count"]),
        first_observed_at_utc=first_at,
        second_observed_at_utc=second_at,
    )
    _mark_authenticated(
        result,
        checked,
        tuple(first["check_rows"]),
        tuple(first["status_rows"]),
    )
    if result.observation_authenticated is not True:
        raise PilotExactTaskPrStatusCheckObservationError(
            "status-check observation lost live provenance"
        )
    return result


def observe_pilot_exact_task_pr_status_checks(
    merge_preflight: PilotExactTaskPrMergePreflight,
) -> PilotExactTaskPrStatusCheckObservation:
    """Observe exact-head checks/statuses only; never decide or mutate."""
    return _observe_verified_pilot_exact_task_pr_status_checks(
        merge_preflight=merge_preflight,
        transport=UrllibReadOnlyTransport(),
        now_provider=_now_utc_seconds,
    )


__all__ = [
    "PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCHEMA",
    "PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_AUTHORITY",
    "PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_SCOPE",
    "PILOT_EXACT_TASK_PR_STATUS_CHECK_OBSERVATION_MAX_PREFLIGHT_AGE_SECONDS",
    "PilotExactTaskPrStatusCheckObservationError",
    "PilotExactTaskPrStatusCheckObservation",
    "observe_pilot_exact_task_pr_status_checks",
]

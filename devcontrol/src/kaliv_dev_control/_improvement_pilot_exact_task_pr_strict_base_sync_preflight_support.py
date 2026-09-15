"""Read-only helpers for ADR-DC-087 strict base-sync preflight."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping

from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport

PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA = (
    "kaliv-rsi-dc-l16-exact-task-pr-strict-base-sync-preflight/v1"
)
PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY = (
    "observed-one-dc-l16-stable-current-base-ancestry-only"
)
PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE = (
    "credential-free-stable-main-tip-exact-head-compare-v1"
)
PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_API_VERSION = "2022-11-28"
PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS = 10

_REPOSITORY = "Ternedal/ModelRig"
_BASE_BRANCH = "main"
_TIMEOUT_SECONDS = 20
_MAX_BRANCH_BYTES = 256 * 1024
_MAX_COMPARE_BYTES = 4 * 1024 * 1024
_MAX_COMPARE_COMMITS = 100_000
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_COMPARE_STATUSES = frozenset({"ahead", "identical"})


class PilotExactTaskPrStrictBaseSyncPreflightError(ValueError):
    """Strict base-sync evidence is stale, drifted, incomplete, or unsafe."""


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
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "strict base-sync evidence is not canonical JSON"
        ) from exc


def _hex64(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX64.fullmatch(value) is None
        or value == "0" * 64
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(f"{name} is invalid")
    return value


def _hex40(value: Any, *, name: str) -> str:
    if (
        not isinstance(value, str)
        or _HEX40.fullmatch(value) is None
        or value == "0" * 40
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(f"{name} is invalid")
    return value


def _utc(value: Any, *, name: str) -> datetime:
    if not isinstance(value, str) or _UTC.fullmatch(value) is None:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            f"{name} must be canonical UTC seconds"
        )
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            f"{name} is invalid"
        ) from exc


def _now_utc_seconds() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _headers() -> Mapping[str, str]:
    return MappingProxyType(
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_API_VERSION,
            "User-Agent": "ModelRig-DevControl-ADR-DC-087",
        }
    )


def _main_url() -> str:
    return "https://api.github.com/repos/Ternedal/ModelRig/branches/main"


def _compare_url(base_sha: str, head_sha: str) -> str:
    _hex40(base_sha, name="compare base sha")
    _hex40(head_sha, name="compare head sha")
    return (
        "https://api.github.com/repos/Ternedal/ModelRig/compare/"
        f"{base_sha}...{head_sha}?per_page=1&page=1"
    )


def _get(
    transport: ReadOnlyTransport,
    url: str,
    *,
    max_bytes: int,
) -> HttpResponse:
    try:
        response = transport.get(
            url,
            headers=_headers(),
            timeout_seconds=_TIMEOUT_SECONDS,
            max_bytes=max_bytes,
        )
    except GitHubReadError as exc:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "credential-free fixed-origin GitHub strict-sync read failed"
        ) from exc
    if (
        type(response) is not HttpResponse
        or response.status != 200
        or len(response.body) > max_bytes
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "GitHub strict-sync response status/size is unsafe"
        )
    content_type = str(response.headers.get("content-type", "")).lower()
    if content_type and not (
        content_type.startswith("application/json")
        or content_type.startswith("application/vnd.github+json")
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "GitHub strict-sync response content type is unsafe"
        )
    return response


def _json(response: HttpResponse, *, name: str) -> Any:
    try:
        return json.loads(response.body.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            f"{name} is not UTF-8 JSON"
        ) from exc


def _etag_sha256(headers: Mapping[str, str]) -> str:
    etag = headers.get("etag", "")
    if (
        not isinstance(etag, str)
        or len(etag) > 512
        or any(marker in etag for marker in ("\r", "\n", "\x00"))
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError("GitHub ETag is invalid")
    return hashlib.sha256(etag.encode("utf-8")).hexdigest()


def _read_main_tip(*, transport: ReadOnlyTransport) -> Mapping[str, str]:
    url = _main_url()
    response = _get(transport, url, max_bytes=_MAX_BRANCH_BYTES)
    raw = _json(response, name="main branch response")
    commit = raw.get("commit") if isinstance(raw, Mapping) else None
    if (
        not isinstance(raw, Mapping)
        or raw.get("name") != _BASE_BRANCH
        or not isinstance(commit, Mapping)
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "main branch response identity is invalid"
        )
    tip = _hex40(commit.get("sha"), name="main branch tip sha")
    return MappingProxyType(
        {
            "tip_sha": tip,
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(response.body).hexdigest(),
            "response_etag_sha256": _etag_sha256(response.headers),
        }
    )


def _read_compare(
    *,
    base_sha: str,
    head_sha: str,
    transport: ReadOnlyTransport,
) -> Mapping[str, Any]:
    url = _compare_url(base_sha, head_sha)
    response = _get(transport, url, max_bytes=_MAX_COMPARE_BYTES)
    raw = _json(response, name="compare response")
    if not isinstance(raw, Mapping):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "compare response is not an object"
        )
    status = raw.get("status")
    ahead_by = raw.get("ahead_by")
    behind_by = raw.get("behind_by")
    total_commits = raw.get("total_commits")
    base_commit = raw.get("base_commit")
    merge_base_commit = raw.get("merge_base_commit")
    if (
        status not in _COMPARE_STATUSES
        or isinstance(ahead_by, bool)
        or not isinstance(ahead_by, int)
        or not 0 <= ahead_by <= _MAX_COMPARE_COMMITS
        or isinstance(behind_by, bool)
        or not isinstance(behind_by, int)
        or not 0 <= behind_by <= _MAX_COMPARE_COMMITS
        or isinstance(total_commits, bool)
        or not isinstance(total_commits, int)
        or not 0 <= total_commits <= _MAX_COMPARE_COMMITS
        or not isinstance(base_commit, Mapping)
        or not isinstance(merge_base_commit, Mapping)
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "compare response graph metadata is invalid"
        )
    observed_base = _hex40(base_commit.get("sha"), name="compare base_commit sha")
    observed_merge_base = _hex40(
        merge_base_commit.get("sha"), name="compare merge_base_commit sha"
    )
    if (
        behind_by != 0
        or observed_base != base_sha
        or observed_merge_base != base_sha
        or total_commits != ahead_by
        or (status == "identical" and (head_sha != base_sha or ahead_by != 0))
        or (status == "ahead" and (head_sha == base_sha or ahead_by < 1))
    ):
        raise PilotExactTaskPrStrictBaseSyncPreflightError(
            "exact head does not provably contain the observed current base"
        )
    return MappingProxyType(
        {
            "status": status,
            "ahead_by": ahead_by,
            "behind_by": behind_by,
            "total_commits": total_commits,
            "base_commit_sha": observed_base,
            "merge_base_sha": observed_merge_base,
            "request_url_sha256": hashlib.sha256(url.encode("utf-8")).hexdigest(),
            "response_body_sha256": hashlib.sha256(response.body).hexdigest(),
            "response_etag_sha256": _etag_sha256(response.headers),
        }
    )


__all__: list[str] = []

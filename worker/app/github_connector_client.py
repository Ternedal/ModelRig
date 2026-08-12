"""Dormant fixed-origin GitHub read client for T-036.

The client is intentionally one layer above credentials and sockets.  It owns
what the model/operator is allowed to request; an injected transport owns how a
trusted credential reaches ``api.github.com``.  That split is load-bearing:

* callers can name only an exact granted repository, one documented read
  operation and (where required) a positive numeric object id;
* the client authorizes against the durable grant store BEFORE transport;
* the transport receives a fixed-origin GET request and no user-supplied
  Authorization/Cookie header surface;
* response identity is checked against the requested repository/object before
  anything becomes result data;
* pagination is structurally absent in this single-object pilot;
* rate-limit and 304 revalidation are explicit, and stale cache is never used
  as a silent network-failure fallback;
* source receipts bind the representation ETag (hashed) and any available
  GitHub SHA, without storing raw content or credentials.

Nothing in this module performs network I/O or registers a ToolGate tool.
``production_activation`` remains false in the grant/source authority it uses.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Mapping, Protocol

from .github_connector_contract import (
    GitHubConnectorContractError,
    GitHubConnectorGrantStore,
    GitHubSourceReceipt,
    normalize_operation,
    normalize_repository,
)

GITHUB_API_ORIGIN = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024

_SHA_RE = re.compile(r"^[0-9a-f]{40,64}$")
_ETAG_MAX = 512


class GitHubReadClientError(RuntimeError):
    """Base class for deterministic GitHub read failures."""


class GitHubReadContractError(GitHubReadClientError):
    """Caller or response contradicted the fixed read contract."""


class GitHubReadDenied(GitHubReadClientError):
    """GitHub did not grant access, without leaking whether an object exists."""


class GitHubReadRateLimited(GitHubReadClientError):
    def __init__(self, reset_at: int | None) -> None:
        super().__init__(
            "GitHub read rate limited"
            + (f" until unix:{reset_at}" if reset_at is not None else "")
        )
        self.reset_at = reset_at


class GitHubReadRemoteError(GitHubReadClientError):
    """Remote/transport response was not a trustworthy single-object result."""


@dataclass(frozen=True)
class GitHubTransportRequest:
    """GET-only request description. Credentials are deliberately not a field."""

    path: str
    headers: tuple[tuple[str, str], ...]
    max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES
    origin: str = GITHUB_API_ORIGIN

    def __post_init__(self) -> None:
        if self.origin != GITHUB_API_ORIGIN:
            raise GitHubReadContractError("GitHub API origin is fixed")
        if not isinstance(self.path, str) or not self.path.startswith("/"):
            raise GitHubReadContractError("GitHub API path must be absolute-path form")
        if "?" in self.path or "#" in self.path or "\\" in self.path:
            raise GitHubReadContractError("GitHub API path cannot carry query/fragment aliases")
        if "//" in self.path or "/../" in self.path or self.path.endswith("/.."):
            raise GitHubReadContractError("GitHub API path is non-canonical")
        if isinstance(self.max_response_bytes, bool) or not isinstance(
            self.max_response_bytes, int
        ):
            raise GitHubReadContractError("max_response_bytes must be an integer")
        if not 1 <= self.max_response_bytes <= DEFAULT_MAX_RESPONSE_BYTES:
            raise GitHubReadContractError("max_response_bytes exceeds pilot ceiling")

        allowed = {"accept", "x-github-api-version", "if-none-match"}
        seen: set[str] = set()
        for name, value in self.headers:
            if not isinstance(name, str) or not isinstance(value, str):
                raise GitHubReadContractError("GitHub request headers must be strings")
            lower = name.strip().lower()
            if lower not in allowed or lower in seen:
                raise GitHubReadContractError("GitHub request header surface is closed")
            if "\r" in value or "\n" in value or "\x00" in value:
                raise GitHubReadContractError("GitHub request header value is invalid")
            seen.add(lower)
        if seen != {name for name, _ in self.headers}:
            # Require callers to hand the canonical lowercase form to transport.
            raise GitHubReadContractError("GitHub request header names must be canonical")
        if "accept" not in seen or "x-github-api-version" not in seen:
            raise GitHubReadContractError("GitHub media/version headers are required")

    @property
    def url(self) -> str:
        return self.origin + self.path


@dataclass(frozen=True)
class GitHubTransportResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def __post_init__(self) -> None:
        if isinstance(self.status, bool) or not isinstance(self.status, int):
            raise GitHubReadContractError("GitHub HTTP status must be an integer")
        if not 100 <= self.status <= 599:
            raise GitHubReadContractError("GitHub HTTP status is invalid")
        if not isinstance(self.body, bytes):
            raise GitHubReadContractError("GitHub response body must be bytes")
        clean: dict[str, str] = {}
        for raw_name, raw_value in self.headers.items():
            if not isinstance(raw_name, str) or not isinstance(raw_value, str):
                raise GitHubReadContractError("GitHub response headers must be strings")
            name = raw_name.strip().lower()
            value = raw_value.strip()
            if not name or "\r" in value or "\n" in value or "\x00" in value:
                raise GitHubReadContractError("GitHub response header is invalid")
            if name in clean:
                raise GitHubReadContractError("duplicate normalized GitHub response header")
            clean[name] = value
        object.__setattr__(self, "headers", clean)


class GitHubReadTransport(Protocol):
    """Credential/socket seam. Implementations may only execute this GET form."""

    def get(self, request: GitHubTransportRequest) -> GitHubTransportResponse:
        ...


@dataclass(frozen=True)
class GitHubReadResult:
    repository: str
    operation: str
    object_id: str
    document: dict
    source: GitHubSourceReceipt
    revalidated_cache: bool


@dataclass(frozen=True)
class _CacheEntry:
    etag: str
    repository_id: int
    object_id: str
    document: dict
    revision: str


class GitHubReadClient:
    """Authorize, fetch and validate one GitHub object without hidden widening."""

    def __init__(
        self,
        *,
        grants: GitHubConnectorGrantStore,
        transport: GitHubReadTransport,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int):
            raise GitHubReadContractError("max_response_bytes must be an integer")
        if not 1 <= max_response_bytes <= DEFAULT_MAX_RESPONSE_BYTES:
            raise GitHubReadContractError("max_response_bytes exceeds pilot ceiling")
        self._grants = grants
        self._transport = transport
        self._max = max_response_bytes
        self._cache: dict[tuple[str, str, str, str], _CacheEntry] = {}

    def read(
        self,
        grant_id: str,
        *,
        repository: str,
        operation: str,
        object_id: int | None = None,
        now: int,
    ) -> GitHubReadResult:
        repository = normalize_repository(repository)
        operation = normalize_operation(operation)
        selector = _selector(operation, object_id)

        # Load current durable authority before even constructing a transport
        # request. Revocation therefore cannot be bypassed by the local cache.
        grant = self._grants.authorize(
            grant_id, repository=repository, operation=operation
        )
        key = (grant.grant_id, repository, operation, selector)
        cached = self._cache.get(key)
        request = GitHubTransportRequest(
            path=_path(repository, operation, selector),
            headers=_request_headers(cached.etag if cached is not None else None),
            max_response_bytes=self._max,
        )

        response = self._transport.get(request)
        if len(response.body) > self._max:
            raise GitHubReadRemoteError("GitHub response exceeded byte ceiling")
        _reject_hidden_pagination(response.headers)
        remaining = _optional_uint_header(response.headers, "x-ratelimit-remaining")
        reset = _optional_uint_header(response.headers, "x-ratelimit-reset")

        if response.status == 429 or (response.status == 403 and remaining == 0):
            raise GitHubReadRateLimited(reset)
        if response.status in {401, 403, 404}:
            # Deliberately merge missing/private/forbidden into one user-facing
            # class so the connector does not become a repository oracle.
            raise GitHubReadDenied("GitHub object unavailable within current access")
        if response.status == 304:
            if cached is None:
                raise GitHubReadRemoteError("GitHub returned 304 without exact cache evidence")
            etag = _etag(response.headers)
            if etag is not None and etag != cached.etag:
                raise GitHubReadRemoteError("GitHub 304 contradicted cached ETag")
            source = _source(
                grant_id=grant.grant_id,
                scope_sha256=grant.scope.digest,
                repository=repository,
                repository_id=cached.repository_id,
                object_type=operation,
                object_id=cached.object_id,
                revision=cached.revision,
                now=now,
            )
            return GitHubReadResult(
                repository=repository,
                operation=operation,
                object_id=cached.object_id,
                document=dict(cached.document),
                source=source,
                revalidated_cache=True,
            )
        if response.status != 200:
            raise GitHubReadRemoteError(f"unexpected GitHub HTTP status {response.status}")

        etag = _etag(response.headers)
        if etag is None:
            raise GitHubReadRemoteError("GitHub single-object response omitted ETag")
        document = _json_object(response.body)
        repository_id, stable_object_id, sha = _validate_identity(
            document, repository=repository, operation=operation, selector=selector
        )
        revision = _revision(etag, sha)
        entry = _CacheEntry(
            etag=etag,
            repository_id=repository_id,
            object_id=stable_object_id,
            document=dict(document),
            revision=revision,
        )
        self._cache[key] = entry
        source = _source(
            grant_id=grant.grant_id,
            scope_sha256=grant.scope.digest,
            repository=repository,
            repository_id=repository_id,
            object_type=operation,
            object_id=stable_object_id,
            revision=revision,
            now=now,
        )
        return GitHubReadResult(
            repository=repository,
            operation=operation,
            object_id=stable_object_id,
            document=document,
            source=source,
            revalidated_cache=False,
        )


def _selector(operation: str, object_id: int | None) -> str:
    if operation == "repository":
        if object_id is not None:
            raise GitHubReadContractError("repository read does not accept object_id")
        return "repository"
    if isinstance(object_id, bool) or not isinstance(object_id, int) or object_id <= 0:
        raise GitHubReadContractError(f"{operation} read requires positive numeric object_id")
    if object_id > 9_223_372_036_854_775_807:
        raise GitHubReadContractError("GitHub object_id exceeds signed 64-bit range")
    return str(object_id)


def _path(repository: str, operation: str, selector: str) -> str:
    owner, repo = repository.split("/", 1)
    base = f"/repos/{owner}/{repo}"
    if operation == "repository":
        return base
    if operation == "issue":
        return f"{base}/issues/{selector}"
    if operation == "pull_request":
        return f"{base}/pulls/{selector}"
    if operation == "workflow_run":
        return f"{base}/actions/runs/{selector}"
    raise GitHubReadContractError("unsupported GitHub read operation")


def _request_headers(etag: str | None) -> tuple[tuple[str, str], ...]:
    headers = [
        ("accept", "application/vnd.github+json"),
        ("x-github-api-version", GITHUB_API_VERSION),
    ]
    if etag is not None:
        headers.append(("if-none-match", etag))
    return tuple(headers)


def _optional_uint_header(headers: Mapping[str, str], name: str) -> int | None:
    raw = headers.get(name)
    if raw is None:
        return None
    if not raw or not raw.isascii() or not raw.isdecimal():
        raise GitHubReadRemoteError(f"GitHub {name} header is not a canonical integer")
    value = int(raw)
    if value > 9_223_372_036_854_775_807:
        raise GitHubReadRemoteError(f"GitHub {name} header exceeds integer range")
    return value


def _etag(headers: Mapping[str, str]) -> str | None:
    raw = headers.get("etag")
    if raw is None:
        return None
    if not raw or len(raw) > _ETAG_MAX or "\r" in raw or "\n" in raw or "\x00" in raw:
        raise GitHubReadRemoteError("GitHub ETag is invalid")
    return raw


def _reject_hidden_pagination(headers: Mapping[str, str]) -> None:
    link = headers.get("link", "")
    compact = link.replace(" ", "").lower()
    if 'rel="next"' in compact or "rel=next" in compact:
        raise GitHubReadRemoteError(
            "single-object GitHub endpoint unexpectedly advertised pagination"
        )


def _json_object(body: bytes) -> dict:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GitHubReadRemoteError("GitHub response was not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise GitHubReadRemoteError("GitHub single-object response must be a JSON object")
    return value


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GitHubReadRemoteError(f"GitHub {field} must be a positive integer")
    return value


def _canonical_full_name(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise GitHubReadRemoteError(f"GitHub {field} must be a repository name")
    try:
        return normalize_repository(value)
    except GitHubConnectorContractError as exc:
        raise GitHubReadRemoteError(f"GitHub {field} is not canonical repository evidence") from exc


def _sha(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SHA_RE.fullmatch(value.lower()):
        raise GitHubReadRemoteError(f"GitHub {field} must be a commit SHA")
    return value.lower()


def _validate_identity(
    document: dict,
    *,
    repository: str,
    operation: str,
    selector: str,
) -> tuple[int, str, str | None]:
    if operation == "repository":
        repository_id = _positive_int(document.get("id"), "repository.id")
        if _canonical_full_name(document.get("full_name"), "repository.full_name") != repository:
            raise GitHubReadRemoteError("GitHub repository response crossed granted scope")
        return repository_id, str(repository_id), None

    if operation == "issue":
        if "pull_request" in document:
            raise GitHubReadRemoteError("issue endpoint returned a pull request object")
        repository_id = _positive_int(document.get("repository_id"), "issue.repository_id")
        number = _positive_int(document.get("number"), "issue.number")
        if str(number) != selector:
            raise GitHubReadRemoteError("GitHub issue response object id mismatch")
        expected_url = GITHUB_API_ORIGIN + "/repos/" + repository
        repository_url = document.get("repository_url")
        if not isinstance(repository_url, str) or repository_url.lower() != expected_url:
            raise GitHubReadRemoteError("GitHub issue response crossed granted repository")
        return repository_id, str(number), None

    if operation == "pull_request":
        number = _positive_int(document.get("number"), "pull_request.number")
        if str(number) != selector:
            raise GitHubReadRemoteError("GitHub pull request object id mismatch")
        base = document.get("base")
        if not isinstance(base, dict):
            raise GitHubReadRemoteError("GitHub pull request omitted base repository evidence")
        repo = base.get("repo")
        if not isinstance(repo, dict):
            raise GitHubReadRemoteError("GitHub pull request omitted base.repo")
        if _canonical_full_name(repo.get("full_name"), "pull_request.base.repo.full_name") != repository:
            raise GitHubReadRemoteError("GitHub pull request crossed granted repository")
        repository_id = _positive_int(repo.get("id"), "pull_request.base.repo.id")
        head = document.get("head")
        if not isinstance(head, dict):
            raise GitHubReadRemoteError("GitHub pull request omitted head revision")
        return repository_id, str(number), _sha(head.get("sha"), "pull_request.head.sha")

    if operation == "workflow_run":
        run_id = _positive_int(document.get("id"), "workflow_run.id")
        if str(run_id) != selector:
            raise GitHubReadRemoteError("GitHub workflow run object id mismatch")
        repo = document.get("repository")
        if not isinstance(repo, dict):
            raise GitHubReadRemoteError("GitHub workflow run omitted repository evidence")
        if _canonical_full_name(repo.get("full_name"), "workflow_run.repository.full_name") != repository:
            raise GitHubReadRemoteError("GitHub workflow run crossed granted repository")
        repository_id = _positive_int(repo.get("id"), "workflow_run.repository.id")
        return repository_id, str(run_id), _sha(document.get("head_sha"), "workflow_run.head_sha")

    raise GitHubReadContractError("unsupported GitHub read operation")


def _revision(etag: str, sha: str | None) -> str:
    etag_digest = hashlib.sha256(etag.encode("utf-8")).hexdigest()
    revision = f"etag-sha256:{etag_digest}"
    if sha is not None:
        revision = f"sha:{sha}+{revision}"
    return revision


def _source(
    *,
    grant_id: str,
    scope_sha256: str,
    repository: str,
    repository_id: int,
    object_type: str,
    object_id: str,
    revision: str,
    now: int,
) -> GitHubSourceReceipt:
    return GitHubSourceReceipt(
        grant_id=grant_id,
        scope_sha256=scope_sha256,
        repository=repository,
        repository_id=repository_id,
        object_type=object_type,  # type: ignore[arg-type]
        object_id=object_id,
        revision=revision,
        retrieved_at=now,
    )

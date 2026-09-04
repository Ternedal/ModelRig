"""Feature-gated ToolGate bridge for the T-036 GitHub read-only pilot.

This is the first runtime composition of the qualified T-036 layers.  It keeps
all authority in the durable grant store, keeps credentials behind the pinned
transport, and adds explicit connector audit evidence instead of asking later
consumers to infer a connector from ToolGate ``origin`` or a tool name.

The pilot is absent unless ``KALIV_GITHUB_CONNECTOR_PILOT`` is explicitly on.
Even when mounted it exposes no model-visible create/revoke operation: the only
model tool is ``github_read`` and its ``network=public`` descriptor means the
existing ToolGate requires a fresh human confirmation before the outbound read.
``production_activation`` remains false in every grant/source receipt.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from fastapi import APIRouter, HTTPException, Query, Request

from . import paths as _paths
from . import tools as _tools
from .github_connector_client import (
    GitHubReadClientError,
    GitHubReadDenied,
    GitHubReadRateLimited,
    GitHubReadResult,
)
from .github_connector_contract import (
    GitHubConnectorContractError,
    GitHubConnectorDenied,
    GitHubConnectorGrant,
    GitHubConnectorGrantStore,
    normalize_operation,
    normalize_repository,
)
from .github_connector_transport import (
    AccountBoundGitHubReadClient,
    EnvironmentFileGitHubCredentialProvider,
    GitHubCredentialError,
    GitHubPinnedTransport,
)
from .netguard import is_loopback

_FEATURE_ENV = "KALIV_GITHUB_CONNECTOR_PILOT"
_TOOL_NAME = "github_read"
_AUDIT_DB = _paths.resolve(
    "./kaliv-github-connector-audit.db", env="KALIV_GITHUB_CONNECTOR_AUDIT_DB"
)
_ALLOWED_OPERATIONS = ("repository", "issue", "pull_request", "workflow_run")


def github_connector_pilot_enabled() -> bool:
    return os.getenv(_FEATURE_ENV, "0").strip().lower() in {"1", "true", "on"}


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())


class GitHubConnectorAuditLog:
    """Privacy-minimized connector evidence; never stores body/content/token.

    ToolGate's generic audit remains the authority for confirmation outcomes.
    This ledger answers the connector-specific questions T-036/T-044 need:
    which connector, exact repository/operation, which durable grant/scope, and
    which source revision actually came back.  Those facts are recorded as
    fields, not reconstructed from ``origin`` or result text.
    """

    def __init__(self, path: str = _AUDIT_DB) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS github_connector_audit (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                ts            TEXT NOT NULL,
                connector     TEXT NOT NULL,
                account       TEXT,
                repository    TEXT NOT NULL,
                operation     TEXT NOT NULL,
                object_id     TEXT,
                outcome       TEXT NOT NULL,
                grant_id      TEXT,
                scope_sha256  TEXT,
                revision      TEXT,
                duration_ms   INTEGER NOT NULL,
                detail        TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def record(
        self,
        *,
        repository: str,
        operation: str,
        outcome: str,
        duration_ms: int,
        detail: str,
        object_id: str | None = None,
        account: str | None = None,
        grant_id: str | None = None,
        scope_sha256: str | None = None,
        revision: str | None = None,
    ) -> None:
        # Only controlled categorical detail strings are accepted by callers;
        # exception text and GitHub document content never enter this method.
        if outcome not in {"executed", "blocked", "error"}:
            raise ValueError("unsupported GitHub connector audit outcome")
        if not isinstance(duration_ms, int) or isinstance(duration_ms, bool) or duration_ms < 0:
            raise ValueError("duration_ms must be a non-negative integer")
        if not isinstance(detail, str) or not detail or len(detail) > 120:
            raise ValueError("detail must contain 1..120 characters")
        with self._lock:
            self._db.execute(
                """
                INSERT INTO github_connector_audit (
                    ts, connector, account, repository, operation, object_id,
                    outcome, grant_id, scope_sha256, revision, duration_ms, detail
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    _iso_now(),
                    "github",
                    account,
                    repository,
                    operation,
                    object_id,
                    outcome,
                    grant_id,
                    scope_sha256,
                    revision,
                    duration_ms,
                    detail,
                ),
            )
            self._db.commit()

    def recent(
        self,
        limit: int = 50,
        *,
        repository: str | None = None,
        operation: str | None = None,
        grant_id: str | None = None,
        outcome: str | None = None,
    ) -> list[dict]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise ValueError("limit must be an integer")
        limit = max(1, min(limit, 500))
        clauses: list[str] = []
        values: list[object] = []
        if repository is not None:
            repository = normalize_repository(repository)
            clauses.append("repository=?")
            values.append(repository)
        if operation is not None:
            operation = normalize_operation(operation)
            clauses.append("operation=?")
            values.append(operation)
        if grant_id is not None:
            clauses.append("grant_id=?")
            values.append(grant_id)
        if outcome is not None:
            if outcome not in {"executed", "blocked", "error"}:
                raise ValueError("unsupported GitHub connector audit outcome")
            clauses.append("outcome=?")
            values.append(outcome)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        values.append(limit)
        with self._lock:
            rows = self._db.execute(
                "SELECT ts, connector, account, repository, operation, object_id,"
                " outcome, grant_id, scope_sha256, revision, duration_ms, detail"
                f" FROM github_connector_audit{where} ORDER BY id DESC LIMIT ?",
                tuple(values),
            ).fetchall()
        return [dict(row) for row in rows]


class GitHubReader(Protocol):
    @property
    def account(self) -> str:
        ...

    def read(
        self,
        grant_id: str,
        *,
        repository: str,
        operation: str,
        object_id: int | None = None,
        now: int,
    ) -> GitHubReadResult:
        ...


@dataclass
class GitHubConnectorPilotRuntime:
    grants: GitHubConnectorGrantStore
    reader: GitHubReader
    audit: GitHubConnectorAuditLog
    now: Callable[[], int] = lambda: int(time.time())

    def _matches(self, repository: str, operation: str) -> tuple[GitHubConnectorGrant, ...]:
        return tuple(
            grant
            for grant in self.grants.list_grants()
            if grant.scope.account == self.reader.account
            and grant.scope.allows(repository, operation)
        )

    def _historical_match(
        self, repository: str, operation: str
    ) -> GitHubConnectorGrant | None:
        matches = tuple(
            grant
            for grant in self.grants.list_grants(include_revoked=True)
            if grant.scope.account == self.reader.account
            and grant.scope.allows(repository, operation)
        )
        return matches[0] if len(matches) == 1 else None

    def run(self, args: dict) -> str:
        started = time.time()
        repository = "unknown/unknown"
        operation = "repository"
        requested_object: str | None = None
        selected: GitHubConnectorGrant | None = None
        try:
            if not isinstance(args, dict):
                raise GitHubConnectorContractError("GitHub read arguments must be an object")
            repository = normalize_repository(args.get("repository"))
            operation = normalize_operation(args.get("operation"))
            raw_object = args.get("object_id")
            if operation == "repository":
                if raw_object is not None:
                    raise GitHubConnectorContractError(
                        "repository read does not accept object_id"
                    )
                object_id = None
            else:
                if isinstance(raw_object, bool) or not isinstance(raw_object, int) or raw_object <= 0:
                    raise GitHubConnectorContractError(
                        f"{operation} read requires positive numeric object_id"
                    )
                object_id = raw_object
                requested_object = str(raw_object)

            matches = self._matches(repository, operation)
            if len(matches) != 1:
                selected = self._historical_match(repository, operation)
                detail = "no_active_exact_grant" if not matches else "ambiguous_active_exact_grants"
                self._record(
                    repository=repository,
                    operation=operation,
                    object_id=requested_object,
                    outcome="blocked",
                    detail=detail,
                    selected=selected,
                    started=started,
                )
                if not matches:
                    raise _tools.ToolDenied(
                        "GitHub-læsningen har ingen aktiv tilladelse til præcis dette repository og denne operation"
                    )
                raise _tools.ToolDenied(
                    "GitHub-læsningen har flere aktive tilladelser til samme scope; ryd scope op før kaldet"
                )
            selected = matches[0]

            result = self.reader.read(
                selected.grant_id,
                repository=repository,
                operation=operation,
                object_id=object_id,
                now=self.now(),
            )
        except _tools.ToolDenied:
            raise
        except (GitHubConnectorContractError, GitHubConnectorDenied, GitHubReadDenied) as exc:
            self._record(
                repository=repository,
                operation=operation,
                object_id=requested_object,
                outcome="blocked",
                detail="authority_or_access_denied",
                selected=selected,
                started=started,
            )
            raise _tools.ToolDenied("GitHub-læsningen blev afvist af aktivt scope/adgang") from exc
        except GitHubReadRateLimited as exc:
            self._record(
                repository=repository,
                operation=operation,
                object_id=requested_object,
                outcome="error",
                detail="rate_limited",
                selected=selected,
                started=started,
            )
            suffix = f" indtil unix:{exc.reset_at}" if exc.reset_at is not None else ""
            raise _tools.ToolError(f"GitHub rate-limit nået{suffix}") from exc
        except (GitHubCredentialError, GitHubReadClientError) as exc:
            self._record(
                repository=repository,
                operation=operation,
                object_id=requested_object,
                outcome="error",
                detail="connector_execution_failed",
                selected=selected,
                started=started,
            )
            raise _tools.ToolError("GitHub connector-kaldet fejlede") from exc

        self._record(
            repository=result.repository,
            operation=result.operation,
            object_id=result.object_id,
            outcome="executed",
            detail="revalidated_cache" if result.revalidated_cache else "fresh_remote_read",
            selected=selected,
            revision=result.source.revision,
            started=started,
        )
        # Deliberate read-only projection: this first ToolGate slice does not
        # return issue/PR bodies or arbitrary nested fields.  It is enough for
        # repo/issue/PR/CI status summaries while keeping the legacy generic
        # ToolGate result-summary row from becoming a private-content mirror.
        return json.dumps(
            {
                "schema": "kaliv-github-tool-result/v1",
                "connector": "github",
                "repository": result.repository,
                "operation": result.operation,
                "object_id": result.object_id,
                "source": result.source.to_dict(),
                "revalidated_cache": result.revalidated_cache,
                "document": _project_document(result.operation, result.document),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _record(
        self,
        *,
        repository: str,
        operation: str,
        object_id: str | None,
        outcome: str,
        detail: str,
        selected: GitHubConnectorGrant | None,
        started: float,
        revision: str | None = None,
    ) -> None:
        self.audit.record(
            repository=repository,
            operation=operation,
            object_id=object_id,
            outcome=outcome,
            account=self.reader.account,
            grant_id=selected.grant_id if selected is not None else None,
            scope_sha256=selected.scope.digest if selected is not None else None,
            revision=revision,
            duration_ms=max(0, int((time.time() - started) * 1000)),
            detail=detail,
        )


def _login(value) -> str | None:
    if isinstance(value, dict):
        login = value.get("login")
        return login if isinstance(login, str) else None
    return None


def _project_document(operation: str, document: dict) -> dict:
    """Closed projection: no body, patch, diff, log text or arbitrary nesting."""
    if operation == "repository":
        keys = (
            "id", "full_name", "private", "visibility", "default_branch",
            "fork", "archived", "disabled", "created_at", "updated_at", "pushed_at",
        )
        return {key: document.get(key) for key in keys if key in document}
    if operation == "issue":
        out = {
            key: document.get(key)
            for key in (
                "id", "number", "title", "state", "state_reason", "locked",
                "comments", "created_at", "updated_at", "closed_at",
            )
            if key in document
        }
        out["author"] = _login(document.get("user"))
        labels = document.get("labels")
        if isinstance(labels, list):
            out["labels"] = [
                item.get("name") for item in labels
                if isinstance(item, dict) and isinstance(item.get("name"), str)
            ][:50]
        return out
    if operation == "pull_request":
        out = {
            key: document.get(key)
            for key in (
                "id", "number", "title", "state", "draft", "merged",
                "mergeable", "mergeable_state", "comments", "review_comments",
                "commits", "additions", "deletions", "changed_files",
                "created_at", "updated_at", "closed_at", "merged_at",
            )
            if key in document
        }
        out["author"] = _login(document.get("user"))
        for side in ("base", "head"):
            value = document.get(side)
            if isinstance(value, dict):
                repo = value.get("repo")
                out[side] = {
                    "ref": value.get("ref") if isinstance(value.get("ref"), str) else None,
                    "sha": value.get("sha") if isinstance(value.get("sha"), str) else None,
                    "repository": repo.get("full_name")
                    if isinstance(repo, dict) and isinstance(repo.get("full_name"), str)
                    else None,
                }
        return out
    if operation == "workflow_run":
        out = {
            key: document.get(key)
            for key in (
                "id", "name", "display_title", "event", "status", "conclusion",
                "run_number", "run_attempt", "head_branch", "head_sha",
                "created_at", "updated_at", "run_started_at",
            )
            if key in document
        }
        out["actor"] = _login(document.get("actor"))
        out["triggering_actor"] = _login(document.get("triggering_actor"))
        return out
    raise GitHubConnectorContractError("unsupported GitHub read operation")


def build_github_read_tool(runtime: GitHubConnectorPilotRuntime) -> _tools.Tool:
    return _tools.Tool(
        name=_TOOL_NAME,
        risk="read",
        impact="read",
        idempotent=False,
        schedulable=False,
        unschedulable_because=(
            "GitHub-piloten laver et eksternt, scope-bundet kald og kræver et frisk bekræftelseskort"
        ),
        network="public",
        network_destinations=("api.github.com",),
        sensitivity="private",
        description=(
            "Læs ét eksplicit GitHub repository-, issue-, pull request- eller workflow-run objekt "
            "inden for en aktiv, tilbagekaldelig repository-tilladelse. Read-only."
        ),
        params={
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Præcist owner/repo, fx Ternedal/ModelRig",
                },
                "operation": {
                    "type": "string",
                    "enum": list(_ALLOWED_OPERATIONS),
                },
                "object_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Påkrævet for issue, pull_request og workflow_run; udelades for repository",
                },
            },
            "required": ["repository", "operation"],
            "additionalProperties": False,
        },
        run=runtime.run,
    )


_DEFAULT_RUNTIME: GitHubConnectorPilotRuntime | None = None
_DEFAULT_LOCK = threading.Lock()


def _default_runtime() -> GitHubConnectorPilotRuntime:
    global _DEFAULT_RUNTIME
    with _DEFAULT_LOCK:
        if _DEFAULT_RUNTIME is None:
            grants = GitHubConnectorGrantStore()
            credentials = EnvironmentFileGitHubCredentialProvider()
            transport = GitHubPinnedTransport(credentials=credentials)
            reader = AccountBoundGitHubReadClient(grants=grants, transport=transport)
            _DEFAULT_RUNTIME = GitHubConnectorPilotRuntime(
                grants=grants,
                reader=reader,
                audit=GitHubConnectorAuditLog(),
            )
        return _DEFAULT_RUNTIME


def _lazy_run(args: dict) -> str:
    try:
        return _default_runtime().run(args)
    except GitHubCredentialError as exc:
        raise _tools.ToolError("GitHub connector-konfiguration mangler eller er ugyldig") from exc


def _default_tool() -> _tools.Tool:
    # Keep token-file parsing and DB opening lazy. Registration advertises a
    # capability; execution is the first point that needs operator config.
    runtime_proxy = type("_RuntimeProxy", (), {"run": staticmethod(_lazy_run)})()
    return build_github_read_tool(runtime_proxy)  # type: ignore[arg-type]


def _loopback_allowed(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host == "testclient" or is_loopback(host)


def _require_loopback(request: Request) -> None:
    if not _loopback_allowed(request):
        raise HTTPException(status_code=403, detail="GitHub connector operator view is loopback-only")


def build_github_connector_router(
    *,
    grant_factory: Callable[[], GitHubConnectorGrantStore] = GitHubConnectorGrantStore,
    audit_factory: Callable[[], GitHubConnectorAuditLog] = GitHubConnectorAuditLog,
) -> APIRouter:
    router = APIRouter(prefix="/github-connector", tags=["github-connector"])

    @router.get("/grants")
    def grants_view(request: Request, include_revoked: bool = False) -> dict:
        _require_loopback(request)
        store = grant_factory()
        try:
            return {
                "connector": "github",
                "grants": [
                    grant.to_dict()
                    for grant in store.list_grants(include_revoked=include_revoked)
                ],
                "production_activation": False,
            }
        finally:
            store.close()

    @router.get("/audit")
    def audit_view(
        request: Request,
        limit: int = Query(default=50, ge=1, le=500),
        repository: str | None = None,
        operation: str | None = None,
        grant_id: str | None = None,
        outcome: str | None = None,
    ) -> dict:
        _require_loopback(request)
        audit = audit_factory()
        try:
            try:
                entries = audit.recent(
                    limit,
                    repository=repository,
                    operation=operation,
                    grant_id=grant_id,
                    outcome=outcome,
                )
            except (ValueError, GitHubConnectorContractError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {
                "connector": "github",
                "entries": entries,
                "production_activation": False,
            }
        finally:
            audit.close()

    return router


def register_github_connector_pilot(app) -> bool:
    """Register exactly once, and only under explicit default-off opt-in."""
    if not github_connector_pilot_enabled():
        return False
    existing = _tools.REGISTRY.get(_TOOL_NAME)
    if existing is not None:
        # Idempotent for reloads only if it is recognisably this pilot.
        if existing.network == "public" and existing.network_destinations == ("api.github.com",):
            return False
        raise RuntimeError("github_read is already registered by another capability")
    _tools.REGISTRY[_TOOL_NAME] = _default_tool()
    app.include_router(build_github_connector_router())
    return True

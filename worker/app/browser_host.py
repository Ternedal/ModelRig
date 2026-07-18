"""Single-request browser process boundary for dormant read-only research.

The host deliberately does not import BrowserUse, Playwright or an LLM. A later
adapter runs inside this process and implements ``BrowserBackend``. The host owns
JSON validation, policy budgets, evidence receipts, citations, timeout handling
and error normalization so an adapter cannot redefine ModelRig's trust boundary.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Protocol

from .research_contract import (
    Citation,
    ReadOnlyBrowserPolicy,
    ResearchContractError,
    ResearchRequest,
    ResearchResult,
    SourceReceipt,
)

HOST_PROTOCOL_VERSION = "modelrig.browser-host.v1"
_MAX_INPUT_BYTES = 64 * 1024
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024
_MAX_CLOSE_SECONDS = 5.0
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ADAPTER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class BrowserHostContractError(ValueError):
    """The process request or backend result violated the BrowserHost contract."""


class BrowserBackendError(RuntimeError):
    """A browser backend failed without exposing private implementation details."""


class BrowserBackendUnavailable(BrowserBackendError):
    """No browser implementation is installed or enabled in this process."""


def _strict_object(value: Any, *, name: str, required: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrowserHostContractError(f"{name} must be an object")
    keys = set(value)
    missing = required - keys
    unknown = keys - required
    if missing:
        raise BrowserHostContractError(f"{name} is missing fields: {sorted(missing)}")
    if unknown:
        raise BrowserHostContractError(f"{name} has unknown fields: {sorted(unknown)}")
    return value


def _strict_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BrowserHostContractError(f"{name} must be an integer")
    return value


def _strict_string(value: Any, *, name: str, max_chars: int) -> str:
    if not isinstance(value, str):
        raise BrowserHostContractError(f"{name} must be a string")
    cleaned = value.strip()
    if not cleaned:
        raise BrowserHostContractError(f"{name} must not be empty")
    if len(cleaned) > max_chars:
        raise BrowserHostContractError(f"{name} exceeds {max_chars} characters")
    return cleaned


def _strict_string_list(value: Any, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BrowserHostContractError(f"{name} must be an array")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_strict_string(item, name=f"{name}[{index}]", max_chars=8_192))
    return tuple(result)


@dataclass(frozen=True)
class BrowserHostRequest:
    request_id: str
    research: ResearchRequest
    protocol_version: str = HOST_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.protocol_version != HOST_PROTOCOL_VERSION:
            raise BrowserHostContractError(
                f"unsupported protocol_version: {self.protocol_version}"
            )
        if not isinstance(self.request_id, str) or not _REQUEST_ID_RE.fullmatch(self.request_id):
            raise BrowserHostContractError("request_id has an invalid format")
        if not isinstance(self.research, ResearchRequest):
            raise BrowserHostContractError("research must be a ResearchRequest")

    @classmethod
    def from_dict(cls, value: Any) -> "BrowserHostRequest":
        root = _strict_object(
            value,
            name="request",
            required={"protocol_version", "request_id", "research"},
        )
        research_data = _strict_object(
            root["research"],
            name="research",
            required={"schema_version", "query", "max_sources", "policy"},
        )
        policy_data = _strict_object(
            research_data["policy"],
            name="policy",
            required={
                "allowed_domains",
                "max_steps",
                "max_pages",
                "timeout_seconds",
                "max_source_bytes",
                "profile_mode",
                "credentials",
                "logins",
                "uploads",
                "downloads",
            },
        )
        try:
            policy = ReadOnlyBrowserPolicy(
                allowed_domains=_strict_string_list(
                    policy_data["allowed_domains"], name="allowed_domains"
                ),
                max_steps=_strict_int(policy_data["max_steps"], name="max_steps"),
                max_pages=_strict_int(policy_data["max_pages"], name="max_pages"),
                timeout_seconds=_strict_int(
                    policy_data["timeout_seconds"], name="timeout_seconds"
                ),
                max_source_bytes=_strict_int(
                    policy_data["max_source_bytes"], name="max_source_bytes"
                ),
                profile_mode=_strict_string(
                    policy_data["profile_mode"], name="profile_mode", max_chars=32
                ),
                credentials=_strict_string(
                    policy_data["credentials"], name="credentials", max_chars=32
                ),
                logins=_strict_string(
                    policy_data["logins"], name="logins", max_chars=32
                ),
                uploads=_strict_string(
                    policy_data["uploads"], name="uploads", max_chars=32
                ),
                downloads=_strict_string(
                    policy_data["downloads"], name="downloads", max_chars=32
                ),
            )
            research = ResearchRequest(
                schema_version=_strict_string(
                    research_data["schema_version"],
                    name="research.schema_version",
                    max_chars=100,
                ),
                query=_strict_string(
                    research_data["query"], name="research.query", max_chars=4_000
                ),
                max_sources=_strict_int(
                    research_data["max_sources"], name="research.max_sources"
                ),
                policy=policy,
            )
        except ResearchContractError as exc:
            raise BrowserHostContractError(str(exc)) from exc
        return cls(
            protocol_version=_strict_string(
                root["protocol_version"], name="protocol_version", max_chars=100
            ),
            request_id=_strict_string(
                root["request_id"], name="request_id", max_chars=64
            ),
            research=research,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "research": self.research.to_dict(),
        }


@dataclass(frozen=True)
class BrowserSourceArtifact:
    """Raw evidence returned by a browser backend before ModelRig makes a receipt."""

    url: str
    title: str
    content: bytes
    excerpt: str
    media_type: str

    def __post_init__(self) -> None:
        if not isinstance(self.content, bytes):
            raise BrowserHostContractError("browser source content must be bytes")


@dataclass(frozen=True)
class BrowserCitationDraft:
    marker: str
    statement: str
    source_indexes: tuple[int, ...]


@dataclass(frozen=True)
class BrowserBackendRun:
    """Adapter-neutral result produced inside the isolated browser process."""

    answer: str
    sources: tuple[BrowserSourceArtifact, ...]
    citations: tuple[BrowserCitationDraft, ...]
    visited_urls: tuple[str, ...]
    steps: int
    warnings: tuple[str, ...] = ()


class BrowserBackend(Protocol):
    adapter_name: str

    async def research(self, request: ResearchRequest) -> BrowserBackendRun:
        ...

    async def close(self) -> None:
        ...


class UnavailableBrowserBackend:
    adapter_name = "unavailable"

    async def research(self, request: ResearchRequest) -> BrowserBackendRun:
        raise BrowserBackendUnavailable("browser backend unavailable")

    async def close(self) -> None:
        return None


@dataclass(frozen=True)
class BrowserHostResponse:
    request_id: str | None
    ok: bool
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    protocol_version: str = HOST_PROTOCOL_VERSION

    @classmethod
    def success(cls, request_id: str, result: dict[str, Any]) -> "BrowserHostResponse":
        return cls(request_id=request_id, ok=True, result=result)

    @classmethod
    def failure(
        cls,
        request_id: str | None,
        code: str,
        message: str,
    ) -> "BrowserHostResponse":
        return cls(
            request_id=request_id,
            ok=False,
            error_code=code,
            error_message=message,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "ok": self.ok,
            "result": self.result if self.ok else None,
            "error": None
            if self.ok
            else {"code": self.error_code, "message": self.error_message},
        }


def _adapter_name(backend: BrowserBackend) -> str:
    name = getattr(backend, "adapter_name", None)
    if not isinstance(name, str) or not _ADAPTER_RE.fullmatch(name):
        raise BrowserHostContractError("backend adapter_name has an invalid format")
    return name


def _build_result(
    request: BrowserHostRequest,
    backend: BrowserBackend,
    run: BrowserBackendRun,
) -> dict[str, Any]:
    policy = request.research.policy
    if isinstance(run.steps, bool) or not isinstance(run.steps, int):
        raise BrowserHostContractError("backend steps must be an integer")
    if not 1 <= run.steps <= policy.max_steps:
        raise BrowserHostContractError("backend exceeded max_steps")
    if not run.visited_urls:
        raise BrowserHostContractError("backend returned no visited URLs")
    if len(run.visited_urls) > policy.max_pages:
        raise BrowserHostContractError("backend exceeded max_pages")
    if not run.sources:
        raise BrowserHostContractError("backend returned no source evidence")
    if len(run.sources) > request.research.max_sources:
        raise BrowserHostContractError("backend exceeded max_sources")

    visited: list[str] = []
    for raw_url in run.visited_urls:
        try:
            visited.append(policy.require_allowed_url(raw_url))
        except ResearchContractError as exc:
            raise BrowserHostContractError("backend visited a forbidden URL") from exc
    visited_set = set(visited)

    adapter = f"browser-host:{_adapter_name(backend)}"
    receipts: list[SourceReceipt] = []
    for source in run.sources:
        if not isinstance(source, BrowserSourceArtifact):
            raise BrowserHostContractError("backend sources have an invalid type")
        try:
            source_url = policy.require_allowed_url(source.url)
        except ResearchContractError as exc:
            raise BrowserHostContractError("backend source URL is forbidden") from exc
        if source_url not in visited_set:
            raise BrowserHostContractError("backend source was not in the visit trace")
        if len(source.content) > policy.max_source_bytes:
            raise BrowserHostContractError("backend source exceeds max_source_bytes")
        try:
            receipt = SourceReceipt.from_content(
                url=source_url,
                title=source.title,
                content=source.content,
                excerpt=source.excerpt,
                media_type=source.media_type,
                adapter=adapter,
            )
            policy.accept_receipt(receipt)
        except ResearchContractError as exc:
            raise BrowserHostContractError("backend source evidence is invalid") from exc
        receipts.append(receipt)

    citations: list[Citation] = []
    for draft in run.citations:
        if not isinstance(draft, BrowserCitationDraft):
            raise BrowserHostContractError("backend citations have an invalid type")
        indexes = tuple(dict.fromkeys(draft.source_indexes))
        if not indexes:
            raise BrowserHostContractError("backend citation has no source indexes")
        if any(
            isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or index >= len(receipts)
            for index in indexes
        ):
            raise BrowserHostContractError("backend citation references an invalid source index")
        try:
            citations.append(
                Citation(
                    marker=draft.marker,
                    statement=draft.statement,
                    source_ids=tuple(receipts[index].source_id for index in indexes),
                )
            )
        except ResearchContractError as exc:
            raise BrowserHostContractError("backend citation is invalid") from exc

    try:
        research_result = ResearchResult(
            answer=run.answer,
            sources=tuple(receipts),
            citations=tuple(citations),
            warnings=run.warnings,
        )
    except ResearchContractError as exc:
        raise BrowserHostContractError("backend research result is invalid") from exc

    return {
        "research": research_result.to_dict(),
        "trace": {
            "adapter": _adapter_name(backend),
            "steps": run.steps,
            "visited_urls": visited,
        },
    }


class BrowserHost:
    def __init__(self, backend: BrowserBackend) -> None:
        self._backend = backend

    async def execute(self, request: BrowserHostRequest) -> BrowserHostResponse:
        failure: BrowserHostResponse | None = None
        run: BrowserBackendRun | None = None
        try:
            run = await asyncio.wait_for(
                self._backend.research(request.research),
                timeout=request.research.policy.timeout_seconds,
            )
        except TimeoutError:
            failure = BrowserHostResponse.failure(
                request.request_id,
                "backend_timeout",
                "browser research exceeded its deadline",
            )
        except BrowserBackendUnavailable:
            failure = BrowserHostResponse.failure(
                request.request_id,
                "backend_unavailable",
                "browser research is not installed or enabled",
            )
        except BrowserBackendError:
            failure = BrowserHostResponse.failure(
                request.request_id,
                "backend_failed",
                "browser research failed",
            )
        except Exception:
            failure = BrowserHostResponse.failure(
                request.request_id,
                "backend_failed",
                "browser research failed",
            )
        finally:
            try:
                await asyncio.wait_for(
                    self._backend.close(),
                    timeout=min(_MAX_CLOSE_SECONDS, request.research.policy.timeout_seconds),
                )
            except Exception:
                return BrowserHostResponse.failure(
                    request.request_id,
                    "cleanup_failed",
                    "browser process cleanup failed",
                )

        if failure is not None:
            return failure
        try:
            assert run is not None
            result = _build_result(request, self._backend, run)
        except BrowserHostContractError:
            return BrowserHostResponse.failure(
                request.request_id,
                "contract_violation",
                "browser backend returned an invalid result",
            )
        return BrowserHostResponse.success(request.request_id, result)


async def handle_payload(
    payload: bytes,
    backend: BrowserBackend | None = None,
) -> BrowserHostResponse:
    if not isinstance(payload, bytes):
        return BrowserHostResponse.failure(None, "invalid_request", "request payload must be bytes")
    if not payload or len(payload) > _MAX_INPUT_BYTES:
        return BrowserHostResponse.failure(None, "invalid_request", "request payload size is invalid")
    try:
        text = payload.decode("utf-8")
        value = json.loads(text)
        request = BrowserHostRequest.from_dict(value)
    except (UnicodeDecodeError, json.JSONDecodeError, BrowserHostContractError):
        return BrowserHostResponse.failure(None, "invalid_request", "browser request is invalid")
    return await BrowserHost(backend or UnavailableBrowserBackend()).execute(request)


def encode_response(response: BrowserHostResponse) -> bytes:
    encoded = (
        json.dumps(
            response.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    if len(encoded) <= _MAX_OUTPUT_BYTES:
        return encoded
    fallback = BrowserHostResponse.failure(
        response.request_id,
        "response_too_large",
        "browser response exceeded the process output limit",
    )
    return (
        json.dumps(
            fallback.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )


def main() -> int:
    payload = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    response = asyncio.run(handle_payload(payload))
    sys.stdout.buffer.write(encode_response(response))
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

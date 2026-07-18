"""Dormant Browser Use adapter for the isolated BrowserHost.

The adapter deliberately keeps Browser Use optional and lazy-loaded. Browser Use
may discover and navigate JavaScript-heavy pages, but it never creates ModelRig
source receipts. Every cited URL is re-fetched through the deterministic pinned
fetcher before raw bytes are handed back to BrowserHost.
"""
from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Callable, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .browser_host import (
    BrowserBackendError,
    BrowserBackendRun,
    BrowserBackendUnavailable,
    BrowserCitationDraft,
    BrowserSourceArtifact,
)
from .research_contract import ResearchContractError, ResearchRequest
from .web_fetch import FetchTrace, WebFetchError

SUPPORTED_BROWSER_USE_VERSION = "0.13.4"
_READ_ONLY_EXCLUDED_ACTIONS = (
    "input",
    "upload_file",
    "send_keys",
    "evaluate",
    "select_dropdown",
    "write_file",
    "read_file",
    "replace_file",
)


class BrowserUseCitationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    marker: str = Field(min_length=1, max_length=4)
    statement: str = Field(min_length=1, max_length=2_000)
    urls: tuple[str, ...] = Field(min_length=1, max_length=10)


class BrowserUseResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=100_000)
    citations: tuple[BrowserUseCitationOutput, ...] = Field(min_length=1, max_length=100)


@dataclass(frozen=True)
class BrowserUseBindings:
    agent_factory: Callable[..., Any]
    profile_factory: Callable[..., Any]
    tools_factory: Callable[..., Any]
    version: str


class VerifiedFetcher(Protocol):
    def fetch(self, url: str, policy: Any) -> FetchTrace:
        ...


LlmFactory = Callable[[], Any]
BindingsLoader = Callable[[], BrowserUseBindings]


def load_browser_use_bindings() -> BrowserUseBindings:
    """Load the exact optional Browser Use version without affecting base startup."""

    try:
        installed = metadata.version("browser-use")
        from browser_use import Agent, BrowserProfile, Tools
    except (metadata.PackageNotFoundError, ImportError) as exc:
        raise BrowserBackendUnavailable("browser-use is not installed") from exc
    if installed != SUPPORTED_BROWSER_USE_VERSION:
        raise BrowserBackendUnavailable("browser-use version is not supported")
    return BrowserUseBindings(
        agent_factory=Agent,
        profile_factory=BrowserProfile,
        tools_factory=Tools,
        version=installed,
    )


def _maybe_await(value: Any):
    if inspect.isawaitable(value):
        return value

    async def completed():
        return value

    return completed()


def _canonical_history_urls(history: Any, request: ResearchRequest) -> tuple[str, ...]:
    try:
        raw_urls = history.urls()
    except Exception as exc:
        raise BrowserBackendError("browser history is unavailable") from exc
    if not isinstance(raw_urls, (list, tuple)):
        raise BrowserBackendError("browser history has an invalid URL list")

    canonical: list[str] = []
    for raw in raw_urls:
        if raw is None:
            continue
        if not isinstance(raw, str):
            raise BrowserBackendError("browser history contained a non-string URL")
        value = raw.strip()
        if not value or value == "about:blank":
            continue
        if urlsplit(value).scheme not in {"http", "https"}:
            raise BrowserBackendError("browser visited a non-web URL")
        try:
            normalized = request.policy.require_allowed_url(value)
        except ResearchContractError as exc:
            raise BrowserBackendError("browser visited a forbidden URL") from exc
        if normalized not in canonical:
            canonical.append(normalized)
    if not canonical:
        raise BrowserBackendError("browser returned no allowed visit trace")
    if len(canonical) > request.policy.max_pages:
        raise BrowserBackendError("browser exceeded max_pages")
    return tuple(canonical)


def _structured_output(history: Any) -> BrowserUseResearchOutput:
    try:
        raw = history.structured_output
    except Exception as exc:
        raise BrowserBackendError("browser structured output is unavailable") from exc
    if raw is None:
        raise BrowserBackendError("browser returned no structured output")
    try:
        return BrowserUseResearchOutput.model_validate(raw)
    except ValidationError as exc:
        raise BrowserBackendError("browser structured output is invalid") from exc


def _history_steps(history: Any, maximum: int) -> int:
    try:
        steps = history.number_of_steps()
    except Exception as exc:
        raise BrowserBackendError("browser step history is unavailable") from exc
    if isinstance(steps, bool) or not isinstance(steps, int) or not 1 <= steps <= maximum:
        raise BrowserBackendError("browser returned an invalid step count")
    return steps


def _history_successful(history: Any) -> bool:
    try:
        value = history.is_successful()
    except Exception as exc:
        raise BrowserBackendError("browser success state is unavailable") from exc
    return value is True


def _history_has_errors(history: Any) -> bool:
    try:
        return bool(history.has_errors())
    except Exception:
        return True


def _build_task(request: ResearchRequest) -> str:
    return (
        "Perform read-only web research for the following request. "
        "Only navigate within the configured allowed domains. Do not type into forms, "
        "submit forms, log in, upload, download, execute JavaScript, write files, or "
        "change remote state. Return structured output only. Every factual claim in "
        "the answer must use a numeric marker like [1], and every citation must include "
        "the exact URL that supports its statement.\n\n"
        f"Research request: {request.query}"
    )


class BrowserUseBackend:
    """Optional Browser Use backend whose evidence is independently re-fetched."""

    adapter_name = "browser-use"

    def __init__(
        self,
        *,
        fetcher: VerifiedFetcher,
        llm_factory: LlmFactory,
        bindings_loader: BindingsLoader = load_browser_use_bindings,
    ) -> None:
        if not callable(llm_factory):
            raise TypeError("llm_factory must be callable")
        if not callable(bindings_loader):
            raise TypeError("bindings_loader must be callable")
        self._fetcher = fetcher
        self._llm_factory = llm_factory
        self._bindings_loader = bindings_loader
        self._agent: Any = None
        self._closed = False

    def _build_agent(self, request: ResearchRequest) -> Any:
        try:
            bindings = self._bindings_loader()
            if bindings.version != SUPPORTED_BROWSER_USE_VERSION:
                raise BrowserBackendUnavailable("browser-use version is not supported")
            llm = self._llm_factory()
            if llm is None:
                raise BrowserBackendUnavailable("browser LLM is not configured")
            profile = bindings.profile_factory(
                headless=True,
                allowed_domains=list(request.policy.allowed_domains),
                user_data_dir=None,
                storage_state=None,
                keep_alive=False,
                block_ip_addresses=True,
                enable_default_extensions=False,
                downloads_path=None,
            )
            tools = bindings.tools_factory(
                exclude_actions=list(_READ_ONLY_EXCLUDED_ACTIONS),
                display_files_in_done_text=False,
            )
            return bindings.agent_factory(
                task=_build_task(request),
                llm=llm,
                browser_profile=profile,
                tools=tools,
                output_model_schema=BrowserUseResearchOutput,
                use_vision=False,
                sensitive_data=None,
                available_file_paths=[],
                max_failures=2,
                max_actions_per_step=1,
                final_response_after_failure=False,
                use_judge=False,
                generate_gif=False,
                save_conversation_path=None,
                calculate_cost=False,
                enable_signal_handler=False,
                display_files_in_done_text=False,
                include_recent_events=False,
            )
        except BrowserBackendUnavailable:
            raise
        except Exception as exc:
            raise BrowserBackendUnavailable("browser-use adapter could not initialize") from exc

    async def _verified_source(
        self,
        raw_url: str,
        request: ResearchRequest,
    ) -> FetchTrace:
        try:
            canonical = request.policy.require_allowed_url(raw_url)
            trace = await asyncio.to_thread(self._fetcher.fetch, canonical, request.policy)
        except (ResearchContractError, WebFetchError) as exc:
            raise BrowserBackendError("cited source could not be verified") from exc
        except Exception as exc:
            raise BrowserBackendError("cited source verification failed") from exc
        if not isinstance(trace, FetchTrace):
            raise BrowserBackendError("verified fetcher returned an invalid trace")
        return trace

    async def research(self, request: ResearchRequest) -> BrowserBackendRun:
        self._closed = False
        self._agent = self._build_agent(request)
        try:
            history = await self._agent.run(max_steps=request.policy.max_steps)
        except BrowserBackendUnavailable:
            raise
        except Exception as exc:
            raise BrowserBackendError("browser-use execution failed") from exc

        if not _history_successful(history):
            raise BrowserBackendError("browser-use did not complete successfully")
        output = _structured_output(history)
        visited = list(_canonical_history_urls(history, request))
        steps = _history_steps(history, request.policy.max_steps)

        unique_urls: list[str] = []
        for citation in output.citations:
            for raw_url in citation.urls:
                try:
                    canonical = request.policy.require_allowed_url(raw_url)
                except ResearchContractError as exc:
                    raise BrowserBackendError("browser citation URL is forbidden") from exc
                if canonical not in visited:
                    raise BrowserBackendError("browser cited a URL outside its visit trace")
                if canonical not in unique_urls:
                    unique_urls.append(canonical)
        if not unique_urls:
            raise BrowserBackendError("browser returned no citation URLs")
        if len(unique_urls) > request.max_sources:
            raise BrowserBackendError("browser exceeded max_sources")

        traces = await asyncio.gather(
            *(self._verified_source(url, request) for url in unique_urls)
        )
        sources: list[BrowserSourceArtifact] = []
        source_index: dict[str, int] = {}
        for requested_url, trace in zip(unique_urls, traces, strict=True):
            if trace.final_url not in visited:
                visited.append(trace.final_url)
            if len(visited) > request.policy.max_pages:
                raise BrowserBackendError("verified redirect exceeded max_pages")
            index = len(sources)
            source_index[requested_url] = index
            source_index[trace.final_url] = index
            sources.append(
                BrowserSourceArtifact(
                    url=trace.final_url,
                    title=trace.receipt.title,
                    content=trace.content,
                    excerpt=trace.receipt.excerpt,
                    media_type=trace.receipt.media_type,
                )
            )

        citations: list[BrowserCitationDraft] = []
        for citation in output.citations:
            indexes: list[int] = []
            for raw_url in citation.urls:
                canonical = request.policy.require_allowed_url(raw_url)
                index = source_index.get(canonical)
                if index is None:
                    raise BrowserBackendError("citation source was not verified")
                if index not in indexes:
                    indexes.append(index)
            citations.append(
                BrowserCitationDraft(
                    marker=citation.marker,
                    statement=citation.statement,
                    source_indexes=tuple(indexes),
                )
            )

        warnings: tuple[str, ...] = ()
        if _history_has_errors(history):
            warnings = ("Browser Use reported one or more recoverable step errors.",)
        return BrowserBackendRun(
            answer=output.answer,
            sources=tuple(sources),
            citations=tuple(citations),
            visited_urls=tuple(visited),
            steps=steps,
            warnings=warnings,
        )

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        agent = self._agent
        self._agent = None
        if agent is None:
            return
        close = getattr(agent, "close", None)
        if close is None:
            browser_session = getattr(agent, "browser_session", None)
            close = getattr(browser_session, "close", None)
        if close is not None:
            await _maybe_await(close())

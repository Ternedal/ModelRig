#!/usr/bin/env python3
from pathlib import Path
import re


ADAPTER = Path("worker/app/browser_use_adapter.py")
RUNTIME_TEST = Path("tests/worker_browser_use_runtime_guard.py")


def exact(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one target, found {count}")
    return text.replace(old, new)


text = ADAPTER.read_text(encoding="utf-8")
text = exact(
    text,
    "from typing import Any, Callable, Protocol",
    "from typing import Any, Callable, Literal, Protocol",
    "typing import",
)
text = exact(
    text,
    "from .research_contract import ResearchContractError, ResearchRequest, SourceReceipt",
    "from .browser_use_network_guard import (\n"
    "    BrowserUseNetworkGuard,\n"
    "    BrowserUseNetworkGuardError,\n"
    ")\n"
    "from .research_contract import ResearchContractError, ResearchRequest, SourceReceipt",
    "network guard import",
)
text = exact(
    text,
    '    "replace_file",\n)',
    '    "replace_file",\n'
    '    "search",\n'
    '    "switch",\n'
    '    "close_tab",\n'
    ')',
    "excluded actions",
)
text = exact(
    text,
    '''class BrowserUseResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=100_000)
    citations: tuple[BrowserUseCitationOutput, ...] = Field(min_length=1, max_length=100)


@dataclass(frozen=True)''',
    '''class BrowserUseResearchOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1, max_length=100_000)
    citations: tuple[BrowserUseCitationOutput, ...] = Field(min_length=1, max_length=100)


class BrowserUseReadOnlyNavigateAction(BaseModel):
    """The only navigation shape exposed to the model: current tab, always."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=8_192)
    new_tab: Literal[False] = False


@dataclass(frozen=True)''',
    "read-only navigate model",
)
text = exact(
    text,
    '''LlmFactory = Callable[[], Any]
BindingsLoader = Callable[[], BrowserUseBindings]''',
    '''LlmFactory = Callable[[], Any]
BindingsLoader = Callable[[], BrowserUseBindings]
NetworkGuardFactory = Callable[..., Any]''',
    "network guard alias",
)
text = exact(
    text,
    '''    return profile


def _maybe_await(value: Any):''',
    '''    return profile


def lock_read_only_tools(tools: Any) -> Any:
    """Validate the real action registry and remove hidden navigation escape hatches."""

    registry = getattr(getattr(tools, "registry", None), "registry", None)
    actions = getattr(registry, "actions", None)
    if not isinstance(actions, dict):
        raise BrowserBackendUnavailable("browser-use action registry is unavailable")
    navigate = actions.get("navigate")
    if navigate is None or not hasattr(navigate, "param_model"):
        raise BrowserBackendUnavailable("browser-use navigate action is unavailable")
    navigate.param_model = BrowserUseReadOnlyNavigateAction
    for forbidden in ("search", "switch", "close_tab"):
        if forbidden in actions:
            raise BrowserBackendUnavailable(
                f"browser-use retained forbidden action {forbidden}"
            )
    return tools


def _maybe_await(value: Any):''',
    "tool lock helper",
)
text = exact(
    text,
    '''        llm_factory: LlmFactory,
        bindings_loader: BindingsLoader = load_browser_use_bindings,
    ) -> None:''',
    '''        llm_factory: LlmFactory,
        bindings_loader: BindingsLoader = load_browser_use_bindings,
        network_guard_factory: NetworkGuardFactory = BrowserUseNetworkGuard,
    ) -> None:''',
    "constructor signature",
)
text = exact(
    text,
    '''        if not callable(bindings_loader):
            raise TypeError("bindings_loader must be callable")
        self._fetcher = fetcher''',
    '''        if not callable(bindings_loader):
            raise TypeError("bindings_loader must be callable")
        if not callable(network_guard_factory):
            raise TypeError("network_guard_factory must be callable")
        self._fetcher = fetcher''',
    "constructor validation",
)
text = exact(
    text,
    '''        self._bindings_loader = bindings_loader
        self._agent: Any = None
        self._download_path: Path | None = None''',
    '''        self._bindings_loader = bindings_loader
        self._network_guard_factory = network_guard_factory
        self._agent: Any = None
        self._network_guard: Any = None
        self._runtime_validated = False
        self._download_path: Path | None = None''',
    "constructor fields",
)
text = exact(
    text,
    '''            if bindings.version != SUPPORTED_BROWSER_USE_VERSION:
                raise BrowserBackendUnavailable("browser-use version is not supported")
            llm = self._llm_factory()''',
    '''            if bindings.version != SUPPORTED_BROWSER_USE_VERSION:
                raise BrowserBackendUnavailable("browser-use version is not supported")
            self._runtime_validated = bindings.runtime_validated
            llm = self._llm_factory()''',
    "runtime validation flag",
)
text = exact(
    text,
    '''            tools = bindings.tools_factory(
                exclude_actions=list(READ_ONLY_EXCLUDED_ACTIONS),
                display_files_in_done_text=False,
            )
            return bindings.agent_factory(''',
    '''            tools = bindings.tools_factory(
                exclude_actions=list(READ_ONLY_EXCLUDED_ACTIONS),
                display_files_in_done_text=False,
            )
            if bindings.runtime_validated:
                tools = lock_read_only_tools(tools)
            return bindings.agent_factory(''',
    "tool lock integration",
)
text = exact(
    text,
    '''    async def research(self, request: ResearchRequest) -> BrowserBackendRun:
        self._closed = False
        self._agent = self._build_agent(request)
        try:
            history = await self._agent.run(max_steps=request.policy.max_steps)
        except BrowserBackendUnavailable:
            raise
        except Exception as exc:
            raise BrowserBackendError("browser-use execution failed") from exc
        self._assert_no_downloads()
''',
    '''    async def research(self, request: ResearchRequest) -> BrowserBackendRun:
        self._closed = False
        self._network_guard = None
        self._agent = self._build_agent(request)
        if self._runtime_validated:
            browser_session = getattr(self._agent, "browser_session", None)
            if browser_session is None:
                raise BrowserBackendUnavailable(
                    "browser-use agent has no browser session for request guarding"
                )
            try:
                self._network_guard = self._network_guard_factory(
                    browser_session,
                    request.policy.allowed_domains,
                )
                await self._network_guard.install()
            except BrowserUseNetworkGuardError as exc:
                raise BrowserBackendUnavailable(
                    "browser request guard could not initialize"
                ) from exc
            except Exception as exc:
                raise BrowserBackendUnavailable(
                    "browser request guard could not initialize"
                ) from exc
        try:
            history = await self._agent.run(max_steps=request.policy.max_steps)
        except BrowserBackendUnavailable:
            raise
        except Exception as exc:
            raise BrowserBackendError("browser-use execution failed") from exc
        if self._network_guard is not None:
            try:
                await self._network_guard.assert_healthy()
            except BrowserUseNetworkGuardError as exc:
                raise BrowserBackendError(
                    "browser request guard failed during execution"
                ) from exc
        self._assert_no_downloads()
''',
    "research integration",
)
text = exact(
    text,
    '''        agent = self._agent
        self._agent = None
        try:
            if agent is None:
                return
            close = getattr(agent, "close", None)
            if close is None:
                browser_session = getattr(agent, "browser_session", None)
                close = getattr(browser_session, "close", None)
            if close is not None:
                await _maybe_await(close())
        finally:
            self._cleanup_runtime_quarantines()''',
    '''        agent = self._agent
        guard = self._network_guard
        self._agent = None
        self._network_guard = None
        guard_error: BrowserBackendError | None = None
        try:
            if guard is not None:
                try:
                    await guard.close()
                except BrowserUseNetworkGuardError as exc:
                    guard_error = BrowserBackendError(
                        "browser request guard cleanup failed"
                    )
                    guard_error.__cause__ = exc
            if agent is not None:
                close = getattr(agent, "close", None)
                if close is None:
                    browser_session = getattr(agent, "browser_session", None)
                    close = getattr(browser_session, "close", None)
                if close is not None:
                    await _maybe_await(close())
        finally:
            self._cleanup_runtime_quarantines()
        if guard_error is not None:
            raise guard_error''',
    "close integration",
)
ADAPTER.write_text(text, encoding="utf-8")


test = RUNTIME_TEST.read_text(encoding="utf-8")
test = exact(
    test,
    '''class Agent:
    def __init__(self, download_path: Path, *, write_download: bool) -> None:
        self.download_path = download_path
        self.write_download = write_download
        self.closed = 0''',
    '''class Agent:
    def __init__(self, download_path: Path, *, write_download: bool) -> None:
        self.download_path = download_path
        self.write_download = write_download
        self.browser_session = object()
        self.closed = 0''',
    "fake agent browser session",
)
test = exact(
    test,
    '''    async def close(self):
        self.closed += 1


class Runtime:''',
    '''    async def close(self):
        self.closed += 1


class FakeNetworkGuard:
    def __init__(self, browser_session, allowed_domains) -> None:
        self.browser_session = browser_session
        self.allowed_domains = tuple(allowed_domains)
        self.installed = 0
        self.health_checks = 0
        self.closed = 0

    async def install(self) -> None:
        self.installed += 1

    async def assert_healthy(self) -> None:
        self.health_checks += 1

    async def close(self) -> None:
        self.closed += 1


class GuardFactory:
    def __init__(self) -> None:
        self.instances: list[FakeNetworkGuard] = []

    def __call__(self, browser_session, allowed_domains):
        guard = FakeNetworkGuard(browser_session, allowed_domains)
        self.instances.append(guard)
        return guard


class Runtime:''',
    "fake guard classes",
)
test = exact(
    test,
    '''    def tools(self, **kwargs):
        self.tools_kwargs = kwargs
        return object()''',
    '''    def tools(self, **kwargs):
        self.tools_kwargs = kwargs
        actions = {
            "navigate": SimpleNamespace(param_model=object),
            "go_back": SimpleNamespace(param_model=object),
            "wait": SimpleNamespace(param_model=object),
            "scroll": SimpleNamespace(param_model=object),
            "extract": SimpleNamespace(param_model=object),
            "done": SimpleNamespace(param_model=object),
        }
        return SimpleNamespace(
            registry=SimpleNamespace(
                registry=SimpleNamespace(actions=actions),
            )
        )''',
    "fake tools registry",
)
test = exact(
    test,
    '''clean_runtime = Runtime(write_download=False)
clean_fetcher = Fetcher()
clean_backend = BrowserUseBackend(
    fetcher=clean_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=clean_runtime.bindings,
)''',
    '''clean_runtime = Runtime(write_download=False)
clean_fetcher = Fetcher()
clean_guards = GuardFactory()
clean_backend = BrowserUseBackend(
    fetcher=clean_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=clean_runtime.bindings,
    network_guard_factory=clean_guards,
)''',
    "clean backend guard",
)
test = exact(
    test,
    '''check(clean_fetcher.calls == 1, "clean run reaches deterministic citation re-fetch")
check(clean_runtime.profile_kwargs["downloads_path"] is None, "Browser Use owns download temp path creation")''',
    '''check(clean_fetcher.calls == 1, "clean run reaches deterministic citation re-fetch")
check(len(clean_guards.instances) == 1, "validated runtime receives one browser request guard")
clean_guard = clean_guards.instances[0]
check(clean_guard.browser_session is clean_runtime.agent.browser_session, "guard binds to the agent browser session")
check(clean_guard.allowed_domains == POLICY.allowed_domains, "guard receives the exact research allowlist")
check(clean_guard.installed == 1, "guard installs before agent execution")
check(clean_guard.health_checks == 1, "guard health is checked after agent execution")
check(clean_runtime.profile_kwargs["downloads_path"] is None, "Browser Use owns download temp path creation")''',
    "clean guard assertions",
)
test = exact(
    test,
    '''check(clean_runtime.agent is not None and clean_runtime.agent.closed == 1, "agent closes before quarantine cleanup")

# Any file written''',
    '''check(clean_runtime.agent is not None and clean_runtime.agent.closed == 1, "agent closes before quarantine cleanup")
check(clean_guard.closed == 1, "request guard closes before browser cleanup")

# Any file written''',
    "clean guard close assertion",
)
test = exact(
    test,
    '''dirty_runtime = Runtime(write_download=True)
dirty_fetcher = Fetcher()
dirty_backend = BrowserUseBackend(
    fetcher=dirty_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=dirty_runtime.bindings,
)''',
    '''dirty_runtime = Runtime(write_download=True)
dirty_fetcher = Fetcher()
dirty_guards = GuardFactory()
dirty_backend = BrowserUseBackend(
    fetcher=dirty_fetcher,
    llm_factory=lambda: object(),
    bindings_loader=dirty_runtime.bindings,
    network_guard_factory=dirty_guards,
)''',
    "dirty backend guard",
)
test = exact(
    test,
    '''check(dirty_fetcher.calls == 0, "forbidden download stops before citation re-fetch")
run(dirty_backend.close())''',
    '''check(dirty_fetcher.calls == 0, "forbidden download stops before citation re-fetch")
check(len(dirty_guards.instances) == 1, "dirty run is still guarded at the network boundary")
dirty_guard = dirty_guards.instances[0]
check(dirty_guard.installed == 1 and dirty_guard.health_checks == 1, "dirty run guard stays healthy")
run(dirty_backend.close())
check(dirty_guard.closed == 1, "dirty run guard closes during cleanup")''',
    "dirty guard assertions",
)
test = exact(
    test,
    '''unsafe_runtime = Runtime(write_download=False, unsafe_path=unsafe_root)
unsafe_backend = BrowserUseBackend(
    fetcher=Fetcher(),
    llm_factory=lambda: object(),
    bindings_loader=unsafe_runtime.bindings,
)''',
    '''unsafe_runtime = Runtime(write_download=False, unsafe_path=unsafe_root)
unsafe_guards = GuardFactory()
unsafe_backend = BrowserUseBackend(
    fetcher=Fetcher(),
    llm_factory=lambda: object(),
    bindings_loader=unsafe_runtime.bindings,
    network_guard_factory=unsafe_guards,
)''',
    "unsafe backend guard",
)
test = exact(
    test,
    '''run(unsafe_backend.close())

check("click" in READ_ONLY_EXCLUDED_ACTIONS''',
    '''run(unsafe_backend.close())
check(not unsafe_guards.instances, "unsafe quarantine fails before a network guard is created")

check("click" in READ_ONLY_EXCLUDED_ACTIONS''',
    "unsafe guard assertion",
)
RUNTIME_TEST.write_text(test, encoding="utf-8")

Path("scripts/_patch_browser_network_guard.py").unlink()
print("patched Browser Use adapter and runtime guard integration")

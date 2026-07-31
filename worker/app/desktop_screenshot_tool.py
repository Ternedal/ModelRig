"""Feature-gated foreground screenshot capability for dormant Computer Use I3.

The capability composes the existing signed desktop contract and hardened Win32
adapter. It captures only an explicitly allowlisted foreground window, requires a
fresh local ToolGate confirmation and returns a short-lived signed ``screen_token``
for a later action boundary. It registers no click/type tool and enables no input.

Raw PNG bytes are returned only to the local caller as the snapshot receipt. Audit
stores a bounded projection with title/image hashes, never the image or token.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .desktop_contract import DesktopSessionGuard
from .desktop_policy import DesktopDenied, TargetAllowlist
from .desktop_win32 import DesktopCaptureAudit, Win32DesktopBackend

FEATURE_ENV = "KALIV_COMPUTER_USE"
ALLOWLIST_ENV = "KALIV_DESKTOP_ALLOWLIST_FILE"
TOOL_NAME = "desktop_screenshot"
_MAX_ALLOWLIST_BYTES = 64 * 1024
_MAX_RESULT_BYTES = 10 * 1024 * 1024
_SESSION_TTL_SECONDS = 10 * 60
_MAX_SESSIONS = 8
_PROCESS = re.compile(r"^[A-Za-z0-9_.-]{1,128}\.exe$", re.IGNORECASE)

_EXECUTION_CONTEXT: contextvars.ContextVar[tuple[str, str] | None] = contextvars.ContextVar(
    "kaliv_desktop_execution_context", default=None
)
_CAPTURE_AUDIT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "kaliv_desktop_capture_audit", default=None
)


class DesktopScreenshotConfigurationError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "on"}


def _session_id(conversation_id: str | None, confirmation_id: str) -> str:
    material = f"{conversation_id or ''}\n{confirmation_id}".encode("utf-8")
    return "desktop_" + hashlib.sha256(material).hexdigest()[:40]


def _allowlist_path() -> Path:
    raw = os.getenv(ALLOWLIST_ENV, "").strip()
    if not raw:
        raise DesktopScreenshotConfigurationError(
            f"{ALLOWLIST_ENV} skal pege på en eksplicit JSON-allowlist"
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise DesktopScreenshotConfigurationError(f"{ALLOWLIST_ENV} skal være en absolut sti")
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise DesktopScreenshotConfigurationError("desktop-allowlisten kan ikke læses") from exc
    if not path.is_file() or path.stat().st_size > _MAX_ALLOWLIST_BYTES:
        raise DesktopScreenshotConfigurationError("desktop-allowlisten er ugyldig eller for stor")
    return path


def _load_allowlist() -> tuple[TargetAllowlist, str]:
    path = _allowlist_path()
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DesktopScreenshotConfigurationError("desktop-allowlisten er ikke gyldig JSON") from exc
    if not isinstance(value, dict) or not 1 <= len(value) <= 32:
        raise DesktopScreenshotConfigurationError(
            "desktop-allowlisten skal være et objekt med 1..32 processer"
        )
    rules: dict[str, list[str]] = {}
    for process, patterns in value.items():
        if not isinstance(process, str) or not _PROCESS.fullmatch(process):
            raise DesktopScreenshotConfigurationError(
                "allowlist-processer skal være basenames der ender på .exe"
            )
        if not isinstance(patterns, list) or not 1 <= len(patterns) <= 32:
            raise DesktopScreenshotConfigurationError(
                f"{process} skal have 1..32 vinduestitel-mønstre"
            )
        clean: list[str] = []
        for pattern in patterns:
            if not isinstance(pattern, str) or not 1 <= len(pattern) <= 200:
                raise DesktopScreenshotConfigurationError(
                    f"{process} indeholder et ugyldigt titelmønster"
                )
            if "\x00" in pattern or "\r" in pattern or "\n" in pattern:
                raise DesktopScreenshotConfigurationError(
                    f"{process} indeholder kontroltegn i et titelmønster"
                )
            if pattern not in clean:
                clean.append(pattern)
        rules[process.lower()] = clean
    return TargetAllowlist(rules=rules), hashlib.sha256(raw).hexdigest()


@dataclass
class _DesktopRuntimeSession:
    guard: DesktopSessionGuard
    allowlist: TargetAllowlist
    allowlist_sha256: str
    last_used: float


class DesktopSessionRegistry:
    """Bounded process-local proof authority; restart invalidates all screen tokens."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        max_sessions: int = _MAX_SESSIONS,
        ttl_seconds: float = _SESSION_TTL_SECONDS,
    ) -> None:
        self.clock = clock
        self.max_sessions = max_sessions
        self.ttl_seconds = float(ttl_seconds)
        self._lock = threading.RLock()
        self._sessions: dict[str, _DesktopRuntimeSession] = {}

    def _prune(self, now: float) -> None:
        for key in [
            key
            for key, session in self._sessions.items()
            if now - session.last_used > self.ttl_seconds
        ]:
            self._sessions.pop(key, None)
        while len(self._sessions) >= self.max_sessions:
            oldest = min(self._sessions, key=lambda key: self._sessions[key].last_used)
            self._sessions.pop(oldest, None)

    def get(self, session_id: str) -> _DesktopRuntimeSession:
        allowlist, digest = _load_allowlist()
        now = float(self.clock())
        with self._lock:
            self._prune(now)
            current = self._sessions.get(session_id)
            if current is None or current.allowlist_sha256 != digest:
                current = _DesktopRuntimeSession(
                    guard=DesktopSessionGuard(allowlist),
                    allowlist=allowlist,
                    allowlist_sha256=digest,
                    last_used=now,
                )
                self._sessions[session_id] = current
            else:
                current.last_used = now
            return current

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()


SESSIONS = DesktopSessionRegistry()
_BACKEND_FACTORY: Callable[[TargetAllowlist], Win32DesktopBackend] = (
    lambda allowlist: Win32DesktopBackend(allowlist, input_enabled=False)
)


def run_desktop_screenshot(args: dict[str, Any]) -> str:
    if not isinstance(args, dict) or args:
        raise DesktopScreenshotConfigurationError(
            "desktop_screenshot accepterer ingen argumenter"
        )
    context = _EXECUTION_CONTEXT.get()
    if context is None:
        raise DesktopScreenshotConfigurationError(
            "desktop_screenshot må kun køre i en frisk lokal ToolGate-godkendelse"
        )
    session_id, origin = context
    if origin != "local":
        raise DesktopDenied("desktop-screenshot kræver en lokal model")

    runtime = SESSIONS.get(session_id)
    backend = _BACKEND_FACTORY(runtime.allowlist)
    capture = backend.capture_foreground()
    receipt = runtime.guard.snapshot(
        capture,
        session_id=session_id,
        origin="local",
        cloud_consent=False,
    )
    audit = DesktopCaptureAudit.from_capture(capture).to_dict()
    audit["screen_token_sha256"] = hashlib.sha256(
        receipt.screen_token.encode("utf-8")
    ).hexdigest()
    audit["allowlist_sha256"] = runtime.allowlist_sha256
    _CAPTURE_AUDIT.set(audit)

    encoded = json.dumps(
        receipt.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    if len(encoded.encode("utf-8")) > _MAX_RESULT_BYTES:
        raise DesktopDenied("screenshot-resultatet overskrider outputgrænsen")
    return encoded


@dataclass(frozen=True)
class DesktopScreenshotTool:
    name: str = TOOL_NAME
    risk: str = "desktop"
    description: str = (
        "Tag et screenshot af det aktuelt aktive, eksplicit allowlistede Windows-vindue. "
        "Kræver lokal model og frisk bekræftelse; ingen klik eller tastatur."
    )
    params: dict[str, Any] = None  # type: ignore[assignment]
    run: Any = run_desktop_screenshot
    sensitivity: str = "secret"
    isolate: bool = False
    env_allow: tuple[str, ...] = ()
    network: str = "none"
    network_destinations: tuple[str, ...] = ()
    impact: str = "desktop"
    cancellation: str = "none"
    idempotent: bool = False
    schedulable: bool = False
    unschedulable_because: str = (
        "et screenshot kræver et menneske til stede og en frisk forgrundsskærm"
    )

    def __post_init__(self) -> None:
        if self.params is None:
            object.__setattr__(
                self,
                "params",
                {"type": "object", "additionalProperties": False, "properties": {}},
            )

    def human_summary(self, args: dict[str, Any]) -> str:
        if args:
            raise DesktopScreenshotConfigurationError(
                "desktop_screenshot accepterer ingen argumenter"
            )
        return (
            "Kaliv vil tage ét screenshot af det aktive Windows-vindue, men kun hvis "
            "processen og vinduestitlen matcher din lokale allowlist. Billedet bliver "
            "kun sendt til den lokale model; der aktiveres ingen klik eller tastatur."
        )


def _install_gate_extension(tools_module: Any) -> None:
    propose = tools_module.ToolGate.propose
    if not getattr(propose, "_kaliv_desktop_screenshot", False):
        original_propose = propose

        def guarded_propose(
            self: Any,
            name: str,
            args: dict,
            conversation_id: str | None = None,
            messages: list | None = None,
            model: str | None = None,
            origin: str = "local",
            pre_approved: str | None = None,
        ) -> dict:
            if name == TOOL_NAME and origin != "local":
                tool = tools_module.REGISTRY.get(name)
                self.audit.record(
                    tool=name,
                    args=args,
                    risk=getattr(tool, "risk", "desktop"),
                    outcome="blocked",
                    conversation_id=conversation_id,
                    result_summary="desktop screenshot requires local origin",
                    origin=origin,
                )
                raise tools_module.ToolDenied(
                    "desktop-screenshot planlægges kun med en lokal model"
                )
            return original_propose(
                self,
                name,
                args,
                conversation_id,
                messages,
                model,
                origin,
                pre_approved,
            )

        guarded_propose._kaliv_desktop_screenshot = True  # type: ignore[attr-defined]
        tools_module.ToolGate.propose = guarded_propose

    execute = tools_module.ToolGate._execute
    if not getattr(execute, "_kaliv_desktop_screenshot", False):
        original_execute = execute

        def confirmed_execute(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
        ) -> dict[str, Any]:
            if getattr(tool, "name", None) != TOOL_NAME:
                return original_execute(self, tool, args, conv, cid, origin)
            if not cid or origin != "local":
                raise tools_module.ToolDenied(
                    "desktop_screenshot kræver en frisk lokal ToolGate-godkendelse"
                )
            started = time.time()
            execution_token = _EXECUTION_CONTEXT.set((_session_id(conv, cid), origin))
            audit_token = _CAPTURE_AUDIT.set(None)
            try:
                result = tool.run(args)
                safe_audit = _CAPTURE_AUDIT.get()
                if not isinstance(safe_audit, dict):
                    raise DesktopScreenshotConfigurationError(
                        "desktop capture produced no trusted audit projection"
                    )
            except (DesktopDenied, DesktopScreenshotConfigurationError) as exc:
                self.audit.record(
                    tool=tool.name,
                    args=args,
                    risk=tool.risk,
                    outcome="blocked",
                    conversation_id=conv,
                    confirmation_id=cid,
                    origin=origin,
                    result_summary=str(exc),
                    duration_ms=int((time.time() - started) * 1000),
                )
                raise tools_module.ToolDenied(str(exc)) from exc
            except Exception as exc:
                self.audit.record(
                    tool=tool.name,
                    args=args,
                    risk=tool.risk,
                    outcome="error",
                    conversation_id=conv,
                    confirmation_id=cid,
                    origin=origin,
                    result_summary="desktop screenshot failed safely",
                    duration_ms=int((time.time() - started) * 1000),
                )
                raise tools_module.ToolError("desktop screenshot failed safely") from exc
            finally:
                _CAPTURE_AUDIT.reset(audit_token)
                _EXECUTION_CONTEXT.reset(execution_token)

            duration_ms = int((time.time() - started) * 1000)
            summary = json.dumps(
                safe_audit, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            self.audit.record(
                tool=tool.name,
                args=args,
                risk=tool.risk,
                outcome="executed",
                conversation_id=conv,
                confirmation_id=cid,
                origin=origin,
                result_summary=summary,
                duration_ms=duration_ms,
            )
            return {
                "tool": tool.name,
                "result": tools_module.wrap_as_data(result),
                "duration_ms": duration_ms,
            }

        confirmed_execute._kaliv_desktop_screenshot = True  # type: ignore[attr-defined]
        tools_module.ToolGate._execute = confirmed_execute


def register_desktop_screenshot_tool() -> bool:
    if not _enabled(os.getenv(FEATURE_ENV)):
        return False
    from . import tools

    _install_gate_extension(tools)
    existing = tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if isinstance(existing, DesktopScreenshotTool):
            return True
        raise RuntimeError(f"{TOOL_NAME} is already registered by another component")
    tools.REGISTRY[TOOL_NAME] = DesktopScreenshotTool()
    return True


__all__ = [
    "ALLOWLIST_ENV",
    "DesktopScreenshotConfigurationError",
    "DesktopScreenshotTool",
    "DesktopSessionRegistry",
    "FEATURE_ENV",
    "SESSIONS",
    "TOOL_NAME",
    "register_desktop_screenshot_tool",
    "run_desktop_screenshot",
]

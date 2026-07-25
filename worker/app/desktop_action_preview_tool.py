"""Confirmed, local-only desktop action preview capability.

This is the last safe code-only slice before real input. It binds every approved
screenshot token to the exact conversation and process-local desktop session that
issued it, then allows a local model to request a signed one-shot action preview.
The tool re-captures the allowlisted foreground window and returns a short-lived
plan token, but it has no executor and imports no SendInput path.
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from .desktop_action_plan import DesktopActionPlanner
from .desktop_contract import DesktopAction
from .desktop_policy import DesktopDenied
from . import desktop_screenshot_tool as screenshot

FEATURE_ENV = screenshot.FEATURE_ENV
TOOL_NAME = "desktop_action_preview"
SCREENSHOT_TOOL = screenshot.TOOL_NAME
_RESULT_SCHEMA = "kaliv-desktop-action-preview-result/v1"
_MAX_BINDINGS = 64
_BINDING_TTL_SECONDS = 120.0

_EXECUTION_CONTEXT: contextvars.ContextVar[tuple[str | None, str, str] | None] = (
    contextvars.ContextVar("kaliv_desktop_preview_execution", default=None)
)
_PREVIEW_AUDIT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "kaliv_desktop_preview_audit", default=None
)


class DesktopActionPreviewConfigurationError(RuntimeError):
    pass


def _conversation_digest(conversation_id: str | None) -> str:
    return hashlib.sha256((conversation_id or "").encode("utf-8")).hexdigest()


def _token_digest(token: str) -> str:
    if not isinstance(token, str) or not 32 <= len(token) <= 16 * 1024:
        raise DesktopActionPreviewConfigurationError("screen_token er ugyldig")
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _unwrap_result(value: str) -> dict[str, Any]:
    prefix = "<<<TOOL_OUTPUT_DATA_NOT_INSTRUCTIONS>>>\n"
    suffix = "\n<<<END_TOOL_OUTPUT>>>"
    if not isinstance(value, str) or not value.startswith(prefix) or not value.endswith(suffix):
        raise DesktopActionPreviewConfigurationError("screenshot-resultatet mangler data-envelope")
    try:
        raw = json.loads(value[len(prefix) : -len(suffix)])
    except json.JSONDecodeError as exc:
        raise DesktopActionPreviewConfigurationError("screenshot-resultatet er ikke gyldig JSON") from exc
    if not isinstance(raw, dict) or raw.get("schema") != "kaliv-desktop-snapshot/v1":
        raise DesktopActionPreviewConfigurationError("screenshot-resultatet har forkert schema")
    token = raw.get("screen_token")
    _token_digest(token)
    return raw


@dataclass(frozen=True)
class _ScreenBinding:
    session_id: str
    conversation_sha256: str
    expires_at: float


class ScreenBindingRegistry:
    """Bounded process-local routing hints; signed guard verification remains final."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.time,
        ttl_seconds: float = _BINDING_TTL_SECONDS,
        max_bindings: int = _MAX_BINDINGS,
    ) -> None:
        self.clock = clock
        self.ttl_seconds = float(ttl_seconds)
        self.max_bindings = int(max_bindings)
        self._lock = threading.RLock()
        self._bindings: dict[str, _ScreenBinding] = {}

    def _prune(self, now: float) -> None:
        for digest in [
            digest for digest, item in self._bindings.items() if item.expires_at <= now
        ]:
            self._bindings.pop(digest, None)
        while len(self._bindings) >= self.max_bindings:
            oldest = min(self._bindings, key=lambda key: self._bindings[key].expires_at)
            self._bindings.pop(oldest, None)

    def bind(
        self,
        screen_token: str,
        *,
        session_id: str,
        conversation_id: str | None,
    ) -> None:
        now = float(self.clock())
        digest = _token_digest(screen_token)
        with self._lock:
            self._prune(now)
            self._bindings[digest] = _ScreenBinding(
                session_id=session_id,
                conversation_sha256=_conversation_digest(conversation_id),
                expires_at=now + self.ttl_seconds,
            )

    def resolve(
        self,
        screen_token: str,
        *,
        conversation_id: str | None,
    ) -> tuple[str, Any]:
        now = float(self.clock())
        digest = _token_digest(screen_token)
        with self._lock:
            self._prune(now)
            binding = self._bindings.get(digest)
        if binding is None:
            raise DesktopDenied("screenshot-beviset er ukendt eller udløbet — tag et nyt")
        if binding.conversation_sha256 != _conversation_digest(conversation_id):
            raise DesktopDenied("screenshot-beviset tilhører en anden samtale")
        # Do not call SESSIONS.get(): that could create a new guard with a new HMAC
        # key and make a stale routing hint look current. Existing proof authority only.
        with screenshot.SESSIONS._lock:  # package-internal shared trust boundary
            runtime = screenshot.SESSIONS._sessions.get(binding.session_id)
        if runtime is None:
            raise DesktopDenied("desktop-sessionen er udløbet — tag et nyt screenshot")
        _, current_allowlist_sha = screenshot._load_allowlist()
        if runtime.allowlist_sha256 != current_allowlist_sha:
            raise DesktopDenied("desktop-allowlisten er ændret — tag et nyt screenshot")
        runtime.guard.codec.verify(
            screen_token,
            session_id=binding.session_id,
            origin="local",
            cloud_consent=False,
            now=now,
        )
        runtime.last_used = now
        return binding.session_id, runtime

    def clear(self) -> None:
        with self._lock:
            self._bindings.clear()


class PlannerRegistry:
    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self.clock = clock
        self._lock = threading.RLock()
        self._planners: dict[str, tuple[int, DesktopActionPlanner]] = {}

    def get(self, session_id: str, guard: Any) -> DesktopActionPlanner:
        identity = id(guard)
        with self._lock:
            current = self._planners.get(session_id)
            if current is None or current[0] != identity:
                current = (
                    identity,
                    DesktopActionPlanner(guard, ttl_s=10.0, clock=self.clock),
                )
                self._planners[session_id] = current
            return current[1]

    def clear(self) -> None:
        with self._lock:
            self._planners.clear()


SCREEN_BINDINGS = ScreenBindingRegistry()
PLANNERS = PlannerRegistry()


def _action(args: dict[str, Any]) -> DesktopAction:
    if not isinstance(args, dict):
        raise DesktopActionPreviewConfigurationError("preview-argumenter skal være et objekt")
    allowed = {"kind", "screen_token", "x", "y", "text", "button"}
    if set(args) - allowed:
        raise DesktopActionPreviewConfigurationError("preview indeholder ukendte argumenter")
    kind = args.get("kind")
    token = args.get("screen_token")
    _token_digest(token)
    if kind == "click":
        if set(args) - {"kind", "screen_token", "x", "y", "button"}:
            raise DesktopActionPreviewConfigurationError("klik-preview indeholder ugyldige felter")
        return DesktopAction(
            kind="click",
            screen_token=token,
            x=args.get("x"),
            y=args.get("y"),
            button=args.get("button", "left"),
        )
    if kind == "type_text":
        if set(args) != {"kind", "screen_token", "text"}:
            raise DesktopActionPreviewConfigurationError("tekst-preview kræver præcis kind, screen_token og text")
        return DesktopAction(kind="type_text", screen_token=token, text=args.get("text"))
    raise DesktopActionPreviewConfigurationError("kind skal være click eller type_text")


def _audit_args(args: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {"kind": args.get("kind")}
    token = args.get("screen_token")
    if isinstance(token, str):
        safe["screen_token_sha256"] = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if args.get("kind") == "click":
        safe.update({"x": args.get("x"), "y": args.get("y"), "button": args.get("button", "left")})
    text = args.get("text")
    if isinstance(text, str):
        safe["text_chars"] = len(text)
        safe["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return safe


def _safe_result(preview: Any) -> tuple[str, dict[str, Any]]:
    raw = preview.to_dict()
    action = raw["action"]
    action.pop("screen_token", None)
    action["screen_token_sha256"] = hashlib.sha256(
        preview.action.screen_token.encode("utf-8")
    ).hexdigest()
    result = {
        "schema": _RESULT_SCHEMA,
        "plan_token": raw["plan_token"],
        "action": action,
        "preview": raw["preview"],
        "expires_in_seconds": raw["expires_in_seconds"],
        "execution_enabled": False,
        "production_activation": False,
    }
    target = result["preview"]["target"]
    audit = {
        "schema": _RESULT_SCHEMA,
        "kind": action["kind"],
        "plan_token_sha256": hashlib.sha256(raw["plan_token"].encode("utf-8")).hexdigest(),
        "screen_token_sha256": action["screen_token_sha256"],
        "process": target["process"],
        "title_sha256": hashlib.sha256(target["title"].encode("utf-8")).hexdigest(),
        "geometry": [target["left"], target["top"], target["width"], target["height"]],
        "expires_in_seconds": raw["expires_in_seconds"],
        "execution_enabled": False,
        "production_activation": False,
    }
    if action["kind"] == "click":
        audit["relative_point"] = [action["x"], action["y"]]
        audit["button"] = action["button"]
    else:
        audit["text_chars"] = len(action["text"])
        audit["text_sha256"] = hashlib.sha256(action["text"].encode("utf-8")).hexdigest()
    return json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")), audit


def run_desktop_action_preview(args: dict[str, Any]) -> str:
    context = _EXECUTION_CONTEXT.get()
    if context is None:
        raise DesktopActionPreviewConfigurationError(
            "desktop_action_preview må kun køre i en frisk lokal ToolGate-godkendelse"
        )
    conversation_id, _confirmation_id, origin = context
    if origin != "local":
        raise DesktopDenied("desktop-preview kræver en lokal model")
    action = _action(args)
    session_id, runtime = SCREEN_BINDINGS.resolve(
        action.screen_token,
        conversation_id=conversation_id,
    )
    backend = screenshot._BACKEND_FACTORY(runtime.allowlist)
    current = backend.capture_foreground()
    planner = PLANNERS.get(session_id, runtime.guard)
    preview = planner.preview(
        action,
        current,
        session_id=session_id,
        origin="local",
        cloud_consent=False,
    )
    result, audit = _safe_result(preview)
    _PREVIEW_AUDIT.set(audit)
    return result


@dataclass(frozen=True)
class DesktopActionPreviewTool:
    name: str = TOOL_NAME
    risk: str = "desktop"
    description: str = (
        "Forbered et kortlivet, signeret preview af et klik eller en teksthandling "
        "på det senest godkendte desktop-screenshot. Udfører ingen input."
    )
    params: dict[str, Any] = None  # type: ignore[assignment]
    run: Any = run_desktop_action_preview
    sensitivity: str = "secret"
    isolate: bool = False
    env_allow: tuple[str, ...] = ()
    network: str = "none"
    network_destinations: tuple[str, ...] = ()
    impact: str = "desktop"
    cancellation: str = "none"
    idempotent: bool = False
    schedulable: bool = False
    unschedulable_because: str = "previewet kræver en frisk skærm og et menneske til stede"

    def __post_init__(self) -> None:
        if self.params is None:
            object.__setattr__(
                self,
                "params",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "kind": {"type": "string", "enum": ["click", "type_text"]},
                        "screen_token": {"type": "string"},
                        "x": {"type": "integer", "minimum": 0},
                        "y": {"type": "integer", "minimum": 0},
                        "button": {"type": "string", "enum": ["left"]},
                        "text": {"type": "string", "minLength": 1, "maxLength": 2000},
                    },
                    "required": ["kind", "screen_token"],
                },
            )

    def human_summary(self, args: dict[str, Any]) -> str:
        action = _action(args)
        if action.kind == "click":
            return (
                f"Kaliv vil forberede — men IKKE udføre — ét venstreklik ved "
                f"({action.x}, {action.y}) i det godkendte vindue. Previewet "
                "genkontrollerer skærmen og udløber efter få sekunder."
            )
        return (
            "Kaliv vil forberede — men IKKE skrive — præcis denne tekst i det "
            f"godkendte vindue ({len(action.text or '')} tegn): «{action.text}». "
            "Previewet genkontrollerer skærmen og udløber efter få sekunder."
        )


def _install_audit_redaction(tools_module: Any) -> None:
    record = tools_module.AuditLog.record
    if getattr(record, "_kaliv_desktop_preview_redaction", False):
        return
    original_record = record

    def redacted_record(self: Any, *, tool: str, args: dict, **kwargs: Any) -> None:
        if tool == TOOL_NAME:
            args = _audit_args(args)
        original_record(self, tool=tool, args=args, **kwargs)

    redacted_record._kaliv_desktop_preview_redaction = True  # type: ignore[attr-defined]
    tools_module.AuditLog.record = redacted_record


def _install_gate_extensions(tools_module: Any) -> None:
    _install_audit_redaction(tools_module)

    execute = tools_module.ToolGate._execute
    if not getattr(execute, "_kaliv_desktop_screen_binding", False):
        previous_execute = execute

        def bind_screenshot(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
        ) -> dict[str, Any]:
            result = previous_execute(self, tool, args, conv, cid, origin)
            if getattr(tool, "name", None) == SCREENSHOT_TOOL:
                if not cid or origin != "local":
                    raise tools_module.ToolDenied("screenshot-binding kræver lokal godkendelse")
                receipt = _unwrap_result(result.get("result"))
                SCREEN_BINDINGS.bind(
                    receipt["screen_token"],
                    session_id=screenshot._session_id(conv, cid),
                    conversation_id=conv,
                )
            return result

        bind_screenshot._kaliv_desktop_screen_binding = True  # type: ignore[attr-defined]
        tools_module.ToolGate._execute = bind_screenshot

    propose = tools_module.ToolGate.propose
    if not getattr(propose, "_kaliv_desktop_preview", False):
        previous_propose = propose

        def local_propose(
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
                    result_summary="desktop action preview requires local origin",
                    origin=origin,
                )
                raise tools_module.ToolDenied("desktop-preview planlægges kun med en lokal model")
            return previous_propose(
                self,
                name,
                args,
                conversation_id,
                messages,
                model,
                origin,
                pre_approved,
            )

        local_propose._kaliv_desktop_preview = True  # type: ignore[attr-defined]
        tools_module.ToolGate.propose = local_propose

    execute = tools_module.ToolGate._execute
    if not getattr(execute, "_kaliv_desktop_preview", False):
        previous_execute = execute

        def confirmed_preview(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
        ) -> dict[str, Any]:
            if getattr(tool, "name", None) != TOOL_NAME:
                return previous_execute(self, tool, args, conv, cid, origin)
            if not cid or origin != "local":
                raise tools_module.ToolDenied(
                    "desktop_action_preview kræver en frisk lokal ToolGate-godkendelse"
                )
            started = time.time()
            context_token = _EXECUTION_CONTEXT.set((conv, cid, origin))
            audit_token = _PREVIEW_AUDIT.set(None)
            try:
                result = tool.run(args)
                safe_audit = _PREVIEW_AUDIT.get()
                if not isinstance(safe_audit, dict):
                    raise DesktopActionPreviewConfigurationError(
                        "desktop preview produced no trusted audit projection"
                    )
            except (DesktopDenied, DesktopActionPreviewConfigurationError) as exc:
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
                    result_summary="desktop preview failed safely",
                    duration_ms=int((time.time() - started) * 1000),
                )
                raise tools_module.ToolError("desktop preview failed safely") from exc
            finally:
                _PREVIEW_AUDIT.reset(audit_token)
                _EXECUTION_CONTEXT.reset(context_token)
            duration_ms = int((time.time() - started) * 1000)
            self.audit.record(
                tool=tool.name,
                args=args,
                risk=tool.risk,
                outcome="executed",
                conversation_id=conv,
                confirmation_id=cid,
                origin=origin,
                result_summary=json.dumps(
                    safe_audit, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                ),
                duration_ms=duration_ms,
            )
            return {
                "tool": tool.name,
                "result": tools_module.wrap_as_data(result),
                "duration_ms": duration_ms,
            }

        confirmed_preview._kaliv_desktop_preview = True  # type: ignore[attr-defined]
        tools_module.ToolGate._execute = confirmed_preview


def register_desktop_action_preview_tool() -> bool:
    if not screenshot._enabled(os.getenv(FEATURE_ENV)):
        return False
    from . import tools

    existing = tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if isinstance(existing, DesktopActionPreviewTool):
            return True
        raise RuntimeError(f"{TOOL_NAME} is already registered by another component")
    _install_gate_extensions(tools)
    tools.REGISTRY[TOOL_NAME] = DesktopActionPreviewTool()
    return True


__all__ = [
    "DesktopActionPreviewConfigurationError",
    "DesktopActionPreviewTool",
    "PLANNERS",
    "SCREEN_BINDINGS",
    "ScreenBindingRegistry",
    "TOOL_NAME",
    "register_desktop_action_preview_tool",
    "run_desktop_action_preview",
]

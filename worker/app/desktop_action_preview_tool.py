"""Compatibility facade for the desktop action preview capability.

The implementation remains byte-for-byte in ``desktop_action_preview_tool_legacy``.
This facade repairs one Python closure-binding bug in the ToolGate extension
installer: the screenshot and preview wrappers must retain independent previous
``_execute`` callables. The original function reused one closure cell and the
second assignment made the screenshot wrapper call itself recursively.
"""
from __future__ import annotations

import json
import time
from typing import Any

from . import desktop_action_preview_tool_legacy as _impl


class _PreviewDenied(
    _impl.DesktopDenied,
    _impl.DesktopActionPreviewConfigurationError,
):
    """One fail-closed preview refusal visible through both public contracts."""


# Legacy functions resolve DesktopDenied through their module globals at call time.
# Use one dual-contract refusal class so direct preview guards and ToolGate wrappers
# preserve the same identity the original single-module implementation exposed.
_impl.DesktopDenied = _PreviewDenied


def _install_gate_extensions(tools_module: Any) -> None:
    _impl._install_audit_redaction(tools_module)

    execute = tools_module.ToolGate._execute
    if not getattr(execute, "_kaliv_desktop_screen_binding", False):
        previous_bind_execute = execute

        def bind_screenshot(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
            _previous: Any = previous_bind_execute,
        ) -> dict[str, Any]:
            result = _previous(self, tool, args, conv, cid, origin)
            if getattr(tool, "name", None) == _impl.SCREENSHOT_TOOL:
                if not cid or origin != "local":
                    raise tools_module.ToolDenied(
                        "screenshot-binding kræver lokal godkendelse"
                    )
                receipt = _impl._unwrap_result(result.get("result"))
                _impl.SCREEN_BINDINGS.bind(
                    receipt["screen_token"],
                    session_id=_impl.screenshot._session_id(conv, cid),
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
            _previous: Any = previous_propose,
        ) -> dict:
            if name == _impl.TOOL_NAME and origin != "local":
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
                raise tools_module.ToolDenied(
                    "desktop-preview planlægges kun med en lokal model"
                )
            return _previous(
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
        previous_preview_execute = execute

        def confirmed_preview(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
            _previous: Any = previous_preview_execute,
        ) -> dict[str, Any]:
            if getattr(tool, "name", None) != _impl.TOOL_NAME:
                return _previous(self, tool, args, conv, cid, origin)
            if not cid or origin != "local":
                raise tools_module.ToolDenied(
                    "desktop_action_preview kræver en frisk lokal ToolGate-godkendelse"
                )
            started = time.time()
            context_token = _impl._EXECUTION_CONTEXT.set((conv, cid, origin))
            audit_token = _impl._PREVIEW_AUDIT.set(None)
            try:
                result = tool.run(args)
                safe_audit = _impl._PREVIEW_AUDIT.get()
                if not isinstance(safe_audit, dict):
                    raise _impl.DesktopActionPreviewConfigurationError(
                        "desktop preview produced no trusted audit projection"
                    )
            except (
                _impl.DesktopDenied,
                _impl.DesktopActionPreviewConfigurationError,
            ) as exc:
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
                _impl._PREVIEW_AUDIT.reset(audit_token)
                _impl._EXECUTION_CONTEXT.reset(context_token)
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
                    safe_audit,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
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


_impl._install_gate_extensions = _install_gate_extensions

__all__ = list(_impl.__all__)
for _name in __all__:
    globals()[_name] = getattr(_impl, _name)


def __getattr__(name: str) -> Any:
    return getattr(_impl, name)

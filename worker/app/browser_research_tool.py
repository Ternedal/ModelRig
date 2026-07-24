"""Feature-gated ToolGate registration for read-only public web research.

The Browser Use runtime lives in a separate Python environment.  This module is
safe to import in the base worker: it imports no browser package, opens no socket
and registers nothing unless ``KALIV_BROWSER_RESEARCH=1`` is explicit.

``external`` is a distinct access class.  The remote operation is read-only, but
an exact user-approved query still leaves the rig.  ToolGate therefore cards it
like a write/desktop action while the canonical descriptor keeps the difference
visible.  A context-bound digest proves the runner was entered through an actual
ToolGate confirmation; calling the runner directly fails closed.
"""
from __future__ import annotations

import contextvars
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .research_contract import ResearchContractError, normalize_domain_rule

FEATURE_ENV = "KALIV_BROWSER_RESEARCH"
PYTHON_ENV = "KALIV_BROWSER_HOST_PYTHON"
MODEL_ENV = "KALIV_BROWSER_MODEL"
OLLAMA_ENV = "KALIV_BROWSER_OLLAMA_URL"
DATA_ENV = "KALIV_BROWSER_DATA_DIR"
EXECUTABLE_ENV = "MODELRIG_BROWSER_EXECUTABLE"
TOOL_NAME = "browser_research"
_MAX_OUTPUT_BYTES = 2 * 1024 * 1024

_APPROVAL_BINDING: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "kaliv_browser_approval_binding", default=None
)


class BrowserResearchConfigurationError(RuntimeError):
    pass


def _enabled(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "on"}


def _canonical_args(args: dict[str, Any]) -> bytes:
    return json.dumps(
        args,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _confirmation_binding(confirmation_id: str, args: dict[str, Any]) -> str:
    args_digest = hashlib.sha256(_canonical_args(args)).hexdigest()
    return hashlib.sha256(
        f"browser-research-v1\n{confirmation_id}\n{args_digest}".encode("utf-8")
    ).hexdigest()


def _normalize_request(args: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise BrowserResearchConfigurationError("browser_research arguments must be an object")
    allowed = {"query", "allowed_domains", "max_sources", "timeout_seconds"}
    unknown = sorted(set(args) - allowed)
    if unknown:
        raise BrowserResearchConfigurationError(
            f"browser_research received unknown fields: {unknown}"
        )

    query = args.get("query")
    if not isinstance(query, str):
        raise BrowserResearchConfigurationError("query must be a string")
    query = " ".join(query.split())
    if not 1 <= len(query) <= 4000:
        raise BrowserResearchConfigurationError("query must contain 1..4000 characters")

    raw_domains = args.get("allowed_domains")
    if not isinstance(raw_domains, list) or not 1 <= len(raw_domains) <= 8:
        raise BrowserResearchConfigurationError(
            "allowed_domains must contain between 1 and 8 public domain rules"
        )
    domains: list[str] = []
    for value in raw_domains:
        if not isinstance(value, str):
            raise BrowserResearchConfigurationError("allowed_domains entries must be strings")
        try:
            normalized = normalize_domain_rule(value)
        except ResearchContractError as exc:
            raise BrowserResearchConfigurationError(str(exc)) from exc
        if normalized not in domains:
            domains.append(normalized)
    if not domains:
        raise BrowserResearchConfigurationError("allowed_domains must not be empty")

    max_sources = args.get("max_sources", 4)
    if isinstance(max_sources, bool) or not isinstance(max_sources, int):
        raise BrowserResearchConfigurationError("max_sources must be an integer")
    if not 1 <= max_sources <= min(8, len(domains) * 4):
        raise BrowserResearchConfigurationError("max_sources is outside the bounded range")

    timeout_seconds = args.get("timeout_seconds", 120)
    if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int):
        raise BrowserResearchConfigurationError("timeout_seconds must be an integer")
    if not 15 <= timeout_seconds <= 240:
        raise BrowserResearchConfigurationError(
            "timeout_seconds must be between 15 and 240"
        )

    return {
        "query": query,
        "allowed_domains": domains,
        "max_sources": max_sources,
        "timeout_seconds": timeout_seconds,
    }


def _browser_python() -> Path:
    raw = os.getenv(PYTHON_ENV, "").strip()
    if not raw:
        raise BrowserResearchConfigurationError(
            f"{PYTHON_ENV} must point to the isolated Browser Use Python executable"
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise BrowserResearchConfigurationError(f"{PYTHON_ENV} must be an absolute path")
    try:
        path = path.resolve(strict=True)
    except OSError as exc:
        raise BrowserResearchConfigurationError(
            f"{PYTHON_ENV} does not identify a readable executable"
        ) from exc
    if not path.is_file():
        raise BrowserResearchConfigurationError(f"{PYTHON_ENV} is not a file")
    try:
        if path.samefile(Path(sys.executable).resolve()):
            raise BrowserResearchConfigurationError(
                "Browser Use must run in its isolated Python environment"
            )
    except OSError:
        pass
    return path


def _loopback_ollama_url() -> str:
    raw = os.getenv(OLLAMA_ENV, "http://127.0.0.1:11434").strip().rstrip("/")
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise BrowserResearchConfigurationError(f"{OLLAMA_ENV} is invalid") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
        or port is None
    ):
        raise BrowserResearchConfigurationError(
            f"{OLLAMA_ENV} must be an explicit loopback URL with a port"
        )
    return raw


def _browser_data_dir() -> Path:
    raw = os.getenv(DATA_ENV, "").strip()
    if raw:
        path = Path(raw).expanduser()
    else:
        root = os.getenv("KALIV_DATA_DIR", "").strip()
        path = Path(root).expanduser() / "browser-research" if root else (
            Path.home() / ".modelrig" / "browser-research"
        )
    path = path.resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _child_environment(data_dir: Path) -> dict[str, str]:
    # This is an allowlist, not a filtered copy.  API keys, bearer tokens,
    # cookies and proxy variables therefore cannot ride into the browser runtime.
    allowed_system = (
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "PATH",
        "TEMP",
        "TMP",
        "USERPROFILE",
        "HOME",
        "LOCALAPPDATA",
        "APPDATA",
        "PROGRAMFILES",
        "PROGRAMFILES(X86)",
    )
    env = {
        key: value
        for key in allowed_system
        if (value := os.getenv(key)) is not None
    }
    model = os.getenv(MODEL_ENV, "").strip()
    if not model or len(model) > 200:
        raise BrowserResearchConfigurationError(
            f"{MODEL_ENV} must name the local model used by Browser Use"
        )
    env.update(
        {
            MODEL_ENV: model,
            OLLAMA_ENV: _loopback_ollama_url(),
            DATA_ENV: str(data_dir),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "BROWSER_USE_LOGGING_LEVEL": "warning",
            "ANONYMIZED_TELEMETRY": "false",
            "DO_NOT_TRACK": "1",
        }
    )
    executable = os.getenv(EXECUTABLE_ENV, "").strip()
    if executable:
        resolved = Path(executable).expanduser().resolve(strict=True)
        if not resolved.is_file():
            raise BrowserResearchConfigurationError(
                f"{EXECUTABLE_ENV} is not a browser executable"
            )
        env[EXECUTABLE_ENV] = str(resolved)
    return env


def _decode_child(stdout: str) -> dict[str, Any]:
    raw = stdout.encode("utf-8", "replace")
    if not raw or len(raw) > _MAX_OUTPUT_BYTES:
        raise BrowserResearchConfigurationError("browser process returned an invalid payload size")
    lines = [line for line in stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise BrowserResearchConfigurationError("browser process violated the one-response contract")
    try:
        value = json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise BrowserResearchConfigurationError("browser process returned invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {"ok", "payload"}:
        raise BrowserResearchConfigurationError("browser process returned an invalid envelope")
    if value["ok"] is not True:
        payload = value.get("payload")
        code = payload.get("code") if isinstance(payload, dict) else None
        raise BrowserResearchConfigurationError(
            f"browser research stopped safely ({code or 'browser_failed'})"
        )
    payload = value["payload"]
    if not isinstance(payload, dict):
        raise BrowserResearchConfigurationError("browser process returned no result payload")
    return payload


def _format_result(payload: dict[str, Any]) -> str:
    research = payload.get("research")
    if not isinstance(research, dict):
        raise BrowserResearchConfigurationError("browser result is missing research evidence")
    answer = research.get("answer")
    sources = research.get("sources")
    if not isinstance(answer, str) or not answer.strip() or not isinstance(sources, list):
        raise BrowserResearchConfigurationError("browser result is malformed")
    lines = [answer.strip(), "", "Verificerede kilder:"]
    for index, source in enumerate(sources, 1):
        if not isinstance(source, dict):
            raise BrowserResearchConfigurationError("browser source is malformed")
        title = source.get("title")
        url = source.get("url")
        digest = source.get("content_sha256")
        if not all(isinstance(value, str) and value for value in (title, url, digest)):
            raise BrowserResearchConfigurationError("browser source evidence is incomplete")
        lines.append(f"[{index}] {title} — {url} (sha256:{digest[:12]})")
    return "\n".join(lines)


def run_browser_research(args: dict[str, Any]) -> str:
    binding = _APPROVAL_BINDING.get()
    if not binding:
        raise BrowserResearchConfigurationError(
            "browser_research may only execute inside a fresh ToolGate confirmation"
        )
    request = _normalize_request(args)
    browser_python = _browser_python()
    data_dir = _browser_data_dir()
    worker_root = Path(__file__).resolve().parents[1]
    bootstrap = (
        "import runpy,sys;"
        f"sys.path.insert(0,{str(worker_root)!r});"
        "runpy.run_module('app.browser_research_process',run_name='__main__')"
    )
    payload = json.dumps(
        {
            "schema": "kaliv-browser-research-launch/v1",
            "approval_binding": binding,
            "request": request,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        with tempfile.TemporaryDirectory(prefix="kaliv-browser-launch-") as cwd:
            result = subprocess.run(
                [str(browser_python), "-I", "-c", bootstrap],
                input=payload,
                text=True,
                encoding="utf-8",
                capture_output=True,
                timeout=request["timeout_seconds"] + 30,
                check=False,
                cwd=cwd,
                env=_child_environment(data_dir),
            )
    except subprocess.TimeoutExpired as exc:
        raise BrowserResearchConfigurationError("browser process exceeded its deadline") from exc
    except OSError as exc:
        raise BrowserResearchConfigurationError("browser process could not be started") from exc
    if result.returncode != 0:
        raise BrowserResearchConfigurationError("browser process failed without a trusted result")
    return _format_result(_decode_child(result.stdout))


@dataclass(frozen=True)
class BrowserResearchTool:
    """The Tool-shaped object registered without importing Browser Use."""

    name: str = TOOL_NAME
    risk: str = "external"
    description: str = (
        "Undersøg offentlige websider på en udtrykkelig domæne-whitelist. "
        "Kun læsning; ingen login, formularer, klik, uploads eller downloads."
    )
    params: dict[str, Any] = None  # type: ignore[assignment]
    run: Any = run_browser_research
    sensitivity: str = "public"
    isolate: bool = False
    env_allow: tuple[str, ...] = ()
    network: str = "public"
    network_destinations: tuple[str, ...] = ("public_web",)
    # Agent 3 v1 has no external-impact enum yet.  A confirmed outbound request
    # is conservatively carried as write impact so its policy cannot downgrade it
    # to an unconfirmed/proactive read.  Canonical access remains `external`.
    impact: str = "write"
    cancellation: str = "forceable"
    idempotent: bool = False
    schedulable: bool = False
    unschedulable_because: str = (
        "offentlig browsing kræver en frisk godkendelse og må ikke køre uden opsyn"
    )

    def __post_init__(self) -> None:
        if self.params is None:
            object.__setattr__(
                self,
                "params",
                {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "query": {"type": "string", "minLength": 1, "maxLength": 4000},
                        "allowed_domains": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 8,
                            "items": {"type": "string"},
                        },
                        "max_sources": {"type": "integer", "minimum": 1, "maximum": 8},
                        "timeout_seconds": {
                            "type": "integer",
                            "minimum": 15,
                            "maximum": 240,
                        },
                    },
                    "required": ["query", "allowed_domains"],
                },
            )

    def human_summary(self, args: dict[str, Any]) -> str:
        request = _normalize_request(args)
        domains = ", ".join(request["allowed_domains"])
        return (
            "Kaliv vil sende denne forespørgsel til den isolerede, lokale "
            f"browser-agent og kun læse fra: {domains}. Forespørgsel: "
            f"“{request['query']}” Ingen login, formularer, klik, uploads eller downloads."
        )


def _install_gate_extension(tools_module: Any) -> None:
    current = tools_module.requires_confirmation
    if not getattr(current, "_kaliv_external_access", False):
        original = current

        def requires_confirmation(tool: Any, origin: str) -> bool:
            return getattr(tool, "risk", None) == "external" or original(tool, origin)

        requires_confirmation._kaliv_external_access = True  # type: ignore[attr-defined]
        tools_module.requires_confirmation = requires_confirmation

    execute = tools_module.ToolGate._execute
    if not getattr(execute, "_kaliv_external_access", False):
        original_execute = execute

        def confirmed_execute(
            self: Any,
            tool: Any,
            args: dict[str, Any],
            conv: str | None,
            cid: str | None,
            origin: str = "local",
        ) -> dict[str, Any]:
            if getattr(tool, "risk", None) != "external":
                return original_execute(self, tool, args, conv, cid, origin)
            if not cid:
                raise tools_module.ToolDenied(
                    "external access requires a fresh ToolGate confirmation"
                )
            token = _APPROVAL_BINDING.set(_confirmation_binding(cid, args))
            try:
                return original_execute(self, tool, args, conv, cid, origin)
            finally:
                _APPROVAL_BINDING.reset(token)

        confirmed_execute._kaliv_external_access = True  # type: ignore[attr-defined]
        tools_module.ToolGate._execute = confirmed_execute


def register_browser_research_tool() -> bool:
    """Register once when explicitly enabled; otherwise leave runtime unchanged."""
    if not _enabled(os.getenv(FEATURE_ENV)):
        return False
    from . import tools

    _install_gate_extension(tools)
    existing = tools.REGISTRY.get(TOOL_NAME)
    if existing is not None:
        if isinstance(existing, BrowserResearchTool):
            return True
        raise RuntimeError(f"{TOOL_NAME} is already registered by another component")
    tools.REGISTRY[TOOL_NAME] = BrowserResearchTool()
    return True


__all__ = [
    "BrowserResearchConfigurationError",
    "BrowserResearchTool",
    "FEATURE_ENV",
    "TOOL_NAME",
    "register_browser_research_tool",
    "run_browser_research",
]

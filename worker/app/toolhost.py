"""Process isolation for tool execution (ISOLATION_DESIGN.md, phase I0).

**Dormant by default.** ``EXECUTOR`` stays in-process unless
``KALIV_TOOL_ISOLATION=process`` is set, and even then only tools that declare
``isolate=True`` leave the worker. Today no tool declares it: this ships the
substrate, tested, before any tool needs it -- so the rig's validation baseline
is untouched and computer-use later lands on ground that already works.

What the process boundary buys (F-012 / ISOLATION_DESIGN §3):
  * T1 a hung tool is KILLED at the timeout instead of pinning a worker thread
  * T2 a crashing tool takes down the child, not the rig
  * T3/T4 a place to drop privileges (restricted token, low integrity, Job
    Object) -- prepared here, provable only on Windows, phase I0 acceptance
  * output caps that hold regardless of what the tool decides to print

What it does NOT buy, stated plainly: this is Tier A isolation. Desktop tools
(Tier B) still reach the user's session by definition -- their safety comes
from the gate, the target allowlist and screenshot binding, not from here.

Deliberately per-call spawn, not a persistent host: tools that own background
work (pull_model) already have the JobStore, and a discrete action (a click, a
screenshot, a file read) is exactly one call. A daemon only becomes necessary
if some tool ever needs to keep state ACROSS calls -- none does.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

DEFAULT_TIMEOUT_S = 30
DEFAULT_OUTPUT_CAP = 20_000

# The child needs a working Python/OS environment and the rig's data paths --
# nothing else. Anything that smells like a credential is dropped: an isolated
# tool has no business inheriting the worker's secrets, and this is the cheap
# half of privilege reduction that works on every OS today.
_ENV_KEEP = (
    "PATH", "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "HOME", "USERPROFILE", "LOCALAPPDATA", "APPDATA", "LANG", "LC_ALL",
)
_ENV_PREFIXES = ("MODELRIG_", "KALIV_", "OLLAMA_URL")
_SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def child_command() -> list[str]:
    """How to start a child, frozen or not.

    The appliance ships the worker as a PyInstaller exe with no Python on the
    box, so ``python -m app.tool_child`` cannot be assumed: a frozen build
    re-invokes ITSELF with a flag (run_worker handles it).
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tool-child"]
    return [sys.executable, "-m", "app.tool_child"]


def child_env(source: dict | None = None) -> dict:
    env = source if source is not None else os.environ
    out = {}
    for k, v in env.items():
        if any(m in k.upper() for m in _SECRET_MARKERS):
            continue
        if k in _ENV_KEEP or k.startswith(_ENV_PREFIXES):
            out[k] = v
    return out


class ProcessExecutor:
    """Runs isolate=True tools in a child process; delegates the rest."""

    def __init__(self, fallback, *, timeout_s: int = DEFAULT_TIMEOUT_S,
                 output_cap: int = DEFAULT_OUTPUT_CAP,
                 child_cmd: list[str] | None = None) -> None:
        self.fallback = fallback
        self.timeout_s = timeout_s
        self.output_cap = output_cap
        self.child_cmd = child_cmd or child_command()

    def execute(self, tool, args: dict) -> str:
        # Lazy import: tools.py selects this executor, so importing it at module
        # level would be a cycle.
        from .tools import ToolDenied, ToolError

        if not getattr(tool, "isolate", False):
            return self.fallback.execute(tool, args)

        req = json.dumps({"tool": tool.name, "args": args}, ensure_ascii=False)
        try:
            proc = subprocess.run(
                self.child_cmd, input=req, capture_output=True, text=True,
                timeout=self.timeout_s, env=child_env(),
            )
        except subprocess.TimeoutExpired as e:
            # subprocess.run has already killed the child here. Grandchildren
            # are NOT covered on Windows without a Job Object -- I0's Windows
            # layer; tracked in ISOLATION_DESIGN §4.1, provable only on the rig.
            raise ToolError(
                f"{tool.name} overskred {self.timeout_s}s og blev stoppet"
            ) from e
        except OSError as e:
            raise ToolError(f"kunne ikke starte isoleret tool-proces: {e}") from e

        payload = _last_json_line(proc.stdout)
        if payload is None:
            tail = (proc.stderr or "").strip()[-400:]
            raise ToolError(
                f"{tool.name}: isoleret proces gav intet resultat "
                f"(exit {proc.returncode}){': ' + tail if tail else ''}"
            )
        if payload.get("ok"):
            return _cap(str(payload.get("result", "")), self.output_cap)
        err = str(payload.get("error") or "ukendt fejl")
        if payload.get("kind") == "denied":
            raise ToolDenied(err)
        raise ToolError(err)


def _last_json_line(stdout: str) -> dict | None:
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and "ok" in obj:
            return obj
    return None


def _cap(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n[... afkortet ved {limit} tegn]"

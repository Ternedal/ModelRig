"""Process isolation for tool execution (ISOLATION_DESIGN.md, phase I0).

**Dormant by default.** ``EXECUTOR`` stays in-process unless
``KALIV_TOOL_ISOLATION=process`` is set, and even then only tools that declare
``isolate=True`` leave the worker. No tool declares it: this ships the
substrate, tested, before any tool needs it.

What the process boundary buys (F-012 / ISOLATION_DESIGN §3):
  * T1 a hung tool is KILLED at the timeout instead of pinning a worker thread
  * T2 a crashing tool takes down the child, not the rig
  * T3/T4 a place to drop privileges -- the Windows half (Job Object,
    restricted token, low integrity) is I0b and needs the rig
  * output bounded WHILE IT IS PRODUCED, not after

What it does NOT buy, stated plainly: this is Tier A isolation. Desktop tools
(Tier B) still reach the user's session by definition -- their safety comes
from the gate, the target allowlist and screenshot binding, not from here.

Per-call spawn, deliberately, not a daemon: tools that own background work
(pull_model) keep their thread in the worker and already have the JobStore,
while a click/screenshot/file-read IS one call.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time

DEFAULT_TIMEOUT_S = 30
DEFAULT_OUTPUT_CAP = 20_000
DEFAULT_STDERR_CAP = 8_000
_READ_CHUNK = 8192
_POLL_S = 0.05

# The OS variables a Python process needs to start at all. NOTHING else is
# inherited by default (analysis F-203): the previous version allowed whole
# MODELRIG_*/KALIV_* prefixes and stripped credentials by NAME markers -- a
# denylist, so a future COOKIE, SESSION, AUTH or CERT would have ridden along.
# A tool now declares exactly what it needs via Tool.env_allow, and the default
# is an empty application environment.
_OS_ESSENTIALS = (
    "PATH", "PYTHONPATH", "PYTHONIOENCODING", "PYTHONUTF8", "PYTHONHOME",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "TMPDIR",
    "LANG", "LC_ALL", "LD_LIBRARY_PATH",
)


class ToolHostError(RuntimeError):
    """Raised inside the host itself (spawn/cap/timeout), never by the tool."""


def child_command() -> list[str]:
    """How to start a child, frozen or not.

    The appliance ships the worker as a PyInstaller exe with no Python on the
    box, so ``python -m app.tool_child`` cannot be assumed: a frozen build
    re-invokes ITSELF with a flag (run_worker handles it).
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--tool-child"]
    return [sys.executable, "-m", "app.tool_child"]


def child_env(tool=None, source: dict | None = None) -> dict:
    """Capability-minimal environment: OS essentials + what the tool declared.

    An allowlist by construction. If a tool needs the audit DB path or the
    documents root, it says so in ``env_allow``; anything it did not name does
    not exist inside the child, credential-shaped or not.
    """
    env = dict(source) if source is not None else dict(os.environ)
    allowed = set(_OS_ESSENTIALS) | set(getattr(tool, "env_allow", ()) or ())
    return {k: v for k, v in env.items() if k in allowed}


def _spawn_kwargs() -> dict:
    """Put the child in its own process group so the whole tree can be killed."""
    if os.name == "posix":
        return {"start_new_session": True}
    return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}


def kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child AND anything it started.

    proc.kill() alone reaps only the direct child; a tool that spawned a
    helper would leave it running with the socket/file still open. On POSIX the
    process group does it. On Windows taskkill /T is the best available until
    I0b lands a Job Object with kill-on-close, which is the real fix and needs
    the rig (ISOLATION_DESIGN §4.1).
    """
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
            proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def _drain(stream, cap: int, sink: list, over: threading.Event) -> None:
    """Read a pipe with a HARD byte cap, counted as bytes arrive.

    The cap has to hold during the run (analysis F-202): the old version used
    subprocess.run(capture_output=True) and truncated the string afterwards, so
    a tool printing without end filled the WORKER's memory first and got capped
    only in the corpse. Here the reader stops at the cap and signals; the caller
    kills the tree.
    """
    total = 0
    try:
        while True:
            chunk = stream.read(_READ_CHUNK)
            if not chunk:
                return
            total += len(chunk)
            if total > cap:
                over.set()
                return
            sink.append(chunk)
    except Exception:
        return
    finally:
        try:
            stream.close()
        except Exception:
            pass


class ProcessExecutor:
    """Runs isolate=True tools in a child process; delegates the rest."""

    def __init__(self, fallback, *, timeout_s: int = DEFAULT_TIMEOUT_S,
                 output_cap: int = DEFAULT_OUTPUT_CAP,
                 stderr_cap: int = DEFAULT_STDERR_CAP,
                 child_cmd: list[str] | None = None) -> None:
        self.fallback = fallback
        self.timeout_s = timeout_s
        self.output_cap = output_cap
        self.stderr_cap = stderr_cap
        self.child_cmd = child_cmd or child_command()

    def execute(self, tool, args: dict) -> str:
        # Lazy import: tools.py selects this executor, so importing it at module
        # level would be a cycle.
        from .tools import ToolDenied, ToolError

        if not getattr(tool, "isolate", False):
            return self.fallback.execute(tool, args)

        req = json.dumps({"tool": tool.name, "args": args}, ensure_ascii=False)
        try:
            proc = subprocess.Popen(
                self.child_cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, env=child_env(tool), **_spawn_kwargs(),
            )
        except OSError as e:
            raise ToolError(f"kunne ikke starte isoleret tool-proces: {e}") from e

        out_chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        over = threading.Event()
        readers = [
            threading.Thread(target=_drain, args=(proc.stdout, self.output_cap, out_chunks, over), daemon=True),
            threading.Thread(target=_drain, args=(proc.stderr, self.stderr_cap, err_chunks, over), daemon=True),
        ]
        for t in readers:
            t.start()
        try:
            proc.stdin.write(req.encode())
            proc.stdin.close()
        except Exception:
            pass

        deadline = time.monotonic() + self.timeout_s
        try:
            while True:
                if over.is_set():
                    kill_tree(proc)
                    raise ToolError(
                        f"{tool.name} skrev mere end {self.output_cap} bytes og blev stoppet "
                        "(output-grænsen håndhæves undervejs, ikke bagefter)"
                    )
                try:
                    proc.wait(timeout=_POLL_S)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() > deadline:
                        kill_tree(proc)
                        raise ToolError(
                            f"{tool.name} overskred {self.timeout_s}s og blev stoppet"
                        )
        finally:
            for t in readers:
                t.join(timeout=1)

        # The cap can also end the run WITHOUT us killing anything: when the
        # reader stops at the limit it closes the pipe, and the child dies of a
        # broken pipe on its next write. That is a capped tool, not a mysterious
        # one -- say so, or the diagnosis names the symptom ("no result") while
        # the cause disappears.
        if over.is_set():
            kill_tree(proc)
            raise ToolError(
                f"{tool.name} skrev mere end {self.output_cap} bytes og blev stoppet "
                "(output-grænsen håndhæves undervejs, ikke bagefter)"
            )

        stdout = b"".join(out_chunks).decode("utf-8", "replace")
        stderr = b"".join(err_chunks).decode("utf-8", "replace")
        payload = _last_json_line(stdout)
        if payload is None:
            tail = stderr.strip()[-400:]
            raise ToolError(
                f"{tool.name}: isoleret proces gav intet resultat "
                f"(exit {proc.returncode}){': ' + tail if tail else ''}"
            )
        if payload.get("ok"):
            return str(payload.get("result", ""))
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

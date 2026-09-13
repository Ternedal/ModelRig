"""Direct production Git process boundary for RSI physical-request observation.

The generic bounded-subprocess Linux path relaunches its Python supervisor from
``bounded_subprocess.py`` on disk. That is appropriate for general DevControl
workloads, but production RSI authority must not reread an ordinary package
source file after the host-controlled Git runtime has been attested. This module
installs a deliberately tiny direct runner for the sole allowed production Git
operation. It executes only the already-attested Git executable, uses no shell,
and never launches ModelRig package code in the child process.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from . import _improvement_physical_runtime_host_control as _host

_TIMEOUT_SECONDS = 120


def _kill_process(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            try:
                process.kill()
            except OSError:
                return
        return
    try:
        process.kill()
    except OSError:
        return


def _run_direct_host_git(
    self: Any,
    args: tuple[str, ...],
    *,
    cwd: Path,
    maximum: int,
    **_kwargs: Any,
) -> bytes:
    """Run the one authority-bearing Git read without a package-file supervisor."""

    if args != ("rev-parse", "--verify", "refs/heads/main^{commit}"):
        raise _host.PhysicalHostRuntimeError(
            "physical request production Git reader operation is unsupported"
        )
    if (
        isinstance(maximum, bool)
        or not isinstance(maximum, int)
        or maximum < 1
        or maximum > _host._MAX_OUTPUT_BYTES
    ):
        raise _host.PhysicalHostRuntimeError(
            "physical request production Git reader output bound is invalid"
        )

    root = _host._existing_link_free_directory(
        cwd,
        name="physical request Git cwd",
    )
    runtime = _host._require_host_controlled_physical_git_runtime(self.runtime)
    no_hooks = runtime.transaction_root / ".physical-authority-no-hooks"
    command = [
        os.fspath(runtime.executable_path),
        "-c",
        "color.ui=false",
        "-c",
        "core.quotepath=false",
        "-c",
        f"core.hooksPath={os.fspath(no_hooks)}",
        "-c",
        "protocol.allow=never",
        "-c",
        "gc.auto=0",
        "-c",
        "maintenance.auto=false",
        "-c",
        "commit.gpgSign=false",
        "-c",
        "tag.gpgSign=false",
        *args,
    ]

    popen_kwargs: dict[str, Any] = {
        "cwd": root,
        "env": _host._host_runtime_environment(runtime),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "shell": False,
        "text": False,
        "bufsize": 0,
    }
    if os.name == "posix":
        popen_kwargs["start_new_session"] = True
    elif os.name == "nt":
        popen_kwargs["creationflags"] = getattr(
            subprocess,
            "CREATE_NEW_PROCESS_GROUP",
            0,
        )
    else:
        raise _host.PhysicalHostRuntimeError(
            "physical request direct Git process platform is unsupported"
        )

    try:
        process = subprocess.Popen(command, **popen_kwargs)
    except (OSError, ValueError) as exc:
        raise _host.PhysicalHostRuntimeError(
            "physical request host-controlled Git process could not start"
        ) from exc

    try:
        stdout, stderr = process.communicate(timeout=_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        _kill_process(process)
        try:
            process.communicate(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise _host.PhysicalHostRuntimeError(
            "physical request host-controlled Git read exceeded its time bound"
        ) from exc

    _host._require_host_controlled_physical_git_runtime(runtime)
    if len(stdout) + len(stderr) > maximum:
        raise _host.PhysicalHostRuntimeError(
            "physical request host-controlled Git read exceeded its output bound"
        )
    if process.returncode != 0:
        raise _host.PhysicalHostRuntimeError(
            "physical request host-controlled Git read failed"
        )
    return stdout


def install_direct_host_controlled_git_process() -> None:
    """Replace only the production host-reader method with the direct runner."""

    if getattr(_host, "_direct_host_git_process_installed", False):
        return
    _host._HostControlledPhysicalGitReader.run = _run_direct_host_git
    _host._direct_host_git_process_installed = True


__all__: list[str] = []

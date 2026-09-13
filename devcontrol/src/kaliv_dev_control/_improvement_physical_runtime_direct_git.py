"""Direct production Git process boundary for RSI physical-request observation.

The generic bounded-subprocess Linux path relaunches its Python supervisor from
``bounded_subprocess.py`` on disk. That is appropriate for general DevControl
workloads, but production RSI authority must not reread an ordinary package
source file after the host-controlled Git runtime has been attested. This module
installs a deliberately tiny direct runner for the sole allowed production Git
operation. It executes only the already-attested Git executable, uses no shell,
and never launches ModelRig package code in the child process.

The observation target is also part of the production authority boundary. A
host-controlled executable reading a caller-writable repository would still let
a same-user process swap ``refs/heads/main`` around the authoritative read. The
production reader therefore requires the checkout root/ancestor chain and its
entire ``.git`` metadata tree to be host-admin controlled before and after the
read. Ordinary worktree files need not be immutable because ``rev-parse`` reads
only repository metadata for this boundary; linked/common Git directories and
external object/config authority are deliberately unsupported and fail closed.
"""
from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path
from typing import Any

from . import _improvement_physical_runtime_host_control as _host

_TIMEOUT_SECONDS = 120
_MAX_GIT_CONFIG_BYTES = 1024 * 1024


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


def _reject_config_includes(config: Path) -> None:
    """Reject include/includeIf from any repository config Git may load."""

    if not config.exists():
        return
    try:
        payload = config.read_bytes()
    except OSError as exc:
        raise _host.PhysicalHostRuntimeError(
            "physical request repository Git config is unavailable"
        ) from exc
    if len(payload) > _MAX_GIT_CONFIG_BYTES:
        raise _host.PhysicalHostRuntimeError(
            "physical request repository Git config is too large"
        )
    try:
        # Git accepts an optional UTF-8 BOM at the beginning of a config file.
        # Decode with utf-8-sig so the security scan sees the same first section
        # header Git sees; otherwise a BOM-prefixed [include] would evade the
        # startswith checks below while Git still follows the include.
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise _host.PhysicalHostRuntimeError(
            "physical request repository Git config is not canonical UTF-8"
        ) from exc
    for line in text.splitlines():
        compact = "".join(line.strip().lower().split())
        if compact.startswith("[include]") or compact.startswith("[includeif"):
            raise _host.PhysicalHostRuntimeError(
                "physical request repository Git config includes external state"
            )


def _reject_external_git_metadata(git_dir: Path) -> None:
    """Reject Git metadata layouts that can redirect object/config authority."""

    if (git_dir / "commondir").exists():
        raise _host.PhysicalHostRuntimeError(
            "physical request repository uses an external common Git directory"
        )
    if (git_dir / "objects" / "info" / "alternates").exists():
        raise _host.PhysicalHostRuntimeError(
            "physical request repository uses external Git object alternates"
        )
    # Git always reads .git/config. When extensions.worktreeConfig is enabled,
    # it additionally reads .git/config.worktree. Scan both unconditionally so
    # a worktree config can never smuggle an include to caller-writable state.
    for name in ("config", "config.worktree"):
        _reject_config_includes(git_dir / name)


def _require_host_controlled_repository(repository_root: Path) -> Path:
    """Require an admin-controlled checkout identity and Git metadata tree."""

    root = _host._existing_link_free_directory(
        repository_root,
        name="physical request Git repository root",
    )
    git_dir = root / ".git"
    if os.name == "posix":
        _host._require_posix_object(root, is_directory=True)
        _host._require_posix_object(git_dir, is_directory=True)
        for candidate in sorted(git_dir.rglob("*")):
            _host._require_posix_object(candidate, is_directory=candidate.is_dir())
        cursor = root.parent
        while True:
            _host._require_posix_object(cursor, is_directory=True)
            if cursor.parent == cursor:
                break
            cursor = cursor.parent
    elif os.name == "nt":
        root, anchor = _host._windows_under_program_files(root)
        _host._require_windows_object(root, is_directory=True)
        _host._require_windows_object(git_dir, is_directory=True)
        for candidate in sorted(git_dir.rglob("*")):
            _host._require_windows_object(candidate, is_directory=candidate.is_dir())
        cursor = root.parent
        anchor_norm = os.path.normcase(os.fspath(anchor))
        while True:
            _host._require_windows_object(cursor, is_directory=True)
            cursor_norm = os.path.normcase(os.path.abspath(os.fspath(cursor)))
            if cursor_norm == anchor_norm:
                break
            parent = cursor.parent
            if parent == cursor:
                raise _host.PhysicalHostRuntimeError(
                    "physical request repository directory chain escaped Program Files"
                )
            cursor = parent
    else:
        raise _host.PhysicalHostRuntimeError(
            "physical request repository host-control platform is unsupported"
        )
    _reject_external_git_metadata(git_dir)
    return root


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

    root = _require_host_controlled_repository(cwd)
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
    _require_host_controlled_repository(root)
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
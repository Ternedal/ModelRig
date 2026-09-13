"""Host-control boundary for production RSI physical-request Git reads.

The generic/private deterministic test seam may snapshot a caller-owned staged
runtime. Production authority must not execute from a tree writable by another
process under the service account. This installer therefore adds a separate
production consume path that accepts only an exact TrustedGitRuntime whose
complete transaction tree is controlled by the host administrator:

* POSIX: root-owned regular files/directories, with no group/world write or
  extended POSIX ACLs in the runtime tree or its ancestor chain.
* Windows: a tree under Program Files whose owner/DACL grants write/control only
  to SYSTEM, Administrators, or TrustedInstaller.

The production Git read executes directly from that host-controlled tree. It
uses no caller-writable transaction copy and no mutable per-run Git config
files. The signed CandidateSnapshotReceipt still pins the exact runtime manifest
and executable digest in the normal reservation transaction.
"""
from __future__ import annotations

import contextvars
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .bounded_subprocess import BoundedSubprocessError, run_bounded_subprocess
from .improvement_physical_authority_keyring import (
    PhysicalRequestAuthorityKeyringError,
    _require_no_posix_acl,
    _validate_windows_acl_snapshot,
    _windows_acl_snapshot,
)
from .trusted_git_runtime_model import (
    TrustedGitRuntimeError,
    _existing_link_free_directory,
    _has_linkish_component,
)
from .trusted_git_runtime_staging import TrustedGitRuntime

_HOST_CONTROLLED_RUNTIME_CONTEXT: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "rsi_physical_host_controlled_git_runtime",
    default=False,
)
_MAX_OUTPUT_BYTES = 4096


class PhysicalHostRuntimeError(ValueError):
    """The production physical-request Git runtime is not host controlled."""


def _require_posix_object(path: Path, *, is_directory: bool) -> None:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime object is unavailable"
        ) from exc
    if stat.S_ISLNK(observed.st_mode):
        raise PhysicalHostRuntimeError(
            "physical request Git runtime contains a symbolic link"
        )
    if is_directory:
        if not stat.S_ISDIR(observed.st_mode) or observed.st_nlink < 1:
            raise PhysicalHostRuntimeError(
                "physical request Git runtime directory is unsafe"
            )
    elif not stat.S_ISREG(observed.st_mode) or observed.st_nlink < 1:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime file is unsafe"
        )
    if observed.st_uid != 0 or stat.S_IMODE(observed.st_mode) & 0o022:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime is not root-controlled"
        )
    try:
        _require_no_posix_acl(path)
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime uses unsafe POSIX ACL state"
        ) from exc


def _require_posix_host_control(runtime: TrustedGitRuntime) -> None:
    root = Path(runtime.transaction_root)
    _require_posix_object(root, is_directory=True)
    for candidate in sorted(root.rglob("*")):
        _require_posix_object(candidate, is_directory=candidate.is_dir())
    cursor = root.parent
    while True:
        _require_posix_object(cursor, is_directory=True)
        if cursor.parent == cursor:
            break
        cursor = cursor.parent


def _windows_under_program_files(path: Path) -> tuple[Path, Path]:
    candidate = Path(os.path.abspath(os.fspath(path)))
    anchor = Path(os.path.abspath(r"C:\Program Files"))
    candidate_norm = os.path.normcase(os.fspath(candidate))
    anchor_norm = os.path.normcase(os.fspath(anchor))
    try:
        common = os.path.normcase(os.path.commonpath([candidate_norm, anchor_norm]))
    except ValueError as exc:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime is outside Program Files"
        ) from exc
    if common != anchor_norm:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime is outside Program Files"
        )
    return candidate, anchor


def _require_windows_object(path: Path, *, is_directory: bool) -> None:
    if _has_linkish_component(path):
        raise PhysicalHostRuntimeError(
            "physical request Git runtime contains a linked path"
        )
    if is_directory:
        if not path.is_dir():
            raise PhysicalHostRuntimeError(
                "physical request Git runtime directory is unavailable"
            )
    elif not path.is_file():
        raise PhysicalHostRuntimeError(
            "physical request Git runtime file is unavailable"
        )
    try:
        owner_sid, entries = _windows_acl_snapshot(path)
        _validate_windows_acl_snapshot(
            owner_sid,
            entries,
            is_directory=is_directory,
        )
    except PhysicalRequestAuthorityKeyringError as exc:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime Windows ACL is not host controlled"
        ) from exc


def _require_windows_host_control(runtime: TrustedGitRuntime) -> None:
    root, anchor = _windows_under_program_files(Path(runtime.transaction_root))
    _require_windows_object(root, is_directory=True)
    for candidate in sorted(root.rglob("*")):
        _require_windows_object(candidate, is_directory=candidate.is_dir())
    cursor = root.parent
    anchor_norm = os.path.normcase(os.fspath(anchor))
    while True:
        _require_windows_object(cursor, is_directory=True)
        cursor_norm = os.path.normcase(os.path.abspath(os.fspath(cursor)))
        if cursor_norm == anchor_norm:
            break
        parent = cursor.parent
        if parent == cursor:
            raise PhysicalHostRuntimeError(
                "physical request Git runtime directory chain escaped Program Files"
            )
        cursor = parent


def _require_host_controlled_physical_git_runtime(
    trusted_git: TrustedGitRuntime,
) -> TrustedGitRuntime:
    """Reconstruct and attest one admin-controlled exact runtime tree."""

    if type(trusted_git) is not TrustedGitRuntime:
        raise PhysicalHostRuntimeError(
            "physical request production Git runtime must be exact TrustedGitRuntime"
        )
    try:
        source = TrustedGitRuntime(Path(os.fspath(trusted_git.transaction_root)).resolve())
        if source.receipt.sha256 != trusted_git.receipt.sha256:
            raise PhysicalHostRuntimeError(
                "physical request Git runtime receipt changed before host-control validation"
            )
        source.verify()
        if os.name == "posix":
            _require_posix_host_control(source)
        elif os.name == "nt":
            _require_windows_host_control(source)
        else:
            raise PhysicalHostRuntimeError(
                "physical request Git runtime host-control platform is unsupported"
            )
        source.verify()
        return source
    except PhysicalHostRuntimeError:
        raise
    except (AttributeError, OSError, TypeError, ValueError, TrustedGitRuntimeError) as exc:
        raise PhysicalHostRuntimeError(
            "physical request Git runtime host-control validation failed"
        ) from exc


def _host_runtime_environment(runtime: TrustedGitRuntime) -> dict[str, str]:
    environment: dict[str, str] = {}
    for name in ("SYSTEMROOT", "WINDIR", "PATHEXT"):
        value = os.environ.get(name)
        if value:
            environment[name] = value
    executable_directories = list(runtime.path_directories)
    for directory in runtime.library_directories:
        if directory not in executable_directories:
            executable_directories.append(directory)
    library_path = os.pathsep.join(
        os.fspath(path) for path in runtime.library_directories
    )
    # These paths deliberately do not exist. Their parent is host controlled,
    # so the untrusted service account cannot populate them between validation
    # and execution. rev-parse needs no home, hooks, or temporary write state.
    no_state = runtime.transaction_root / ".physical-authority-no-state"
    environment.update(
        {
            "PATH": os.pathsep.join(
                os.fspath(path) for path in executable_directories
            ),
            "GIT_EXEC_PATH": os.fspath(runtime.exec_path),
            "HOME": os.fspath(no_state),
            "XDG_CONFIG_HOME": os.fspath(no_state),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_NO_REPLACE_OBJECTS": "1",
            "TEMP": os.fspath(no_state),
            "TMP": os.fspath(no_state),
            "TMPDIR": os.fspath(no_state),
            "LC_ALL": "C",
            "LANG": "C",
        }
    )
    if library_path:
        environment["LD_LIBRARY_PATH"] = library_path
        environment["DYLD_LIBRARY_PATH"] = library_path
    return environment


class _HostControlledPhysicalGitReader:
    """Minimal no-shell reader for the only Git operation this boundary needs."""

    def __init__(self, runtime: TrustedGitRuntime) -> None:
        self.runtime = _require_host_controlled_physical_git_runtime(runtime)

    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        maximum: int,
        **_kwargs: Any,
    ) -> bytes:
        if args != ("rev-parse", "--verify", "refs/heads/main^{commit}"):
            raise PhysicalHostRuntimeError(
                "physical request production Git reader operation is unsupported"
            )
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or maximum < 1
            or maximum > _MAX_OUTPUT_BYTES
        ):
            raise PhysicalHostRuntimeError(
                "physical request production Git reader output bound is invalid"
            )
        root = _existing_link_free_directory(cwd, name="physical request Git cwd")
        runtime = _require_host_controlled_physical_git_runtime(self.runtime)
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
        try:
            result = run_bounded_subprocess(
                command,
                cwd=root,
                env=_host_runtime_environment(runtime),
                stdin_bytes=None,
                timeout_seconds=120,
                max_output_bytes=maximum,
                stdout_prefix_bytes=maximum,
                stderr_prefix_bytes=maximum,
            )
        except BoundedSubprocessError as exc:
            raise PhysicalHostRuntimeError(
                "physical request host-controlled Git process boundary failed"
            ) from exc
        _require_host_controlled_physical_git_runtime(runtime)
        if result.output_limit_exceeded or result.timed_out:
            raise PhysicalHostRuntimeError(
                "physical request host-controlled Git read exceeded its bound"
            )
        if result.returncode != 0:
            raise PhysicalHostRuntimeError(
                "physical request host-controlled Git read failed"
            )
        if result.stdout.truncated or result.stderr.truncated:
            raise PhysicalHostRuntimeError(
                "physical request host-controlled Git evidence is incomplete"
            )
        return result.stdout.prefix


def install_host_controlled_physical_runtime_boundary(implementation: Any) -> None:
    """Add a production-only host-controlled runtime path without changing tests."""

    if implementation is None:
        raise PhysicalHostRuntimeError("reservation implementation is unavailable")
    if getattr(implementation, "_host_controlled_runtime_boundary_installed", False):
        return

    original_snapshot = implementation._snapshot_trusted_git_runtime
    original_observe = implementation.observe_local_main_head
    production_consume = implementation._consume_physical_qualification_request_once

    def snapshot_runtime(
        trusted_git: TrustedGitRuntime,
        *,
        operation_root: Path,
    ) -> tuple[TrustedGitRuntime, Path]:
        if not _HOST_CONTROLLED_RUNTIME_CONTEXT.get():
            return original_snapshot(trusted_git, operation_root=operation_root)
        runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        operation = implementation._safe_root(
            operation_root,
            name="physical request Git operation root",
        )
        cleanup_root = Path(
            tempfile.mkdtemp(prefix=".rsi-host-runtime-sentinel-", dir=operation)
        ).resolve()
        return runtime, cleanup_root

    def observe_local_main_head(
        *,
        trusted_git: TrustedGitRuntime,
        repository_root: Path,
        operation_root: Path,
        observed_at_utc: str,
        repository: str = "Ternedal/ModelRig",
    ) -> Any:
        if not _HOST_CONTROLLED_RUNTIME_CONTEXT.get():
            return original_observe(
                trusted_git=trusted_git,
                repository_root=repository_root,
                operation_root=operation_root,
                observed_at_utc=observed_at_utc,
                repository=repository,
            )
        runtime = _require_host_controlled_physical_git_runtime(trusted_git)
        manifest = runtime.receipt.manifest
        executable = next(
            item
            for item in manifest.files
            if item.relative_path == manifest.executable_relative_path
        )
        observation = implementation._observe_with_reader(
            reader=_HostControlledPhysicalGitReader(runtime),
            repository_root=repository_root,
            repository=repository,
            observed_at_utc=observed_at_utc,
            git_runtime_manifest_sha256=manifest.sha256,
            git_executable_sha256=executable.sha256,
        )
        _require_host_controlled_physical_git_runtime(runtime)
        return observation

    def consume_host_controlled_runtime(*args: Any, **kwargs: Any) -> Any:
        token = _HOST_CONTROLLED_RUNTIME_CONTEXT.set(True)
        try:
            return production_consume(*args, **kwargs)
        finally:
            _HOST_CONTROLLED_RUNTIME_CONTEXT.reset(token)

    implementation._snapshot_trusted_git_runtime = snapshot_runtime
    implementation.observe_local_main_head = observe_local_main_head
    implementation._consume_physical_qualification_request_once_host_controlled = (
        consume_host_controlled_runtime
    )
    implementation._host_controlled_runtime_boundary_installed = True


__all__: list[str] = []
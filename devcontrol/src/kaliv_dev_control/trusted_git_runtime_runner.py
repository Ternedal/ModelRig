"""No-shell execution through one staged and reverified Git runtime."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Mapping

from .trusted_git_runtime_model import (
    _MAX_OUTPUT_BYTES,
    TrustedGitRuntimeError,
    TrustedGitRuntimeEvidence,
    _existing_link_free_directory,
    _has_linkish_component,
    _integer,
)
from .trusted_git_runtime_staging import TrustedGitRuntime


class TrustedGitRunner:
    """No-shell runner using only one staged and reverified Git runtime."""

    def __init__(self, runtime: TrustedGitRuntime, *, operation_root: Path) -> None:
        if not isinstance(runtime, TrustedGitRuntime):
            raise TrustedGitRuntimeError("trusted Git runner requires a runtime")
        self.runtime = runtime
        self.operation_root = _existing_link_free_directory(
            operation_root,
            name="Git operation root",
        )
        self._home = self.operation_root / "isolated-home"
        self._xdg = self.operation_root / "isolated-xdg"
        self._hooks = self.operation_root / "disabled-hooks"
        self._template = self.operation_root / "empty-template"
        self._temp = self.operation_root / "isolated-temp"
        for directory in (
            self._home,
            self._xdg,
            self._hooks,
            self._template,
            self._temp,
        ):
            if directory.exists():
                if (
                    not directory.is_dir()
                    or _has_linkish_component(directory)
                    or any(directory.iterdir())
                ):
                    raise TrustedGitRuntimeError(
                        "Git isolation directory is unsafe"
                    )
            else:
                directory.mkdir()
        self._global_config = self.operation_root / "empty-global-config"
        if self._global_config.exists():
            if (
                not self._global_config.is_file()
                or _has_linkish_component(self._global_config)
                or self._global_config.read_bytes() != b""
            ):
                raise TrustedGitRuntimeError(
                    "Git global configuration is unsafe"
                )
        else:
            self._global_config.write_bytes(b"")
        self.runtime.verify()
        self._verify_isolation()

    def _verify_isolation(self) -> None:
        for directory in (
            self._home,
            self._xdg,
            self._hooks,
            self._template,
            self._temp,
        ):
            if (
                not directory.is_dir()
                or _has_linkish_component(directory)
                or any(directory.iterdir())
            ):
                raise TrustedGitRuntimeError("Git isolation directory changed")
        if (
            not self._global_config.is_file()
            or _has_linkish_component(self._global_config)
            or self._global_config.read_bytes() != b""
        ):
            raise TrustedGitRuntimeError("Git global configuration changed")

    def environment(self, extra: Mapping[str, str] | None = None) -> dict[str, str]:
        environment: dict[str, str] = {}
        for name in ("SYSTEMROOT", "WINDIR", "PATHEXT"):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        executable_directories = list(self.runtime.path_directories)
        for directory in self.runtime.library_directories:
            if directory not in executable_directories:
                executable_directories.append(directory)
        library_path = os.pathsep.join(
            os.fspath(path) for path in self.runtime.library_directories
        )
        environment.update(
            {
                "PATH": os.pathsep.join(
                    os.fspath(path) for path in executable_directories
                ),
                "GIT_EXEC_PATH": os.fspath(self.runtime.exec_path),
                "HOME": os.fspath(self._home),
                "XDG_CONFIG_HOME": os.fspath(self._xdg),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.fspath(self._global_config),
                "GIT_TERMINAL_PROMPT": "0",
                "GCM_INTERACTIVE": "Never",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "TEMP": os.fspath(self._temp),
                "TMP": os.fspath(self._temp),
                "TMPDIR": os.fspath(self._temp),
                "LC_ALL": "C",
                "LANG": "C",
            }
        )
        if library_path:
            environment["LD_LIBRARY_PATH"] = library_path
            environment["DYLD_LIBRARY_PATH"] = library_path
        if extra:
            allowed = {
                "GIT_INDEX_FILE",
                "GIT_AUTHOR_NAME",
                "GIT_AUTHOR_EMAIL",
                "GIT_AUTHOR_DATE",
                "GIT_COMMITTER_NAME",
                "GIT_COMMITTER_EMAIL",
                "GIT_COMMITTER_DATE",
            }
            if set(extra) - allowed:
                raise TrustedGitRuntimeError(
                    "Git environment contains an unsupported field"
                )
            for name, value in extra.items():
                if (
                    not isinstance(value, str)
                    or not value
                    or "\x00" in value
                    or "\n" in value
                    or "\r" in value
                ):
                    raise TrustedGitRuntimeError(
                        f"Git environment {name} is invalid"
                    )
                environment[name] = value
        return environment

    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        stdin: bytes | None = None,
        maximum: int = _MAX_OUTPUT_BYTES,
        timeout_seconds: int = 120,
        expected_codes: tuple[int, ...] = (0,),
        extra_env: Mapping[str, str] | None = None,
    ) -> bytes:
        if (
            not isinstance(args, tuple)
            or not args
            or any(
                not isinstance(item, str) or not item or "\x00" in item
                for item in args
            )
        ):
            raise TrustedGitRuntimeError("Git arguments are invalid")
        _integer(maximum, name="Git output bound", low=1, high=_MAX_OUTPUT_BYTES)
        _integer(timeout_seconds, name="Git timeout", low=1, high=3600)
        root = _existing_link_free_directory(cwd, name="Git cwd")
        self.runtime.verify()
        self._verify_isolation()
        command = [
            os.fspath(self.runtime.executable_path),
            "-c",
            "color.ui=false",
            "-c",
            "core.quotepath=false",
            "-c",
            f"core.hooksPath={os.fspath(self._hooks)}",
            "-c",
            "protocol.allow=never",
            "-c",
            "protocol.file.allow=always",
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
            kwargs: dict[str, Any] = {
                "cwd": root,
                "stdout": subprocess.PIPE,
                "stderr": subprocess.PIPE,
                "timeout": timeout_seconds,
                "check": False,
                "shell": False,
                "env": self.environment(extra_env),
            }
            if stdin is None:
                kwargs["stdin"] = subprocess.DEVNULL
            else:
                kwargs["input"] = stdin
            completed = subprocess.run(command, **kwargs)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise TrustedGitRuntimeError("Git command failed to complete") from exc
        if len(completed.stdout) + len(completed.stderr) > maximum:
            raise TrustedGitRuntimeError("Git command exceeded its output bound")
        if completed.returncode not in expected_codes:
            raise TrustedGitRuntimeError("Git command failed")
        self.runtime.verify()
        self._verify_isolation()
        return completed.stdout

    def evidence(self) -> TrustedGitRuntimeEvidence:
        version = self.run(
            ("--version",),
            cwd=self.operation_root,
            maximum=4096,
        ).decode("utf-8", errors="strict").strip()
        manifest = self.runtime.receipt.manifest
        executable = next(
            item
            for item in manifest.files
            if item.relative_path == manifest.executable_relative_path
        )
        return TrustedGitRuntimeEvidence(
            runtime_manifest_sha256=manifest.sha256,
            runtime_file_count=len(manifest.files),
            runtime_bytes=manifest.total_bytes,
            executable_sha256=executable.sha256,
            version=version,
            exec_path_relative_path=manifest.exec_path_relative_path,
            path_relative_directories=manifest.path_relative_directories,
            library_relative_directories=tuple(
                path.relative_to(self.runtime.runtime_root).as_posix()
                for path in self.runtime.library_directories
            ),
        )

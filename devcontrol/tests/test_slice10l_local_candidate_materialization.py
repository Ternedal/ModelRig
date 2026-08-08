"""Shared real-Git test helpers retained for H5C and later contracts.

The former v1 local-candidate test suite was superseded by the Ed25519/v2
end-to-end suite. Only the neutral Git fixture helpers remain at this import path
for backwards-compatible test imports.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from functools import lru_cache
from pathlib import Path

from kaliv_dev_control.trusted_git_runtime import (
    TrustedGitRuntime,
    capture_trusted_git_runtime_manifest,
    stage_trusted_git_runtime,
)


def git(root: Path, *args: str, stdin: bytes | None = None) -> bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise AssertionError(completed.stderr.decode("utf-8", errors="replace"))
    return completed.stdout


def _copy_runtime_library(source: Path, destination: Path) -> None:
    target = destination / source.name
    if target.exists():
        if target.read_bytes() != source.read_bytes():
            raise unittest.SkipTest(
                f"runtime library basename collision: {source.name}"
            )
        return
    shutil.copy2(source, target)


def _copy_dynamic_libraries(executable: Path, destination: Path) -> None:
    ldd = shutil.which("ldd")
    if ldd is None:
        return
    dependencies = subprocess.run(
        [ldd, str(executable)],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if dependencies.returncode != 0:
        return
    observed: set[Path] = set()
    for line in dependencies.stdout.splitlines():
        text = line.strip()
        candidate = ""
        if "=>" in text:
            candidate = text.split("=>", 1)[1].strip().split(" ", 1)[0]
        elif text.startswith("/"):
            candidate = text.split(" ", 1)[0]
        if candidate.startswith("/"):
            path = Path(candidate).resolve()
            if path.is_file() and path not in observed:
                observed.add(path)
                _copy_runtime_library(path, destination)


@lru_cache(maxsize=1)
def trusted_git() -> TrustedGitRuntime:
    if os.name == "nt":
        raise unittest.SkipTest("portable real-Git closure proof runs on POSIX")
    executable = shutil.which("git")
    if executable is None:
        raise unittest.SkipTest("Git executable is unavailable")
    installed = Path(executable).resolve()
    root = Path(tempfile.mkdtemp(prefix="kaliv-test-git-runtime-"))
    source = root / "source"
    bin_root = source / "bin"
    helper_root = source / "libexec" / "git-core"
    library_root = source / "lib"
    bin_root.mkdir(parents=True)
    helper_root.mkdir(parents=True)
    library_root.mkdir(parents=True)
    shutil.copy2(installed, bin_root / "git")

    exec_path_result = subprocess.run(
        [str(installed), "--exec-path"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if exec_path_result.returncode != 0:
        raise unittest.SkipTest("Git exec-path discovery failed")
    exec_path = Path(exec_path_result.stdout.strip()).resolve()
    upload_pack = exec_path / "git-upload-pack"
    if not upload_pack.is_file():
        raise unittest.SkipTest("Git upload-pack helper is unavailable")
    staged_upload_pack = helper_root / "git-upload-pack"
    shutil.copy2(upload_pack, staged_upload_pack)
    staged_upload_pack.chmod(0o755)

    _copy_dynamic_libraries(installed, library_root)
    _copy_dynamic_libraries(upload_pack.resolve(), library_root)
    manifest = capture_trusted_git_runtime_manifest(
        source.resolve(),
        executable_relative_path="bin/git",
        exec_path_relative_path="libexec/git-core",
        path_relative_directories=("bin", "libexec/git-core", "lib"),
    )
    staging = root / "staging"
    staging.mkdir()
    transaction = stage_trusted_git_runtime(
        manifest,
        source_root=source.resolve(),
        staging_root=staging.resolve(),
    )
    runtime = TrustedGitRuntime(transaction.resolve())
    roles = {item.relative_path: item.role for item in manifest.files}
    if roles.get("libexec/git-core/git-upload-pack") != "helper":
        raise AssertionError("upload-pack is not bound as a runtime helper")
    return runtime

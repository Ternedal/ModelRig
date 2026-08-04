"""Complete local Git runtime capture, staging, verification and execution."""
from __future__ import annotations

from pathlib import Path

from .trusted_git_runtime_model import (
    TRUSTED_GIT_RUNTIME_EVIDENCE_SCHEMA,
    TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA,
    TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA,
    TrustedGitRuntimeError,
    TrustedGitRuntimeEvidence,
    TrustedGitRuntimeFile,
    TrustedGitRuntimeManifest,
    TrustedGitRuntimeStagingReceipt,
    _existing_link_free_directory,
    _has_linkish_component,
    _regular_unaliased_file,
    _relative,
    _sha256_bytes,
)
from .trusted_git_runtime_runner import TrustedGitRunner
from .trusted_git_runtime_staging import (
    TrustedGitRuntime,
    load_trusted_git_runtime_receipt,
    stage_trusted_git_runtime,
)


def capture_trusted_git_runtime_manifest(
    source_root: Path,
    *,
    executable_relative_path: str,
    exec_path_relative_path: str,
    path_relative_directories: tuple[str, ...],
) -> TrustedGitRuntimeManifest:
    """Hash a reviewed runtime with platform-independent path ordering."""

    root = _existing_link_free_directory(source_root, name="Git runtime source root")
    executable = _relative(
        executable_relative_path,
        name="Git runtime executable path",
    )
    exec_path = _relative(
        exec_path_relative_path,
        name="Git runtime exec path",
        allow_dot=True,
    )
    path_dirs = tuple(
        _relative(item, name="Git runtime PATH directory", allow_dot=True)
        for item in path_relative_directories
    )
    candidates = sorted(
        root.rglob("*"),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    entries: list[TrustedGitRuntimeFile] = []
    for candidate in candidates:
        if candidate.is_dir():
            if _has_linkish_component(candidate):
                raise TrustedGitRuntimeError(
                    "Git runtime source contains a linked directory"
                )
            continue
        stat = _regular_unaliased_file(candidate, name="Git runtime source file")
        relative = candidate.relative_to(root).as_posix()
        payload = candidate.read_bytes()
        role = "data"
        if relative == executable:
            role = "executable"
        elif exec_path == "." or relative.startswith(exec_path + "/"):
            role = "helper"
        elif candidate.suffix.lower() in {".dll", ".so", ".dylib"}:
            role = "library"
        entries.append(
            TrustedGitRuntimeFile(
                relative_path=relative,
                sha256=_sha256_bytes(payload),
                size_bytes=len(payload),
                executable=(
                    relative == executable or bool(stat.st_mode & 0o111)
                ),
                role=role,
            )
        )
    return TrustedGitRuntimeManifest(
        executable_relative_path=executable,
        exec_path_relative_path=exec_path,
        path_relative_directories=path_dirs,
        files=tuple(entries),
    )


__all__ = [
    "TRUSTED_GIT_RUNTIME_EVIDENCE_SCHEMA",
    "TRUSTED_GIT_RUNTIME_MANIFEST_SCHEMA",
    "TRUSTED_GIT_RUNTIME_STAGING_RECEIPT_SCHEMA",
    "TrustedGitRuntime",
    "TrustedGitRuntimeError",
    "TrustedGitRuntimeEvidence",
    "TrustedGitRuntimeFile",
    "TrustedGitRuntimeManifest",
    "TrustedGitRuntimeStagingReceipt",
    "TrustedGitRunner",
    "capture_trusted_git_runtime_manifest",
    "load_trusted_git_runtime_receipt",
    "stage_trusted_git_runtime",
]

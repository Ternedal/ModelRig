"""Create-once staging and on-disk verification for a trusted Git runtime."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from .trusted_git_runtime_model import (
    _MAX_FILE_BYTES,
    TrustedGitRuntimeError,
    TrustedGitRuntimeManifest,
    TrustedGitRuntimeStagingReceipt,
    _existing_link_free_directory,
    _has_linkish_component,
    _path_hash,
    _regular_unaliased_file,
    _sha256_bytes,
    _transaction_id,
)


def _write_file(path: Path, payload: bytes, *, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _has_linkish_component(path.parent) or path.exists():
        raise TrustedGitRuntimeError("Git runtime staging path is unsafe")
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    path.chmod(0o755 if executable else 0o644)


def _verify_runtime_tree(runtime_root: Path, manifest: TrustedGitRuntimeManifest) -> None:
    root = _existing_link_free_directory(runtime_root, name="staged Git runtime")
    expected = {item.relative_path: item for item in manifest.files}
    observed: set[str] = set()
    for candidate in sorted(root.rglob("*")):
        if candidate.is_dir():
            if _has_linkish_component(candidate):
                raise TrustedGitRuntimeError("staged Git runtime contains a linked directory")
            continue
        relative = candidate.relative_to(root).as_posix()
        item = expected.get(relative)
        if item is None:
            raise TrustedGitRuntimeError("staged Git runtime contains an extra file")
        stat = _regular_unaliased_file(candidate, name="staged Git runtime file")
        payload = candidate.read_bytes()
        if stat.st_size != item.size_bytes or _sha256_bytes(payload) != item.sha256:
            raise TrustedGitRuntimeError("staged Git runtime file changed")
        if item.executable and not bool(stat.st_mode & 0o111):
            raise TrustedGitRuntimeError("staged Git runtime executable bit changed")
        observed.add(relative)
    if observed != set(expected):
        raise TrustedGitRuntimeError("staged Git runtime is incomplete")


def stage_trusted_git_runtime(
    manifest: TrustedGitRuntimeManifest,
    *,
    source_root: Path,
    staging_root: Path,
) -> Path:
    """Publish one verified runtime transaction without overwriting anything."""

    if not isinstance(manifest, TrustedGitRuntimeManifest):
        raise TrustedGitRuntimeError("Git runtime staging requires a manifest")
    source = _existing_link_free_directory(source_root, name="Git runtime source root")
    destination = _existing_link_free_directory(staging_root, name="Git runtime staging root")
    transaction_id = _transaction_id(manifest.sha256)
    final = destination / transaction_id
    lock = destination / f".{transaction_id}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise TrustedGitRuntimeError("Git runtime transaction is already reserved") from exc
    temporary: Path | None = None
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write((manifest.sha256 + "\n").encode("ascii"))
            handle.flush()
            os.fsync(handle.fileno())
        if final.exists():
            raise TrustedGitRuntimeError("Git runtime transaction already exists")
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{transaction_id}.", dir=destination)
        )
        runtime = temporary / "runtime"
        runtime.mkdir()
        for item in manifest.files:
            source_path = source.joinpath(*PurePosixPath(item.relative_path).parts)
            stat = _regular_unaliased_file(
                source_path,
                name="Git runtime source file",
            )
            payload = source_path.read_bytes()
            if stat.st_size != item.size_bytes or _sha256_bytes(payload) != item.sha256:
                raise TrustedGitRuntimeError(
                    "Git runtime source does not match the pinned manifest"
                )
            _write_file(
                runtime.joinpath(*PurePosixPath(item.relative_path).parts),
                payload,
                executable=item.executable,
            )
        _verify_runtime_tree(runtime, manifest)
        receipt = TrustedGitRuntimeStagingReceipt(
            manifest=manifest,
            transaction_id=transaction_id,
            source_root_path_sha256=_path_hash(source),
            runtime_relative_path="runtime",
            complete=True,
        )
        _write_file(
            temporary / "receipt.json",
            receipt.canonical_json().encode("utf-8"),
            executable=False,
        )
        if final.exists():
            raise TrustedGitRuntimeError("Git runtime transaction already exists")
        temporary.rename(final)
        temporary = None
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass
    return final


def load_trusted_git_runtime_receipt(
    transaction_root: Path,
) -> TrustedGitRuntimeStagingReceipt:
    root = _existing_link_free_directory(
        transaction_root,
        name="Git runtime transaction root",
    )
    receipt_path = root / "receipt.json"
    stat = _regular_unaliased_file(receipt_path, name="Git runtime receipt")
    if stat.st_size > _MAX_FILE_BYTES:
        raise TrustedGitRuntimeError("Git runtime receipt is too large")
    payload = receipt_path.read_bytes()
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TrustedGitRuntimeError("Git runtime receipt is invalid JSON") from exc
    receipt = TrustedGitRuntimeStagingReceipt.from_mapping(value)
    if payload != receipt.canonical_json().encode("utf-8"):
        raise TrustedGitRuntimeError("Git runtime receipt is not canonical")
    if root.name != receipt.transaction_id:
        raise TrustedGitRuntimeError("Git runtime transaction path is invalid")
    top_level = {item.name for item in root.iterdir()}
    if top_level != {"runtime", "receipt.json"}:
        raise TrustedGitRuntimeError("Git runtime transaction layout is invalid")
    _verify_runtime_tree(root / receipt.runtime_relative_path, receipt.manifest)
    return receipt


class TrustedGitRuntime:
    """Verified view of one staged complete Git runtime transaction."""

    def __init__(self, transaction_root: Path) -> None:
        self.transaction_root = _existing_link_free_directory(
            transaction_root,
            name="Git runtime transaction root",
        )
        self.receipt = load_trusted_git_runtime_receipt(self.transaction_root)
        self.runtime_root = self.transaction_root / self.receipt.runtime_relative_path

    @property
    def executable_path(self) -> Path:
        return self.runtime_root.joinpath(
            *PurePosixPath(self.receipt.manifest.executable_relative_path).parts
        )

    @property
    def exec_path(self) -> Path:
        relative = self.receipt.manifest.exec_path_relative_path
        return self.runtime_root if relative == "." else self.runtime_root.joinpath(
            *PurePosixPath(relative).parts
        )

    @property
    def path_directories(self) -> tuple[Path, ...]:
        result: list[Path] = []
        for relative in self.receipt.manifest.path_relative_directories:
            result.append(
                self.runtime_root
                if relative == "."
                else self.runtime_root.joinpath(*PurePosixPath(relative).parts)
            )
        return tuple(result)

    @property
    def library_directories(self) -> tuple[Path, ...]:
        relative_directories = sorted(
            {
                str(PurePosixPath(item.relative_path).parent)
                for item in self.receipt.manifest.files
                if item.role == "library"
            }
        )
        return tuple(
            self.runtime_root
            if relative == "."
            else self.runtime_root.joinpath(*PurePosixPath(relative).parts)
            for relative in relative_directories
        )

    def verify(self) -> None:
        current = load_trusted_git_runtime_receipt(self.transaction_root)
        if current.sha256 != self.receipt.sha256:
            raise TrustedGitRuntimeError("Git runtime receipt changed")

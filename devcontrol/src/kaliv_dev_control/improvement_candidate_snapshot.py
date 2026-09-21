"""Read-only snapshot collection for one verified local RSI candidate.

This is the I/O adapter deliberately kept out of improvement_candidate_provenance.
It first revalidates the existing DC-L13 materialization receipt, then reads the
exact local bare candidate repository through TrustedGitRunner. Only rev-parse,
ls-tree and cat-file are used. No checkout, fetch, ref update, network transport,
publication, merge, release, deployment or activation is performed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from .contract import DevelopmentTask
from .improvement_candidate_provenance import (
    CandidateProvenanceError,
    MaterializedCandidateIdentity,
    SnapshotEntry,
    candidate_tree_sha,
)
from .local_candidate_materialization import (
    LocalCandidateMaterializationReceipt,
    PublisherAuthorizationVerifier,
    PublisherRequestVerifier,
    SemanticReviewVerifier,
    verify_local_candidate_materialization,
)
from .trusted_git_runtime import TrustedGitRunner, TrustedGitRuntime, TrustedGitRuntimeError
from .trusted_git_runtime_model import _existing_link_free_directory, _has_linkish_component

SNAPSHOT_RECEIPT_SCHEMA = "kaliv-rsi-candidate-snapshot-receipt/v1"
SNAPSHOT_AUTHORITY = "evidence-only"
SNAPSHOT_MERGE_AUTHORITY = "human"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_BLOB_SHA = re.compile(r"^[0-9a-f]{40}$")
_ALLOWED_MODES = {"100644", "100755", "120000"}


class CandidateSnapshotError(ValueError):
    """Candidate snapshot collection is malformed, unsafe or exceeds budget."""


class GitReader(Protocol):
    def run(
        self,
        args: tuple[str, ...],
        *,
        cwd: Path,
        maximum: int,
        **kwargs: Any,
    ) -> bytes: ...


def _canonical(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateSnapshotError("snapshot receipt is not canonical JSON") from exc


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CandidateSnapshotError(f"{name} is invalid")
    return value


def _positive_int(value: Any, *, name: str, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise CandidateSnapshotError(f"{name} must be in {low}..{high}")
    return value


def _git_blob_sha1(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


@dataclass(frozen=True, slots=True)
class SnapshotBudget:
    max_files: int = 20_000
    max_file_bytes: int = 128 * 1024 * 1024
    max_total_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        _positive_int(self.max_files, name="max_files", low=1, high=100_000)
        _positive_int(
            self.max_file_bytes,
            name="max_file_bytes",
            low=1,
            high=256 * 1024 * 1024,
        )
        _positive_int(
            self.max_total_bytes,
            name="max_total_bytes",
            low=1,
            high=2 * 1024 * 1024 * 1024,
        )
        if self.max_file_bytes > self.max_total_bytes:
            raise CandidateSnapshotError("max_file_bytes exceeds total snapshot budget")


@dataclass(frozen=True, slots=True)
class SnapshotManifestEntry:
    path: str
    mode: str
    blob_sha1: str
    size_bytes: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "blob_sha1": self.blob_sha1,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class CandidateSnapshotReceipt:
    materialization_receipt_sha256: str
    task_sha256: str
    candidate_commit_sha: str
    candidate_tree_sha: str
    file_count: int
    total_bytes: int
    manifest_sha256: str
    git_runtime_manifest_sha256: str
    git_executable_sha256: str
    network_performed: bool = False
    repository_mutated: bool = False
    authority: str = SNAPSHOT_AUTHORITY
    merge_authority: str = SNAPSHOT_MERGE_AUTHORITY
    schema: str = SNAPSHOT_RECEIPT_SCHEMA

    def __post_init__(self) -> None:
        for name in (
            "materialization_receipt_sha256",
            "task_sha256",
            "manifest_sha256",
            "git_runtime_manifest_sha256",
            "git_executable_sha256",
        ):
            _hex(getattr(self, name), name=name, pattern=_SHA64)
        _hex(self.candidate_commit_sha, name="candidate_commit_sha", pattern=_SHA40)
        _hex(self.candidate_tree_sha, name="candidate_tree_sha", pattern=_SHA40)
        _positive_int(self.file_count, name="file_count", low=1, high=100_000)
        _positive_int(
            self.total_bytes,
            name="total_bytes",
            low=1,
            high=2 * 1024 * 1024 * 1024,
        )
        if self.network_performed is not False or self.repository_mutated is not False:
            raise CandidateSnapshotError("snapshot receipt must remain read-only and offline")
        if self.authority != SNAPSHOT_AUTHORITY or self.merge_authority != "human":
            raise CandidateSnapshotError("snapshot receipt authority is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "materialization_receipt_sha256": self.materialization_receipt_sha256,
            "task_sha256": self.task_sha256,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_tree_sha": self.candidate_tree_sha,
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "manifest_sha256": self.manifest_sha256,
            "git_runtime_manifest_sha256": self.git_runtime_manifest_sha256,
            "git_executable_sha256": self.git_executable_sha256,
            "network_performed": self.network_performed,
            "repository_mutated": self.repository_mutated,
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


@dataclass(frozen=True, slots=True)
class CollectedCandidateSnapshot:
    entries: tuple[SnapshotEntry, ...]
    manifest: tuple[SnapshotManifestEntry, ...]
    receipt: CandidateSnapshotReceipt

    def verify(self) -> None:
        if not self.entries or len(self.entries) != len(self.manifest):
            raise CandidateSnapshotError("collected snapshot entry count is inconsistent")
        by_path = {entry.path: entry for entry in self.entries}
        if len(by_path) != len(self.entries):
            raise CandidateSnapshotError("collected snapshot paths are duplicated")
        total = 0
        for item in self.manifest:
            entry = by_path.get(item.path)
            if entry is None or entry.mode != item.mode:
                raise CandidateSnapshotError("snapshot manifest is not bound to entries")
            if len(entry.content) != item.size_bytes:
                raise CandidateSnapshotError("snapshot manifest size does not match entry")
            if _git_blob_sha1(entry.content) != item.blob_sha1:
                raise CandidateSnapshotError("snapshot manifest blob hash does not match entry")
            if hashlib.sha256(entry.content).hexdigest() != item.sha256:
                raise CandidateSnapshotError("snapshot manifest content hash does not match entry")
            total += item.size_bytes
        manifest_hash = _sha256_text(
            _canonical([item.to_dict() for item in self.manifest])
        )
        if manifest_hash != self.receipt.manifest_sha256:
            raise CandidateSnapshotError("snapshot manifest digest does not match receipt")
        if len(self.entries) != self.receipt.file_count or total != self.receipt.total_bytes:
            raise CandidateSnapshotError("snapshot receipt counts do not match entries")
        if candidate_tree_sha(self.entries) != self.receipt.candidate_tree_sha:
            raise CandidateSnapshotError("snapshot no longer reproduces candidate tree")


def _parse_tree_listing(raw: bytes, *, budget: SnapshotBudget) -> tuple[tuple[str, str, str], ...]:
    if not isinstance(raw, bytes) or not raw:
        raise CandidateSnapshotError("candidate tree listing is empty")
    rows = raw.split(b"\0")
    if rows[-1] != b"":
        raise CandidateSnapshotError("candidate tree listing is not NUL terminated")
    parsed: list[tuple[str, str, str]] = []
    for position, row in enumerate(rows[:-1]):
        try:
            header, path_bytes = row.split(b"\t", 1)
            mode_bytes, kind, oid_bytes = header.split(b" ", 2)
            mode = mode_bytes.decode("ascii", errors="strict")
            object_kind = kind.decode("ascii", errors="strict")
            oid = oid_bytes.decode("ascii", errors="strict")
            path = path_bytes.decode("utf-8", errors="strict")
        except (ValueError, UnicodeDecodeError) as exc:
            raise CandidateSnapshotError(
                f"candidate tree row {position} is malformed"
            ) from exc
        if mode not in _ALLOWED_MODES or object_kind != "blob":
            raise CandidateSnapshotError(
                "candidate tree contains unsupported object type or mode"
            )
        _hex(oid, name="candidate blob SHA", pattern=_BLOB_SHA)
        # SnapshotEntry owns the canonical path contract; instantiate a zero-byte
        # sentinel now so path/mode failures happen before any blob reads.
        try:
            SnapshotEntry(path=path, mode=mode, content=b"")
        except CandidateProvenanceError as exc:
            raise CandidateSnapshotError(f"candidate tree path is invalid: {exc}") from exc
        if any(char in path for char in ("\n", "\r", "\t")):
            raise CandidateSnapshotError("candidate tree path contains control whitespace")
        parsed.append((path, mode, oid))
        if len(parsed) > budget.max_files:
            raise CandidateSnapshotError("candidate snapshot exceeds file-count budget")
    paths = [item[0] for item in parsed]
    if len(paths) != len(set(paths)):
        raise CandidateSnapshotError("candidate tree listing contains duplicate paths")
    if not parsed:
        raise CandidateSnapshotError("candidate tree contains no files")
    return tuple(parsed)


def _repository_args(repository: Path, *args: str) -> tuple[str, ...]:
    return ("--git-dir", os.fspath(repository), *args)


def _collect_with_reader(
    *,
    reader: GitReader,
    repository: Path,
    operation_root: Path,
    identity: MaterializedCandidateIdentity,
    git_runtime_manifest_sha256: str,
    git_executable_sha256: str,
    budget: SnapshotBudget,
) -> CollectedCandidateSnapshot:
    """Collect and validate an exact snapshot using a read-only Git reader."""

    if not isinstance(identity, MaterializedCandidateIdentity):
        raise CandidateSnapshotError("candidate identity is invalid")
    if not isinstance(budget, SnapshotBudget):
        raise CandidateSnapshotError("snapshot budget is invalid")
    _hex(git_runtime_manifest_sha256, name="Git runtime manifest SHA", pattern=_SHA64)
    _hex(git_executable_sha256, name="Git executable SHA", pattern=_SHA64)

    try:
        commit = reader.run(
            _repository_args(repository, "rev-parse", f"{identity.commit_sha}^{{commit}}"),
            cwd=operation_root,
            maximum=4096,
        ).decode("ascii", errors="strict").strip()
        tree = reader.run(
            _repository_args(repository, "rev-parse", f"{identity.commit_sha}^{{tree}}"),
            cwd=operation_root,
            maximum=4096,
        ).decode("ascii", errors="strict").strip()
    except (UnicodeDecodeError, TrustedGitRuntimeError) as exc:
        raise CandidateSnapshotError("candidate commit/tree identity could not be read") from exc
    if commit != identity.commit_sha or tree != identity.tree_sha:
        raise CandidateSnapshotError("materialized commit/tree identity changed before collection")

    try:
        listing = reader.run(
            _repository_args(
                repository,
                "ls-tree",
                "-r",
                "-z",
                "--full-tree",
                identity.commit_sha,
            ),
            cwd=operation_root,
            maximum=32 * 1024 * 1024,
        )
    except TrustedGitRuntimeError as exc:
        raise CandidateSnapshotError("candidate tree listing could not be read") from exc
    rows = _parse_tree_listing(listing, budget=budget)

    sizes: list[int] = []
    total = 0
    for _path, _mode, oid in rows:
        try:
            raw_size = reader.run(
                _repository_args(repository, "cat-file", "-s", oid),
                cwd=operation_root,
                maximum=128,
            ).decode("ascii", errors="strict").strip()
            size = int(raw_size, 10)
        except (UnicodeDecodeError, ValueError, TrustedGitRuntimeError) as exc:
            raise CandidateSnapshotError("candidate blob size could not be read") from exc
        if size < 0 or size > budget.max_file_bytes:
            raise CandidateSnapshotError("candidate blob exceeds per-file budget")
        total += size
        if total > budget.max_total_bytes:
            raise CandidateSnapshotError("candidate snapshot exceeds total byte budget")
        sizes.append(size)

    entries: list[SnapshotEntry] = []
    manifest: list[SnapshotManifestEntry] = []
    for (path, mode, oid), size in zip(rows, sizes, strict=True):
        try:
            payload = reader.run(
                _repository_args(repository, "cat-file", "blob", oid),
                cwd=operation_root,
                maximum=max(1, size),
            )
        except TrustedGitRuntimeError as exc:
            raise CandidateSnapshotError("candidate blob could not be read") from exc
        if len(payload) != size:
            raise CandidateSnapshotError("candidate blob byte count changed during collection")
        if _git_blob_sha1(payload) != oid:
            raise CandidateSnapshotError("candidate blob bytes do not match Git object identity")
        entry = SnapshotEntry(path=path, mode=mode, content=payload)
        entries.append(entry)
        manifest.append(
            SnapshotManifestEntry(
                path=path,
                mode=mode,
                blob_sha1=oid,
                size_bytes=size,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    snapshot = tuple(entries)
    if candidate_tree_sha(snapshot) != identity.tree_sha:
        raise CandidateSnapshotError("collected files do not reproduce materialized root tree")
    ordered_manifest = tuple(manifest)
    manifest_sha = _sha256_text(_canonical([item.to_dict() for item in ordered_manifest]))
    receipt = CandidateSnapshotReceipt(
        materialization_receipt_sha256=identity.materialization_receipt_sha256,
        task_sha256=identity.task_sha256,
        candidate_commit_sha=identity.commit_sha,
        candidate_tree_sha=identity.tree_sha,
        file_count=len(snapshot),
        total_bytes=total,
        manifest_sha256=manifest_sha,
        git_runtime_manifest_sha256=git_runtime_manifest_sha256,
        git_executable_sha256=git_executable_sha256,
    )
    collected = CollectedCandidateSnapshot(
        entries=snapshot,
        manifest=ordered_manifest,
        receipt=receipt,
    )
    collected.verify()
    return collected


def collect_verified_candidate_snapshot(
    *,
    receipt: LocalCandidateMaterializationReceipt,
    task: DevelopmentTask,
    authorization_verifier: PublisherAuthorizationVerifier,
    publisher_verifier: PublisherRequestVerifier,
    semantic_verifier: SemanticReviewVerifier,
    control_plane_root: Path,
    source_repository: Path,
    materialization_root: Path,
    trusted_git: TrustedGitRuntime,
    collector_root: Path,
    budget: SnapshotBudget = SnapshotBudget(),
) -> CollectedCandidateSnapshot:
    """Reverify DC-L13 evidence, then read the local candidate without mutation."""

    if not isinstance(receipt, LocalCandidateMaterializationReceipt):
        raise CandidateSnapshotError("snapshot collector requires materialization receipt")
    if not isinstance(task, DevelopmentTask):
        raise CandidateSnapshotError("snapshot collector requires DevelopmentTask")
    if not isinstance(trusted_git, TrustedGitRuntime):
        raise CandidateSnapshotError("snapshot collector requires trusted Git runtime")
    try:
        verify_local_candidate_materialization(
            receipt=receipt,
            task=task,
            authorization_verifier=authorization_verifier,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=Path(control_plane_root),
            source_repository=Path(source_repository),
            materialization_root=Path(materialization_root),
            trusted_git=trusted_git,
        )
    except ValueError as exc:
        raise CandidateSnapshotError(f"candidate materialization did not reverify: {exc}") from exc

    try:
        identity = MaterializedCandidateIdentity.from_receipt(receipt)
    except CandidateProvenanceError as exc:
        raise CandidateSnapshotError(f"candidate identity is invalid: {exc}") from exc

    root = _existing_link_free_directory(
        Path(materialization_root), name="materialization root"
    )
    transaction = root / receipt.transaction_id
    repository = transaction / receipt.repository_relative_path
    if (
        not transaction.is_dir()
        or _has_linkish_component(transaction)
        or not repository.is_dir()
        or _has_linkish_component(repository)
    ):
        raise CandidateSnapshotError("materialized candidate repository is missing or unsafe")

    scratch_root = _existing_link_free_directory(
        Path(collector_root), name="snapshot collector root"
    )
    try:
        scratch_root.resolve().relative_to(transaction.resolve())
    except ValueError:
        pass
    else:
        raise CandidateSnapshotError("collector scratch root must be outside materialization transaction")

    scratch = Path(tempfile.mkdtemp(prefix=".rsi-candidate-snapshot-", dir=scratch_root))
    try:
        try:
            reader = TrustedGitRunner(trusted_git, operation_root=scratch)
            git_evidence = reader.evidence()
            collected = _collect_with_reader(
                reader=reader,
                repository=repository,
                operation_root=scratch,
                identity=identity,
                git_runtime_manifest_sha256=git_evidence.runtime_manifest_sha256,
                git_executable_sha256=git_evidence.executable_sha256,
                budget=budget,
            )
            # Reverify runtime after all object reads and the candidate receipt
            # after collection, closing simple before/after mutation races.
            trusted_git.verify()
            verify_local_candidate_materialization(
                receipt=receipt,
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=Path(control_plane_root),
                source_repository=Path(source_repository),
                materialization_root=Path(materialization_root),
                trusted_git=trusted_git,
            )
            collected.verify()
            return collected
        except TrustedGitRuntimeError as exc:
            raise CandidateSnapshotError("trusted Git runtime failed during snapshot collection") from exc
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

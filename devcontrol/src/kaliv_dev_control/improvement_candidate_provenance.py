"""Evidence-only binding from a materialized RSI candidate to measured runtime code.

The previous regression layer deliberately keeps Git identity and the Agent 3
``backend.code_sha256`` measurement separate.  This module closes that gap
without adding execution authority:

* one verified LocalCandidateMaterializationReceipt supplies the candidate commit,
  root tree and task identity;
* a complete, caller-supplied snapshot is hashed with Git's object rules and must
  reproduce the materialized root tree exactly;
* the worker/app Python subset is fingerprinted with the same algorithm used by
  ``worker/app/build_identity.py``;
* the candidate eval must report that exact fingerprint and the exact eval digest
  already accepted by CandidateRegressionProof.

The module performs no filesystem I/O, subprocess execution, network access, Git
mutation, publication, merge, release, deployment or activation.  Snapshot bytes
are inputs; producing them from the local bare candidate repository remains a
separate read-only collection concern.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Mapping

from .improvement_proposal import AGENT3_EVAL_SCHEMA, canonical_sha256
from .improvement_regression import CandidateRegressionProof
from .local_candidate_materialization import LocalCandidateMaterializationReceipt

PROVENANCE_SCHEMA = "kaliv-rsi-candidate-runtime-provenance/v1"
PROVENANCE_AUTHORITY = "evidence-only"
PROVENANCE_MERGE_AUTHORITY = "human"

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA64 = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED_MODES = {"100644", "100755", "120000"}


class CandidateProvenanceError(ValueError):
    """Candidate source/runtime evidence is malformed, incomplete or unbound."""


def _canonical(value: Mapping[str, Any]) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise CandidateProvenanceError("provenance proof is not canonical JSON") from exc


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hex(value: Any, *, name: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise CandidateProvenanceError(f"{name} is invalid")
    return value


def _path(value: Any) -> str:
    if not isinstance(value, str) or not value or value.strip() != value:
        raise CandidateProvenanceError("snapshot path is invalid")
    if "\\" in value or value.startswith("/") or "\x00" in value:
        raise CandidateProvenanceError("snapshot path must be canonical repository-relative POSIX")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise CandidateProvenanceError("snapshot path is non-canonical")
    if PurePosixPath(value).as_posix() != value:
        raise CandidateProvenanceError("snapshot path is non-canonical")
    return value


def _git_object_sha1(kind: bytes, payload: bytes) -> bytes:
    header = kind + b" " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).digest()


@dataclass(frozen=True, slots=True)
class SnapshotEntry:
    path: str
    mode: str
    content: bytes

    def __post_init__(self) -> None:
        _path(self.path)
        if self.mode not in _ALLOWED_MODES:
            raise CandidateProvenanceError("snapshot entry mode is unsupported")
        if not isinstance(self.content, bytes):
            raise CandidateProvenanceError("snapshot entry content must be bytes")


@dataclass(frozen=True, slots=True)
class MaterializedCandidateIdentity:
    materialization_receipt_sha256: str
    task_sha256: str
    commit_sha: str
    tree_sha: str

    def __post_init__(self) -> None:
        _hex(
            self.materialization_receipt_sha256,
            name="materialization_receipt_sha256",
            pattern=_SHA64,
        )
        _hex(self.task_sha256, name="task_sha256", pattern=_SHA64)
        _hex(self.commit_sha, name="commit_sha", pattern=_SHA40)
        _hex(self.tree_sha, name="tree_sha", pattern=_SHA40)

    @classmethod
    def from_receipt(
        cls, receipt: LocalCandidateMaterializationReceipt
    ) -> "MaterializedCandidateIdentity":
        if not isinstance(receipt, LocalCandidateMaterializationReceipt):
            raise CandidateProvenanceError(
                "candidate provenance requires LocalCandidateMaterializationReceipt"
            )
        if (
            receipt.bare_repository is not True
            or receipt.isolated_index is not True
            or receipt.local_source_only is not True
            or receipt.remote_configured is not False
            or receipt.network_write_performed is not False
            or receipt.remote_push_performed is not False
            or receipt.pull_request_created is not False
            or receipt.ready_for_review is not False
            or receipt.reviewers_requested is not False
            or receipt.merged is not False
            or receipt.released is not False
            or receipt.deployed is not False
            or receipt.merge_authority != "human"
        ):
            raise CandidateProvenanceError(
                "materialization receipt is not the local-only human-merge boundary"
            )
        return cls(
            materialization_receipt_sha256=receipt.sha256,
            task_sha256=receipt.task_sha256,
            commit_sha=receipt.candidate.commit_sha,
            tree_sha=receipt.candidate.tree_sha,
        )


def _snapshot_map(entries: tuple[SnapshotEntry, ...]) -> dict[str, SnapshotEntry]:
    if not isinstance(entries, tuple) or not entries:
        raise CandidateProvenanceError("candidate snapshot must be a non-empty tuple")
    mapped: dict[str, SnapshotEntry] = {}
    for entry in entries:
        if not isinstance(entry, SnapshotEntry):
            raise CandidateProvenanceError("candidate snapshot contains an invalid entry")
        if entry.path in mapped:
            raise CandidateProvenanceError("candidate snapshot contains duplicate paths")
        mapped[entry.path] = entry
    return mapped


def _build_tree(entries: Mapping[str, SnapshotEntry]) -> str:
    """Reproduce Git's root tree SHA-1 from a complete file/symlink snapshot."""

    root: dict[str, Any] = {}
    for path, entry in entries.items():
        cursor = root
        parts = path.split("/")
        for segment in parts[:-1]:
            existing = cursor.get(segment)
            if isinstance(existing, SnapshotEntry):
                raise CandidateProvenanceError(
                    "snapshot path collides with a file at an ancestor"
                )
            if existing is None:
                existing = {}
                cursor[segment] = existing
            cursor = existing
        leaf = parts[-1]
        if leaf in cursor:
            raise CandidateProvenanceError("snapshot path collides with another entry")
        cursor[leaf] = entry

    def tree_oid(node: Mapping[str, Any]) -> bytes:
        records: list[tuple[bytes, bytes]] = []
        for name, value in node.items():
            name_bytes = name.encode("utf-8")
            if isinstance(value, SnapshotEntry):
                oid = _git_object_sha1(b"blob", value.content)
                sort_key = name_bytes
                record = (
                    value.mode.encode("ascii")
                    + b" "
                    + name_bytes
                    + b"\0"
                    + oid
                )
            else:
                oid = tree_oid(value)
                sort_key = name_bytes + b"/"
                record = b"40000 " + name_bytes + b"\0" + oid
            records.append((sort_key, record))
        payload = b"".join(record for _, record in sorted(records, key=lambda item: item[0]))
        return _git_object_sha1(b"tree", payload)

    return tree_oid(root).hex()


def worker_code_sha256(entries: tuple[SnapshotEntry, ...]) -> str:
    """Match worker/app/build_identity.py::_hash_source_tree exactly."""

    mapped = _snapshot_map(entries)
    prefix = "worker/app/"
    selected = []
    for path, entry in mapped.items():
        if not path.startswith(prefix) or not path.endswith(".py"):
            continue
        relative = path[len(prefix):]
        parts = relative.split("/")
        if "__pycache__" in parts or parts[-1] == "_build_stamp.py":
            continue
        selected.append((relative, entry.content))
    if not selected:
        raise CandidateProvenanceError("candidate snapshot contains no worker/app Python source")
    digest = hashlib.sha256()
    for relative, content in sorted(selected, key=lambda item: item[0]):
        canonical = content.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(canonical).digest())
    return digest.hexdigest()


def candidate_tree_sha(entries: tuple[SnapshotEntry, ...]) -> str:
    return _build_tree(_snapshot_map(entries))


@dataclass(frozen=True, slots=True)
class CandidateRuntimeProvenance:
    materialization_receipt_sha256: str
    task_sha256: str
    candidate_commit_sha: str
    candidate_tree_sha: str
    snapshot_tree_sha: str
    worker_code_sha256: str
    candidate_eval_sha256: str
    regression_proof_sha256: str
    accepted_regression: bool
    authority: str = PROVENANCE_AUTHORITY
    merge_authority: str = PROVENANCE_MERGE_AUTHORITY
    schema: str = PROVENANCE_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "materialization_receipt_sha256": self.materialization_receipt_sha256,
            "task_sha256": self.task_sha256,
            "candidate_commit_sha": self.candidate_commit_sha,
            "candidate_tree_sha": self.candidate_tree_sha,
            "snapshot_tree_sha": self.snapshot_tree_sha,
            "worker_code_sha256": self.worker_code_sha256,
            "candidate_eval_sha256": self.candidate_eval_sha256,
            "regression_proof_sha256": self.regression_proof_sha256,
            "accepted_regression": self.accepted_regression,
            "authority": self.authority,
            "merge_authority": self.merge_authority,
        }

    def canonical_json(self) -> str:
        return _canonical(self.to_dict())

    @property
    def sha256(self) -> str:
        return _sha256_text(self.canonical_json())


def build_candidate_runtime_provenance(
    *,
    materialized: MaterializedCandidateIdentity,
    snapshot: tuple[SnapshotEntry, ...],
    candidate_report: Mapping[str, Any],
    regression_proof: CandidateRegressionProof,
) -> CandidateRuntimeProvenance:
    """Bind one materialized Git candidate to the runtime code that was evaluated."""

    if not isinstance(materialized, MaterializedCandidateIdentity):
        raise CandidateProvenanceError("materialized candidate identity is invalid")
    if not isinstance(regression_proof, CandidateRegressionProof):
        raise CandidateProvenanceError("candidate regression proof is invalid")
    if regression_proof.accepted is not True:
        raise CandidateProvenanceError("candidate regression proof is not accepted")
    if regression_proof.task_sha256 != materialized.task_sha256:
        raise CandidateProvenanceError(
            "materialized candidate task does not match regression task"
        )
    if not isinstance(candidate_report, Mapping):
        raise CandidateProvenanceError("candidate eval report must be an object")
    if candidate_report.get("schema") != AGENT3_EVAL_SCHEMA:
        raise CandidateProvenanceError("candidate eval report schema is unsupported")

    observed_tree = candidate_tree_sha(snapshot)
    if observed_tree != materialized.tree_sha:
        raise CandidateProvenanceError(
            "candidate snapshot does not reproduce the materialized Git tree"
        )
    observed_code = worker_code_sha256(snapshot)
    backend = candidate_report.get("backend")
    if not isinstance(backend, Mapping):
        raise CandidateProvenanceError("candidate eval backend identity is missing")
    measured_code = _hex(
        backend.get("code_sha256"),
        name="candidate eval backend.code_sha256",
        pattern=_SHA64,
    )
    if measured_code != observed_code:
        raise CandidateProvenanceError(
            "candidate eval measured different worker code than the materialized tree"
        )
    eval_sha = canonical_sha256(candidate_report)
    if eval_sha != regression_proof.candidate_eval_sha256:
        raise CandidateProvenanceError(
            "candidate eval is not the report accepted by regression proof"
        )
    if measured_code != regression_proof.candidate_code_sha256:
        raise CandidateProvenanceError(
            "candidate runtime code is not the identity accepted by regression proof"
        )

    return CandidateRuntimeProvenance(
        materialization_receipt_sha256=materialized.materialization_receipt_sha256,
        task_sha256=materialized.task_sha256,
        candidate_commit_sha=materialized.commit_sha,
        candidate_tree_sha=materialized.tree_sha,
        snapshot_tree_sha=observed_tree,
        worker_code_sha256=observed_code,
        candidate_eval_sha256=eval_sha,
        regression_proof_sha256=regression_proof.sha256,
        accepted_regression=True,
    )

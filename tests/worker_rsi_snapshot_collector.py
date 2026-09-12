"""Contract tests for the read-only RSI candidate snapshot collector."""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from kaliv_dev_control.improvement_candidate_provenance import (  # noqa: E402
    MaterializedCandidateIdentity,
    SnapshotEntry,
    candidate_tree_sha,
)
from kaliv_dev_control.improvement_candidate_snapshot import (  # noqa: E402
    CandidateSnapshotError,
    SnapshotBudget,
    _collect_with_reader,
)

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(fragment: str, fn, message: str) -> None:
    try:
        fn()
    except CandidateSnapshotError as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def blob_oid(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


SNAPSHOT = (
    SnapshotEntry("README.md", "100644", b"candidate\n"),
    SnapshotEntry("worker/app/__init__.py", "100644", b""),
    SnapshotEntry("worker/app/planner.py", "100644", b"def choose():\n    return 'rig_status'\n"),
)
COMMIT = "4" * 40
TREE = candidate_tree_sha(SNAPSHOT)
IDENTITY = MaterializedCandidateIdentity(
    materialization_receipt_sha256="3" * 64,
    task_sha256="2" * 64,
    commit_sha=COMMIT,
    tree_sha=TREE,
)
REPOSITORY = Path("candidate.git")
OPERATION_ROOT = Path("collector")


class FakeReader:
    def __init__(
        self,
        entries: tuple[SnapshotEntry, ...] = SNAPSHOT,
        *,
        tree: str = TREE,
        listing_override: bytes | None = None,
        size_override: dict[str, int] | None = None,
        payload_override: dict[str, bytes] | None = None,
    ) -> None:
        self.entries = entries
        self.tree = tree
        self.listing_override = listing_override
        self.size_override = size_override or {}
        self.payload_override = payload_override or {}
        self.blob_reads = 0
        self.by_oid = {blob_oid(entry.content): entry for entry in entries}

    def listing(self) -> bytes:
        if self.listing_override is not None:
            return self.listing_override
        rows = []
        for entry in self.entries:
            oid = blob_oid(entry.content)
            rows.append(
                entry.mode.encode("ascii")
                + b" blob "
                + oid.encode("ascii")
                + b"\t"
                + entry.path.encode("utf-8")
                + b"\0"
            )
        return b"".join(rows)

    def run(self, args, *, cwd, maximum, **kwargs):
        del cwd, maximum, kwargs
        command = args[2:]
        if command == ("rev-parse", f"{COMMIT}^{{commit}}"):
            return (COMMIT + "\n").encode("ascii")
        if command == ("rev-parse", f"{COMMIT}^{{tree}}"):
            return (self.tree + "\n").encode("ascii")
        if command == ("ls-tree", "-r", "-z", "--full-tree", COMMIT):
            return self.listing()
        if len(command) == 3 and command[:2] == ("cat-file", "-s"):
            oid = command[2]
            if oid in self.size_override:
                return (str(self.size_override[oid]) + "\n").encode("ascii")
            return (str(len(self.by_oid[oid].content)) + "\n").encode("ascii")
        if len(command) == 3 and command[:2] == ("cat-file", "blob"):
            self.blob_reads += 1
            oid = command[2]
            return self.payload_override.get(oid, self.by_oid[oid].content)
        raise AssertionError(f"unexpected fake Git command: {command!r}")


def collect(reader: FakeReader, *, budget: SnapshotBudget = SnapshotBudget()):
    return _collect_with_reader(
        reader=reader,
        repository=REPOSITORY,
        operation_root=OPERATION_ROOT,
        identity=IDENTITY,
        git_runtime_manifest_sha256="a" * 64,
        git_executable_sha256="b" * 64,
        budget=budget,
    )


# Happy path: every byte is bound through Git blob/tree identity into a receipt.
reader = FakeReader()
collected = collect(reader)
check(collected.entries == SNAPSHOT, "collector returns the exact candidate snapshot bytes")
check(
    collected.receipt.candidate_commit_sha == COMMIT
    and collected.receipt.candidate_tree_sha == TREE
    and collected.receipt.file_count == len(SNAPSHOT)
    and collected.receipt.total_bytes == sum(len(entry.content) for entry in SNAPSHOT),
    "snapshot receipt binds materialized commit/tree and exact size/count",
)
check(
    collected.receipt.network_performed is False
    and collected.receipt.repository_mutated is False
    and collected.receipt.authority == "evidence-only"
    and collected.receipt.merge_authority == "human",
    "snapshot receipt carries no execution or publication authority",
)
collected.verify()
check(reader.blob_reads == len(SNAPSHOT), "each listed blob is read exactly once after sizing")

# Gitlinks/submodules are not silently converted to files.
gitlink = b"160000 commit " + ("c" * 40).encode("ascii") + b"\tvendor/submodule\0"
expect_error(
    "unsupported object type or mode",
    lambda: collect(FakeReader(listing_override=gitlink)),
    "gitlinks/submodules fail closed",
)

# File-count budget is enforced from listing metadata before any blob payload read.
expect_error(
    "file-count budget",
    lambda: collect(FakeReader(), budget=SnapshotBudget(max_files=2, max_file_bytes=1024, max_total_bytes=4096)),
    "file-count budget rejects oversized trees",
)

# Per-file and total budgets are enforced from cat-file -s before cat-file blob.
large_oid = blob_oid(SNAPSHOT[0].content)
large_reader = FakeReader(size_override={large_oid: 100})
expect_error(
    "per-file budget",
    lambda: collect(large_reader, budget=SnapshotBudget(max_files=10, max_file_bytes=32, max_total_bytes=256)),
    "per-file byte budget rejects before blob contents are read",
)
check(large_reader.blob_reads == 0, "per-file rejection performs no blob payload reads")

total_sizes = {blob_oid(entry.content): 20 for entry in SNAPSHOT}
total_reader = FakeReader(size_override=total_sizes)
expect_error(
    "total byte budget",
    lambda: collect(total_reader, budget=SnapshotBudget(max_files=10, max_file_bytes=32, max_total_bytes=40)),
    "aggregate byte budget rejects before blob contents are read",
)
check(total_reader.blob_reads == 0, "aggregate rejection performs no blob payload reads")

# If bytes change between size/list and read, the Git object identity catches it.
target_oid = blob_oid(SNAPSHOT[0].content)
tamper_reader = FakeReader(payload_override={target_oid: b"tampered!!\n"})
expect_error(
    "byte count changed",
    lambda: collect(tamper_reader),
    "blob byte-count mutation during collection fails closed",
)

same_size_tamper = b"candidate?"
check(len(same_size_tamper) == len(SNAPSHOT[0].content), "test fixture keeps tamper length stable")
tamper_reader = FakeReader(payload_override={target_oid: same_size_tamper})
expect_error(
    "do not match Git object identity",
    lambda: collect(tamper_reader),
    "same-size blob mutation is caught by Git blob SHA-1",
)

# The commit's advertised root tree must remain the materialized tree.
wrong_tree = FakeReader(tree="d" * 40)
expect_error(
    "commit/tree identity changed",
    lambda: collect(wrong_tree),
    "candidate root tree cannot move between materialization and collection",
)

# Malformed/non-NUL tree output never becomes a partial snapshot.
expect_error(
    "not NUL terminated",
    lambda: collect(FakeReader(listing_override=b"100644 blob " + ("e" * 40).encode("ascii") + b"\tREADME.md")),
    "truncated ls-tree output fails closed",
)

print(f"\n===== RSI SNAPSHOT COLLECTOR: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

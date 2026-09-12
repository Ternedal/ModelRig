"""Source/runtime identity plus RSI provenance, collection and qualification contracts.

Run: PYTHONPATH=worker python3 tests/worker_build_identity.py
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "devcontrol" / "src"))

from app.build_identity import _canonical_bytes  # noqa: E402
from kaliv_dev_control.improvement_candidate_provenance import (  # noqa: E402
    CandidateProvenanceError,
    MaterializedCandidateIdentity,
    SnapshotEntry,
    build_candidate_runtime_provenance,
    candidate_tree_sha,
    worker_code_sha256,
)
from kaliv_dev_control.improvement_candidate_snapshot import (  # noqa: E402
    CandidateSnapshotError,
    CandidateSnapshotReceipt,
    SnapshotBudget,
    _collect_with_reader,
)
from kaliv_dev_control.improvement_promotion import (  # noqa: E402
    PROMOTION_AUTHORITY,
    PROMOTION_ISSUER_SYSTEM_ID,
    PromotionReceipt,
    proposal_sha256,
)
from kaliv_dev_control.improvement_proposal import (  # noqa: E402
    AGENT3_EVAL_SCHEMA,
    ImprovementProposal,
    canonical_sha256,
)
from kaliv_dev_control.improvement_qualification_packet import (  # noqa: E402
    MISSING_PHYSICAL_GATES,
    QualificationPacket,
    QualificationPacketError,
    build_qualification_packet,
)
from kaliv_dev_control.improvement_regression import CandidateRegressionProof  # noqa: E402

passed = failed = 0


def check(condition, message):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def expect_error(error_type, fragment, fn, message):
    try:
        fn()
    except error_type as exc:
        check(fragment in str(exc), message)
    else:
        check(False, message)


def _hash(path: Path) -> str:
    return hashlib.sha256(_canonical_bytes(path)).hexdigest()


def _blob_oid(payload: bytes) -> str:
    header = b"blob " + str(len(payload)).encode("ascii") + b"\0"
    return hashlib.sha1(header + payload).hexdigest()


# Existing F-726 source identity contract.
_d = Path(tempfile.mkdtemp(prefix="kaliv-eol-"))
_lf = _d / "lf.py"
_lf.write_bytes(b"def f():\n    return 1\n")
_crlf = _d / "crlf.py"
_crlf.write_bytes(b"def f():\r\n    return 1\r\n")
_cr = _d / "cr.py"
_cr.write_bytes(b"def f():\r    return 1\r")
check(_hash(_lf) == _hash(_crlf), "LF and CRLF logical source hash identically")
check(_hash(_lf) == _hash(_cr), "lone CR normalizes to the same source identity")
_changed = _d / "changed.py"
_changed.write_bytes(b"def f():\n    return 2\n")
check(_hash(_lf) != _hash(_changed), "real content changes still change identity")
_blankline = _d / "blank.py"
_blankline.write_bytes(b"def f():\n\n    return 1\n")
check(_hash(_lf) != _hash(_blankline), "real whitespace/source changes remain visible")
check(b"\r" not in _canonical_bytes(_crlf), "canonical worker bytes contain no CR")

_ga = ROOT / ".gitattributes"
check(_ga.exists(), ".gitattributes exists")
if _ga.exists():
    _text = _ga.read_text(encoding="utf-8")
    check(
        "*.py    text eol=lf" in _text or "*.py text eol=lf" in _text,
        ".gitattributes pins Python source to LF",
    )
    for _ext in ("*.go", "*.kt", "*.json"):
        check(_ext in _text, f".gitattributes pins {_ext}")


# RSI provenance bridge: exact materialized Git tree -> worker fingerprint -> eval.
_snapshot_lf = (
    SnapshotEntry("README.md", "100644", b"candidate\n"),
    SnapshotEntry("worker/app/__init__.py", "100644", b""),
    SnapshotEntry(
        "worker/app/planner.py",
        "100644",
        b"def choose():\n    return 'rig_status'\n",
    ),
    SnapshotEntry("worker/app/nested/tool.py", "100755", b"VALUE = 1\n"),
    SnapshotEntry("worker/app/_build_stamp.py", "100644", b"CODE_SHA256 = 'x'\n"),
)
_snapshot_crlf = tuple(
    SnapshotEntry(entry.path, entry.mode, entry.content.replace(b"\n", b"\r\n"))
    if entry.path.endswith(".py")
    else entry
    for entry in _snapshot_lf
)
_code = worker_code_sha256(_snapshot_lf)
check(
    _code == worker_code_sha256(_snapshot_crlf),
    "RSI bridge matches checkout-independent worker fingerprint semantics",
)
check(
    candidate_tree_sha(_snapshot_lf) == "a08d9d197ceab8b88a70518521e1f57b8fd87318",
    "candidate tree hashing matches a git write-tree reference vector",
)
check(
    candidate_tree_sha(_snapshot_lf) != candidate_tree_sha(_snapshot_crlf),
    "Git tree identity remains byte-exact while runtime identity normalizes EOL",
)
expect_error(
    CandidateProvenanceError,
    "symlink",
    lambda: worker_code_sha256(
        _snapshot_lf
        + (SnapshotEntry("worker/app/link.py", "120000", b"planner.py"),)
    ),
    "worker Python symlinks fail closed",
)

_task_sha = "2" * 64
_materialized = MaterializedCandidateIdentity(
    materialization_receipt_sha256="3" * 64,
    task_sha256=_task_sha,
    commit_sha="4" * 40,
    tree_sha=candidate_tree_sha(_snapshot_lf),
)
_candidate_report = {
    "schema": AGENT3_EVAL_SCHEMA,
    "backend": {"code_sha256": _code},
}
_eval_sha = canonical_sha256(_candidate_report)
_regression = CandidateRegressionProof(
    proposal_id="RSI_A3_001",
    proposal_sha256="5" * 64,
    promotion_receipt_sha256="6" * 64,
    task_id="RSI_TASK_001",
    task_sha256=_task_sha,
    repository="Ternedal/ModelRig",
    base_sha="7" * 40,
    baseline_eval_sha256="8" * 64,
    candidate_eval_sha256=_eval_sha,
    baseline_code_sha256="9" * 64,
    candidate_code_sha256=_code,
    baseline_planner_model="incumbent",
    candidate_planner_model="candidate",
    task_set={
        "schema": "kaliv-agent3-model-eval-task-set/v1",
        "name": "t",
        "version": "1",
        "task_count": 1,
    },
    repetitions=1,
    baseline_exact_match_rate=0.0,
    candidate_exact_match_rate=1.0,
    baseline_discipline_rate=1.0,
    candidate_discipline_rate=1.0,
    exact_improvements=("read-rig-status#1",),
    exact_regressions=(),
    discipline_regressions=(),
    risk_score_regressions=(),
    findings=(),
    accepted=True,
)
_provenance = build_candidate_runtime_provenance(
    materialized=_materialized,
    snapshot=_snapshot_lf,
    candidate_report=_candidate_report,
    regression_proof=_regression,
)
check(
    _provenance.candidate_commit_sha == _materialized.commit_sha
    and _provenance.candidate_tree_sha == _materialized.tree_sha
    and _provenance.snapshot_tree_sha == _materialized.tree_sha
    and _provenance.worker_code_sha256 == _code
    and _provenance.candidate_eval_sha256 == _eval_sha
    and _provenance.accepted_regression is True
    and _provenance.authority == "evidence-only"
    and _provenance.merge_authority == "human",
    "accepted RSI provenance binds commit/tree, worker fingerprint and exact eval",
)

_tree_tampered = tuple(
    SnapshotEntry(entry.path, entry.mode, b"tampered\n")
    if entry.path == "README.md"
    else entry
    for entry in _snapshot_lf
)
check(
    worker_code_sha256(_tree_tampered) == _code,
    "non-worker edits do not falsely change worker runtime identity",
)
expect_error(
    CandidateProvenanceError,
    "does not reproduce the materialized Git tree",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_tree_tampered,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "non-worker mutation is caught by exact Git-tree binding",
)
_worker_tampered = tuple(
    SnapshotEntry(
        entry.path,
        entry.mode,
        b"def choose():\n    return 'model_list'\n",
    )
    if entry.path == "worker/app/planner.py"
    else entry
    for entry in _snapshot_lf
)
_worker_identity = MaterializedCandidateIdentity(
    materialization_receipt_sha256="a" * 64,
    task_sha256=_task_sha,
    commit_sha="b" * 40,
    tree_sha=candidate_tree_sha(_worker_tampered),
)
expect_error(
    CandidateProvenanceError,
    "measured different worker code",
    lambda: build_candidate_runtime_provenance(
        materialized=_worker_identity,
        snapshot=_worker_tampered,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "changed worker tree cannot reuse an eval from the old worker code",
)
_wrong_eval = {
    "schema": AGENT3_EVAL_SCHEMA,
    "backend": {"code_sha256": _code},
    "extra": True,
}
expect_error(
    CandidateProvenanceError,
    "not the report accepted by regression proof",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_snapshot_lf,
        candidate_report=_wrong_eval,
        regression_proof=_regression,
    ),
    "same fingerprint cannot substitute a different eval payload",
)
_rejected = replace(_regression, findings=("candidate regressed",), accepted=False)
expect_error(
    CandidateProvenanceError,
    "regression proof is not accepted",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_snapshot_lf,
        candidate_report=_candidate_report,
        regression_proof=_rejected,
    ),
    "runtime provenance cannot elevate a rejected candidate",
)
_wrong_task = MaterializedCandidateIdentity(
    materialization_receipt_sha256="c" * 64,
    task_sha256="d" * 64,
    commit_sha="e" * 40,
    tree_sha=candidate_tree_sha(_snapshot_lf),
)
expect_error(
    CandidateProvenanceError,
    "task does not match regression task",
    lambda: build_candidate_runtime_provenance(
        materialized=_wrong_task,
        snapshot=_snapshot_lf,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "another DevelopmentTask cannot attach to this regression proof",
)
expect_error(
    CandidateProvenanceError,
    "requires LocalCandidateMaterializationReceipt",
    lambda: MaterializedCandidateIdentity.from_receipt(object()),
    "materialization adapter refuses arbitrary objects",
)


# Read-only collector core. Production wiring uses the staged TrustedGitRunner;
# this fake isolates parsing, object binding and budgets from runtime staging.
_COLLECT_SNAPSHOT = (
    SnapshotEntry("README.md", "100644", b"candidate\n"),
    SnapshotEntry("worker/app/__init__.py", "100644", b""),
    SnapshotEntry(
        "worker/app/planner.py",
        "100644",
        b"def choose():\n    return 'rig_status'\n",
    ),
)
_COLLECT_COMMIT = "4" * 40
_COLLECT_TREE = candidate_tree_sha(_COLLECT_SNAPSHOT)
_COLLECT_IDENTITY = MaterializedCandidateIdentity(
    materialization_receipt_sha256="3" * 64,
    task_sha256="2" * 64,
    commit_sha=_COLLECT_COMMIT,
    tree_sha=_COLLECT_TREE,
)


class _FakeReader:
    def __init__(
        self,
        entries=_COLLECT_SNAPSHOT,
        *,
        tree=_COLLECT_TREE,
        listing_override=None,
        size_override=None,
        payload_override=None,
    ):
        self.entries = entries
        self.tree = tree
        self.listing_override = listing_override
        self.size_override = size_override or {}
        self.payload_override = payload_override or {}
        self.blob_reads = 0
        self.by_oid = {_blob_oid(entry.content): entry for entry in entries}

    def listing(self):
        if self.listing_override is not None:
            return self.listing_override
        rows = []
        for entry in self.entries:
            oid = _blob_oid(entry.content)
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
        if command == ("rev-parse", f"{_COLLECT_COMMIT}^{{commit}}"):
            return (_COLLECT_COMMIT + "\n").encode("ascii")
        if command == ("rev-parse", f"{_COLLECT_COMMIT}^{{tree}}"):
            return (self.tree + "\n").encode("ascii")
        if command == ("ls-tree", "-r", "-z", "--full-tree", _COLLECT_COMMIT):
            return self.listing()
        if len(command) == 3 and command[:2] == ("cat-file", "-s"):
            oid = command[2]
            size = self.size_override.get(oid, len(self.by_oid[oid].content))
            return (str(size) + "\n").encode("ascii")
        if len(command) == 3 and command[:2] == ("cat-file", "blob"):
            self.blob_reads += 1
            oid = command[2]
            return self.payload_override.get(oid, self.by_oid[oid].content)
        raise AssertionError(f"unexpected fake Git command: {command!r}")


def _collect(reader, *, budget=SnapshotBudget()):
    return _collect_with_reader(
        reader=reader,
        repository=Path("candidate.git"),
        operation_root=Path("collector"),
        identity=_COLLECT_IDENTITY,
        git_runtime_manifest_sha256="a" * 64,
        git_executable_sha256="b" * 64,
        budget=budget,
    )


_reader = _FakeReader()
_collected = _collect(_reader)
check(_collected.entries == _COLLECT_SNAPSHOT, "collector returns exact candidate bytes")
check(
    _collected.receipt.candidate_commit_sha == _COLLECT_COMMIT
    and _collected.receipt.candidate_tree_sha == _COLLECT_TREE
    and _collected.receipt.file_count == len(_COLLECT_SNAPSHOT)
    and _collected.receipt.total_bytes
    == sum(len(entry.content) for entry in _COLLECT_SNAPSHOT),
    "collector receipt binds commit/tree plus exact count and bytes",
)
check(
    _collected.receipt.network_performed is False
    and _collected.receipt.repository_mutated is False
    and _collected.receipt.authority == "evidence-only"
    and _collected.receipt.merge_authority == "human",
    "collector receipt is offline, read-only and non-authorizing",
)
_collected.verify()
check(_reader.blob_reads == len(_COLLECT_SNAPSHOT), "collector reads each sized blob once")

_gitlink = (
    b"160000 commit "
    + ("c" * 40).encode("ascii")
    + b"\tvendor/submodule\0"
)
expect_error(
    CandidateSnapshotError,
    "unsupported object type or mode",
    lambda: _collect(_FakeReader(listing_override=_gitlink)),
    "gitlinks/submodules fail closed",
)
expect_error(
    CandidateSnapshotError,
    "file-count budget",
    lambda: _collect(
        _FakeReader(),
        budget=SnapshotBudget(max_files=2, max_file_bytes=1024, max_total_bytes=4096),
    ),
    "file-count budget rejects oversized trees",
)
_large_oid = _blob_oid(_COLLECT_SNAPSHOT[0].content)
_large_reader = _FakeReader(size_override={_large_oid: 100})
expect_error(
    CandidateSnapshotError,
    "per-file budget",
    lambda: _collect(
        _large_reader,
        budget=SnapshotBudget(max_files=10, max_file_bytes=32, max_total_bytes=256),
    ),
    "per-file budget rejects before payload reads",
)
check(_large_reader.blob_reads == 0, "per-file rejection performs no payload reads")
_total_reader = _FakeReader(
    size_override={_blob_oid(entry.content): 20 for entry in _COLLECT_SNAPSHOT}
)
expect_error(
    CandidateSnapshotError,
    "total byte budget",
    lambda: _collect(
        _total_reader,
        budget=SnapshotBudget(max_files=10, max_file_bytes=32, max_total_bytes=40),
    ),
    "aggregate byte budget rejects before payload reads",
)
check(_total_reader.blob_reads == 0, "aggregate rejection performs no payload reads")
_target_oid = _blob_oid(_COLLECT_SNAPSHOT[0].content)
_count_tamper = _FakeReader(payload_override={_target_oid: b"tampered!!\n"})
expect_error(
    CandidateSnapshotError,
    "byte count changed",
    lambda: _collect(_count_tamper),
    "mid-collection blob length mutation fails closed",
)
_same_size_tamper = b"candidate?"
check(
    len(_same_size_tamper) == len(_COLLECT_SNAPSHOT[0].content),
    "same-size tamper fixture is stable",
)
_hash_tamper = _FakeReader(payload_override={_target_oid: _same_size_tamper})
expect_error(
    CandidateSnapshotError,
    "do not match Git object identity",
    lambda: _collect(_hash_tamper),
    "same-size mutation is caught by Git blob identity",
)
expect_error(
    CandidateSnapshotError,
    "commit/tree identity changed",
    lambda: _collect(_FakeReader(tree="d" * 40)),
    "candidate root tree cannot move before collection",
)
_truncated = b"100644 blob " + ("e" * 40).encode("ascii") + b"\tREADME.md"
expect_error(
    CandidateSnapshotError,
    "not NUL terminated",
    lambda: _collect(_FakeReader(listing_override=_truncated)),
    "truncated ls-tree output fails closed",
)


# Pre-physical qualification: a complete software chain still cannot become GO.
_qual_proposal = ImprovementProposal.from_mapping(
    {
        "schema": "kaliv-rsi-improvement-proposal/v1",
        "proposal_id": "RSI_QUAL_001",
        "repository": "Ternedal/ModelRig",
        "base_sha": "7" * 40,
        "source_schema": AGENT3_EVAL_SCHEMA,
        "evidence_sha256": "8" * 64,
        "finding_ids": ["A3-QUAL-001"],
        "title": "Qualification chain fixture",
        "problem": "Candidate skal bindes til fysisk gate uden auto-activation.",
        "hypothesis": "En komplet softwarekæde kan bevises uden at tildele GO.",
        "expected_gain": "Qualification bliver auditable og fail-closed.",
        "implementation_strategy": "Bind proposal, promotion, snapshot, regression og provenance.",
        "suggested_paths": ["worker/app/planner.py"],
        "suggested_tests": ["python tests/worker_build_identity.py"],
        "acceptance_criteria": ["software chain complete men GO forbliver false"],
        "required_evals": [AGENT3_EVAL_SCHEMA],
        "risk": "medium",
        "authority": "proposal-only",
        "merge_authority": "human",
    }
)
_qual_proposal_sha = proposal_sha256(_qual_proposal)
_qual_promotion = PromotionReceipt.from_mapping(
    {
        "schema": "kaliv-rsi-promotion-receipt/v1",
        "proposal_id": _qual_proposal.proposal_id,
        "proposal_sha256": _qual_proposal_sha,
        "authorization_sha256": "a" * 64,
        "authorization_signature_sha256": "b" * 64,
        "task_id": "RSI_TASK_QUAL_001",
        "task_sha256": _task_sha,
        "repository": _qual_proposal.repository,
        "base_sha": _qual_proposal.base_sha,
        "reviewer_actor_id": "anders.test",
        "issuer_system_id": PROMOTION_ISSUER_SYSTEM_ID,
        "verified_at_utc": "2026-09-12T19:01:00Z",
        "required_evals": list(_qual_proposal.required_evals),
        "authority": PROMOTION_AUTHORITY,
    }
)
_qual_regression = replace(
    _regression,
    proposal_id=_qual_proposal.proposal_id,
    proposal_sha256=_qual_proposal_sha,
    promotion_receipt_sha256=_qual_promotion.sha256,
    task_id=_qual_promotion.task_id,
    task_sha256=_qual_promotion.task_sha256,
    repository=_qual_promotion.repository,
    base_sha=_qual_promotion.base_sha,
    baseline_eval_sha256=_qual_proposal.evidence_sha256,
)
_qual_provenance = build_candidate_runtime_provenance(
    materialized=_materialized,
    snapshot=_snapshot_lf,
    candidate_report=_candidate_report,
    regression_proof=_qual_regression,
)
_qual_snapshot = CandidateSnapshotReceipt(
    materialization_receipt_sha256=_materialized.materialization_receipt_sha256,
    task_sha256=_qual_promotion.task_sha256,
    candidate_commit_sha=_materialized.commit_sha,
    candidate_tree_sha=_materialized.tree_sha,
    file_count=len(_snapshot_lf),
    total_bytes=sum(len(entry.content) for entry in _snapshot_lf),
    manifest_sha256="c" * 64,
    git_runtime_manifest_sha256="d" * 64,
    git_executable_sha256="e" * 64,
)
_qual_packet = build_qualification_packet(
    proposal=_qual_proposal,
    promotion=_qual_promotion,
    snapshot=_qual_snapshot,
    regression=_qual_regression,
    provenance=_qual_provenance,
)
check(
    _qual_packet.software_chain_complete is True
    and _qual_packet.ready_for_human_go is False
    and _qual_packet.activation_authorized is False
    and _qual_packet.automatic_activation is False
    and _qual_packet.remote_publication_authorized is False,
    "complete RSI software chain remains non-authorizing before physical gates",
)
check(
    _qual_packet.fresh_physical_evidence_required is True
    and _qual_packet.independent_collector_approver_required is True
    and _qual_packet.missing_physical_gates == MISSING_PHYSICAL_GATES,
    "qualification preserves every DC-L15/DC-L16 external gate",
)
check(
    QualificationPacket.from_json(_qual_packet.canonical_json()).canonical_json()
    == _qual_packet.canonical_json(),
    "qualification packet canonical JSON roundtrips exactly",
)

_qual_mapping = _qual_packet.to_dict()
_qual_mapping["ready_for_human_go"] = True
expect_error(
    QualificationPacketError,
    "may not grant pilot or activation authority",
    lambda: QualificationPacket.from_mapping(_qual_mapping),
    "serialized qualification cannot be flipped into human GO",
)
_qual_mapping = _qual_packet.to_dict()
_qual_mapping["missing_physical_gates"] = list(MISSING_PHYSICAL_GATES[:-1])
expect_error(
    QualificationPacketError,
    "must preserve all external physical/human gates",
    lambda: QualificationPacket.from_mapping(_qual_mapping),
    "qualification cannot delete the final human pilot decision",
)
_qual_mapping = _qual_packet.to_dict()
_qual_mapping["activation_token"] = "go"
expect_error(
    QualificationPacketError,
    "fields mismatch",
    lambda: QualificationPacket.from_mapping(_qual_mapping),
    "unknown activation fields fail closed",
)
expect_error(
    QualificationPacketError,
    "another task",
    lambda: build_qualification_packet(
        proposal=_qual_proposal,
        promotion=_qual_promotion,
        snapshot=replace(_qual_snapshot, task_sha256="f" * 64),
        regression=_qual_regression,
        provenance=_qual_provenance,
    ),
    "snapshot from another DevelopmentTask cannot enter the packet",
)
expect_error(
    QualificationPacketError,
    "runtime provenance is not bound",
    lambda: build_qualification_packet(
        proposal=_qual_proposal,
        promotion=_qual_promotion,
        snapshot=_qual_snapshot,
        regression=_qual_regression,
        provenance=replace(_qual_provenance, candidate_tree_sha="f" * 40),
    ),
    "runtime provenance cannot swap the materialized candidate tree",
)
expect_error(
    QualificationPacketError,
    "accepted regression proof",
    lambda: build_qualification_packet(
        proposal=_qual_proposal,
        promotion=_qual_promotion,
        snapshot=_qual_snapshot,
        regression=replace(
            _qual_regression,
            accepted=False,
            findings=("candidate regressed",),
        ),
        provenance=_qual_provenance,
    ),
    "rejected candidate can never be packaged as qualified software evidence",
)

print(
    f"\n===== BUILD IDENTITY + RSI PROVENANCE/QUALIFICATION: "
    f"{passed} passed, {failed} failed ====="
)
raise SystemExit(1 if failed else 0)

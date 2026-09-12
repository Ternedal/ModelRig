"""The source fingerprint must identify the SOURCE, not the checkout (F-726).

The Windows appliance hashes its source tree and the code-identity gate compares
that hash to what a source checkout produces (F-607). The whole binding rests on
one assumption: byte-identical logical source produces an identical hash no
matter where it was checked out. Git breaks that assumption on its own -- with
core.autocrlf=true a file lands as CRLF on Windows and LF on the Linux CI runner
-- so without normalization the gate reports validated_code_mismatch on the rig
for a file nobody changed, and physical validation (F-701) cannot pass for a
spurious reason. That failure would look exactly like a real mismatch.

The RSI provenance extension reuses the same identity rule to prove that an
accepted candidate eval measured the worker code from one exact materialized Git
tree, without granting any execution or publication authority.

Run: PYTHONPATH=worker python3 tests/worker_build_identity.py
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
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
from kaliv_dev_control.improvement_proposal import (  # noqa: E402
    AGENT3_EVAL_SCHEMA,
    canonical_sha256,
)
from kaliv_dev_control.improvement_regression import (  # noqa: E402
    CandidateRegressionProof,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def expect_provenance_error(fragment, fn, msg):
    try:
        fn()
    except CandidateProvenanceError as exc:
        check(fragment in str(exc), msg)
    else:
        check(False, msg)


def _hash(path: Path) -> str:
    return hashlib.sha256(_canonical_bytes(path)).hexdigest()


# --- the same logical source hashes the same under any line ending ----------
_d = Path(tempfile.mkdtemp(prefix="kaliv-eol-"))
_lf = _d / "lf.py"
_lf.write_bytes(b"def f():\n    return 1\n")
_crlf = _d / "crlf.py"
_crlf.write_bytes(b"def f():\r\n    return 1\r\n")
_cr = _d / "cr.py"
_cr.write_bytes(b"def f():\r    return 1\r")

check(_hash(_lf) == _hash(_crlf),
      "LF and CRLF of identical source hash the same -- a Windows autocrlf "
      "checkout matches the CI checkout")
check(_hash(_lf) == _hash(_cr),
      "a lone CR (old-Mac style) normalizes too, so no checkout style leaks "
      "into the identity")

# --- normalization must not erase a REAL difference -------------------------
_changed = _d / "changed.py"
_changed.write_bytes(b"def f():\n    return 2\n")
check(_hash(_lf) != _hash(_changed),
      "a real content change still changes the hash -- normalization ignores "
      "line endings, not logic")

_blankline = _d / "blank.py"
_blankline.write_bytes(b"def f():\n\n    return 1\n")
check(_hash(_lf) != _hash(_blankline),
      "adding a blank line changes the hash -- only the CR/LF bytes are "
      "normalized, not the presence of lines")

# --- the bytes are actually normalized, not just compared -------------------
check(b"\r" not in _canonical_bytes(_crlf),
      "the canonical bytes contain no CR, so anything hashing them is "
      "checkout-independent by construction")

# --- .gitattributes is the on-disk half, and must exist ---------------------
_ga = ROOT / ".gitattributes"
check(_ga.exists(), ".gitattributes exists -- the working tree is pinned to LF, "
                    "not left to each machine's autocrlf")
if _ga.exists():
    _text = _ga.read_text(encoding="utf-8")
    check("*.py    text eol=lf" in _text or "*.py text eol=lf" in _text,
          ".gitattributes pins *.py to LF -- the files the fingerprint reads "
          "cannot arrive as CRLF")
    for _ext in ("*.go", "*.kt", "*.json"):
        check(_ext in _text,
              f".gitattributes pins {_ext} too -- every source language the "
              "generators scan is covered")

# --- RSI materialized-tree -> measured runtime provenance -------------------
_snapshot_lf = (
    SnapshotEntry("README.md", "100644", b"candidate\n"),
    SnapshotEntry("worker/app/__init__.py", "100644", b""),
    SnapshotEntry("worker/app/planner.py", "100644", b"def choose():\n    return 'rig_status'\n"),
    SnapshotEntry("worker/app/nested/tool.py", "100755", b"VALUE = 1\n"),
    # A build stamp is generated from the worker fingerprint and must never
    # recursively change the fingerprint it carries.
    SnapshotEntry("worker/app/_build_stamp.py", "100644", b"CODE_SHA256 = 'x'\n"),
)
_snapshot_crlf = tuple(
    SnapshotEntry(entry.path, entry.mode, entry.content.replace(b"\n", b"\r\n"))
    if entry.path.endswith(".py") else entry
    for entry in _snapshot_lf
)

_code = worker_code_sha256(_snapshot_lf)
check(_code == worker_code_sha256(_snapshot_crlf),
      "RSI provenance uses the exact checkout-independent worker fingerprint rule")
check(candidate_tree_sha(_snapshot_lf) != candidate_tree_sha(_snapshot_crlf),
      "Git tree identity remains byte-exact even though worker runtime identity normalizes EOL")

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
    task_set={"schema": "kaliv-agent3-model-eval-task-set/v1", "name": "t", "version": "1", "task_count": 1},
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
    "accepted provenance binds materialized commit/tree, worker fingerprint and exact regression eval without authority",
)

# Change a non-worker file: runtime fingerprint is identical but Git tree no
# longer matches the materialized candidate, so the provenance chain must stop.
_tree_tampered = tuple(
    SnapshotEntry(entry.path, entry.mode, b"tampered\n")
    if entry.path == "README.md" else entry
    for entry in _snapshot_lf
)
check(worker_code_sha256(_tree_tampered) == _code,
      "non-worker edits do not falsely change worker runtime identity")
expect_provenance_error(
    "does not reproduce the materialized Git tree",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_tree_tampered,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "a non-worker tree mutation is still caught by exact materialized Git-tree binding",
)

# Change worker source and update the claimed Git tree: the runtime eval must
# independently report the new worker fingerprint or the bridge refuses it.
_worker_tampered = tuple(
    SnapshotEntry(entry.path, entry.mode, b"def choose():\n    return 'model_list'\n")
    if entry.path == "worker/app/planner.py" else entry
    for entry in _snapshot_lf
)
_worker_identity = MaterializedCandidateIdentity(
    materialization_receipt_sha256="a" * 64,
    task_sha256=_task_sha,
    commit_sha="b" * 40,
    tree_sha=candidate_tree_sha(_worker_tampered),
)
expect_provenance_error(
    "measured different worker code",
    lambda: build_candidate_runtime_provenance(
        materialized=_worker_identity,
        snapshot=_worker_tampered,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "a materialized worker change cannot reuse an eval collected from the old worker code",
)

_wrong_eval = {"schema": AGENT3_EVAL_SCHEMA, "backend": {"code_sha256": _code}, "extra": True}
expect_provenance_error(
    "not the report accepted by regression proof",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_snapshot_lf,
        candidate_report=_wrong_eval,
        regression_proof=_regression,
    ),
    "runtime binding cannot substitute a different eval payload with the same code fingerprint",
)

_rejected = CandidateRegressionProof(
    **{**_regression.__dict__} if hasattr(_regression, "__dict__") else {
        "proposal_id": _regression.proposal_id,
        "proposal_sha256": _regression.proposal_sha256,
        "promotion_receipt_sha256": _regression.promotion_receipt_sha256,
        "task_id": _regression.task_id,
        "task_sha256": _regression.task_sha256,
        "repository": _regression.repository,
        "base_sha": _regression.base_sha,
        "baseline_eval_sha256": _regression.baseline_eval_sha256,
        "candidate_eval_sha256": _regression.candidate_eval_sha256,
        "baseline_code_sha256": _regression.baseline_code_sha256,
        "candidate_code_sha256": _regression.candidate_code_sha256,
        "baseline_planner_model": _regression.baseline_planner_model,
        "candidate_planner_model": _regression.candidate_planner_model,
        "task_set": _regression.task_set,
        "repetitions": _regression.repetitions,
        "baseline_exact_match_rate": _regression.baseline_exact_match_rate,
        "candidate_exact_match_rate": _regression.candidate_exact_match_rate,
        "baseline_discipline_rate": _regression.baseline_discipline_rate,
        "candidate_discipline_rate": _regression.candidate_discipline_rate,
        "exact_improvements": _regression.exact_improvements,
        "exact_regressions": _regression.exact_regressions,
        "discipline_regressions": _regression.discipline_regressions,
        "risk_score_regressions": _regression.risk_score_regressions,
        "findings": ("candidate regressed",),
        "accepted": False,
    }
)
expect_provenance_error(
    "regression proof is not accepted",
    lambda: build_candidate_runtime_provenance(
        materialized=_materialized,
        snapshot=_snapshot_lf,
        candidate_report=_candidate_report,
        regression_proof=_rejected,
    ),
    "runtime provenance can never turn a rejected candidate into an accepted one",
)

_wrong_task = MaterializedCandidateIdentity(
    materialization_receipt_sha256="c" * 64,
    task_sha256="d" * 64,
    commit_sha="e" * 40,
    tree_sha=candidate_tree_sha(_snapshot_lf),
)
expect_provenance_error(
    "task does not match regression task",
    lambda: build_candidate_runtime_provenance(
        materialized=_wrong_task,
        snapshot=_snapshot_lf,
        candidate_report=_candidate_report,
        regression_proof=_regression,
    ),
    "materialization from another DevelopmentTask cannot be attached to this regression proof",
)

expect_provenance_error(
    "requires LocalCandidateMaterializationReceipt",
    lambda: MaterializedCandidateIdentity.from_receipt(object()),
    "materialization adapter refuses unverified arbitrary objects",
)

print(f"\n===== BUILD IDENTITY: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

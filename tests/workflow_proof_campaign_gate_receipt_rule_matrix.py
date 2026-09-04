#!/usr/bin/env python3
"""Rule-by-rule regression matrix for reusable proof campaign receipts.

Every negative case starts from a receipt/source pair that the real validator
accepts, mutates only the evidence needed to violate one contract rule, and
requires that rule's own ReceiptError message. Source-report forgeries recompute
the receipt digest/byte metadata deliberately: semantic rules must defend their
own boundary instead of being rescued by an unrelated stale-digest check.

The matrix covers all five reusable gates. It also exercises configuration
construction, JSON loading, source binding, commit authority and T-033 freshness
so weakening one of those fail-closed guards makes this suite red.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "proof_campaign_gate_receipt.py"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=cwd, text=True, capture_output=True, check=False, timeout=30
    )


def git(root: Path, *args: str) -> str:
    result = run("git", *args, cwd=root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def load_module():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("proof_campaign_gate_receipt_matrix", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load proof_campaign_gate_receipt.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_json(path: Path, value) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def nested_set(value: dict, path: tuple[str, ...], replacement) -> None:
    current = value
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement


def expect_receipt_error(name: str, action: Callable[[], object], expected: str) -> None:
    try:
        action()
    except M.ReceiptError as exc:
        message = str(exc)
        check(expected in message, f"{name} is rejected by its own rule ({message})")
    except Exception as exc:
        check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
    else:
        check(False, f"{name} forgery was accepted")


M = load_module()

with tempfile.TemporaryDirectory(prefix="modelrig-proof-receipt-matrix-") as td:
    repo = Path(td)
    git(repo, "init")
    git(repo, "config", "user.email", "proof-matrix@example.invalid")
    git(repo, "config", "user.name", "Proof Receipt Matrix")
    (repo / "scope.txt").write_text("scope-v1\n", encoding="utf-8")
    git(repo, "add", "--", "scope.txt")
    git(repo, "commit", "-m", "base")
    sha = git(repo, "rev-parse", "HEAD")

    M.ROOT = repo
    M.RECEIPTS = {
        "stage_a": Path("validation/proof-gates/stage-a-latest.json"),
        "forced_recovery": Path("validation/proof-gates/forced-recovery-latest.json"),
        "workflows": Path("validation/proof-gates/workflows-latest.json"),
        "t023": Path("validation/proof-gates/t023-latest.json"),
        "t033": Path("validation/proof-gates/t033-latest.json"),
    }
    M.SOURCES = {
        "stage_a": Path("validation/physical-validation-candidate-final-latest.json"),
        "forced_recovery": None,
        "workflows": Path("validation/workflow-proof-latest.json"),
        "t023": Path("validation/agent3-termination-ui-physical-latest.json"),
        "t033": Path("validation/agent3-memory-protected-backup-physical-latest.json"),
    }
    for gate_name in M.RECEIPTS:
        M.proof_scope.PROOF_SCOPES[gate_name] = ("scope.txt",)

    fixed_now = datetime(2026, 8, 22, 12, 0, 0, tzinfo=timezone.utc)
    planner = "qwen3:14b"
    rounds = 1
    workflows_per_round = 3
    expected_executions = rounds * workflows_per_round
    threshold = 0.95

    gate_kwargs = {
        "stage_a": {"planner_model": planner},
        "forced_recovery": {},
        "workflows": {
            "planner_model": planner,
            "workflow_rounds": rounds,
            "workflow_threshold": threshold,
        },
        "t023": {},
        "t033": {},
    }
    baseline_reports = {
        "stage_a": {
            "schema": "kaliv-physical-validation-candidate-final/v1",
            "candidate": {"git_sha": sha},
            "gate": {"passed": True, "production_activation": False},
        },
        # Deliberately not 14 workflows. This proves the validator consumes the
        # producer's explicit cardinality instead of a repository constant.
        "workflows": {
            "schema": "modelrig-workflow-proof/v1",
            "sha": sha,
            "planner_model": planner,
            "requested_rounds": rounds,
            "rounds": rounds,
            "workflows_per_round": workflows_per_round,
            "expected_executions": expected_executions,
            "executions": expected_executions,
            "mean_completion_rate": 0.97,
            "threshold": threshold,
            "runner_failures": 0,
            "passed": True,
        },
        "t023": {
            "schema": "kaliv-agent3-termination-ui-physical/v1",
            "candidate": {"git_sha": sha},
            "success": True,
            "production_activation": False,
        },
        "t033": {
            "schema": "kaliv-agent3-memory-protected-backup-physical/v1",
            "candidate": {"git_sha": sha},
            "success": True,
            "production_activation": False,
            "generated_at": fixed_now.isoformat().replace("+00:00", "Z"),
        },
    }

    for gate_name, report in baseline_reports.items():
        source = M.SOURCES[gate_name]
        if source is None:
            raise RuntimeError(f"unexpected source-less baseline report: {gate_name}")
        write_json(repo / source, report)

    baseline_receipts: dict[str, dict] = {}
    for gate_name in M.RECEIPTS:
        M.record(
            gate_name,
            sha,
            "test",
            now=fixed_now,
            **gate_kwargs[gate_name],
        )
        receipt_path = repo / M.RECEIPTS[gate_name]
        baseline_receipts[gate_name] = json.loads(receipt_path.read_text(encoding="utf-8"))

    def validate_gate(gate_name: str, *, head_sha: str = sha):
        return M.validate(
            gate_name,
            head_sha,
            now=fixed_now,
            **gate_kwargs[gate_name],
        )

    def reset_gate(gate_name: str) -> None:
        source = M.SOURCES[gate_name]
        if source is not None:
            write_json(repo / source, copy.deepcopy(baseline_reports[gate_name]))
        write_json(repo / M.RECEIPTS[gate_name], copy.deepcopy(baseline_receipts[gate_name]))

    def receipt_case(
        gate_name: str,
        name: str,
        mutator: Callable[[dict], None],
        expected: str,
    ) -> None:
        reset_gate(gate_name)
        receipt = copy.deepcopy(baseline_receipts[gate_name])
        mutator(receipt)
        write_json(repo / M.RECEIPTS[gate_name], receipt)
        expect_receipt_error(f"{gate_name}: {name}", lambda: validate_gate(gate_name), expected)

    def source_case(
        gate_name: str,
        name: str,
        mutator: Callable[[dict], None],
        expected: str,
    ) -> None:
        reset_gate(gate_name)
        source = M.SOURCES[gate_name]
        if source is None:
            raise RuntimeError(f"source case requested for source-less gate: {gate_name}")
        report = copy.deepcopy(baseline_reports[gate_name])
        mutator(report)
        raw = write_json(repo / source, report)
        receipt = copy.deepcopy(baseline_receipts[gate_name])
        receipt["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
        receipt["source"]["bytes"] = len(raw)
        write_json(repo / M.RECEIPTS[gate_name], receipt)
        expect_receipt_error(f"{gate_name}: {name}", lambda: validate_gate(gate_name), expected)

    def set_value(path: tuple[str, ...], replacement):
        return lambda value: nested_set(value, path, replacement)

    print("\naccepted baselines:")
    for gate_name in M.RECEIPTS:
        accepted = validate_gate(gate_name)
        check(
            accepted.get("passed") is True and accepted.get("reused") is True,
            f"untouched {gate_name} receipt is accepted",
        )

    print("\nconfiguration construction:")
    expect_receipt_error(
        "stage_a missing planner",
        lambda: M._configuration(
            "stage_a", planner_model=None, workflow_rounds=None, workflow_threshold=None
        ),
        "Stage A receipt requires planner_model",
    )
    expect_receipt_error(
        "workflows missing planner",
        lambda: M._configuration(
            "workflows", planner_model=" ", workflow_rounds=1, workflow_threshold=0.95
        ),
        "workflow receipt requires planner_model",
    )
    expect_receipt_error(
        "workflows boolean rounds",
        lambda: M._configuration(
            "workflows", planner_model=planner, workflow_rounds=True, workflow_threshold=0.95
        ),
        "workflow receipt requires positive workflow_rounds",
    )
    expect_receipt_error(
        "workflows zero rounds",
        lambda: M._configuration(
            "workflows", planner_model=planner, workflow_rounds=0, workflow_threshold=0.95
        ),
        "workflow receipt requires positive workflow_rounds",
    )
    expect_receipt_error(
        "workflows boolean threshold",
        lambda: M._configuration(
            "workflows", planner_model=planner, workflow_rounds=1, workflow_threshold=True
        ),
        "workflow receipt requires workflow_threshold",
    )
    expect_receipt_error(
        "workflows threshold below range",
        lambda: M._configuration(
            "workflows", planner_model=planner, workflow_rounds=1, workflow_threshold=-0.01
        ),
        "workflow_threshold must be between 0 and 1",
    )
    expect_receipt_error(
        "workflows threshold above range",
        lambda: M._configuration(
            "workflows", planner_model=planner, workflow_rounds=1, workflow_threshold=1.01
        ),
        "workflow_threshold must be between 0 and 1",
    )

    print("\nJSON loading boundaries:")
    load_dir = repo / "validation" / "load-matrix"
    load_dir.mkdir(parents=True, exist_ok=True)
    missing_rel = Path("validation/load-matrix/missing.json")
    expect_receipt_error(
        "missing JSON evidence",
        lambda: M._load_json(missing_rel),
        "JSON evidence is missing or irregular",
    )

    symlink_rel = Path("validation/load-matrix/symlink.json")
    symlink_abs = repo / symlink_rel
    write_json(symlink_abs, {"ok": True})
    original_is_symlink = Path.is_symlink

    def fake_is_symlink(path: Path) -> bool:
        if path == symlink_abs:
            return True
        return original_is_symlink(path)

    with patch.object(Path, "is_symlink", fake_is_symlink):
        expect_receipt_error(
            "symlink JSON evidence",
            lambda: M._load_json(symlink_rel),
            "path is a symlink",
        )

    empty_rel = Path("validation/load-matrix/empty.json")
    (repo / empty_rel).write_bytes(b"")
    expect_receipt_error(
        "empty JSON evidence",
        lambda: M._load_json(empty_rel),
        "JSON evidence size is invalid",
    )

    oversized_rel = Path("validation/load-matrix/oversized.json")
    old_max_json_bytes = M.MAX_JSON_BYTES
    try:
        M.MAX_JSON_BYTES = 8
        (repo / oversized_rel).write_bytes(b'{"x": 1}\n')
        expect_receipt_error(
            "oversized JSON evidence",
            lambda: M._load_json(oversized_rel),
            "JSON evidence size is invalid",
        )
    finally:
        M.MAX_JSON_BYTES = old_max_json_bytes

    invalid_rel = Path("validation/load-matrix/invalid.json")
    (repo / invalid_rel).write_text("{not-json}\n", encoding="utf-8")
    expect_receipt_error(
        "invalid JSON evidence",
        lambda: M._load_json(invalid_rel),
        "JSON evidence is invalid",
    )

    list_rel = Path("validation/load-matrix/list.json")
    write_json(repo / list_rel, [])
    expect_receipt_error(
        "non-object JSON evidence",
        lambda: M._load_json(list_rel),
        "JSON evidence is not an object",
    )

    escape = repo.parent / f"{repo.name}-escape.json"
    escape.write_text("{}\n", encoding="utf-8")
    try:
        expect_receipt_error(
            "repository escape",
            lambda: M._load_json(escape),
            "path escapes repository",
        )
    finally:
        escape.unlink(missing_ok=True)

    print("\ncommit authority:")
    missing_commit = "0" * 40
    expect_receipt_error(
        "record missing commit",
        lambda: M.record("forced_recovery", missing_commit, "test", now=fixed_now),
        "taken_on_sha is not a local Git commit",
    )
    expect_receipt_error(
        "validate missing head commit",
        lambda: validate_gate("forced_recovery", head_sha=missing_commit),
        "head_sha is not a local Git commit",
    )
    receipt_case(
        "forced_recovery",
        "missing taken_on commit",
        set_value(("taken_on_sha",), missing_commit),
        "receipt taken_on_sha is invalid or unavailable",
    )

    print("\ncommon receipt rules for every gate:")
    gate_order = list(M.RECEIPTS)
    for index, gate_name in enumerate(gate_order):
        other_gate = gate_order[(index + 1) % len(gate_order)]
        receipt_case(
            gate_name,
            "receipt schema",
            set_value(("schema",), "forged-receipt/v0"),
            "receipt schema mismatch",
        )
        receipt_case(
            gate_name,
            "receipt gate",
            set_value(("gate",), other_gate),
            "receipt gate mismatch",
        )
        receipt_case(
            gate_name,
            "receipt passed",
            set_value(("passed",), False),
            "receipt is not PASS",
        )
        receipt_case(
            gate_name,
            "receipt production activation",
            set_value(("production_activation",), True),
            "receipt moved production activation",
        )
        receipt_case(
            gate_name,
            "receipt configuration",
            set_value(("configuration",), {"forged": True}),
            "receipt measurement configuration mismatch",
        )

    receipt_case(
        "forced_recovery",
        "source-less gate names source",
        set_value(("source",), {"path": "forged.json"}),
        "source-less gate receipt unexpectedly names a source",
    )

    print("\nsource metadata binding for every sourced gate:")
    for gate_name in ("stage_a", "workflows", "t023", "t033"):
        receipt_case(
            gate_name,
            "source metadata missing",
            set_value(("source",), None),
            "receipt source metadata is missing",
        )
        receipt_case(
            gate_name,
            "source path missing",
            set_value(("source", "path"), None),
            "receipt source path is missing",
        )
        receipt_case(
            gate_name,
            "source digest invalid",
            set_value(("source", "sha256"), "not-a-digest"),
            "receipt source digest is invalid",
        )
        receipt_case(
            gate_name,
            "source digest mismatch",
            set_value(("source", "sha256"), "0" * 64),
            "receipt source digest no longer matches",
        )
        baseline_size = baseline_receipts[gate_name]["source"]["bytes"]
        receipt_case(
            gate_name,
            "source byte count",
            set_value(("source", "bytes"), baseline_size + 1),
            "receipt source byte count no longer matches",
        )

        reset_gate(gate_name)
        source = M.SOURCES[gate_name]
        if source is None:
            raise RuntimeError(f"unexpected source-less gate: {gate_name}")
        raw = (repo / source).read_bytes()
        alternate = Path(f"validation/alternate-{gate_name}.json")
        (repo / alternate).parent.mkdir(parents=True, exist_ok=True)
        (repo / alternate).write_bytes(raw)
        receipt = copy.deepcopy(baseline_receipts[gate_name])
        receipt["source"]["path"] = alternate.as_posix()
        receipt["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
        receipt["source"]["bytes"] = len(raw)
        write_json(repo / M.RECEIPTS[gate_name], receipt)
        expect_receipt_error(
            f"{gate_name}: non-canonical source path",
            lambda gate_name=gate_name: validate_gate(gate_name),
            "receipt source path is not the canonical gate source",
        )

    print("\nStage A source verdict:")
    source_case(
        "stage_a",
        "schema",
        set_value(("schema",), "forged-stage-a/v0"),
        "Stage A final report schema mismatch",
    )
    source_case(
        "stage_a",
        "failed verdict",
        set_value(("gate", "passed"), False),
        "Stage A final report is not PASS",
    )
    source_case(
        "stage_a",
        "production activation",
        set_value(("gate", "production_activation"), True),
        "Stage A final report moved production activation",
    )
    source_case(
        "stage_a",
        "candidate sha",
        set_value(("candidate", "git_sha"), "f" * 40),
        "stage_a source candidate mismatch",
    )

    print("\nworkflow source verdict:")
    workflow_cases = [
        ("schema", set_value(("schema",), "forged-workflow-proof/v0"), "workflow aggregate schema mismatch"),
        ("failed verdict", set_value(("passed",), False), "workflow aggregate is not PASS"),
        ("requested rounds bool", set_value(("requested_rounds",), True), "workflow requested_rounds are invalid"),
        ("rounds bool", set_value(("rounds",), True), "workflow rounds are invalid"),
        ("workflows per round bool", set_value(("workflows_per_round",), True), "workflow workflows_per_round is invalid"),
        ("expected executions bool", set_value(("expected_executions",), True), "workflow expected_executions is invalid"),
        (
            "expected execution relationship",
            lambda report: (
                nested_set(report, ("expected_executions",), expected_executions + 1),
                nested_set(report, ("executions",), expected_executions + 1),
            ),
            "workflow expected execution count does not match measured rounds/spec",
        ),
        ("execution count bool", set_value(("executions",), True), "workflow execution count is invalid"),
        ("execution count mismatch", set_value(("executions",), expected_executions - 1), "workflow execution count does not match expected executions"),
        ("runner failures", set_value(("runner_failures",), 1), "workflow aggregate contains runner failures"),
        ("mean type", set_value(("mean_completion_rate",), "0.97"), "workflow aggregate mean/threshold is invalid"),
        ("threshold type", set_value(("threshold",), "0.95"), "workflow aggregate mean/threshold is invalid"),
        ("mean below threshold", set_value(("mean_completion_rate",), 0.0), "workflow aggregate is below threshold"),
        ("planner missing", set_value(("planner_model",), ""), "workflow aggregate planner_model is missing"),
        ("requested rounds configuration", set_value(("requested_rounds",), 2), "workflow requested rounds differ from requested configuration"),
        (
            "rounds configuration",
            lambda report: (
                nested_set(report, ("rounds",), 2),
                nested_set(report, ("expected_executions",), 2 * workflows_per_round),
                nested_set(report, ("executions",), 2 * workflows_per_round),
            ),
            "workflow rounds differ from requested configuration",
        ),
        ("threshold configuration", set_value(("threshold",), 0.90), "workflow threshold differs from requested configuration"),
        ("planner configuration", set_value(("planner_model",), "other:latest"), "workflow planner differs from requested configuration"),
        ("candidate sha", set_value(("sha",), "f" * 40), "workflows source candidate mismatch"),
    ]
    for name, mutator, expected in workflow_cases:
        source_case("workflows", name, mutator, expected)

    print("\nT-023 source verdict:")
    source_case(
        "t023",
        "schema",
        set_value(("schema",), "forged-t023/v0"),
        "T-023 report schema mismatch",
    )
    source_case(
        "t023",
        "failed verdict",
        set_value(("success",), False),
        "T-023 report is not PASS",
    )
    source_case(
        "t023",
        "production activation",
        set_value(("production_activation",), True),
        "T-023 report moved production activation",
    )
    source_case(
        "t023",
        "candidate sha",
        set_value(("candidate", "git_sha"), "f" * 40),
        "t023 source candidate mismatch",
    )

    print("\nT-033 source verdict and freshness:")
    source_case(
        "t033",
        "schema",
        set_value(("schema",), "forged-t033/v0"),
        "T-033 report schema mismatch",
    )
    source_case(
        "t033",
        "failed verdict",
        set_value(("success",), False),
        "T-033 report is not PASS",
    )
    source_case(
        "t033",
        "production activation",
        set_value(("production_activation",), True),
        "T-033 report moved production activation",
    )
    source_case(
        "t033",
        "missing generated_at",
        set_value(("generated_at",), None),
        "T-033 source generated_at is invalid",
    )
    source_case(
        "t033",
        "future generated_at",
        set_value(
            ("generated_at",),
            (fixed_now + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        ),
        "T-033 source generated_at is in the future",
    )
    source_case(
        "t033",
        "stale generated_at",
        set_value(
            ("generated_at",),
            (fixed_now - timedelta(hours=M.T033_MAX_AGE_HOURS + 1)).isoformat().replace(
                "+00:00", "Z"
            ),
        ),
        "T-033 physical evidence is",
    )
    source_case(
        "t033",
        "candidate sha",
        set_value(("candidate", "git_sha"), "f" * 40),
        "t033 source candidate mismatch",
    )

    print("\nfinal baseline restoration:")
    for gate_name in M.RECEIPTS:
        reset_gate(gate_name)
        restored = validate_gate(gate_name)
        check(restored.get("passed") is True, f"{gate_name} baseline remains accepted")

print(f"\n===== PROOF RECEIPT RULE MATRIX: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

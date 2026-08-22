#!/usr/bin/env python3
"""Rule-by-rule regression matrix for reusable proof campaign receipts.

Each negative case starts from the same workflow receipt/source pair that the
real validator accepts, mutates exactly the evidence needed to violate one
contract rule, and requires that rule's own ReceiptError message. Source-report
forgeries recompute the receipt digest/byte metadata deliberately: the test must
exercise the semantic rule, not get rescued by an earlier stale-digest check.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Callable

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


def write_json(path: Path, value: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


def nested_set(value: dict, path: tuple[str, ...], replacement) -> None:
    current = value
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = replacement


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
    M.RECEIPTS = {"workflows": Path("validation/proof-gates/workflows-latest.json")}
    M.SOURCES = {"workflows": Path("validation/workflow-proof-latest.json")}
    M.proof_scope.PROOF_SCOPES["workflows"] = ("scope.txt",)

    receipt_path = repo / M.RECEIPTS["workflows"]
    source_path = repo / M.SOURCES["workflows"]
    planner = "qwen3:14b"
    rounds = 1
    workflows_per_round = 3
    expected_executions = rounds * workflows_per_round
    threshold = 0.95

    # Deliberately not 14. This baseline proves the validator consumes the
    # producer's explicit cardinality fields instead of a repository constant.
    baseline_report = {
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
    }
    write_json(source_path, baseline_report)
    M.record(
        "workflows",
        sha,
        "test",
        planner_model=planner,
        workflow_rounds=rounds,
        workflow_threshold=threshold,
    )
    baseline_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    def validate() -> dict:
        return M.validate(
            "workflows",
            sha,
            planner_model=planner,
            workflow_rounds=rounds,
            workflow_threshold=threshold,
        )

    accepted = validate()
    check(
        accepted.get("passed") is True and accepted.get("reused") is True,
        "untouched non-14 workflow receipt is accepted",
    )

    def apply_case(
        receipt_mutator: Callable[[dict], None] | None,
        report_mutator: Callable[[dict], None] | None,
        *,
        refresh_source_metadata: bool,
    ) -> None:
        receipt = copy.deepcopy(baseline_receipt)
        report = copy.deepcopy(baseline_report)
        if report_mutator is not None:
            report_mutator(report)
        raw = write_json(source_path, report)
        if refresh_source_metadata:
            receipt["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
            receipt["source"]["bytes"] = len(raw)
        if receipt_mutator is not None:
            receipt_mutator(receipt)
        write_json(receipt_path, receipt)

    def set_receipt(path: tuple[str, ...], replacement):
        return lambda receipt: nested_set(receipt, path, replacement)

    def set_report(path: tuple[str, ...], replacement):
        return lambda report: nested_set(report, path, replacement)

    cases = [
        (
            "receipt schema",
            set_receipt(("schema",), "forged-receipt/v0"),
            None,
            False,
            "receipt schema mismatch",
        ),
        (
            "receipt gate",
            set_receipt(("gate",), "t033"),
            None,
            False,
            "receipt gate mismatch",
        ),
        (
            "receipt passed",
            set_receipt(("passed",), False),
            None,
            False,
            "receipt is not PASS",
        ),
        (
            "receipt production activation",
            set_receipt(("production_activation",), True),
            None,
            False,
            "receipt moved production activation",
        ),
        (
            "receipt configuration",
            set_receipt(("configuration", "workflow_threshold"), 0.90),
            None,
            False,
            "receipt measurement configuration mismatch",
        ),
        (
            "receipt source byte count",
            set_receipt(("source", "bytes"), baseline_receipt["source"]["bytes"] + 1),
            None,
            False,
            "receipt source byte count no longer matches",
        ),
        (
            "workflow report schema",
            None,
            set_report(("schema",), "forged-workflow-proof/v0"),
            True,
            "workflow aggregate schema mismatch",
        ),
        (
            "workflow report passed",
            None,
            set_report(("passed",), False),
            True,
            "workflow aggregate is not PASS",
        ),
        (
            "workflow requested rounds validity",
            None,
            set_report(("requested_rounds",), 0),
            True,
            "workflow requested_rounds are invalid",
        ),
        (
            "workflow measured rounds validity",
            None,
            set_report(("rounds",), 0),
            True,
            "workflow rounds are invalid",
        ),
        (
            "workflow workflows-per-round validity",
            None,
            set_report(("workflows_per_round",), 0),
            True,
            "workflow workflows_per_round is invalid",
        ),
        (
            "workflow expected-executions validity",
            None,
            set_report(("expected_executions",), 0),
            True,
            "workflow expected_executions is invalid",
        ),
        (
            "workflow expected execution relationship",
            None,
            lambda report: (
                nested_set(report, ("expected_executions",), expected_executions + 1),
                nested_set(report, ("executions",), expected_executions + 1),
            ),
            True,
            "workflow expected execution count does not match measured rounds/spec",
        ),
        (
            "workflow measured execution count",
            None,
            set_report(("executions",), expected_executions - 1),
            True,
            "workflow execution count does not match expected executions",
        ),
        (
            "workflow runner failures",
            None,
            set_report(("runner_failures",), 7),
            True,
            "workflow aggregate contains runner failures",
        ),
        (
            "workflow requested rounds configuration",
            None,
            set_report(("requested_rounds",), 2),
            True,
            "workflow requested rounds differ from requested configuration",
        ),
        (
            "workflow rounds configuration",
            None,
            lambda report: (
                nested_set(report, ("rounds",), 2),
                nested_set(report, ("expected_executions",), 2 * workflows_per_round),
                nested_set(report, ("executions",), 2 * workflows_per_round),
            ),
            True,
            "workflow rounds differ from requested configuration",
        ),
        (
            "workflow planner configuration",
            None,
            set_report(("planner_model",), "other:latest"),
            True,
            "workflow planner differs from requested configuration",
        ),
        (
            "workflow threshold configuration",
            None,
            set_report(("threshold",), 0.90),
            True,
            "workflow threshold differs from requested configuration",
        ),
        (
            "workflow mean below threshold",
            None,
            set_report(("mean_completion_rate",), 0.0),
            True,
            "workflow aggregate is below threshold",
        ),
    ]

    print("\nrule-specific negative matrix:")
    for name, receipt_mutator, report_mutator, refresh_source_metadata, expected in cases:
        apply_case(
            receipt_mutator,
            report_mutator,
            refresh_source_metadata=refresh_source_metadata,
        )
        try:
            validate()
        except M.ReceiptError as exc:
            message = str(exc)
            check(expected in message, f"{name} is rejected by its own rule ({message})")
        except Exception as exc:
            check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
        else:
            check(False, f"{name} forgery was accepted")

    # Restore the canonical pair and prove the matrix did not leave a poisoned
    # fixture that makes every subsequent case reject for unrelated reasons.
    write_json(source_path, baseline_report)
    write_json(receipt_path, baseline_receipt)
    restored = validate()
    check(restored.get("passed") is True, "baseline is still accepted after all mutations")

print(f"\n===== PROOF RECEIPT RULE MATRIX: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

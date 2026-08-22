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
from datetime import datetime, timedelta, timezone
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

# ---------------------------------------------------------------------------
# Per-gate source verdicts.
#
# The matrix above is built around the workflows gate.  Its source verdict is
# the most intricate one, but it is not the only one: stage_a, t023 and t033
# each recheck their producer's own report before it may back a receipt, and
# nothing exercised those rules.  A sweep that disables each rule in turn found
# them unguarded, and four were reachable -- a stage_a report recording a FAILED
# candidate, and both production_activation checks, were accepted once their
# rule was removed.  The loop below runs the same shape as above against every
# gate that has a source, so a removed rule fells the suite rather than passing
# unnoticed.
# ---------------------------------------------------------------------------

GATE_FIXTURES = {
    "stage_a": {
        "source": Path("validation/physical-validation-candidate-final-latest.json"),
        "receipt": Path("validation/proof-gates/stage-a-latest.json"),
        "report": lambda sha, now: {
            "schema": "kaliv-physical-validation-candidate-final/v1",
            "gate": {"passed": True, "production_activation": False},
            "candidate": {"git_sha": sha},
        },
        "cases": [
            ("stage_a schema", ("schema",), "forged-final/v0",
             "Stage A final report schema mismatch"),
            ("stage_a verdict", ("gate", "passed"), False,
             "Stage A final report is not PASS"),
            ("stage_a activation", ("gate", "production_activation"), True,
             "Stage A final report moved production activation"),
            ("stage_a candidate sha", ("candidate", "git_sha"), "0" * 40,
             "source candidate mismatch"),
        ],
    },
    "t023": {
        "source": Path("validation/agent3-termination-ui-physical-latest.json"),
        "receipt": Path("validation/proof-gates/t023-latest.json"),
        "report": lambda sha, now: {
            "schema": "kaliv-agent3-termination-ui-physical/v1",
            "success": True,
            "production_activation": False,
            "candidate": {"git_sha": sha},
        },
        "cases": [
            ("t023 schema", ("schema",), "forged-t023/v0",
             "T-023 report schema mismatch"),
            ("t023 verdict", ("success",), False,
             "T-023 report is not PASS"),
            ("t023 activation", ("production_activation",), True,
             "T-023 report moved production activation"),
            ("t023 candidate sha", ("candidate", "git_sha"), "0" * 40,
             "source candidate mismatch"),
        ],
    },
    "t033": {
        "source": Path("validation/agent3-memory-protected-backup-physical-latest.json"),
        "receipt": Path("validation/proof-gates/t033-latest.json"),
        "report": lambda sha, now: {
            "schema": "kaliv-agent3-memory-protected-backup-physical/v1",
            "success": True,
            "production_activation": False,
            "generated_at": now.isoformat(),
            "candidate": {"git_sha": sha},
        },
        "cases": [
            ("t033 schema", ("schema",), "forged-t033/v0",
             "T-033 report schema mismatch"),
            ("t033 verdict", ("success",), False,
             "T-033 report is not PASS"),
            ("t033 activation", ("production_activation",), True,
             "T-033 report moved production activation"),
            ("t033 freshness missing", ("generated_at",), None,
             "T-033 source generated_at is invalid"),
            ("t033 candidate sha", ("candidate", "git_sha"), "0" * 40,
             "source candidate mismatch"),
        ],
    },
}


def run_gate_matrix(gate: str, fixture: dict) -> None:
    with tempfile.TemporaryDirectory(prefix=f"modelrig-gate-{gate}-") as gate_td:
        repo = Path(gate_td)
        git(repo, "init")
        git(repo, "config", "user.email", "proof-matrix@example.invalid")
        git(repo, "config", "user.name", "Proof Receipt Matrix")
        (repo / "scope.txt").write_text("scope-v1\n", encoding="utf-8")
        git(repo, "add", "--", "scope.txt")
        git(repo, "commit", "-m", "base")
        sha = git(repo, "rev-parse", "HEAD")

        M.ROOT = repo
        M.RECEIPTS = {gate: fixture["receipt"]}
        M.SOURCES = {gate: fixture["source"]}
        M.proof_scope.PROOF_SCOPES[gate] = ("scope.txt",)

        receipt_path = repo / fixture["receipt"]
        source_path = repo / fixture["source"]
        now = datetime.now(timezone.utc)
        planner = "qwen3:14b"
        base_report = fixture["report"](sha, now)

        write_json(source_path, base_report)
        M.record(gate, sha, "test", planner_model=planner, now=now)
        base_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        def validate_gate() -> dict:
            return M.validate(gate, sha, planner_model=planner, now=now)

        accepted = validate_gate()
        check(
            accepted.get("passed") is True and accepted.get("reused") is True,
            f"{gate}: untouched receipt is accepted",
        )

        for name, path, replacement, expected in fixture["cases"]:
            report = copy.deepcopy(base_report)
            nested_set(report, path, replacement)
            raw = write_json(source_path, report)
            # A consistent forgery: whoever can write the receipt on the rig can
            # write the report, so the digest is refreshed.  Leaving it stale
            # would only re-measure the digest check and report every rule below
            # as guarded when it is not.
            receipt = copy.deepcopy(base_receipt)
            receipt["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
            receipt["source"]["bytes"] = len(raw)
            write_json(receipt_path, receipt)
            try:
                validate_gate()
            except M.ReceiptError as exc:
                message = str(exc)
                check(expected in message, f"{name} is rejected by its own rule ({message})")
            except Exception as exc:
                check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
            else:
                check(False, f"{name} forgery was accepted")

        write_json(source_path, base_report)
        write_json(receipt_path, base_receipt)
        restored = validate_gate()
        check(
            restored.get("passed") is True,
            f"{gate}: baseline is still accepted after all mutations",
        )


print("\nper-gate source verdicts:")
for gate_name, gate_fixture in GATE_FIXTURES.items():
    run_gate_matrix(gate_name, gate_fixture)


# ---------------------------------------------------------------------------
# Evidence loading and source binding.
#
# _load_json and the receipt's source block are shared by every gate, so a
# removed rule here weakens all of them at once.  The digest and canonical-path
# checks are not a defence against a forger who can write both files -- the
# per-gate cases above deliberately refresh the digest for exactly that reason.
# They are the layer that catches an accidental mismatch, and nothing measured
# them.
# ---------------------------------------------------------------------------

def run_source_binding_matrix() -> None:
    with tempfile.TemporaryDirectory(prefix="modelrig-source-binding-") as bind_td:
        repo = Path(bind_td)
        git(repo, "init")
        git(repo, "config", "user.email", "proof-matrix@example.invalid")
        git(repo, "config", "user.name", "Proof Receipt Matrix")
        (repo / "scope.txt").write_text("scope-v1\n", encoding="utf-8")
        git(repo, "add", "--", "scope.txt")
        git(repo, "commit", "-m", "base")
        sha = git(repo, "rev-parse", "HEAD")

        gate = "t023"
        source_rel = Path("validation/agent3-termination-ui-physical-latest.json")
        receipt_rel = Path("validation/proof-gates/t023-latest.json")
        M.ROOT = repo
        M.RECEIPTS = {gate: receipt_rel}
        M.SOURCES = {gate: source_rel}
        M.proof_scope.PROOF_SCOPES[gate] = ("scope.txt",)

        source_path = repo / source_rel
        receipt_path = repo / receipt_rel
        planner = "qwen3:14b"
        now = datetime.now(timezone.utc)
        base_report = {
            "schema": "kaliv-agent3-termination-ui-physical/v1",
            "success": True,
            "production_activation": False,
            "candidate": {"git_sha": sha},
        }
        write_json(source_path, base_report)
        M.record(gate, sha, "test", planner_model=planner, now=now)
        base_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        def validate_gate() -> dict:
            return M.validate(gate, sha, planner_model=planner, now=now)

        def restore() -> None:
            if source_path.is_symlink():
                source_path.unlink()
            write_json(source_path, base_report)
            write_json(receipt_path, base_receipt)

        def expect(name: str, expected: str) -> None:
            try:
                validate_gate()
            except M.ReceiptError as exc:
                message = str(exc)
                check(expected in message, f"{name} is rejected by its own rule ({message})")
            except Exception as exc:
                check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
            else:
                check(False, f"{name} forgery was accepted")
            restore()

        # --- receipt source block ------------------------------------------
        for name, mutate, expected in (
            ("source metadata not a dict",
             lambda r: r.__setitem__("source", "validation/x.json"),
             "receipt source metadata is missing"),
            ("source path not a string",
             lambda r: r["source"].__setitem__("path", 17),
             "receipt source path is missing"),
            ("source digest not a sha256",
             lambda r: r["source"].__setitem__("sha256", "not-a-digest"),
             "receipt source digest is invalid"),
            ("source digest stale",
             lambda r: r["source"].__setitem__("sha256", "0" * 64),
             "receipt source digest no longer matches"),
            ("source byte count stale",
             lambda r: r["source"].__setitem__("bytes", 999_999),
             "receipt source byte count no longer matches"),
        ):
            receipt = copy.deepcopy(base_receipt)
            mutate(receipt)
            write_json(receipt_path, receipt)
            expect(name, expected)

        # A receipt naming a real file that is not the canonical gate source.
        decoy = repo / "validation" / "decoy.json"
        raw_decoy = write_json(decoy, base_report)
        receipt = copy.deepcopy(base_receipt)
        receipt["source"]["path"] = "validation/decoy.json"
        receipt["source"]["sha256"] = hashlib.sha256(raw_decoy).hexdigest()
        receipt["source"]["bytes"] = len(raw_decoy)
        write_json(receipt_path, receipt)
        expect("source path is not canonical", "not the canonical gate source")

        # --- evidence loading ----------------------------------------------
        source_path.write_bytes(b"")
        expect("evidence file is empty", "JSON evidence size is invalid")

        write_json(source_path, base_report)
        source_path.write_text(json.dumps([base_report]), encoding="utf-8")
        raw_list = source_path.read_bytes()
        receipt = copy.deepcopy(base_receipt)
        receipt["source"]["sha256"] = hashlib.sha256(raw_list).hexdigest()
        receipt["source"]["bytes"] = len(raw_list)
        write_json(receipt_path, receipt)
        expect("evidence top level is not an object", "JSON evidence is not an object")

        # Symlinked evidence.  Linux-only in CI; skipped rather than failed if
        # the platform refuses, so a Windows runner does not turn this red for
        # a reason that has nothing to do with the rule.
        real = repo / "validation" / "real-report.json"
        raw_real = write_json(real, base_report)
        try:
            source_path.unlink()
            source_path.symlink_to(real)
        except OSError:
            print("  SKIP: symlink cases (platform refused symlink creation)")
            restore()
        else:
            receipt = copy.deepcopy(base_receipt)
            receipt["source"]["sha256"] = hashlib.sha256(raw_real).hexdigest()
            receipt["source"]["bytes"] = len(raw_real)
            write_json(receipt_path, receipt)
            expect("evidence path is a symlink", "path is a symlink")

        restored = validate_gate()
        check(
            restored.get("passed") is True,
            "source binding: baseline is still accepted after all mutations",
        )


print("\nevidence loading and source binding:")
run_source_binding_matrix()


# ---------------------------------------------------------------------------
# Guards and configuration construction.
#
# The rules below sit before any evidence is read: unknown gate names, commit
# existence, and the shape of the measurement configuration a receipt is bound
# to.  They are cheap to state and cheap to remove, which is exactly why they
# need a test that notices.
# ---------------------------------------------------------------------------

def run_guard_matrix() -> None:
    with tempfile.TemporaryDirectory(prefix="modelrig-guards-") as guard_td:
        repo = Path(guard_td)
        git(repo, "init")
        git(repo, "config", "user.email", "proof-matrix@example.invalid")
        git(repo, "config", "user.name", "Proof Receipt Matrix")
        (repo / "scope.txt").write_text("scope-v1\n", encoding="utf-8")
        git(repo, "add", "--", "scope.txt")
        git(repo, "commit", "-m", "base")
        sha = git(repo, "rev-parse", "HEAD")
        absent = "0" * 40

        source_rel = Path("validation/agent3-termination-ui-physical-latest.json")
        receipt_rel = Path("validation/proof-gates/t023-latest.json")
        fr_receipt_rel = Path("validation/proof-gates/forced-recovery-latest.json")
        M.ROOT = repo
        M.RECEIPTS = {"t023": receipt_rel, "forced_recovery": fr_receipt_rel}
        M.SOURCES = {"t023": source_rel, "forced_recovery": None}
        M.proof_scope.PROOF_SCOPES["t023"] = ("scope.txt",)
        M.proof_scope.PROOF_SCOPES["forced_recovery"] = ("scope.txt",)

        planner = "qwen3:14b"
        now = datetime.now(timezone.utc)
        write_json(repo / source_rel, {
            "schema": "kaliv-agent3-termination-ui-physical/v1",
            "success": True,
            "production_activation": False,
            "candidate": {"git_sha": sha},
        })

        def expect(name: str, expected: str, fn) -> None:
            try:
                fn()
            except M.ReceiptError as exc:
                message = str(exc)
                check(expected in message, f"{name} is rejected by its own rule ({message})")
            except Exception as exc:
                check(False, f"{name} raised unexpected {type(exc).__name__}: {exc}")
            else:
                check(False, f"{name} was accepted")

        # --- gate and commit guards ----------------------------------------
        expect("record rejects unknown gate", "unknown gate",
               lambda: M.record("not_a_gate", sha, "test", planner_model=planner, now=now))
        expect("record rejects absent commit", "not a local Git commit",
               lambda: M.record("t023", absent, "test", planner_model=planner, now=now))
        expect("validate rejects unknown gate", "unknown gate",
               lambda: M.validate("not_a_gate", sha, planner_model=planner, now=now))
        expect("validate rejects absent head", "not a local Git commit",
               lambda: M.validate("t023", absent, planner_model=planner, now=now))

        # A receipt whose taken_on_sha no longer resolves locally.
        M.record("t023", sha, "test", planner_model=planner, now=now)
        good = json.loads((repo / receipt_rel).read_text(encoding="utf-8"))
        broken = copy.deepcopy(good)
        broken["taken_on_sha"] = absent
        write_json(repo / receipt_rel, broken)
        expect("receipt taken_on_sha must resolve", "taken_on_sha is invalid or unavailable",
               lambda: M.validate("t023", sha, planner_model=planner, now=now))
        write_json(repo / receipt_rel, good)

        # --- source-less gate ----------------------------------------------
        M.record("forced_recovery", sha, "test", planner_model=planner, now=now)
        fr = json.loads((repo / fr_receipt_rel).read_text(encoding="utf-8"))
        check(fr.get("source") is None, "forced_recovery receipt names no source")
        fr_forged = copy.deepcopy(fr)
        fr_forged["source"] = {"path": "validation/x.json", "sha256": "0" * 64, "bytes": 1}
        write_json(repo / fr_receipt_rel, fr_forged)
        expect("source-less gate may not name a source", "unexpectedly names a source",
               lambda: M.validate("forced_recovery", sha, planner_model=planner, now=now))

        # --- missing evidence file ------------------------------------------
        (repo / source_rel).unlink()
        expect("evidence file must exist", "missing or irregular",
               lambda: M.validate("t023", sha, planner_model=planner, now=now))

        # --- configuration construction --------------------------------------
        for name, expected, kwargs in (
            ("stage_a requires planner", "Stage A receipt requires planner_model",
             dict(gate="stage_a", planner_model="  ")),
            ("workflows requires planner", "workflow receipt requires planner_model",
             dict(gate="workflows", planner_model="")),
            ("workflows requires positive rounds", "requires positive workflow_rounds",
             dict(gate="workflows", planner_model=planner, workflow_rounds=0,
                  workflow_threshold=0.95)),
            ("workflows rejects bool rounds", "requires positive workflow_rounds",
             dict(gate="workflows", planner_model=planner, workflow_rounds=True,
                  workflow_threshold=0.95)),
            ("workflows requires threshold", "requires workflow_threshold",
             dict(gate="workflows", planner_model=planner, workflow_rounds=1,
                  workflow_threshold=None)),
            ("workflows threshold in range", "must be between 0 and 1",
             dict(gate="workflows", planner_model=planner, workflow_rounds=1,
                  workflow_threshold=1.5)),
        ):
            gate_name = kwargs.pop("gate")
            kwargs.setdefault("workflow_rounds", None)
            kwargs.setdefault("workflow_threshold", None)
            expect(name, expected,
                   lambda g=gate_name, k=kwargs: M._configuration(g, **k))

        # --- workflow report type checks -------------------------------------
        # Reached through _source_verdict, so they need a workflows fixture.
        wf_source = Path("validation/workflow-proof-latest.json")
        wf_receipt = Path("validation/proof-gates/workflows-latest.json")
        M.RECEIPTS["workflows"] = wf_receipt
        M.SOURCES["workflows"] = wf_source
        M.proof_scope.PROOF_SCOPES["workflows"] = ("scope.txt",)
        wf_rounds, wf_per_round, wf_threshold = 1, 3, 0.95
        wf_base = {
            "schema": "modelrig-workflow-proof/v1",
            "sha": sha,
            "planner_model": planner,
            "requested_rounds": wf_rounds,
            "rounds": wf_rounds,
            "workflows_per_round": wf_per_round,
            "expected_executions": wf_rounds * wf_per_round,
            "executions": wf_rounds * wf_per_round,
            "mean_completion_rate": 0.97,
            "threshold": wf_threshold,
            "runner_failures": 0,
            "passed": True,
        }
        write_json(repo / wf_source, wf_base)
        M.record("workflows", sha, "test", planner_model=planner,
                 workflow_rounds=wf_rounds, workflow_threshold=wf_threshold, now=now)
        wf_receipt_doc = json.loads((repo / wf_receipt).read_text(encoding="utf-8"))

        for name, path, replacement, expected in (
            ("workflow executions must be an int", ("executions",), "3",
             "workflow execution count is invalid"),
            ("workflow executions rejects bool", ("executions",), True,
             "workflow execution count is invalid"),
            ("workflow mean must be numeric", ("mean_completion_rate",), "0.97",
             "workflow aggregate mean/threshold is invalid"),
            ("workflow planner must be a non-empty string", ("planner_model",), "   ",
             "workflow aggregate planner_model is missing"),
        ):
            report = copy.deepcopy(wf_base)
            nested_set(report, path, replacement)
            raw = write_json(repo / wf_source, report)
            doc = copy.deepcopy(wf_receipt_doc)
            doc["source"]["sha256"] = hashlib.sha256(raw).hexdigest()
            doc["source"]["bytes"] = len(raw)
            write_json(repo / wf_receipt, doc)
            expect(name, expected,
                   lambda: M.validate("workflows", sha, planner_model=planner,
                                      workflow_rounds=wf_rounds,
                                      workflow_threshold=wf_threshold, now=now))

        # T-033 evidence dated in the future is a clock fault, not freshness.
        t33_source = Path("validation/agent3-memory-protected-backup-physical-latest.json")
        t33_receipt = Path("validation/proof-gates/t033-latest.json")
        M.RECEIPTS["t033"] = t33_receipt
        M.SOURCES["t033"] = t33_source
        M.proof_scope.PROOF_SCOPES["t033"] = ("scope.txt",)
        t33_base = {
            "schema": "kaliv-agent3-memory-protected-backup-physical/v1",
            "success": True,
            "production_activation": False,
            "generated_at": now.isoformat(),
            "candidate": {"git_sha": sha},
        }
        write_json(repo / t33_source, t33_base)
        M.record("t033", sha, "test", planner_model=planner, now=now)
        t33_doc = json.loads((repo / t33_receipt).read_text(encoding="utf-8"))
        future = copy.deepcopy(t33_base)
        future["generated_at"] = (now + timedelta(hours=6)).isoformat()
        raw_future = write_json(repo / t33_source, future)
        doc = copy.deepcopy(t33_doc)
        doc["source"]["sha256"] = hashlib.sha256(raw_future).hexdigest()
        doc["source"]["bytes"] = len(raw_future)
        doc["source"]["generated_at"] = future["generated_at"]
        write_json(repo / t33_receipt, doc)
        expect("T-033 evidence may not be dated in the future",
               "generated_at is in the future",
               lambda: M.validate("t033", sha, planner_model=planner, now=now))


print("\nguards and configuration:")
run_guard_matrix()

print(f"\n===== PROOF RECEIPT RULE MATRIX: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

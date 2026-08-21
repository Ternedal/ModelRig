#!/usr/bin/env python3
"""Regression contracts for run-proof-campaign skip/reuse semantics.

The verdict test extracts the real PowerShell function from the production
script. It deliberately does not restate the final conjunction in Python.
Receipt tests run the real proof_campaign_gate_receipt module against a small
throw-away Git repository so changed scope and stale evidence are behavioural
failures, not source-text assertions.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run-proof-campaign.ps1"
RECEIPT_MODULE = ROOT / "scripts" / "proof_campaign_gate_receipt.py"

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
    )


def git(root: Path, *args: str) -> str:
    result = run("git", *args, cwd=root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout)
    return result.stdout.strip()


def commit(root: Path, message: str) -> str:
    git(root, "add", "--", "scope.txt", "other.txt")
    git(root, "commit", "-m", message)
    return git(root, "rev-parse", "HEAD")


def load_receipt_module():
    scripts = str(ROOT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    spec = importlib.util.spec_from_file_location("proof_campaign_gate_receipt_test", RECEIPT_MODULE)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load proof_campaign_gate_receipt.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def powershell_engines() -> list[str]:
    engines: list[str] = []
    for name in ("pwsh", "powershell", "powershell.exe"):
        path = shutil.which(name)
        if path and path not in engines:
            engines.append(path)
    return engines


def run_verdict_matrix(shell: str, function_text: str) -> tuple[subprocess.CompletedProcess[str], dict[int, int]]:
    cases = []
    for mask in range(32):
        values = ["$false" if (mask & (1 << bit)) else "$true" for bit in range(5)]
        # Parentheses are mandatory in PowerShell argument mode. Without them,
        # [ordered]@ is parsed as a string token and the hashtable body as a
        # separate scriptblock, so the function never receives five gate maps.
        gates = [f"([ordered]@{{passed={value}}})" for value in values]
        cases.append(
            f"$r = Get-ProofCampaignPassed {gates[0]} {gates[1]} {gates[2]} {gates[3]} {gates[4]}; "
            f"Write-Output ('{mask}:' + ([int][bool]$r))"
        )
    probe = function_text + "\n" + "\n".join(cases)
    result = run(shell, "-NoProfile", "-Command", probe)
    observed: dict[int, int] = {}
    for line in result.stdout.splitlines():
        if re.fullmatch(r"\d+:[01]", line.strip()):
            left, right = line.strip().split(":", 1)
            observed[int(left)] = int(right)
    return result, observed


source = SCRIPT.read_text(encoding="utf-8")

print("source-level fail-closed markers:")
for unsafe in (
    "$workflowPass = $true",
    "$t23pass=$true",
    "$t33pass=$true",
    "stage_a=$true",
    "forced_recovery=$true",
):
    check(unsafe not in source, f"optimistic legacy default is absent: {unsafe}")

check("schema='modelrig-proof-day/v2'" in source, "summary schema was bumped for structured gate records")
check("[string]$Agent4LanAddress = \"\"" in source, "Agent4LanAddress is a real operator parameter")
check("$a4lan = $null" in source, "Agent4 LAN summary variable is defined even when Agent4 is excluded")
for gate in ("stage_a", "forced_recovery", "workflows", "t023", "t033"):
    check(f"Try-ReuseGate '{gate}'" in source, f"{gate} skip path must validate a receipt")
check(
    "passed = $false" in source[source.index("function New-ProofGate"):source.index("# BEGIN PROOF VERDICT FUNCTION")],
    "new gates start red",
)

print("\nactual PowerShell verdict over all 32 skip subsets:")
match = re.search(
    r"# BEGIN PROOF VERDICT FUNCTION\s*(function Get-ProofCampaignPassed[\s\S]*?)\s*# END PROOF VERDICT FUNCTION",
    source,
)
check(match is not None, "production verdict function can be extracted")
if match is not None:
    engines = powershell_engines()
    check(bool(engines), "PowerShell is available for verdict execution")
    function_text = match.group(1)
    for shell in engines:
        label = Path(shell).name
        result, observed = run_verdict_matrix(shell, function_text)
        check(result.returncode == 0, f"extracted production verdict executes under {label}")
        check(len(observed) == 32, f"{label} produced all 32 verdict observations")
        check(observed.get(0) == 1, f"all five proven gates produce PASS under {label}")
        check(
            all(observed.get(mask) == 0 for mask in range(1, 32)),
            f"every non-empty skip subset remains non-green under {label}",
        )

        # Harness self-test: the maximally broken verdict must be visible as all
        # ones. The old malformed argument syntax produced all-zero/null output
        # here, which could make the negative-subset assertion pass by accident.
        mutant = re.sub(
            r"return \[bool\]\([\s\S]*?\)\s*\n\}",
            "return $true\n}",
            function_text,
            count=1,
        )
        mutant_result, mutant_observed = run_verdict_matrix(shell, mutant)
        check(mutant != function_text, f"always-true control mutation was applied under {label}")
        check(mutant_result.returncode == 0, f"always-true control mutation executes under {label}")
        check(
            len(mutant_observed) == 32 and all(mutant_observed.get(mask) == 1 for mask in range(32)),
            f"verdict harness exposes an always-true mutation under {label}",
        )

print("\nreceipt behaviour against real Git history:")
M = load_receipt_module()
with tempfile.TemporaryDirectory(prefix="modelrig-proof-receipt-test-") as td:
    repo = Path(td)
    git(repo, "init")
    git(repo, "config", "user.email", "proof-test@example.invalid")
    git(repo, "config", "user.name", "Proof Test")
    (repo / "scope.txt").write_text("scope-v1\n", encoding="utf-8")
    (repo / "other.txt").write_text("other-v1\n", encoding="utf-8")
    sha1 = commit(repo, "base")

    M.ROOT = repo
    M.RECEIPTS = {
        "stage_a": Path("validation/proof-gates/stage-a-latest.json"),
        "forced_recovery": Path("validation/proof-gates/forced-recovery-latest.json"),
        "workflows": Path("validation/proof-gates/workflows-latest.json"),
        "t023": Path("validation/proof-gates/t023-latest.json"),
        "t033": Path("validation/proof-gates/t033-latest.json"),
    }
    M.SOURCES = {
        "stage_a": None,
        "forced_recovery": None,
        "workflows": Path("validation/workflow-proof-latest.json"),
        "t023": None,
        "t033": Path("validation/agent3-memory-protected-backup-physical-latest.json"),
    }
    M.proof_scope.PROOF_SCOPES["forced_recovery"] = ("scope.txt",)
    M.proof_scope.PROOF_SCOPES["workflows"] = ("scope.txt",)
    M.proof_scope.PROOF_SCOPES["t033"] = ("scope.txt",)

    M.record("forced_recovery", sha1, "test")
    first = M.validate("forced_recovery", sha1)
    check(first["passed"] is True and first["reused"] is True, "exact-SHA receipt is reusable")

    (repo / "other.txt").write_text("other-v2\n", encoding="utf-8")
    sha2 = commit(repo, "out of scope")
    second = M.validate("forced_recovery", sha2)
    check(second["passed"] is True, "out-of-scope commit may carry the receipt")

    (repo / "scope.txt").write_text("scope-v2\n", encoding="utf-8")
    sha3 = commit(repo, "in scope")
    try:
        M.validate("forced_recovery", sha3)
    except M.ReceiptError:
        changed_scope_blocked = True
    else:
        changed_scope_blocked = False
    check(changed_scope_blocked, "in-scope code change invalidates reuse")

    receipt_path = repo / M.RECEIPTS["forced_recovery"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["taken_on_sha"] = "0" * 40
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    try:
        M.validate("forced_recovery", sha3)
    except M.ReceiptError:
        wrong_sha_blocked = True
    else:
        wrong_sha_blocked = False
    check(wrong_sha_blocked, "missing/different taken_on_sha fails closed")

    workflow_path = repo / M.SOURCES["workflows"]
    workflow_path.parent.mkdir(parents=True, exist_ok=True)
    workflow_path.write_text(
        json.dumps(
            {
                "schema": "modelrig-workflow-proof/v1",
                "sha": sha3,
                "planner_model": "qwen3:14b",
                "rounds": 22,
                "executions": 308,
                "mean_completion_rate": 0.97,
                "threshold": 0.95,
                "runner_failures": 0,
                "passed": True,
            }
        ),
        encoding="utf-8",
    )
    M.record(
        "workflows",
        sha3,
        "test",
        planner_model="qwen3:14b",
        workflow_rounds=22,
        workflow_threshold=0.95,
    )
    same_config = M.validate(
        "workflows",
        sha3,
        planner_model="qwen3:14b",
        workflow_rounds=22,
        workflow_threshold=0.95,
    )
    check(same_config["passed"] is True, "same workflow measurement configuration can be reused")
    try:
        M.validate(
            "workflows",
            sha3,
            planner_model="qwen3:14b",
            workflow_rounds=22,
            workflow_threshold=0.98,
        )
    except M.ReceiptError:
        stricter_config_blocked = True
    else:
        stricter_config_blocked = False
    check(stricter_config_blocked, "easier workflow receipt cannot satisfy a stricter threshold")

    t033_path = repo / M.SOURCES["t033"]
    old = datetime.now(timezone.utc) - timedelta(hours=25)
    t033_path.write_text(
        json.dumps(
            {
                "schema": "kaliv-agent3-memory-protected-backup-physical/v1",
                "generated_at": old.isoformat().replace("+00:00", "Z"),
                "success": True,
                "candidate": {"git_sha": sha3},
                "errors": [],
                "production_activation": False,
            }
        ),
        encoding="utf-8",
    )
    try:
        M.record("t033", sha3, "test")
    except M.ReceiptError:
        stale_t033_blocked = True
    else:
        stale_t033_blocked = False
    check(stale_t033_blocked, "stale T-033 source cannot be rejuvenated by a new receipt")

print(f"\n===== PROOF CAMPAIGN FAIL-CLOSED: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

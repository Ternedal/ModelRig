"""Stage-B isolated-process driver for ADR-DC-034 through ADR-DC-066.

The exact-task contracts in this range are independent adversarial qualifications:
each owns its own fixture/cleanup and imports earlier contracts only for helpers. Run
them in isolated Python processes so the locked Stage-B chain does not serialize the
entire publication/lifecycle path before ADR-DC-067. Contract assertions and source
boundaries remain unchanged.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
_PER_CONTRACT_TIMEOUT_SECONDS = 1800
_MAX_PARALLEL_CONTRACTS = 4

_CONTRACT_FILES = (
    "rsi_pilot_exact_task_execution_plan_requirements_contract.py",
    "rsi_pilot_exact_task_development_task_binding_contract.py",
    "rsi_pilot_exact_task_development_task_binding_live_provenance_contract.py",
    "rsi_pilot_exact_task_executor_capability_live_guard_contract.py",
    "rsi_pilot_exact_task_executor_secret_custody_contract.py",
    "rsi_pilot_exact_task_executor_capability_semantics_contract.py",
    "rsi_pilot_exact_task_execution_plan_contract.py",
    "rsi_pilot_exact_task_prelaunch_reservation_contract.py",
    "rsi_pilot_exact_task_execution_transaction_contract.py",
    "rsi_pilot_exact_task_post_execution_evaluation_contract.py",
    "rsi_pilot_exact_task_local_commit_plan_contract.py",
    "rsi_pilot_exact_task_local_commit_object_identity_contract.py",
    "rsi_pilot_exact_task_local_commit_write_authorization_contract.py",
    "rsi_pilot_exact_task_local_commit_transaction_contract.py",
    "rsi_pilot_exact_task_post_commit_integration_evaluation_contract.py",
    "rsi_pilot_exact_task_integration_readiness_contract.py",
    "rsi_pilot_exact_task_remote_publication_plan_contract.py",
    "rsi_pilot_exact_task_remote_state_observation_contract.py",
    "rsi_pilot_exact_task_remote_publication_authorization_contract.py",
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py",
    "rsi_pilot_exact_task_remote_publication_recovery_contract.py",
    "rsi_pilot_exact_task_post_publication_attestation_contract.py",
    "rsi_pilot_exact_task_pr_lifecycle_authorization_contract.py",
    "rsi_pilot_exact_task_pr_lifecycle_transaction_contract.py",
    "rsi_pilot_exact_task_pr_lifecycle_recovery_contract.py",
    "rsi_pilot_exact_task_post_lifecycle_attestation_contract.py",
    "rsi_pilot_exact_task_review_state_attestation_contract.py",
    "rsi_pilot_exact_task_merge_readiness_evaluation_contract.py",
    "rsi_pilot_exact_task_merge_authorization_contract.py",
    "rsi_pilot_exact_task_merge_transaction_contract.py",
    "rsi_pilot_exact_task_merge_recovery_contract.py",
    "rsi_pilot_exact_task_post_merge_attestation_contract.py",
    "rsi_pilot_exact_task_release_readiness_evaluation_contract.py",
    "rsi_pilot_exact_task_release_plan_contract.py",
    "rsi_pilot_exact_task_release_state_observation_contract.py",
    "rsi_pilot_exact_task_release_authorization_contract.py",
)


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_contract_file(filename: str) -> tuple[str, int, float, str]:
    path = SUPPORT / filename
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    try:
        completed = subprocess.run(
            [sys.executable, "-u", str(path)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=_PER_CONTRACT_TIMEOUT_SECONDS,
            check=False,
        )
        return (
            filename,
            completed.returncode,
            time.monotonic() - started,
            completed.stdout or "",
        )
    except subprocess.TimeoutExpired as exc:
        return (
            filename,
            124,
            time.monotonic() - started,
            _decode_timeout_output(exc.stdout),
        )


def run_contract() -> None:
    worker_count = min(
        _MAX_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(_CONTRACT_FILES),
    )
    print(
        f"Stage-B exact-task midchain: {len(_CONTRACT_FILES)} contracts, "
        f"{worker_count} isolated workers, "
        f"{_PER_CONTRACT_TIMEOUT_SECONDS}s per-contract bound",
        flush=True,
    )

    results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_run_contract_file, filename): filename
            for filename in _CONTRACT_FILES
        }
        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)
            if returncode != 0 and output:
                # Surface the real child traceback immediately. Previously it
                # was buffered until every worker completed, so the 6600s
                # parent timeout could kill the bridge before the actionable
                # failure was ever printed.
                print(
                    f"--- {filename} failure output ---\n{output[-12000:]}\n"
                    f"--- end {filename} failure output ---",
                    flush=True,
                )

    failures = []
    for filename in _CONTRACT_FILES:
        returncode, elapsed, output = results[filename]
        if returncode == 0:
            continue
        failures.append(
            f"{filename}: exit {returncode} after {elapsed:.1f}s\n{output[-12000:]}"
        )

    if failures:
        raise AssertionError(
            "Stage-B exact-task midchain qualification failed:\n\n"
            + "\n\n".join(failures)
        )


if __name__ == "__main__":
    run_contract()

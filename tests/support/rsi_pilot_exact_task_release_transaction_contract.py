"""Locked Stage-B wrapper for ADR-DC-067 through ADR-DC-098 product-pilot pre-start qualification.

The contracts are independent adversarial qualifications: each creates and cleans
up its own fixture. Run them in isolated Python processes so the exact-head gate
does not serialize the increasingly deep fixture chain. This changes orchestration
only; every contract still executes in full and retains its own assertions.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rsi_pilot_exact_task_release_transaction_contract_base import (
    _ledger,
    _live_authority,
)

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
_PER_CONTRACT_TIMEOUT_SECONDS = 1800
# Deep downstream contracts rebuild increasingly nested provenance; four concurrent
# copies oversubscribe hosted runners and magnify per-contract wall time. Match the
# empirically stable midchain fan-out.
_MAX_PARALLEL_CONTRACTS = 2

_CONTRACT_FILES = (
    "rsi_pilot_exact_task_release_transaction_contract_base.py",
    "rsi_pilot_exact_task_release_recovery_contract.py",
    "rsi_pilot_exact_task_post_release_attestation_contract.py",
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py",
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py",
    "rsi_pilot_exact_task_staging_deployment_transaction_contract.py",
    "rsi_pilot_exact_task_staging_deployment_recovery_contract.py",
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_recovery_contract.py",
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py",
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py",
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py",
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py",
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py",
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py",
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py",
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py",
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py",
    "rsi_pilot_exact_task_production_activation_readiness_contract.py",
    "rsi_pilot_exact_task_production_activation_authorization_contract.py",
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py",
    "rsi_pilot_exact_task_production_activation_recovery_contract.py",
    "rsi_pilot_exact_task_post_production_activation_attestation_contract.py",
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py",
    "rsi_pilot_exact_task_product_pilot_start_readiness_contract.py",
    "rsi_pilot_exact_task_product_pilot_start_authorization_contract.py",
    "rsi_pilot_exact_task_product_pilot_lineage_attestation_contract.py",
)

_CONTRACT_SHARD_ENV = "MODELRIG_STAGE_B_CONTRACT_SHARD"
_REQUIRED_SHARD_COUNT = 3


def _selected_contract_files() -> tuple[str, ...]:
    raw = os.environ.get(_CONTRACT_SHARD_ENV, "").strip()
    if not raw:
        return _CONTRACT_FILES
    try:
        index_text, total_text = raw.split("/", 1)
        index = int(index_text)
        total = int(total_text)
    except (ValueError, TypeError) as exc:
        raise AssertionError(
            f"invalid Stage-B contract shard {raw!r}; expected 1/3, 2/3, or 3/3"
        ) from exc
    if total != _REQUIRED_SHARD_COUNT or not 1 <= index <= total:
        raise AssertionError(
            f"invalid Stage-B contract shard {raw!r}; expected 1/3, 2/3, or 3/3"
        )
    selected = _CONTRACT_FILES[index - 1 :: total]
    if not selected:
        raise AssertionError(f"Stage-B contract shard {raw!r} selected no contracts")
    return selected



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
        output = completed.stdout or ""
        return filename, completed.returncode, time.monotonic() - started, output
    except subprocess.TimeoutExpired as exc:
        output = _decode_timeout_output(exc.stdout)
        return filename, 124, time.monotonic() - started, output


def run_contract() -> None:
    contract_files = _selected_contract_files()
    shard = os.environ.get(_CONTRACT_SHARD_ENV, "").strip() or "all"
    worker_count = min(
        _MAX_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(contract_files),
    )
    print(
        f"Stage-B exact-task contracts: {len(_CONTRACT_FILES)} contracts, "
        f"{worker_count} isolated workers, "
        f"{_PER_CONTRACT_TIMEOUT_SECONDS}s per-contract bound",
        flush=True,
    )

    results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(_run_contract_file, filename): filename
            for filename in contract_files
        }
        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)

    failures = []
    for filename in contract_files:
        returncode, elapsed, output = results[filename]
        if returncode == 0:
            continue
        suffix = output[-12000:]
        failures.append(
            f"{filename}: exit {returncode} after {elapsed:.1f}s\n{suffix}"
        )

    if failures:
        raise AssertionError(
            "Stage-B exact-task contract qualification failed:\n\n"
            + "\n\n".join(failures)
        )


if __name__ == "__main__":
    run_contract()

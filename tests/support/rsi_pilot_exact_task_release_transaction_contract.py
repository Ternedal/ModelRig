"""Locked Stage-B wrapper through authoritative DC-L16 product-pilot pre-start qualification.

Most contracts are independent adversarial qualifications and run in isolated
Python processes. The product-pilot tail is the deliberate exception: its
ADR-098/099/100, readiness-v2 and ADR-097 contracts share one immutable deep
fixture inside a dedicated driver while each canonical contract still executes
in full. This changes orchestration only, not authority semantics.
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
_PER_CONTRACT_TIMEOUT_SECONDS = 2400
_TARGETED_DEEP_TIMEOUT_SECONDS = 3600
_TARGETED_DEEP_TIMEOUT_CONTRACTS = frozenset(
    {
        "rsi_pilot_exact_task_release_recovery_stage_b_driver.py",
        "rsi_pilot_exact_task_post_release_attestation_contract.py",
        "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py",
        "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py",
        "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py",
        "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py",
        "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py",
        "rsi_pilot_exact_task_staging_success_status_recovery_contract.py",
        "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py",
        "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py",
    }
)
# Deep downstream contracts rebuild increasingly nested provenance; four concurrent
# copies oversubscribe hosted runners and magnify per-contract wall time. Match the
# empirically stable midchain fan-out.
_MAX_PARALLEL_CONTRACTS = 2
_MAX_SHARDED_PARALLEL_CONTRACTS = 2

_CONTRACT_FILES = (
    "rsi_pilot_exact_task_release_transaction_contract_base.py",
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py",
    "rsi_pilot_exact_task_post_release_attestation_contract.py",
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py",
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py",
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py",
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py",
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py",
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py",
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
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py",
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py",
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py",
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py",
)

_CONTRACT_SHARD_ENV = "MODELRIG_STAGE_B_CONTRACT_SHARD"
_REQUIRED_SHARD_COUNT = 4

# Measured wall seconds per contract (#1682): exact-head run 44609234933 on main
# `ef0473d`, 20/11/2026, two contracts in flight per hosted shard. Equal file
# counts were not equal work -- the strided partition gave 158 / 81 / 116 min of
# shard wall time, because the late contracts rebuild deeper provenance. These
# costs decide membership (longest first onto the least-loaded shard). With four
# hosted shards (the chain's critical path was downstream, so one more runner
# buys ~30 min of wall time) they carry ~167 / 176 / 176 / 172 CPU-minutes,
# i.e. under 90 min of wall each with two in flight. Refresh from the
# "PASS: <file> (<s>s)" lines of a green run when it drifts; the coverage gate
# refuses a table that does not name exactly the contracts above, and a
# partition more than 15 % apart.
_CONTRACT_COST_SECONDS = {
    "rsi_pilot_exact_task_release_transaction_contract_base.py": 1183,
    "rsi_pilot_exact_task_release_recovery_stage_b_driver.py": 610,
    "rsi_pilot_exact_task_post_release_attestation_contract.py": 2496,
    "rsi_pilot_exact_task_deploy_readiness_evaluation_contract.py": 1187,
    "rsi_pilot_exact_task_staging_deployment_plan_contract.py": 1029,
    "rsi_pilot_exact_task_staging_deployment_state_observation_contract.py": 818,
    "rsi_pilot_exact_task_staging_deployment_authorization_contract.py": 1150,
    "rsi_pilot_exact_task_staging_deployment_transaction_stage_b_driver.py": 603,
    "rsi_pilot_exact_task_staging_deployment_recovery_stage_b_driver.py": 790,
    "rsi_pilot_exact_task_post_staging_deployment_attestation_contract.py": 2685,
    "rsi_pilot_exact_task_staging_deployment_status_plan_contract.py": 1020,
    "rsi_pilot_exact_task_staging_deployment_status_state_observation_contract.py": 1342,
    "rsi_pilot_exact_task_staging_deployment_status_authorization_contract.py": 1892,
    "rsi_pilot_exact_task_staging_deployment_status_transaction_contract.py": 1020,
    "rsi_pilot_exact_task_staging_deployment_status_recovery_stage_b_driver.py": 1343,
    "rsi_pilot_exact_task_post_staging_deployment_status_attestation_contract.py": 2630,
    "rsi_pilot_exact_task_staging_runtime_verification_contract.py": 1013,
    "rsi_pilot_exact_task_staging_runtime_build_identity_contract.py": 1335,
    "rsi_pilot_exact_task_staging_success_status_plan_contract.py": 1847,
    "rsi_pilot_exact_task_staging_success_status_state_observation_contract.py": 1008,
    "rsi_pilot_exact_task_staging_success_status_authorization_contract.py": 1343,
    "rsi_pilot_exact_task_staging_success_status_transaction_contract.py": 1875,
    "rsi_pilot_exact_task_staging_success_status_recovery_contract.py": 1434,
    "rsi_pilot_exact_task_post_staging_success_status_attestation_contract.py": 1348,
    "rsi_pilot_exact_task_production_activation_readiness_contract.py": 1854,
    "rsi_pilot_exact_task_production_activation_authorization_contract.py": 1030,
    "rsi_pilot_exact_task_production_activation_transaction_stage_b_driver.py": 1347,
    "rsi_pilot_exact_task_production_activation_recovery_stage_b_driver.py": 1097,
    "rsi_pilot_exact_task_post_production_activation_attestation_stage_b_driver.py": 593,
    "rsi_pilot_exact_task_product_pilot_start_requirements_contract.py": 1338,
    "rsi_pilot_exact_task_product_pilot_tail_stage_b_driver.py": 1092,
}


def _shard_assignment(total: int = _REQUIRED_SHARD_COUNT) -> dict[int, tuple[str, ...]]:
    """Deterministic cost-weighted partition: every contract in exactly one shard.

    Longest-processing-time-first onto the least-loaded shard; ties broken by
    file name, then lowest shard index. Within a shard the original
    _CONTRACT_FILES order is kept, so the deep-provenance contracts still start
    after the shallow ones they build on.
    """
    missing = set(_CONTRACT_FILES) - set(_CONTRACT_COST_SECONDS)
    extra = set(_CONTRACT_COST_SECONDS) - set(_CONTRACT_FILES)
    if missing or extra:
        raise AssertionError(
            f"Stage-B contract cost table drifted: missing={sorted(missing)} extra={sorted(extra)}"
        )
    load = {index: 0 for index in range(1, total + 1)}
    members: dict[int, set[str]] = {index: set() for index in range(1, total + 1)}
    for filename in sorted(_CONTRACT_FILES, key=lambda f: (-_CONTRACT_COST_SECONDS[f], f)):
        target = min(load, key=lambda index: (load[index], index))
        members[target].add(filename)
        load[target] += _CONTRACT_COST_SECONDS[filename]
    return {
        index: tuple(f for f in _CONTRACT_FILES if f in members[index])
        for index in range(1, total + 1)
    }


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
            f"invalid Stage-B contract shard {raw!r}; expected 1/4 … 4/4"
        ) from exc
    if total != _REQUIRED_SHARD_COUNT or not 1 <= index <= total:
        raise AssertionError(
            f"invalid Stage-B contract shard {raw!r}; expected 1/4 … 4/4"
        )
    selected = _shard_assignment(total)[index]
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
    timeout_seconds = (
        _TARGETED_DEEP_TIMEOUT_SECONDS
        if filename in _TARGETED_DEEP_TIMEOUT_CONTRACTS
        else _PER_CONTRACT_TIMEOUT_SECONDS
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-u", str(path)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout_seconds,
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
    parallel_limit = (
        _MAX_SHARDED_PARALLEL_CONTRACTS
        if shard != "all"
        else _MAX_PARALLEL_CONTRACTS
    )
    worker_count = min(
        parallel_limit,
        max(1, os.cpu_count() or 1),
        len(contract_files),
    )
    print(
        f"Stage-B exact-task contracts: {len(_CONTRACT_FILES)} contracts, "
        f"{worker_count} isolated workers, "
        f"{_PER_CONTRACT_TIMEOUT_SECONDS}s default per-contract bound, "
        f"{_TARGETED_DEEP_TIMEOUT_SECONDS}s targeted deep-contract bound",
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

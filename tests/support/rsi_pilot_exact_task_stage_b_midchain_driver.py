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
_DEEP_SHARD_TIMEOUT_SECONDS = 2400
_TARGETED_DEEP_TIMEOUT_SECONDS = 3600
_TARGETED_DEEP_TIMEOUT_CONTRACTS = frozenset(
    {"rsi_pilot_exact_task_post_merge_attestation_contract.py"}
)
# These contracts are CPU-heavy nested provenance qualifications. Two workers are
# useful for the ordinary shards, but shard 2/3 contains the publication/merge
# tail where each contract recursively rebuilds most of ADR-034+. Running two of
# those tails together oversubscribes the hosted runner and turns otherwise-valid
# contracts into exact 1800s timeout failures. Keep process isolation, but run
# that specific deep shard serially. The outer Stage-B job still runs the three
# shards in parallel.
_MAX_PARALLEL_CONTRACTS = 2

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

_CONTRACT_SHARD_ENV = "MODELRIG_STAGE_B_CONTRACT_SHARD"
_REQUIRED_SHARD_COUNT = 3

# Measured wall seconds per contract (#1682): exact-head run 44609234933 on main
# `ef0473d`, 20/11/2026 -- shards 1/3 and 3/3 with two contracts in flight, the
# deep cohorts 2a/2b serial. Strided membership gave 39 / 111 / 52 / 59 min of
# wall time. Membership is now decided by cost *within the same parallelism
# class*: the deep set (what used to be the strided second third) stays the deep
# set and stays serial with its deep timeouts, split 2a/2b by cost (~81 / 82
# min); the remaining contracts are split 1/3 vs 3/3 by cost (~47 / 46 min
# wall). Nothing moves between the serial and the parallel class. Refresh from
# the "PASS: <file> (<s>s)" lines of a green run; the coverage gate refuses a
# table that does not name exactly the contracts, and cohorts more than 15 %
# apart.
_CONTRACT_COST_SECONDS = {
    "rsi_pilot_exact_task_execution_plan_requirements_contract.py": 154,
    "rsi_pilot_exact_task_development_task_binding_contract.py": 321,
    "rsi_pilot_exact_task_development_task_binding_live_provenance_contract.py": 224,
    "rsi_pilot_exact_task_executor_capability_live_guard_contract.py": 154,
    "rsi_pilot_exact_task_executor_secret_custody_contract.py": 1,
    "rsi_pilot_exact_task_executor_capability_semantics_contract.py": 223,
    "rsi_pilot_exact_task_execution_plan_contract.py": 154,
    "rsi_pilot_exact_task_prelaunch_reservation_contract.py": 318,
    "rsi_pilot_exact_task_execution_transaction_contract.py": 224,
    "rsi_pilot_exact_task_post_execution_evaluation_contract.py": 154,
    "rsi_pilot_exact_task_local_commit_plan_contract.py": 231,
    "rsi_pilot_exact_task_local_commit_object_identity_contract.py": 228,
    "rsi_pilot_exact_task_local_commit_write_authorization_contract.py": 166,
    "rsi_pilot_exact_task_local_commit_transaction_contract.py": 341,
    "rsi_pilot_exact_task_post_commit_integration_evaluation_contract.py": 264,
    "rsi_pilot_exact_task_integration_readiness_contract.py": 213,
    "rsi_pilot_exact_task_remote_publication_plan_contract.py": 357,
    "rsi_pilot_exact_task_remote_state_observation_contract.py": 555,
    "rsi_pilot_exact_task_remote_publication_authorization_contract.py": 565,
    "rsi_pilot_exact_task_remote_publication_transaction_contract.py": 1974,
    "rsi_pilot_exact_task_remote_publication_recovery_contract.py": 630,
    "rsi_pilot_exact_task_post_publication_attestation_contract.py": 594,
    "rsi_pilot_exact_task_pr_lifecycle_authorization_contract.py": 843,
    "rsi_pilot_exact_task_pr_lifecycle_transaction_contract.py": 838,
    "rsi_pilot_exact_task_pr_lifecycle_recovery_contract.py": 618,
    "rsi_pilot_exact_task_post_lifecycle_attestation_contract.py": 1133,
    "rsi_pilot_exact_task_review_state_attestation_contract.py": 838,
    "rsi_pilot_exact_task_merge_readiness_evaluation_contract.py": 610,
    "rsi_pilot_exact_task_merge_authorization_contract.py": 864,
    "rsi_pilot_exact_task_merge_transaction_contract.py": 843,
    "rsi_pilot_exact_task_merge_recovery_contract.py": 605,
    "rsi_pilot_exact_task_post_merge_attestation_contract.py": 2593,
    "rsi_pilot_exact_task_release_readiness_evaluation_contract.py": 856,
    "rsi_pilot_exact_task_release_plan_contract.py": 602,
    "rsi_pilot_exact_task_release_state_observation_contract.py": 841,
    "rsi_pilot_exact_task_release_authorization_contract.py": 821,
}

# The deep cohort: identical to the pre-#1682 strided second third, so the
# serial execution and the deep timeouts keyed on "2/3", "2a/3", "2b/3" cover
# exactly the contracts they always covered.
_DEEP_CONTRACT_FILES = _CONTRACT_FILES[1::_REQUIRED_SHARD_COUNT]
_SHALLOW_CONTRACT_FILES = tuple(f for f in _CONTRACT_FILES if f not in _DEEP_CONTRACT_FILES)


def _cost_split(files: tuple[str, ...], parts: int) -> tuple[tuple[str, ...], ...]:
    """Deterministic longest-first split of ``files`` into ``parts`` cohorts, original order kept."""
    missing = set(_CONTRACT_FILES) - set(_CONTRACT_COST_SECONDS)
    extra = set(_CONTRACT_COST_SECONDS) - set(_CONTRACT_FILES)
    if missing or extra:
        raise AssertionError(
            f"Stage-B midchain cost table drifted: missing={sorted(missing)} extra={sorted(extra)}"
        )
    load = [0] * parts
    members: list[set[str]] = [set() for _ in range(parts)]
    for filename in sorted(files, key=lambda f: (-_CONTRACT_COST_SECONDS[f], f)):
        target = min(range(parts), key=lambda i: (load[i], i))
        members[target].add(filename)
        load[target] += _CONTRACT_COST_SECONDS[filename]
    return tuple(tuple(f for f in files if f in members[i]) for i in range(parts))


def _shard_assignment() -> dict[str, tuple[str, ...]]:
    """Every hosted shard id -> its contracts. 2/3 is the whole deep cohort (direct callers)."""
    shallow_a, shallow_b = _cost_split(_SHALLOW_CONTRACT_FILES, 2)
    deep_a, deep_b = _cost_split(_DEEP_CONTRACT_FILES, 2)
    return {
        "1/3": shallow_a,
        "3/3": shallow_b,
        "2/3": _DEEP_CONTRACT_FILES,
        "2a/3": deep_a,
        "2b/3": deep_b,
    }


def _selected_contract_files() -> tuple[str, ...]:
    raw = os.environ.get(_CONTRACT_SHARD_ENV, "").strip()
    if not raw:
        return _CONTRACT_FILES
    assignment = _shard_assignment()
    if raw not in assignment:
        raise AssertionError(
            f"invalid Stage-B contract shard {raw!r}; expected 1/3, 2/3, 2a/3, 2b/3, or 3/3"
        )
    selected = assignment[raw]
    if not selected:
        raise AssertionError(f"Stage-B contract shard {raw!r} selected no contracts")
    return selected



def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _contract_timeout_seconds(filename: str | None = None) -> int:
    if filename in _TARGETED_DEEP_TIMEOUT_CONTRACTS:
        return _TARGETED_DEEP_TIMEOUT_SECONDS
    shard = os.environ.get(_CONTRACT_SHARD_ENV, "").strip()
    return (
        _DEEP_SHARD_TIMEOUT_SECONDS
        if shard in {"2/3", "2a/3", "2b/3"}
        else _PER_CONTRACT_TIMEOUT_SECONDS
    )


def _worker_count(contract_count: int) -> int:
    shard = os.environ.get(_CONTRACT_SHARD_ENV, "").strip()
    if shard in {"2/3", "2a/3", "2b/3"}:
        return 1
    return min(
        _MAX_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        contract_count,
    )


def _run_contract_file(filename: str) -> tuple[str, int, float, str]:
    path = SUPPORT / filename
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    timeout_seconds = _contract_timeout_seconds(filename)
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
    contract_files = _selected_contract_files()
    shard = os.environ.get(_CONTRACT_SHARD_ENV, "").strip() or "all"
    worker_count = _worker_count(len(contract_files))
    timeout_seconds = _contract_timeout_seconds()
    print(
        f"Stage-B exact-task midchain: {len(_CONTRACT_FILES)} contracts, "
        f"shard {shard}, {worker_count} isolated worker(s), "
        f"{timeout_seconds}s default per-contract bound, "
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
    for filename in contract_files:
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

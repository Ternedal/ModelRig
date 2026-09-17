"""Stage-B isolated-process driver for ADR-DC-030 through ADR-DC-033.

ADR-DC-030..031 qualify as two shallow isolated contracts with at most two workers.
ADR-DC-032 and ADR-DC-033 then qualify together in one isolated shared-provenance
child: both canonical contracts execute in full, but the deterministic deep upstream
material is built once and kept alive across the adjacent pair. The nonce-reuse
contract remains the single bridge into ADR-DC-034 through ADR-DC-097 and runs only
after the admission phases, preventing nested worker oversubscription.
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
_DEFAULT_TIMEOUT_SECONDS = 1800
_SHARED_DEEP_CHAIN_TIMEOUT_SECONDS = 3000
_NONCE_CHAIN_TIMEOUT_SECONDS = 6600
_MAX_SHALLOW_PARALLEL_CONTRACTS = 2

_SHALLOW_CONTRACT_FILES = (
    "rsi_pilot_exact_task_execution_authorization_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_observation_contract.py",
)
_SHARED_DEEP_CHAIN_FILE = (
    "rsi_pilot_exact_task_execution_revalidation_attestation_admission_stage_b_driver.py"
)
_NONCE_CHAIN_FILE = "rsi_pilot_exact_task_execution_admission_nonce_reuse_contract.py"


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _timeout_for(filename: str) -> int:
    if filename == _NONCE_CHAIN_FILE:
        return _NONCE_CHAIN_TIMEOUT_SECONDS
    if filename == _SHARED_DEEP_CHAIN_FILE:
        return _SHARED_DEEP_CHAIN_TIMEOUT_SECONDS
    return _DEFAULT_TIMEOUT_SECONDS


def _run_contract_file(filename: str) -> tuple[str, int, float, str]:
    path = SUPPORT / filename
    started = time.monotonic()
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    timeout = _timeout_for(filename)
    try:
        completed = subprocess.run(
            [sys.executable, "-u", str(path)],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
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


def _raise_failures(
    phase: str,
    files: tuple[str, ...],
    results: dict[str, tuple[int, float, str]],
) -> None:
    failures = []
    for filename in files:
        returncode, elapsed, output = results[filename]
        if returncode == 0:
            continue
        failures.append(
            f"{filename}: exit {returncode} after {elapsed:.1f}s\n{output[-12000:]}"
        )
    if failures:
        raise AssertionError(
            f"Stage-B exact-task admission-chain {phase} failed:\n\n"
            + "\n\n".join(failures)
        )


def run_contract() -> None:
    shallow_worker_count = min(
        _MAX_SHALLOW_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(_SHALLOW_CONTRACT_FILES),
    )
    print(
        "Stage-B exact-task admission chain: phase 1a/2, "
        f"{len(_SHALLOW_CONTRACT_FILES)} shallow standalone contracts, "
        f"{shallow_worker_count} isolated workers",
        flush=True,
    )

    shallow_results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=shallow_worker_count) as executor:
        futures = {}
        for filename in _SHALLOW_CONTRACT_FILES:
            print(
                f"  START: {filename} ({_timeout_for(filename)}s bound)",
                flush=True,
            )
            futures[executor.submit(_run_contract_file, filename)] = filename

        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            shallow_results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)

    _raise_failures("shallow standalone phase", _SHALLOW_CONTRACT_FILES, shallow_results)

    # Two independent hosted runners showed the shared fixture working: ADR-DC-032
    # completed fully and ADR-DC-033 started before the original 2400s aggregate
    # bound expired. Widen only the aggregate diagnostic bound to 3000s and retain
    # internal per-contract timing so the next run measures the remaining cost.
    print(
        "Stage-B exact-task admission chain: phase 1b/2, "
        "ADR-DC-032 -> ADR-DC-033 shared-provenance isolated child",
        flush=True,
    )
    print(
        f"  START: {_SHARED_DEEP_CHAIN_FILE} "
        f"({_timeout_for(_SHARED_DEEP_CHAIN_FILE)}s aggregate bound)",
        flush=True,
    )
    filename, returncode, elapsed, output = _run_contract_file(_SHARED_DEEP_CHAIN_FILE)
    status = "PASS" if returncode == 0 else f"FAIL({returncode})"
    print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)
    shared_results = {filename: (returncode, elapsed, output)}
    _raise_failures(
        "shared deep ADR-032/033 phase",
        (_SHARED_DEEP_CHAIN_FILE,),
        shared_results,
    )

    # Do not overlap the downstream bridge with the admission phases. The bridge
    # itself runs isolated workers for ADR-DC-034..066 and ADR-DC-067..097.
    print(
        "Stage-B exact-task admission chain: phase 2/2, nonce/downstream bridge",
        flush=True,
    )
    print(
        f"  START: {_NONCE_CHAIN_FILE} ({_timeout_for(_NONCE_CHAIN_FILE)}s bound)",
        flush=True,
    )
    filename, returncode, elapsed, output = _run_contract_file(_NONCE_CHAIN_FILE)
    status = "PASS" if returncode == 0 else f"FAIL({returncode})"
    print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)
    bridge_results = {filename: (returncode, elapsed, output)}
    _raise_failures("nonce/downstream phase", (_NONCE_CHAIN_FILE,), bridge_results)


if __name__ == "__main__":
    run_contract()

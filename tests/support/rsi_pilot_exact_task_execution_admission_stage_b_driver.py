"""Stage-B isolated-process driver for ADR-DC-030 through ADR-DC-097.

ADR-DC-030..031 qualify as two shallow isolated contracts with at most two workers.
ADR-DC-032 and ADR-DC-033 then qualify together in one isolated shared-provenance
child. The focused ADR-DC-033 nonce-reuse guard, ADR-DC-034..066 midchain, and
ADR-DC-067..097 downstream chain run as sibling phases afterwards.

Keeping the downstream drivers outside the nonce guard preserves the locked
transitive Stage-B entrypoint without recursively nesting their internally
parallel workers or forcing both chains through one aggregate subprocess timeout.
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
_NONCE_REUSE_TIMEOUT_SECONDS = 1800
_MIDCHAIN_TIMEOUT_SECONDS = 4000
_DOWNSTREAM_TIMEOUT_SECONDS = 4000
_MAX_SHALLOW_PARALLEL_CONTRACTS = 2

_SHALLOW_CONTRACT_FILES = (
    "rsi_pilot_exact_task_execution_authorization_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_observation_contract.py",
)
_SHARED_DEEP_CHAIN_FILE = (
    "rsi_pilot_exact_task_execution_revalidation_attestation_admission_stage_b_driver.py"
)
_NONCE_REUSE_FILE = "rsi_pilot_exact_task_execution_admission_nonce_reuse_contract.py"
_MIDCHAIN_DRIVER_FILE = "rsi_pilot_exact_task_stage_b_midchain_driver.py"
_DOWNSTREAM_DRIVER_FILE = "rsi_pilot_exact_task_release_transaction_contract.py"


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _timeout_for(filename: str) -> int:
    if filename == _SHARED_DEEP_CHAIN_FILE:
        return _SHARED_DEEP_CHAIN_TIMEOUT_SECONDS
    if filename == _NONCE_REUSE_FILE:
        return _NONCE_REUSE_TIMEOUT_SECONDS
    if filename == _MIDCHAIN_DRIVER_FILE:
        return _MIDCHAIN_TIMEOUT_SECONDS
    if filename == _DOWNSTREAM_DRIVER_FILE:
        return _DOWNSTREAM_TIMEOUT_SECONDS
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


def _run_serial_phase(phase: str, filename: str) -> None:
    print(f"Stage-B exact-task admission chain: {phase}", flush=True)
    print(
        f"  START: {filename} ({_timeout_for(filename)}s bound)",
        flush=True,
    )
    result_name, returncode, elapsed, output = _run_contract_file(filename)
    status = "PASS" if returncode == 0 else f"FAIL({returncode})"
    print(f"  {status}: {result_name} ({elapsed:.1f}s)", flush=True)
    _raise_failures(
        phase,
        (filename,),
        {result_name: (returncode, elapsed, output)},
    )


def run_contract() -> None:
    shallow_worker_count = min(
        _MAX_SHALLOW_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(_SHALLOW_CONTRACT_FILES),
    )
    print(
        "Stage-B exact-task admission chain: phase 1a/3, "
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

    _run_serial_phase(
        "phase 1b/3, ADR-DC-032 -> ADR-DC-033 shared-provenance isolated child",
        _SHARED_DEEP_CHAIN_FILE,
    )
    _run_serial_phase(
        "phase 2a/3, focused ADR-DC-033 nonce-reuse guard",
        _NONCE_REUSE_FILE,
    )
    _run_serial_phase(
        "phase 2b/3, ADR-DC-034 through ADR-DC-066 isolated midchain",
        _MIDCHAIN_DRIVER_FILE,
    )
    _run_serial_phase(
        "phase 3/3, ADR-DC-067 through ADR-DC-097 isolated downstream chain",
        _DOWNSTREAM_DRIVER_FILE,
    )


if __name__ == "__main__":
    run_contract()

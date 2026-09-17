"""Stage-B isolated-process driver for ADR-DC-030 through ADR-DC-033.

ADR-DC-029 previously ran the authorization, revalidation, admission and focused
nonce-reuse contracts serially in one process. These contracts own independent
fixtures and can qualify concurrently. The nonce-reuse contract remains the single
bridge into ADR-DC-034 through ADR-DC-097, so downstream coverage still runs once.
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
_DEFAULT_TIMEOUT_SECONDS = 1200
_NONCE_CHAIN_TIMEOUT_SECONDS = 3300
_MAX_PARALLEL_CONTRACTS = 4

# Start the nonce-reuse bridge first so the ADR-DC-034..097 qualification can
# make progress while the four standalone ADR-DC-030..033 contracts qualify.
_CONTRACT_FILES = (
    "rsi_pilot_exact_task_execution_admission_nonce_reuse_contract.py",
    "rsi_pilot_exact_task_execution_authorization_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_observation_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_attestation_contract.py",
    "rsi_pilot_exact_task_execution_admission_contract.py",
)


def _decode_timeout_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _timeout_for(filename: str) -> int:
    if filename == "rsi_pilot_exact_task_execution_admission_nonce_reuse_contract.py":
        return _NONCE_CHAIN_TIMEOUT_SECONDS
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


def run_contract() -> None:
    worker_count = min(
        _MAX_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(_CONTRACT_FILES),
    )
    print(
        f"Stage-B exact-task admission chain: {len(_CONTRACT_FILES)} contracts, "
        f"{worker_count} isolated workers",
        flush=True,
    )

    results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for filename in _CONTRACT_FILES:
            print(
                f"  START: {filename} ({_timeout_for(filename)}s bound)",
                flush=True,
            )
            futures[executor.submit(_run_contract_file, filename)] = filename

        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)

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
            "Stage-B exact-task admission-chain qualification failed:\n\n"
            + "\n\n".join(failures)
        )


if __name__ == "__main__":
    run_contract()

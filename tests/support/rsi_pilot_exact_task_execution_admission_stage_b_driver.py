"""Stage-B isolated-process driver for ADR-DC-030 through ADR-DC-033.

ADR-DC-029 previously ran the authorization, revalidation, admission and focused
nonce-reuse contracts serially in one process. The four standalone ADR-DC-030..033
contracts own independent fixtures and qualify concurrently. The nonce-reuse
contract remains the single bridge into ADR-DC-034 through ADR-DC-097 and runs only
after the standalone batch, preventing nested worker oversubscription.
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
_NONCE_CHAIN_TIMEOUT_SECONDS = 6600
_MAX_PARALLEL_CONTRACTS = 4

_STANDALONE_CONTRACT_FILES = (
    "rsi_pilot_exact_task_execution_authorization_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_observation_contract.py",
    "rsi_pilot_exact_task_execution_revalidation_attestation_contract.py",
    "rsi_pilot_exact_task_execution_admission_contract.py",
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
    worker_count = min(
        _MAX_PARALLEL_CONTRACTS,
        max(1, os.cpu_count() or 1),
        len(_STANDALONE_CONTRACT_FILES),
    )
    print(
        "Stage-B exact-task admission chain: phase 1/2, "
        f"{len(_STANDALONE_CONTRACT_FILES)} standalone contracts, "
        f"{worker_count} isolated workers",
        flush=True,
    )

    standalone_results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {}
        for filename in _STANDALONE_CONTRACT_FILES:
            print(
                f"  START: {filename} ({_timeout_for(filename)}s bound)",
                flush=True,
            )
            futures[executor.submit(_run_contract_file, filename)] = filename

        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            standalone_results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)

    _raise_failures("standalone phase", _STANDALONE_CONTRACT_FILES, standalone_results)

    # Do not overlap the downstream bridge with the standalone batch. The bridge
    # itself runs isolated workers for ADR-DC-034..066 and ADR-DC-067..097; running
    # those workers under an already saturated outer executor caused deterministic
    # CPU oversubscription and timeout cascades on hosted CI runners.
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

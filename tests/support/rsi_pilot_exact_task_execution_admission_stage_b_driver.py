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
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
_DEFAULT_TIMEOUT_SECONDS = 1800
_SHARED_DEEP_CHAIN_TIMEOUT_SECONDS = 3000
_NONCE_REUSE_TIMEOUT_SECONDS = 7200
_FULL_PHASE_TIMEOUT_SECONDS = 19800
_SHARDED_PHASE_TIMEOUT_SECONDS = 11400
_MAX_SHALLOW_PARALLEL_CONTRACTS = 2
_STAGE_B_SLICE_ENV = "MODELRIG_STAGE_B_SLICE"
_CONTRACT_SHARD_ENV = "MODELRIG_STAGE_B_CONTRACT_SHARD"
_CACHE_ROOT_ENV = "MODELRIG_STAGE_B_CACHE_ROOT"
_SUPPORTED_STAGE_B_SLICES = ("all", "admission", "midchain", "downstream")

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


def _stage_b_slice() -> str:
    value = os.environ.get(_STAGE_B_SLICE_ENV, "all").strip() or "all"
    if value not in _SUPPORTED_STAGE_B_SLICES:
        raise AssertionError(
            f"unsupported Stage-B slice {value!r}; expected one of "
            f"{', '.join(_SUPPORTED_STAGE_B_SLICES)}"
        )
    return value


def _contract_shard_is_active() -> bool:
    return bool(os.environ.get(_CONTRACT_SHARD_ENV, "").strip())


def _timeout_for(filename: str) -> int:
    if filename == _SHARED_DEEP_CHAIN_FILE:
        return _SHARED_DEEP_CHAIN_TIMEOUT_SECONDS
    if filename == _NONCE_REUSE_FILE:
        return _NONCE_REUSE_TIMEOUT_SECONDS
    if filename in (_MIDCHAIN_DRIVER_FILE, _DOWNSTREAM_DRIVER_FILE):
        if _contract_shard_is_active():
            return _SHARDED_PHASE_TIMEOUT_SECONDS
        return _FULL_PHASE_TIMEOUT_SECONDS
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


def _run_admission_prefix() -> None:
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


def _external_cache_root(stage_b_slice: str) -> Path | None:
    raw = os.environ.get(_CACHE_ROOT_ENV, "").strip()
    if not raw:
        return None
    if stage_b_slice == "all":
        raise AssertionError("Stage-B all slice cannot consume an external cache root")

    root = Path(raw)
    if not root.is_absolute() or root.is_symlink():
        raise AssertionError("Stage-B cache root must be absolute and not a symlink")
    if not root.parent.is_dir() or root.parent.is_symlink():
        raise AssertionError("Stage-B cache root parent must be a real directory")

    if stage_b_slice == "admission":
        if root.exists():
            if not root.is_dir() or any(root.iterdir()):
                raise AssertionError(
                    "Stage-B admission cache root must be absent or an empty directory"
                )
        else:
            root.mkdir()
        return root.resolve()

    if not root.is_dir():
        raise AssertionError("Stage-B preloaded cache root must already exist")
    proof_cache_path = root / "proofs.json"
    start_ledger_root = root / "start-ledger"
    if (
        proof_cache_path.is_symlink()
        or not proof_cache_path.is_file()
        or start_ledger_root.is_symlink()
        or not start_ledger_root.is_dir()
    ):
        raise AssertionError(
            "Stage-B preloaded cache root must contain proofs.json and start-ledger/"
        )
    return root.resolve()


def _restore_env(name: str, previous: str | None) -> None:
    if previous is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = previous


def _run_preloaded_slice(stage_b_slice: str, cache_root: Path) -> None:
    previous_proof_cache = os.environ.get("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE")
    previous_start_ledger = os.environ.get("MODELRIG_STAGE_B_START_LEDGER_ROOT")
    os.environ["MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE"] = str(
        cache_root / "proofs.json"
    )
    os.environ["MODELRIG_STAGE_B_START_LEDGER_ROOT"] = str(
        cache_root / "start-ledger"
    )
    try:
        if stage_b_slice == "midchain":
            _run_serial_phase(
                "phase 2b/3, ADR-DC-034 through ADR-DC-066 isolated midchain",
                _MIDCHAIN_DRIVER_FILE,
            )
        elif stage_b_slice == "downstream":
            _run_serial_phase(
                "phase 3/3, ADR-DC-067 onward isolated downstream chain",
                _DOWNSTREAM_DRIVER_FILE,
            )
        else:
            raise AssertionError(
                f"Stage-B preloaded cache is not valid for slice {stage_b_slice!r}"
            )
    finally:
        _restore_env("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE", previous_proof_cache)
        _restore_env("MODELRIG_STAGE_B_START_LEDGER_ROOT", previous_start_ledger)


def _run_cached_slice(stage_b_slice: str) -> None:
    external_root = _external_cache_root(stage_b_slice)
    if stage_b_slice in ("midchain", "downstream") and external_root is not None:
        _run_preloaded_slice(stage_b_slice, external_root)
        return

    proof_cache_temp = None
    if external_root is None:
        proof_cache_temp = tempfile.TemporaryDirectory(
            prefix="rsi-exact-task-stage-b-proof-cache-"
        )
        proof_cache_root = Path(proof_cache_temp.name).resolve()
    else:
        proof_cache_root = external_root

    proof_cache_path = proof_cache_root / "proofs.json"
    start_ledger_root = proof_cache_root / "start-ledger"
    start_ledger_root.mkdir()
    previous_proof_cache = os.environ.get("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE")
    previous_start_ledger = os.environ.get("MODELRIG_STAGE_B_START_LEDGER_ROOT")
    os.environ["MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE"] = str(proof_cache_path)
    os.environ["MODELRIG_STAGE_B_START_LEDGER_ROOT"] = str(start_ledger_root)
    try:
        _run_serial_phase(
            "phase 2a/3, focused ADR-DC-033 nonce-reuse guard",
            _NONCE_REUSE_FILE,
        )
        if not proof_cache_path.is_file():
            raise AssertionError(
                "Stage-B ADR-033 nonce guard did not publish the shared proof cache"
            )
        if stage_b_slice in ("all", "midchain"):
            _run_serial_phase(
                "phase 2b/3, ADR-DC-034 through ADR-DC-066 isolated midchain",
                _MIDCHAIN_DRIVER_FILE,
            )
        if stage_b_slice in ("all", "downstream"):
            _run_serial_phase(
                "phase 3/3, ADR-DC-067 onward isolated downstream chain",
                _DOWNSTREAM_DRIVER_FILE,
            )
    finally:
        _restore_env("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE", previous_proof_cache)
        _restore_env("MODELRIG_STAGE_B_START_LEDGER_ROOT", previous_start_ledger)
        if proof_cache_temp is not None:
            proof_cache_temp.cleanup()


def run_contract() -> None:
    stage_b_slice = _stage_b_slice()
    if stage_b_slice in ("all", "admission") and _contract_shard_is_active():
        raise AssertionError(
            "Stage-B admission/all slice cannot be combined with a contract shard"
        )
    print(
        f"Stage-B exact-task admission chain selected slice: {stage_b_slice}",
        flush=True,
    )
    if stage_b_slice in ("all", "admission"):
        _run_admission_prefix()
    _run_cached_slice(stage_b_slice)


if __name__ == "__main__":
    run_contract()

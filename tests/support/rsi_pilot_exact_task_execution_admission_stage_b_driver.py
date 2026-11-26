"""Stage-B isolated-process driver for ADR-DC-030 through ADR-DC-097.

ADR-DC-030..031 qualify as two shallow isolated contracts with at most two workers.
ADR-DC-032 and ADR-DC-033 then qualify together in one isolated shared-provenance
child, and the focused ADR-DC-033 nonce-reuse guard qualifies beside it: two isolated
processes, started together. The ADR-DC-034..066 midchain and ADR-DC-067..097
downstream chain run as sibling phases afterwards.

The shared-provenance child and the nonce guard share nothing on disk. The child
never reads the Stage-B proof cache; the guard builds its own proof and is the phase
that publishes that cache. Run one after the other they were about nine tenths of
the admission job, which every other Stage-B slice waits for. Measured on two cores,
25 Nov 2026, same commit: 3151 s in sequence (1755 + 1396), 1729 s side by side
(1729 and 1382) - neither contract got slower. The verdict is unchanged: both run in
full, and either failing fails admission. What changes is that a failing child no
longer stops the guard from starting; the failure is reported when both have ended.

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
# A hang guard, not a performance budget. 3000 s was set on 1 Oct 2026; the child has
# since been measured at 1254-1273 s on a fast hosted runner and 2195 and 2464 s on
# slow ones (#2497, 25 Nov 2026: 82 % of the bound, with nothing wrong). One runner a
# fifth slower than the slowest seen would have failed a whole Stage-B run on time
# alone. 5400 s is a little over twice the slowest observation, and since the child
# runs beside the nonce guard (7200 s) it does not lengthen admission's worst case.
_SHARED_DEEP_CHAIN_TIMEOUT_SECONDS = 5400
_NONCE_REUSE_TIMEOUT_SECONDS = 7200
_FULL_PHASE_TIMEOUT_SECONDS = 19800
_SHARDED_PHASE_TIMEOUT_SECONDS = 18000
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


def _run_contract_file(
    filename: str, base_env: dict[str, str] | None = None
) -> tuple[str, int, float, str]:
    path = SUPPORT / filename
    started = time.monotonic()
    env = dict(os.environ if base_env is None else base_env)
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
    if returncode == 0 and filename in (_MIDCHAIN_DRIVER_FILE, _DOWNSTREAM_DRIVER_FILE):
        timing_lines = [
            line
            for line in output.splitlines()
            if line.startswith("Stage-B exact-task ")
            or line.lstrip().startswith("PASS: ")
        ]
        if timing_lines:
            print(f"--- {filename} timing summary ---", flush=True)
            for line in timing_lines:
                print(line, flush=True)
            print(f"--- end {filename} timing summary ---", flush=True)
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


def _run_shared_child_beside_nonce_guard(
    previous_proof_cache: str | None, previous_start_ledger: str | None
) -> None:
    """Phase 1b and phase 2a as two isolated processes started together.

    Each gets the environment it had when they ran in sequence. The nonce guard
    inherits the proof-cache and start-ledger targets the caller has just set. The
    shared-provenance child ran before those were set, so it gets them as they were
    before: it must not find a cache target and decide to use it.
    """
    guard_env = dict(os.environ)
    child_env = dict(guard_env)
    for name, previous in (
        ("MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE", previous_proof_cache),
        ("MODELRIG_STAGE_B_START_LEDGER_ROOT", previous_start_ledger),
    ):
        if previous is None:
            child_env.pop(name, None)
        else:
            child_env[name] = previous
    phases = (
        (
            "phase 1b/3, ADR-DC-032 -> ADR-DC-033 shared-provenance isolated child",
            _SHARED_DEEP_CHAIN_FILE,
            child_env,
        ),
        ("phase 2a/3, focused ADR-DC-033 nonce-reuse guard", _NONCE_REUSE_FILE, guard_env),
    )
    print(
        "Stage-B exact-task admission chain: phases 1b/3 and 2a/3 side by side, "
        f"{len(phases)} isolated workers",
        flush=True,
    )
    results: dict[str, tuple[int, float, str]] = {}
    with ThreadPoolExecutor(max_workers=len(phases)) as executor:
        futures = {}
        for phase, filename, env in phases:
            print(f"Stage-B exact-task admission chain: {phase}", flush=True)
            print(
                f"  START: {filename} ({_timeout_for(filename)}s bound)",
                flush=True,
            )
            futures[executor.submit(_run_contract_file, filename, env)] = filename
        for future in as_completed(futures):
            filename, returncode, elapsed, output = future.result()
            results[filename] = (returncode, elapsed, output)
            status = "PASS" if returncode == 0 else f"FAIL({returncode})"
            print(f"  {status}: {filename} ({elapsed:.1f}s)", flush=True)
    _raise_failures(
        "shared-provenance child and nonce-reuse guard",
        tuple(filename for _, filename, _ in phases),
        results,
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
        if stage_b_slice in ("all", "admission"):
            _run_shared_child_beside_nonce_guard(
                previous_proof_cache, previous_start_ledger
            )
        else:
            # A midchain or downstream slice without a published cache builds its
            # own; the shared-provenance child is admission's and is not run here.
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

#!/usr/bin/env python3
"""Run the repository's top-level Python test scripts with a hard per-file timeout.

The existing CI gates intentionally execute each ``tests/*.py`` file as its own
process. This runner preserves that contract while preventing one blocked
socket/process test from owning a GitHub runner indefinitely.
"""
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
from typing import Iterable

DEFAULT_PATTERNS = (
    "tests/backend_*.py",
    "tests/e2e.py",
    "tests/worker_*.py",
    "tests/workflow_*.py",
)
DEFAULT_TIMEOUT_SECONDS = 900.0
TIMEOUT_EXIT_CODE = 124
KILL_GRACE_SECONDS = 5.0
FAILURE_TAIL_LINES = 160


def _tests_for_patterns(patterns: Iterable[str]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for pattern in patterns:
        for raw in sorted(glob.glob(pattern)):
            path = Path(raw)
            key = path.as_posix()
            if key in seen or not path.is_file():
                continue
            seen.add(key)
            result.append(path)
    return result


def _terminate_process_tree(process: subprocess.Popen[object]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=KILL_GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait(timeout=KILL_GRACE_SECONDS)


def _tail(path: Path, lines: int = FAILURE_TAIL_LINES) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def run_test_file(
    path: Path,
    *,
    log_path: Path,
    timeout_seconds: float,
    python_executable: str = sys.executable,
    environment: dict[str, str] | None = None,
) -> int:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")

    env = dict(os.environ if environment is None else environment)
    env["PYTHONPATH"] = "worker"

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"===== {path.as_posix()} =====\n")
        log.flush()
        kwargs: dict[str, object] = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        process = subprocess.Popen(
            [python_executable, str(path)],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            **kwargs,
        )
        try:
            return process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(process)
            log.write(
                f"TIMEOUT: {path.as_posix()} exceeded {timeout_seconds:g} seconds "
                f"(exit {TIMEOUT_EXIT_CODE})\n"
            )
            log.flush()
            return TIMEOUT_EXIT_CODE


def run_suite(
    *,
    patterns: Iterable[str],
    log_path: Path,
    timeout_seconds: float,
) -> int:
    tests = _tests_for_patterns(patterns)
    if not tests:
        print("No repository Python test scripts matched the configured patterns.", file=sys.stderr)
        return 2

    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    print(f"Repository Python suite: {len(tests)} files; per-file timeout={timeout_seconds:g}s")
    for index, path in enumerate(tests, start=1):
        label = path.as_posix()
        print(f"::group::{label}")
        print(f"START [{index}/{len(tests)}] {label}", flush=True)
        started = time.monotonic()
        code = run_test_file(path, log_path=log_path, timeout_seconds=timeout_seconds)
        elapsed = time.monotonic() - started
        if code == 0:
            print(f"PASS  [{index}/{len(tests)}] {label} ({elapsed:.1f}s)")
            print("::endgroup::")
            continue

        reason = "TIMEOUT" if code == TIMEOUT_EXIT_CODE else "FAIL"
        print(f"{reason} [{index}/{len(tests)}] {label} (exit {code}, {elapsed:.1f}s)", file=sys.stderr)
        tail = _tail(log_path)
        if tail:
            print("----- failure log tail -----", file=sys.stderr)
            print(tail, file=sys.stderr)
            print("----- end failure log tail -----", file=sys.stderr)
        print("::endgroup::")
        return code
    return 0


def self_test() -> int:
    with tempfile.TemporaryDirectory(prefix="modelrig-suite-runner-") as raw:
        root = Path(raw)
        log = root / "suite.log"
        ok = root / "ok.py"
        fail = root / "fail.py"
        hang = root / "hang.py"
        ok.write_text("raise SystemExit(0)\n", encoding="utf-8")
        fail.write_text("raise SystemExit(7)\n", encoding="utf-8")
        hang.write_text("import time\ntime.sleep(30)\n", encoding="utf-8")
        env = dict(os.environ)

        if run_test_file(ok, log_path=log, timeout_seconds=2.0, environment=env) != 0:
            raise AssertionError("runner self-test: success path failed")
        if run_test_file(fail, log_path=log, timeout_seconds=2.0, environment=env) != 7:
            raise AssertionError("runner self-test: failure code was not preserved")
        started = time.monotonic()
        if run_test_file(hang, log_path=log, timeout_seconds=0.2, environment=env) != TIMEOUT_EXIT_CODE:
            raise AssertionError("runner self-test: timeout path did not fail closed")
        if time.monotonic() - started > 8.0:
            raise AssertionError("runner self-test: timeout did not terminate promptly")
    print("repository Python suite runner self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="/tmp/modelrig-python-suite.log")
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    return run_suite(
        patterns=DEFAULT_PATTERNS,
        log_path=Path(args.log),
        timeout_seconds=args.timeout_seconds,
    )


if __name__ == "__main__":
    raise SystemExit(main())

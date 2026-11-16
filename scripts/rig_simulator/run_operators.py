#!/usr/bin/env python3
"""Run the rig operators against a simulated appliance and judge each run.

The rig is the scarcest resource in the project, and rig days have mostly
found defects in the apparatus: a path that is not there, an argument a script
does not accept, a PowerShell construct 5.1 cannot parse, a token set one step
too late. Those defects do not need a GPU to show up. They need the scripts to
be *run*, once, on Windows, against something that answers like the appliance.

This runner does that in one process:

1. starts a mock Ollama (``mock_ollama.py``), a heartbeat ticker that advances
   a supervisor-style heartbeat file, the real worker (uvicorn) and the real
   backend binary, all on loopback, and waits for both ``/healthz``;
2. runs every operator in ``operators.json`` that applies to this platform,
   with the manifest's placeholders filled in (``${BACKEND_URL}`` ...);
3. judges each run against its expectation: exit code in the allowed set, a
   JSON object on stdout when required, a journal line with the required
   fields when required, and never a Python traceback on stderr;
4. writes one report and exits 0 only if every applicable operator passed.

The simulator proves that operators run to a verdict. It does not prove that
the verdict would be PASS on the rig, and it produces no evidence: it writes
only below ``validation/rig-simulator/``, which is ignored by Git.

Usage (CI runs this on ``windows-latest`` with ``--require-all``)::

    python scripts/rig_simulator/run_operators.py --backend-bin <modelrig-server> --require-all

``--no-stack`` runs only the operators that do not need the stack, for a quick
local check of the static ones.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import manifest as manifest_mod  # noqa: E402
import mock_ollama  # noqa: E402

REPORT_SCHEMA = "kaliv-rig-simulator-report/v1"
WORK_RELATIVE = Path("validation") / "rig-simulator"
TRACEBACK = "Traceback (most recent call last)"
TAIL = 4000
HEALTH_TIMEOUT_S = 120.0
IS_WINDOWS = os.name == "nt"


# ---------------------------------------------------------------- stack ---
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def http_ok(url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
            return response.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_health(url: str, deadline: float) -> bool:
    while time.monotonic() < deadline:
        if http_ok(url + "/healthz"):
            return True
        time.sleep(0.5)
    return False


class Heartbeat:
    """Writes unix milliseconds to a file every tick, as the supervisor does."""

    def __init__(self, path: Path, period_s: float = 0.5) -> None:
        self.path = path
        self.period_s = period_s
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.path.write_text(str(int(time.time() * 1000)), encoding="ascii")
            except OSError:
                pass
            self._stop.wait(self.period_s)

    def start(self) -> "Heartbeat":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)


def _popen(cmd: list[str], *, cwd: Path, env: dict[str, str], log: Path) -> subprocess.Popen:
    kwargs: dict[str, Any] = {}
    if IS_WINDOWS:
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True
    handle = log.open("w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=handle, stderr=subprocess.STDOUT, **kwargs)


def _stop(proc: subprocess.Popen | None) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except (subprocess.TimeoutExpired, OSError):
        try:
            proc.kill()
            proc.wait(timeout=5)
        except (subprocess.TimeoutExpired, OSError):
            pass


@dataclass
class Stack:
    repo_root: Path
    work_dir: Path
    backend_bin: Path | None
    ollama: mock_ollama.Server | None = None
    heartbeat: Heartbeat | None = None
    worker: subprocess.Popen | None = None
    backend: subprocess.Popen | None = None
    worker_url: str = ""
    backend_url: str = ""
    ollama_url: str = ""
    heartbeat_path: Path = Path()
    problems: list[str] | None = None

    def up(self) -> list[str]:
        """Start everything; return the list of things that did not come up."""
        problems: list[str] = []
        self.ollama = mock_ollama.Server(0).start()
        self.ollama_url = self.ollama.url
        self.heartbeat_path = self.work_dir / "supervisor-heartbeat"
        self.heartbeat = Heartbeat(self.heartbeat_path).start()

        worker_port = free_port()
        self.worker_url = f"http://127.0.0.1:{worker_port}"
        worker_env = dict(
            os.environ,
            PYTHONPATH=str(self.repo_root / "worker"),
            PYTHONDONTWRITEBYTECODE="1",
            MODELRIG_OLLAMA_URL=self.ollama_url,
            MODELRIG_DB=str(self.work_dir / "worker.db"),
        )
        self.worker = _popen(
            [sys.executable, "-B", "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(worker_port)],
            cwd=self.repo_root / "worker", env=worker_env, log=self.work_dir / "worker.log",
        )

        if self.backend_bin is None:
            problems.append("backend binary not given (--backend-bin)")
        else:
            backend_port = free_port()
            self.backend_url = f"http://127.0.0.1:{backend_port}"
            backend_env = dict(
                os.environ,
                MODELRIG_HOST="127.0.0.1",
                MODELRIG_PORT=str(backend_port),
                MODELRIG_OLLAMA_URL=self.ollama_url,
                MODELRIG_WORKER_URL=self.worker_url,
                MODELRIG_DATA=str(self.work_dir / "backend.json"),
            )
            self.backend = _popen([str(self.backend_bin)], cwd=self.repo_root, env=backend_env, log=self.work_dir / "backend.log")

        deadline = time.monotonic() + HEALTH_TIMEOUT_S
        if not wait_health(self.worker_url, deadline):
            problems.append(f"worker did not answer /healthz within {HEALTH_TIMEOUT_S:.0f}s")
        if self.backend is not None and not wait_health(self.backend_url, deadline):
            problems.append(f"backend did not answer /healthz within {HEALTH_TIMEOUT_S:.0f}s")
        self.problems = problems
        return problems

    def down(self) -> None:
        _stop(self.backend)
        _stop(self.worker)
        if self.heartbeat is not None:
            self.heartbeat.stop()
        if self.ollama is not None:
            self.ollama.stop()

    def logs(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for name in ("worker.log", "backend.log"):
            path = self.work_dir / name
            if path.is_file():
                out[name] = _tail(path.read_text(encoding="utf-8", errors="replace"))
        return out


# ------------------------------------------------------------ operators ---
def _tail(text: str) -> str:
    return text if len(text) <= TAIL else "…" + text[-TAIL:]


def write_fresh_wav(path: Path, seconds: float = 1.0, rate: int = 16000) -> Path:
    """One second of near-silence, written now: 'a WAV recorded just now'."""
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"".join(struct.pack("<h", (i % 7) - 3) for i in range(frames)))
    return path


def git_head(repo_root: Path) -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo_root), capture_output=True, text=True, timeout=30)
    sha = result.stdout.strip()
    if result.returncode != 0 or len(sha) != 40:
        raise RuntimeError(f"git rev-parse HEAD failed in {repo_root}: {result.stderr.strip()}")
    return sha


def substitute(value: str, variables: dict[str, str]) -> str:
    def repl(match: Any) -> str:
        name = match.group(1)
        if name not in variables:
            raise KeyError(name)
        return variables[name]

    return manifest_mod.PLACEHOLDER.sub(repl, value)


def command_for(op: manifest_mod.Operator, repo_root: Path, variables: dict[str, str]) -> list[str]:
    args = [substitute(a, variables) for a in op.args]
    script = str(repo_root / op.script)
    if op.kind == "python":
        return [sys.executable, "-B", script, *args]
    if op.kind == "powershell":
        exe = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
        return [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", script, *args]
    raise ValueError(op.kind)


def parse_stdout_json(stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        pass
    for line in reversed(text.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
    return None


def lookup(value: Any, dotted: str) -> Any:
    """``probes.backend.status`` -> value["probes"]["backend"]["status"], or None."""
    current = value
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def judge(op: manifest_mod.Operator, *, exit_code: int | None, stdout: str, stderr: str, repo_root: Path) -> list[str]:
    """Every string returned is one broken expectation."""
    failures: list[str] = []
    expect = op.expect
    if exit_code is None:
        failures.append(f"timed out after {op.timeout_seconds}s")
    elif exit_code not in expect.exit_codes:
        failures.append(f"exit {exit_code} not in {list(expect.exit_codes)}")
    if not expect.allow_traceback and TRACEBACK in stderr:
        failures.append("Python traceback on stderr")
    if not expect.allow_traceback and TRACEBACK in stdout:
        failures.append("Python traceback on stdout")
    if expect.stdout_json is not None:
        parsed = parse_stdout_json(stdout)
        if parsed is None:
            failures.append("stdout holds no JSON object")
        else:
            for key, wanted in expect.stdout_json.items():
                actual = lookup(parsed, key)
                if actual != wanted:
                    failures.append(f"stdout JSON {key}={actual!r}, expected {wanted!r}")
    if expect.jsonl_last is not None:
        path = repo_root / expect.jsonl_last["path"]
        if not path.is_file():
            failures.append(f"journal {expect.jsonl_last['path']} was not written")
        else:
            lines = [ln for ln in path.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
            try:
                last = json.loads(lines[-1]) if lines else None
            except json.JSONDecodeError:
                last = None
            if not isinstance(last, dict):
                failures.append("journal's last line is not a JSON object")
            else:
                for key, wanted in expect.jsonl_last["fields"].items():
                    if last.get(key) != wanted:
                        failures.append(f"journal {key}={last.get(key)!r}, expected {wanted!r}")
    for relative in expect.files_exist:
        if not (repo_root / relative).is_file():
            failures.append(f"expected file missing: {relative}")
    return failures


def run_operator(op: manifest_mod.Operator, *, repo_root: Path, variables: dict[str, str], env: dict[str, str]) -> dict[str, Any]:
    cmd = command_for(op, repo_root, variables)
    started = time.monotonic()
    exit_code: int | None
    try:
        completed = subprocess.run(
            cmd, cwd=str(repo_root), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=op.timeout_seconds,
        )
        exit_code, stdout, stderr = completed.returncode, completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = None
        stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    duration = time.monotonic() - started
    failures = judge(op, exit_code=exit_code, stdout=stdout, stderr=stderr, repo_root=repo_root)
    return {
        "id": op.id,
        "script": op.script,
        "kind": op.kind,
        "command": cmd,
        "status": "pass" if not failures else "fail",
        "exit": exit_code,
        "duration_seconds": round(duration, 2),
        "failures": failures,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "why": op.why,
    }


def applicable(op: manifest_mod.Operator, *, with_stack: bool) -> str | None:
    """None if the operator runs here, else the reason it is skipped."""
    if op.platform == "windows" and not IS_WINDOWS:
        return "windows-only operator on a non-Windows host"
    if op.needs_stack and not with_stack:
        return "needs the simulated stack (--no-stack given)"
    return None


# ----------------------------------------------------------------- main ---
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manifest", type=Path, default=HERE / "operators.json")
    parser.add_argument("--repository-root", type=Path, default=HERE.parents[1])
    parser.add_argument("--backend-bin", type=Path, help="the built modelrig-server binary")
    parser.add_argument("--report", type=Path, help="where to write the report (default: validation/rig-simulator/report.json)")
    parser.add_argument("--only", action="append", default=[], help="run only this operator id (repeatable)")
    parser.add_argument("--no-stack", action="store_true", help="skip the stack; run only operators with needs_stack=false")
    parser.add_argument("--require-all", action="store_true", help="a skipped operator counts as a failure")
    args = parser.parse_args(argv)

    repo_root = args.repository_root.resolve()
    work_dir = repo_root / WORK_RELATIVE
    work_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report or (work_dir / "report.json")

    try:
        manifest = manifest_mod.load_manifest(args.manifest, repo_root)
    except manifest_mod.ManifestError as exc:
        print(f"MANIFEST INVALID: {exc}")
        return 2

    operators = [op for op in manifest.operators if not args.only or op.id in args.only]
    unknown = set(args.only) - {op.id for op in manifest.operators}
    if unknown:
        print(f"unknown operator ids: {sorted(unknown)}")
        return 2

    with_stack = not args.no_stack and any(op.needs_stack for op in operators)
    stack: Stack | None = None
    stack_problems: list[str] = []
    results: list[dict[str, Any]] = []
    head = git_head(repo_root)
    try:
        if with_stack:
            backend_bin = args.backend_bin.resolve() if args.backend_bin else None
            if backend_bin is not None and not backend_bin.is_file():
                print(f"backend binary not found: {backend_bin}")
                return 2
            stack = Stack(repo_root=repo_root, work_dir=work_dir, backend_bin=backend_bin)
            stack_problems = stack.up()
            for problem in stack_problems:
                print(f"STACK: {problem}")

        variables = {
            "REPO": str(repo_root),
            "HEAD_SHA": head,
            "BACKEND_URL": stack.backend_url if stack else "",
            "WORKER_URL": stack.worker_url if stack else "",
            "OLLAMA_URL": stack.ollama_url if stack else "",
            "HEARTBEAT": str(stack.heartbeat_path) if stack else "",
            "FRESH_WAV": str(work_dir / "fresh.wav"),
            "WORK_DIR": str(work_dir),
            "PYTHON": sys.executable,
        }
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        env.update({f"RIG_SIM_{k}": v for k, v in variables.items()})

        for op in operators:
            reason = applicable(op, with_stack=with_stack)
            if reason is None and op.needs_stack and stack_problems:
                reason = "stack did not come up: " + "; ".join(stack_problems)
            if reason is not None:
                results.append({"id": op.id, "script": op.script, "kind": op.kind, "status": "skipped", "reason": reason, "why": op.why})
                print(f"SKIP  {op.id}: {reason}")
                continue
            write_fresh_wav(work_dir / "fresh.wav")
            result = run_operator(op, repo_root=repo_root, variables=variables, env=env)
            results.append(result)
            mark = "PASS " if result["status"] == "pass" else "FAIL "
            print(f"{mark} {op.id} ({result['duration_seconds']}s, exit {result['exit']})")
            for failure in result["failures"]:
                print(f"       - {failure}")
    finally:
        if stack is not None:
            stack.down()

    failed = [r for r in results if r["status"] == "fail"]
    skipped = [r for r in results if r["status"] == "skipped"]
    verdict_ok = not failed and not stack_problems and not (args.require_all and skipped)
    report = {
        "schema": REPORT_SCHEMA,
        "verdict": "PASS" if verdict_ok else "FAIL",
        "platform": {"os": os.name, "system": _platform.system(), "release": _platform.release(), "python": sys.version.split()[0]},
        "head_sha": head,
        "require_all": bool(args.require_all),
        "stack": {
            "started": with_stack,
            "problems": stack_problems,
            "backend_url": stack.backend_url if stack else None,
            "worker_url": stack.worker_url if stack else None,
            "ollama_url": stack.ollama_url if stack else None,
            "logs": stack.logs() if stack and (failed or stack_problems) else {},
        },
        "pending": [{"script": p.script, "issue": p.issue, "why": p.why} for p in manifest.pending],
        "operators": results,
        "counts": {"pass": len([r for r in results if r["status"] == "pass"]), "fail": len(failed), "skipped": len(skipped)},
        "production_activation": False,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{report['verdict']}: {report['counts']} -> {report_path}")
    return 0 if verdict_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

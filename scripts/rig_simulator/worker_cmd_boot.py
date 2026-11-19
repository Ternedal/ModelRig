#!/usr/bin/env python3
"""Boot the real worker with the environment a rig-day stack command line generates.

The rig simulator already proves that start-stage-a-validation-stack.ps1 writes
the right `set "K=V"` lines for V1 gates 2, 3 and 8 (-WriteWorkerCmdOnly, #2437).
This operator closes the next gap: it takes exactly those lines, starts the
production worker entrypoint (app.entrypoint:app, as the generated worker cmd
does) with them, waits for /healthz and checks that the routes the gates need
are mounted in the worker's own OpenAPI surface.

What it proves: the worker boots with that environment on the rig's
interpreter, and the gate routes mount. What it does not prove: that a gate
passes (no GPU, no speech backends, no camera, no Ollama model here).

Isolation: every inherited KALIV_*/MODELRIG_* variable is dropped, the data
root is a scratch directory, and Ollama points at an unused loopback port.
The stack's own scheduler/audit paths come from -SchedulerDataDir, which the
operator places in scratch.

Usage (Windows):
  python scripts/rig_simulator/worker_cmd_boot.py --repository-root . --scratch <dir> \
      --expect-path /experimental/e2e-latency/voice --report <file> -- <stack args...>
Usage (any OS, for tests): --worker-cmd <file> instead of the stack args.

With --status-true, fields of the worker's own consciousness status must be
true (for example that the CognitiveProfile from the generated profile path
loaded).

Exit 0 = booted, every expected path mounted and every status field true; 1 = it did not; 2 = usage or
the stack refused to write the worker cmd. Prints one JSON object on stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCHEMA = "kaliv-rig-simulator-worker-cmd-boot/v1"
ISOLATED_PREFIXES = ("KALIV_", "MODELRIG_")
SET_LINE = re.compile(r'^set "([A-Za-z_][A-Za-z0-9_]*)=(.*)"$')
HEALTH_TIMEOUT_S = 120.0
TAIL = 3000


def parse_worker_cmd(text: str) -> dict[str, str]:
    """The `set "K=V"` lines of a generated worker cmd, in order (later wins, as in cmd.exe)."""
    env: dict[str, str] = {}
    for line in text.splitlines():
        match = SET_LINE.match(line.strip())
        if match:
            env[match.group(1)] = match.group(2)
    return env


def worker_cmd_from_stack(repo: Path, stack_args: list[str], stray: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """The worker cmd text and the KALIV_* names the stack reported as inherited from its shell."""
    exe = shutil.which("powershell.exe") or shutil.which("powershell") or "powershell.exe"
    script = repo / "scripts" / "start-stage-a-validation-stack.ps1"
    completed = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
         *stack_args, "-WriteWorkerCmdOnly"],
        cwd=str(repo), capture_output=True, text=True, timeout=120,
        env={**{k: v for k, v in os.environ.items() if not k.startswith(ISOLATED_PREFIXES)}, **(stray or {})},
    )
    out = completed.stdout
    if completed.returncode != 0 or "WORKER-CMD-BEGIN" not in out or "WORKER-CMD-END" not in out:
        raise RuntimeError(f"stack refused to write the worker cmd (exit {completed.returncode}): "
                           f"{(completed.stderr or out)[-600:]}")
    inherited: list[str] = []
    for line in out.splitlines():
        if line.startswith("INHERITED-KALIV: "):
            value = line.split(": ", 1)[1].strip()
            inherited = [] if value == "none" else value.split(",")
    return out.split("WORKER-CMD-BEGIN", 1)[1].split("WORKER-CMD-END", 1)[0], inherited


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def get_json(url: str) -> object | None:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:  # noqa: S310 - loopback only
            return json.loads(response.read().decode("utf-8")) if response.status == 200 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


STATUS_PATH = "/experimental/consciousness/status"


def lookup(value: object, dotted: str) -> object:
    for part in dotted.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def boot(repo: Path, scratch: Path, cmd_env: dict[str, str], expected: list[str],
         status_true: list[str] | None = None) -> dict:
    scratch.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if not k.startswith(ISOLATED_PREFIXES)}
    env.update(cmd_env)
    env.update(
        PYTHONPATH=str(repo / "worker"),  # what the cmd sets, made explicit for non-Windows test runs
        PYTHONDONTWRITEBYTECODE="1",
        KALIV_DATA_DIR=str(scratch / "kaliv-data"),
        MODELRIG_DB=str(scratch / "worker.db"),
        MODELRIG_OLLAMA_URL=f"http://127.0.0.1:{free_port()}",  # nothing listens: no model is needed to boot
    )
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    log_path = scratch / "worker.log"
    report: dict = {"schema": SCHEMA, "ok": False, "flags": sorted(k for k in cmd_env if k.startswith("KALIV_")),
                    "expected_paths": expected}
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            [sys.executable, "-B", "-m", "uvicorn", "app.entrypoint:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(repo / "worker"), env=env, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + HEALTH_TIMEOUT_S
            healthy = False
            while time.monotonic() < deadline and proc.poll() is None:
                if get_json(url + "/healthz") is not None:
                    healthy = True
                    break
                time.sleep(0.5)
            report["healthy"] = healthy
            report["exit_before_health"] = proc.poll()
            if healthy:
                schema = get_json(url + "/openapi.json")
                paths = sorted(schema.get("paths", {})) if isinstance(schema, dict) else []
                report["missing_paths"] = [p for p in expected if p not in paths]
                status = get_json(url + STATUS_PATH) if status_true else None
                report["status_not_true"] = [f for f in (status_true or []) if lookup(status, f) is not True]
                report["ok"] = not report["missing_paths"] and not report["status_not_true"]
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
    if not report["ok"]:
        report["worker_log_tail"] = log_path.read_text(encoding="utf-8", errors="replace")[-TAIL:]
    return report


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    stack_args: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, stack_args = argv[:cut], argv[cut + 1:]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", required=True)
    parser.add_argument("--scratch", required=True)
    parser.add_argument("--expect-path", action="append", default=[])
    parser.add_argument("--status-true", action="append", default=[],
                        help=f"dotted field of {STATUS_PATH} that must be true, e.g. prerequisites.cognitive_profile_available")
    parser.add_argument("--stray", action="append", default=[], metavar="KALIV_NAME=VALUE",
                        help="put this variable in the stack's shell, as a leftover from an earlier attempt would be")
    parser.add_argument("--report")
    parser.add_argument("--worker-cmd", help="a generated worker cmd file instead of running the stack")
    args = parser.parse_args(argv)
    repo = Path(args.repository_root).resolve()
    if bool(args.worker_cmd) == bool(stack_args):
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": "give either --worker-cmd or stack args after --"}))
        return 2
    stray = dict(item.split("=", 1) for item in args.stray if "=" in item)
    inherited: list[str] | None = None
    try:
        if args.worker_cmd:
            text = Path(args.worker_cmd).read_text(encoding="ascii")
        else:
            text, inherited = worker_cmd_from_stack(repo, stack_args, stray)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": str(exc)}))
        return 2
    cmd_env = parse_worker_cmd(text)
    if not cmd_env:
        print(json.dumps({"schema": SCHEMA, "ok": False, "error": "the worker cmd has no set lines"}))
        return 2
    report = boot(repo, Path(args.scratch), cmd_env, args.expect_path, args.status_true)
    if inherited is not None:
        report["inherited_kaliv"] = inherited
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "worker_log_tail"} if report["ok"] else report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

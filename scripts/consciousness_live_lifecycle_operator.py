#!/usr/bin/env python3
"""Run the whole consciousness_live_lifecycle gate (V1 gate 2) as one operator.

``docs/consciousness-core/LIVE_LIFECYCLE_QUALIFICATION.md`` describes about ten
manual steps: the live-cycle probe, a status capture, a worker restart, two
qualification snapshots around a profile swap, the snapshot adapter and the
qualifier. Done by hand, each response has to be saved byte for byte, the swap
must not cross a restart, and the profile must be put back afterwards. This
operator does those steps in that order and refuses as soon as one of them
does not hold.

What it does
------------
1. Checks that the worker answers on loopback and that the qualification
   snapshot is enabled, before anything runs.
2. Runs ``consciousness_live_cycle_probe.py`` against the clean checkout.
3. Saves ``/experimental/consciousness/status`` exactly as the worker sent it.
4. Asks the operator to restart the worker, then waits until
   ``runtime_instance_ref`` has changed and the first lived-continuity receipt
   is there. It never restarts, kills or starts a process itself.
5. Saves the pre-swap snapshot, writes the operator's swap profile over the
   profile file, saves the post-swap snapshot, and puts the original profile
   file back, byte for byte, also when a step fails.
6. Runs ``consciousness_live_lifecycle_from_snapshots.py`` and the qualifier.

Every worker response is written as received: no JSON round trip, so no
reformatting, no time-zone rewrite and no byte-order mark (#2390, F4).

What it does not do
-------------------
It activates nothing and sets no flag. The worker must already run with the
consciousness flags and ``KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1``
(START_DEV_APPLIANCE sets the first but not the second), with a SelfState, a
selected approved Person Revision, a profile file and a model in Ollama: lived
continuity after the restart comes from an autonomous tick, which calls the
model. The preflight names whatever of this the worker's status says is missing.
It does not decide whether the gate passed: the qualifier does, and the exit
code is the qualifier's verdict.

Run (from the clean candidate checkout, worker running)
-------------------------------------------------------
    python scripts\\consciousness_live_lifecycle_operator.py `
        --profile-file C:\\Kaliv\\data\\kaliv-consciousness-profile.json `
        --swap-profile C:\\Rig\\profile-swap.json

Exit code 0: QUALIFIED. 1: the qualifier refused. 2: a step failed before it.
"""
from __future__ import annotations

import sys

# Runs from the candidate checkout: leave no bytecode behind for the freeze gate.
sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DEFAULT_WORKER_URL = "http://127.0.0.1:8099"
STATUS_PATH = "/experimental/consciousness/status"
SNAPSHOT_PATH = "/experimental/consciousness/qualification-snapshot"
STATUS_SCHEMA = "kaliv-consciousness-core/runtime-status/v1"
SNAPSHOT_SCHEMA = "kaliv-consciousness-core/qualification-snapshot/v1"
RUN_SCHEMA = "kaliv-consciousness-core/live-lifecycle-operator-run/v1"
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_PROFILE_BYTES = 32 * 1024
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

FILES = {
    "live_cycle": "consciousness-live-cycle.json",
    "pre_restart_status": "consciousness-status-pre-restart.json",
    "pre_swap_snapshot": "consciousness-pre-swap.json",
    "post_swap_snapshot": "consciousness-post-swap.json",
    "profile_original": "profile-original.json",
    "profile_swap": "profile-swap.json",
    "qualifier_input": "consciousness-live-lifecycle-input.json",
    "qualifier_report": "consciousness-live-lifecycle-latest.json",
    "run_record": "operator-run.json",
}


class OperatorError(RuntimeError):
    """A step failed; nothing after it ran."""


# --------------------------------------------------------------------------
# Worker access: raw bytes only
# --------------------------------------------------------------------------

def normalize_worker_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK_HOSTS:
        raise OperatorError(
            f"worker URL must be http:// on loopback (127.0.0.1, localhost, ::1): {value!r}"
        )
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise OperatorError("worker URL must be a bare origin")
    if parsed.path not in ("", "/"):
        raise OperatorError("worker URL must be a bare origin, without a path")
    return value.strip().rstrip("/")


def fetch(url: str, *, timeout: float) -> tuple[int, bytes]:
    """GET ``url``; return the status and the body exactly as received.

    Returns status 0 when the worker cannot be reached (e.g. while it restarts).
    """
    request = urllib.request.Request(url, method="GET", headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - loopback only
            body = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read(MAX_RESPONSE_BYTES + 1)
        status = exc.code
    except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
        return 0, b""
    if len(body) > MAX_RESPONSE_BYTES:
        raise OperatorError(f"{url} answered with more than {MAX_RESPONSE_BYTES} bytes")
    return status, body


def parse_object(raw: bytes, name: str) -> dict[str, Any]:
    if raw.startswith(b"\xef\xbb\xbf"):
        raise OperatorError(f"{name} starts with a byte-order mark")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OperatorError(f"{name} is not UTF-8 JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise OperatorError(f"{name} is not a JSON object")
    return value


# status "enabled" key -> the flag that turns it on
REQUIRED_FLAGS = {
    "core": "KALIV_CONSCIOUSNESS_CORE_ENABLED",
    "supervisor": "KALIV_CONSCIOUSNESS_SUPERVISOR_ENABLED",
    "chat_admission": "KALIV_CONSCIOUSNESS_CHAT_ENABLED",
    "turn_cognition": "KALIV_CONSCIOUSNESS_TURN_COGNITION_ENABLED",
    "event_step": "KALIV_CONSCIOUSNESS_EVENT_STEP_ENABLED",
    "sleep_lifecycle": "KALIV_CONSCIOUSNESS_SLEEP_LIFECYCLE_ENABLED",
    "unplanned_liveness": "KALIV_CONSCIOUSNESS_UNPLANNED_LIVENESS_ENABLED",
    "policy_checkpoint": "KALIV_CONSCIOUSNESS_POLICY_CHECKPOINT_ENABLED",
    "autonomous_cognition": "KALIV_CONSCIOUSNESS_AUTONOMOUS_ENABLED",
    "autonomous_scheduler": "KALIV_CONSCIOUSNESS_AUTONOMOUS_SCHEDULER_ENABLED",
    "autonomous_checkpoint": "KALIV_CONSCIOUSNESS_AUTONOMOUS_CHECKPOINT_ENABLED",
    "continuous_loop": "KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED",
}
PREREQUISITES = {
    "self_state_present": "no SelfState (run python -m app.consciousness_core.dev_bootstrap from worker/)",
    "active_person_available": "no selected, approved active Person Revision",
    "cognitive_profile_available": "no CognitiveProfile file at KALIV_CONSCIOUSNESS_PROFILE_FILE",
}


def readiness_gaps(status: Mapping[str, Any]) -> list[str]:
    """What the worker's own status says is missing for this gate."""
    gaps: list[str] = []
    enabled = status.get("enabled") if isinstance(status.get("enabled"), Mapping) else {}
    off = [flag for key, flag in REQUIRED_FLAGS.items() if enabled.get(key) is not True]
    if off:
        gaps.append("flags not set to 1: " + ", ".join(off))
    prerequisites = status.get("prerequisites") if isinstance(status.get("prerequisites"), Mapping) else {}
    gaps.extend(text for key, text in PREREQUISITES.items() if prerequisites.get(key) is not True)
    mounted = status.get("mounted") if isinstance(status.get("mounted"), Mapping) else {}
    if not gaps and mounted.get("live_session") is not True:
        gaps.append("no live session is mounted (see the worker log)")
    if not gaps and mounted.get("autonomous_scheduler") is not True:
        # Measured 16/11: without it no autonomous tick runs, so lived
        # continuity never forms after the restart and the snapshot stays 409.
        gaps.append(
            "the autonomous scheduler is not mounted: the worker needs KALIV_SCHEDULER=1 "
            "(validation stack: -EnableScheduler)"
        )
    return gaps


def runtime_ref(value: Mapping[str, Any], name: str) -> str:
    ref = value.get("runtime_instance_ref")
    if not isinstance(ref, str) or not ref.startswith("runtime-instance:"):
        raise OperatorError(f"{name} has no runtime_instance_ref")
    return ref


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def write_new(path: Path, data: bytes) -> None:
    """Write a file that must not exist yet, completely or not at all."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            raise OperatorError(f"{path} already exists")
        os.replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()


def replace_bytes(path: Path, data: bytes) -> None:
    """Atomically give an existing file new bytes and check them."""
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    staged = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, path)
    finally:
        if staged.exists():
            staged.unlink()
    if path.read_bytes() != data:
        raise OperatorError(f"{path} does not read back as written")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# The operator
# --------------------------------------------------------------------------

def _python_command(script: str, *args: str) -> list[str]:
    return [sys.executable, "-B", str(SCRIPTS / script), *args]


def run_command(command: Sequence[str]) -> int:
    return subprocess.run(list(command), cwd=ROOT, check=False).returncode


def git_head(root: Path) -> str:
    proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False)
    sha = proc.stdout.strip()
    if proc.returncode != 0 or len(sha) != 40:
        raise OperatorError("the operator must run from a Git checkout of the candidate")
    return sha


def git_dirty(root: Path) -> list[str]:
    proc = subprocess.run(["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise OperatorError("the checkout's status could not be read")
    return [line for line in proc.stdout.splitlines() if line.strip()]


class Operator:
    def __init__(
        self,
        *,
        worker_url: str,
        out_dir: Path,
        profile_file: Path,
        swap_profile: Path,
        candidate_sha: str,
        keep_swapped_profile: bool = False,
        timeout: float = 10.0,
        restart_timeout: float = 900.0,
        continuity_timeout: float = 900.0,
        poll_interval: float = 2.0,
        fetch_fn: Callable[..., tuple[int, bytes]] = fetch,
        command_fn: Callable[[Sequence[str]], int] = run_command,
        prompt_fn: Callable[[str], Any] = input,
        say: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        dirty_fn: Callable[[], list[str]] = lambda: git_dirty(ROOT),
    ) -> None:
        self.base = normalize_worker_url(worker_url)
        self.out = out_dir
        self.profile_file = profile_file
        self.swap_profile = swap_profile
        self.candidate_sha = candidate_sha
        self.keep_swapped_profile = keep_swapped_profile
        self.timeout = timeout
        self.restart_timeout = restart_timeout
        self.continuity_timeout = continuity_timeout
        self.poll_interval = poll_interval
        self.fetch = fetch_fn
        self.command = command_fn
        self.prompt = prompt_fn
        self.say = say
        self.clock = clock
        self.sleep = sleep
        self.dirty = dirty_fn
        self.saved: dict[str, str] = {}

    def path(self, key: str) -> Path:
        return self.out / FILES[key]

    def save(self, key: str, data: bytes) -> None:
        write_new(self.path(key), data)
        self.saved[key] = sha256(data)

    def get(self, endpoint: str) -> tuple[int, bytes]:
        return self.fetch(self.base + endpoint, timeout=self.timeout)

    # -- steps -------------------------------------------------------------

    def preflight(self) -> tuple[bytes, bytes]:
        if len(self.candidate_sha) != 40 or any(c not in "0123456789abcdef" for c in self.candidate_sha):
            raise OperatorError("candidate SHA must be 40 lowercase hex characters")
        if self.out.exists():
            raise OperatorError(f"{self.out} already exists; every run gets a new directory")
        dirty = self.dirty()
        if dirty:
            raise OperatorError(
                "the checkout is not clean, so the live-cycle probe would refuse it: "
                + ", ".join(dirty[:5]) + (" ..." if len(dirty) > 5 else "")
            )
        original = self._read_profile(self.profile_file, "the profile file")
        swap = self._read_profile(self.swap_profile, "the swap profile")
        if swap == original:
            raise OperatorError("the swap profile is byte for byte the current profile; nothing would change")
        status, raw = self.get(STATUS_PATH)
        if status != 200:
            raise OperatorError(
                f"the worker's consciousness status did not answer HTTP 200 on {self.base} (got {status or 'no answer'})"
            )
        current = parse_object(raw, "status")
        if current.get("schema") != STATUS_SCHEMA:
            raise OperatorError("status has another schema")
        missing = readiness_gaps(current)
        if missing:
            raise OperatorError(
                "the worker is not ready for the lifecycle gate: " + "; ".join(missing)
            )
        status, _ = self.get(SNAPSHOT_PATH)
        if status == 404:
            raise OperatorError(
                "the qualification snapshot is disabled: start the worker with "
                "KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1"
            )
        if status not in (200, 409):
            raise OperatorError(f"the qualification snapshot answered HTTP {status or 'nothing'}")
        return original, swap

    @staticmethod
    def _read_profile(path: Path, name: str) -> bytes:
        if not path.is_file():
            raise OperatorError(f"{name} {path} is not a file")
        data = path.read_bytes()
        if not data or len(data) > MAX_PROFILE_BYTES:
            raise OperatorError(f"{name} {path} is empty or larger than {MAX_PROFILE_BYTES} bytes")
        parse_object(data, name)
        return data

    def live_cycle(self) -> None:
        self.out.mkdir(parents=True)
        report = self.path("live_cycle")
        code = self.command(_python_command(
            "consciousness_live_cycle_probe.py", "--worker-url", self.base, "--report", str(report),
        ))
        if code != 0 or not report.is_file():
            raise OperatorError(f"the live-cycle probe failed (exit {code}); see {report}")
        data = report.read_bytes()
        probe = parse_object(data, "the live-cycle report")
        if probe.get("candidate", {}).get("git_sha") != self.candidate_sha:
            raise OperatorError("the live-cycle report is bound to another commit than this checkout")
        self.saved["live_cycle"] = sha256(data)

    def capture_status(self) -> str:
        status, raw = self.get(STATUS_PATH)
        if status != 200:
            raise OperatorError(f"status answered HTTP {status or 'nothing'} before the restart")
        value = parse_object(raw, "status before the restart")
        if value.get("schema") != STATUS_SCHEMA:
            raise OperatorError("status before the restart has another schema")
        ref = runtime_ref(value, "status before the restart")
        self.save("pre_restart_status", raw)
        return ref

    def await_restart(self, before: str) -> str:
        self.say(
            "\nRestart the worker now, with the same environment (all consciousness flags and "
            "KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1)."
        )
        self.prompt("Press Enter when you have started it again: ")
        deadline = self.clock() + self.restart_timeout
        while True:
            status, raw = self.get(STATUS_PATH)
            if status == 200:
                after = runtime_ref(parse_object(raw, "status after the restart"), "status after the restart")
                if after != before:
                    return after
            if self.clock() >= deadline:
                raise OperatorError(
                    "the worker's runtime_instance_ref did not change: a restart is not proven"
                )
            self.sleep(self.poll_interval)

    def await_snapshot(self, runtime: str) -> bytes:
        deadline = self.clock() + self.continuity_timeout
        while True:
            status, raw = self.get(SNAPSHOT_PATH)
            if status == 200:
                value = parse_object(raw, "the pre-swap snapshot")
                if value.get("schema") != SNAPSHOT_SCHEMA:
                    raise OperatorError("the pre-swap snapshot has another schema")
                if runtime_ref(value, "the pre-swap snapshot") != runtime:
                    raise OperatorError("the worker restarted again before the pre-swap snapshot")
                return raw
            if status == 404:
                raise OperatorError(
                    "the qualification snapshot is disabled after the restart: the worker was "
                    "started without KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1"
                )
            if self.clock() >= deadline:
                raise OperatorError(
                    f"no lived-continuity snapshot after the restart (last HTTP {status or 'nothing'})"
                )
            self.sleep(self.poll_interval)

    def swap(self, original: bytes, swap_bytes: bytes, pre_swap: bytes, runtime: str) -> None:
        self.save("profile_original", original)
        self.save("profile_swap", swap_bytes)
        if self.profile_file.read_bytes() != original:
            raise OperatorError("the profile file changed during the run; it is left as it is")
        before_profile = parse_object(pre_swap, "the pre-swap snapshot").get("cognitive_profile")
        try:
            replace_bytes(self.profile_file, swap_bytes)
            status, raw = self.get(SNAPSHOT_PATH)
            if status != 200:
                raise OperatorError(
                    f"the snapshot after the swap answered HTTP {status or 'nothing'}; "
                    "the worker probably refused the swap profile"
                )
            value = parse_object(raw, "the post-swap snapshot")
            if value.get("schema") != SNAPSHOT_SCHEMA:
                raise OperatorError("the post-swap snapshot has another schema")
            if runtime_ref(value, "the post-swap snapshot") != runtime:
                raise OperatorError("the worker restarted during the model swap")
            if value.get("cognitive_profile") == before_profile:
                raise OperatorError("the worker still reports the old CognitiveProfile; the swap was not observed")
            self.save("post_swap_snapshot", raw)
        finally:
            conflict = False
            if not self.keep_swapped_profile:
                conflict = not self._restore_profile(original, swap_bytes)
        if conflict:
            raise OperatorError(
                "the profile file was changed by someone else during the swap; it is left as it is"
            )

    def _restore_profile(self, original: bytes, swap_bytes: bytes) -> bool:
        """Put the original back without ever replacing another writer's file.

        Codex P2 and ChatGPT's follow-up on #2407: compare-then-replace still
        loses an update written between the comparison and the replace. So:

        1. the current file is moved aside in one atomic rename, which captures
           exactly what was there, and a writer after it creates a new file;
        2. the captured bytes are compared with the operator's swap;
        3. the original (or, on a conflict, the captured file) is published
           with a no-replace link or rename, so a file that appeared since step 1
           always wins.

        No path is ever replaced, so no completed write is lost. The profile is
        briefly absent between steps 1 and 3; the snapshots are taken by then.
        Limit: a writer that rewrites the file in place (not atomically) while
        it is held open is outside this guarantee. On Windows the rename then
        fails, and that is reported as a conflict.
        Returns False on a conflict.
        """
        path = self.profile_file
        aside = path.with_name(f".{path.name}.operator-restore-{os.getpid()}")
        try:
            os.rename(path, aside)
        except FileNotFoundError:
            self.say(f"Profile file NOT restored: it was removed during the swap: {path}")
            return False
        except OSError as exc:
            self.say(f"Profile file NOT restored: it could not be captured ({exc}): {path}")
            return False
        self._after_capture()
        captured = aside.read_bytes()
        if captured == swap_bytes:
            outcome = self._publish_no_replace(original, path)
            if outcome:
                aside.unlink()
                self.say(f"Profile file restored: {path}")
                return True
            aside.unlink()
            self.say(f"Profile file NOT restored: someone else wrote it during the restore: {path}")
            return False
        # Someone else's content: put it back where it was, unless they wrote again.
        if not self._link_no_replace(aside, path):
            self.say(f"Profile file NOT restored: someone else changed it during the swap; "
                     f"their earlier version is kept at {aside}: {path}")
            return False
        aside.unlink()
        if captured == original:
            return True
        self.say(f"Profile file NOT restored: someone else changed it during the swap: {path}")
        return False

    def _after_capture(self) -> None:
        """Seam for tests: runs between the capture and the publication."""

    @staticmethod
    def _link_no_replace(source: Path, target: Path) -> bool:
        """Give target source's bytes unless target exists. True if published."""
        try:
            os.link(source, target)
            return True
        except FileExistsError:
            return False
        except OSError:
            if os.name != "nt":
                raise
        try:
            data = source.read_bytes()
            with open(target, "xb") as handle:  # NTFS without links: exclusive create
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            return True
        except FileExistsError:
            return False

    def _publish_no_replace(self, data: bytes, target: Path) -> bool:
        descriptor, name = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
        staged = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            return self._link_no_replace(staged, target)
        finally:
            staged.unlink(missing_ok=True)

    def qualify(self) -> int:
        code = self.command(_python_command(
            "consciousness_live_lifecycle_from_snapshots.py",
            "--candidate-sha", self.candidate_sha,
            "--live-cycle", str(self.path("live_cycle")),
            "--pre-restart-status", str(self.path("pre_restart_status")),
            "--pre-swap-snapshot", str(self.path("pre_swap_snapshot")),
            "--post-swap-snapshot", str(self.path("post_swap_snapshot")),
            "--output", str(self.path("qualifier_input")),
        ))
        if code != 0 or not self.path("qualifier_input").is_file():
            raise OperatorError(f"assembling the qualifier input failed (exit {code})")
        self.saved["qualifier_input"] = sha256(self.path("qualifier_input").read_bytes())
        code = self.command(_python_command(
            "consciousness_live_lifecycle_qualifier.py",
            str(self.path("qualifier_input")),
            "--report", str(self.path("qualifier_report")),
        ))
        if not self.path("qualifier_report").is_file():
            raise OperatorError(f"the qualifier wrote no report (exit {code})")
        report = parse_object(self.path("qualifier_report").read_bytes(), "the qualifier report")
        self.saved["qualifier_report"] = sha256(self.path("qualifier_report").read_bytes())
        qualified = (
            code == 0
            and report.get("state") == "QUALIFIED"
            and report.get("consciousness_live_lifecycle_gate_satisfied") is True
        )
        return 0 if qualified else 1

    def record(self, verdict: str, error: str | None) -> None:
        if not self.out.is_dir():
            return
        record = {
            "schema": RUN_SCHEMA,
            "finished_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "candidate_git_sha": self.candidate_sha,
            "worker_url": self.base,
            "profile_file": str(self.profile_file),
            "profile_restored": not self.keep_swapped_profile,
            "verdict": verdict,
            "error": error,
            "files_sha256": dict(sorted(self.saved.items())),
            "production_activation": False,
        }
        write_new(self.path("run_record"), (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def run(self) -> int:
        try:
            original, swap_bytes = self.preflight()
            self.say(f"Candidate {self.candidate_sha}; evidence goes to {self.out}")
            self.say("1/5 live-cycle probe")
            self.live_cycle()
            self.say("2/5 status before the restart")
            before = self.capture_status()
            self.say("3/5 worker restart")
            after = self.await_restart(before)
            self.say("4/5 lived continuity after the restart, then the model swap")
            pre_swap = self.await_snapshot(after)
            self.save("pre_swap_snapshot", pre_swap)
            self.swap(original, swap_bytes, pre_swap, after)
            self.say("5/5 assembly and qualifier")
            code = self.qualify()
        except OperatorError as exc:
            self.say(f"STOPPED: {exc}")
            self.record("STOPPED", str(exc))
            return 2
        verdict = "QUALIFIED" if code == 0 else "REFUSED"
        self.record(verdict, None)
        self.say(f"{verdict}: {self.path('qualifier_report')}")
        return code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--profile-file", type=Path, required=True,
                        help="the CognitiveProfile file the worker reads (KALIV_CONSCIOUSNESS_PROFILE_FILE)")
    parser.add_argument("--swap-profile", type=Path, required=True,
                        help="the profile to swap to; only the model calibration should differ")
    parser.add_argument("--worker-url", default=DEFAULT_WORKER_URL)
    parser.add_argument("--out", type=Path, default=None,
                        help="new directory for this run (default validation/consciousness-lifecycle/<UTC time>)")
    parser.add_argument("--keep-swapped-profile", action="store_true",
                        help="leave the swap profile in place instead of restoring the original")
    parser.add_argument("--restart-timeout", type=float, default=900.0)
    parser.add_argument("--continuity-timeout", type=float, default=900.0)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or (ROOT / "validation" / "consciousness-lifecycle" / stamp)
    try:
        operator = Operator(
            worker_url=args.worker_url,
            out_dir=out,
            profile_file=args.profile_file,
            swap_profile=args.swap_profile,
            candidate_sha=git_head(ROOT),
            keep_swapped_profile=args.keep_swapped_profile,
            restart_timeout=args.restart_timeout,
            continuity_timeout=args.continuity_timeout,
        )
    except OperatorError as exc:
        print(f"STOPPED: {exc}")
        return 2
    return operator.run()


if __name__ == "__main__":
    raise SystemExit(main())

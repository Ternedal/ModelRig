#!/usr/bin/env python3
"""Contract for scripts/consciousness_live_lifecycle_operator.py (V1 gate 2).

A fake worker serves the two loopback routes over real HTTP, so the operator's
own fetch path is exercised. The probe, the snapshot adapter and the qualifier
are replaced by recorders; their command lines are checked against the real
scripts' argument parsers.

Run: python3 tests/workflow_consciousness_live_lifecycle_operator.py
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

sys.dont_write_bytecode = True

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "consciousness_live_lifecycle_operator.py"
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402
SPEC = importlib.util.spec_from_file_location("consciousness_lifecycle_operator", SCRIPT)
assert SPEC and SPEC.loader
op = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = op
SPEC.loader.exec_module(op)

SHA = "c" * 40
REF_A = "runtime-instance:" + "a" * 32
REF_B = "runtime-instance:" + "b" * 32
REF_C = "runtime-instance:" + "d" * 32
PROFILE_A = b'{"schema": "kaliv-consciousness-core/cognitive-profile-config/v1", "model": "qwen3:14b"}\n'
PROFILE_B = b'{"schema": "kaliv-consciousness-core/cognitive-profile-config/v1", "model": "gemma3:12b"}\n'

CHECKS = 0
FAILED: list[str] = []


def check(condition: bool, label: str) -> None:
    global CHECKS
    CHECKS += 1
    if not condition:
        FAILED.append(label)
        print(f"  FAIL: {label}")


READY = (
    '"enabled":{' + ",".join(f'"{k}":true' for k in op.REQUIRED_FLAGS) + '},'
    '"mounted":{"supervisor":true,"live_session":true,"autonomous_scheduler":true},'
    '"prerequisites":{"self_state_present":true,"active_person_available":true,"cognitive_profile_available":true},'
)


def status_bytes(ref: str, ready: str = READY) -> bytes:
    # Deliberately odd formatting and a +00:00 offset: saved files must keep it.
    return (
        '{ "schema" : "kaliv-consciousness-core/runtime-status/v1",\n'
        f'  "runtime_instance_ref":"{ref}", {ready} "at": "2026-11-16T10:00:00+00:00" ,"production_activation":false}}'
    ).encode()


def snapshot_bytes(ref: str, model: str) -> bytes:
    return (
        '{"schema":"kaliv-consciousness-core/qualification-snapshot/v1", '
        f'"runtime_instance_ref":"{ref}","wake_receipt":{{}},"session_bootstrap_receipt":{{}},'
        f'"self_state":{{}},"cognitive_profile":{{"model":"{model}"}},"lived_continuity":{{}},'
        '"at":"2026-11-16T10:05:00+00:00",   "production_activation":false}'
    ).encode()


class FakeWorker:
    """The worker as the operator sees it, with a scriptable restart."""

    def __init__(self, profile_file: Path) -> None:
        self.profile_file = profile_file
        self.ref = REF_A
        self.snapshot_enabled = True
        self.continuity_after: int = 1   # snapshot answers 409 this many times after a restart
        self._pending = 0
        self.restart_during_swap = False
        self.ignore_profile = False
        self.restart_again = False      # a second restart while continuity forms
        self.ready = READY
        self.served: dict[str, list[bytes]] = {"status": [], "snapshot": []}
        worker = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:
                pass

            def do_GET(self) -> None:  # noqa: N802
                code, body = worker.answer(self.path)
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def restart(self) -> None:
        self.ref = REF_B
        self._pending = self.continuity_after

    def answer(self, path: str) -> tuple[int, bytes]:
        if path == op.STATUS_PATH:
            body = status_bytes(self.ref, self.ready)
            self.served["status"].append(body)
            return 200, body
        if path == op.SNAPSHOT_PATH:
            if not self.snapshot_enabled:
                return 404, b'{"detail":"Consciousness qualification evidence is disabled"}'
            if self.ref == REF_A or self._pending > 0:
                self._pending = max(0, self._pending - 1)
                if self._pending == 0 and self.restart_again:
                    self.ref = REF_C
                return 409, b'{"detail":"lived continuity unavailable"}'
            current = self.profile_file.read_bytes()
            if current == PROFILE_B and self.restart_during_swap:
                self.ref = REF_C
            model = json.loads(current)["model"] if not self.ignore_profile else "qwen3:14b"
            if self.ignore_profile and current == PROFILE_B:
                model = "qwen3:14b"
            body = snapshot_bytes(self.ref, model)
            self.served["snapshot"].append(body)
            return 200, body
        return 404, b"{}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


class Commands:
    """Stand-ins for the probe, the adapter and the qualifier."""

    def __init__(self, *, probe_sha: str = SHA, probe_code: int = 0, qualified: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.probe_sha = probe_sha
        self.probe_code = probe_code
        self.qualified = qualified
        self.on_probe: Callable[[], None] | None = None

    def __call__(self, command: list[str]) -> int:
        self.calls.append(list(command))
        script = Path(command[2]).name
        args = command[3:]

        def value(flag: str) -> str:
            return args[args.index(flag) + 1]

        if script == "consciousness_live_cycle_probe.py":
            if self.on_probe:
                self.on_probe()
            Path(value("--report")).write_text(json.dumps({"candidate": {"git_sha": self.probe_sha}}))
            return self.probe_code
        if script == "consciousness_live_lifecycle_from_snapshots.py":
            Path(value("--output")).write_text('{"assembled": true}')
            return 0
        if script == "consciousness_live_lifecycle_qualifier.py":
            state = "QUALIFIED" if self.qualified else "INVALID"
            Path(value("--report")).write_text(json.dumps({
                "state": state, "consciousness_live_lifecycle_gate_satisfied": self.qualified,
            }))
            return 0 if self.qualified else 1
        raise AssertionError(f"unexpected command {command}")


class Run:
    def __init__(self, tmp: Path, **worker_options: Any) -> None:
        self.tmp = tmp
        self.profile = tmp / "kaliv-consciousness-profile.json"
        self.profile.write_bytes(PROFILE_A)
        self.swap = tmp / "swap.json"
        self.swap.write_bytes(PROFILE_B)
        self.out = tmp / "run"
        self.worker = FakeWorker(self.profile)
        for key, val in worker_options.items():
            setattr(self.worker, key, val)
        self.commands = Commands()
        self.said: list[str] = []
        self.prompts = 0

    def prompt(self, _text: str) -> None:
        self.prompts += 1
        self.worker.restart()

    def operator(self, **options: Any) -> Any:
        settings: dict[str, Any] = dict(
            worker_url=self.worker.url, out_dir=self.out, profile_file=self.profile,
            swap_profile=self.swap, candidate_sha=SHA, command_fn=self.commands,
            prompt_fn=self.prompt, say=self.said.append, poll_interval=0.0,
            restart_timeout=2.0, continuity_timeout=2.0, dirty_fn=lambda: [],
        )
        settings.update(options)
        return op.Operator(**settings)

    def go(self, **options: Any) -> int:
        try:
            return self.operator(**options).run()
        finally:
            self.worker.close()

    def text(self) -> str:
        return "\n".join(self.said)

    def record(self) -> dict[str, Any]:
        return json.loads((self.out / op.FILES["run_record"]).read_bytes())

    def scripts_called(self) -> list[str]:
        return [Path(c[2]).name for c in self.commands.calls]


def case(fn: Callable[[Run], None], **worker_options: Any) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        fn(Run(Path(tmp), **worker_options))


# --------------------------------------------------------------------------

def a_full_run_qualifies_and_saves_raw_bytes(r: Run) -> None:
    code = r.go()
    check(code == 0, f"a full run exits 0: {r.text()}")
    check(r.prompts == 1, "the operator asks for exactly one restart")
    saved = (r.out / op.FILES["pre_restart_status"]).read_bytes()
    check(saved == status_bytes(REF_A), "the pre-restart status is the response byte for byte")
    check(b"+00:00" in saved and b'{ "schema" :' in saved, "no reformatting, no time-zone rewrite")
    check((r.out / op.FILES["pre_swap_snapshot"]).read_bytes() == snapshot_bytes(REF_B, "qwen3:14b"),
          "the pre-swap snapshot is byte for byte, from the restarted runtime")
    check((r.out / op.FILES["post_swap_snapshot"]).read_bytes() == snapshot_bytes(REF_B, "gemma3:12b"),
          "the post-swap snapshot is byte for byte, same runtime, new profile")
    check(r.profile.read_bytes() == PROFILE_A, "the original profile file is restored byte for byte")
    check((r.out / op.FILES["profile_original"]).read_bytes() == PROFILE_A, "the original profile is kept with the evidence")
    check(r.scripts_called() == [
        "consciousness_live_cycle_probe.py",
        "consciousness_live_lifecycle_from_snapshots.py",
        "consciousness_live_lifecycle_qualifier.py",
    ], f"probe, adapter, qualifier in that order: {r.scripts_called()}")
    adapter = r.commands.calls[1]
    check(adapter[adapter.index("--candidate-sha") + 1] == SHA, "the adapter gets the candidate SHA")
    record = r.record()
    check(record["verdict"] == "QUALIFIED" and record["production_activation"] is False, "the run record says QUALIFIED")
    for key in ("live_cycle", "pre_restart_status", "pre_swap_snapshot", "post_swap_snapshot",
                "qualifier_input", "qualifier_report"):
        data = (r.out / op.FILES[key]).read_bytes()
        check(record["files_sha256"].get(key) == op.sha256(data), f"the run record binds {key}")
    leftovers = [p.name for p in r.tmp.rglob("*.tmp")]
    check(not leftovers, f"no temporary files left: {leftovers}")


def the_qualifier_decides_the_exit_code(r: Run) -> None:
    r.commands.qualified = False
    code = r.go()
    check(code == 1, "a refused qualifier gives exit 1")
    check(r.record()["verdict"] == "REFUSED", "and the record says REFUSED")
    check(r.profile.read_bytes() == PROFILE_A, "the profile is restored")


def a_disabled_snapshot_stops_before_the_probe(r: Run) -> None:
    code = r.go()
    check(code == 2, "exit 2")
    check("KALIV_CONSCIOUSNESS_QUALIFICATION_EVIDENCE_ENABLED=1" in r.text(), "names the missing flag")
    check(not r.commands.calls, "the probe never ran")
    check(not r.out.exists(), "no evidence directory is created")


def an_unready_worker_is_named_before_the_probe(r: Run) -> None:
    r.worker.ready = READY.replace('"continuous_loop":true', '"continuous_loop":false').replace(
        '"self_state_present":true', '"self_state_present":false')
    code = r.go()
    check(code == 2, "exit 2")
    check("KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED" in r.text(), f"names the missing flag: {r.text()}")
    check("no SelfState" in r.text() and "dev_bootstrap" in r.text(), "names the missing SelfState and how to make it")
    check("KALIV_CONSCIOUSNESS_CORE_ENABLED" not in r.text(), "and only what is missing")
    check(not r.commands.calls and not r.out.exists(), "nothing ran, nothing written")


def no_live_session_is_named(r: Run) -> None:
    r.worker.ready = READY.replace('"live_session":true', '"live_session":false')
    code = r.go()
    check(code == 2 and "no live session is mounted" in r.text(), r.text())


def no_restart_is_refused(r: Run) -> None:
    r.prompt = lambda _text: None  # type: ignore[method-assign]
    code = r.go()
    check(code == 2 and "restart is not proven" in r.text(), f"an unchanged runtime ref is refused: {r.text()}")
    check(r.scripts_called() == ["consciousness_live_cycle_probe.py"], "nothing after the probe ran")
    check(not (r.out / op.FILES["pre_swap_snapshot"]).exists(), "no snapshot is saved")
    check(r.profile.read_bytes() == PROFILE_A, "the profile is never touched")
    check(r.record()["verdict"] == "STOPPED", "the record says STOPPED")


def waiting_for_lived_continuity(r: Run) -> None:
    code = r.go()
    check(code == 0, f"409s while continuity forms are waited out: {r.text()}")


def continuity_that_never_forms_is_refused(r: Run) -> None:
    code = r.go()
    check(code == 2 and "no lived-continuity snapshot" in r.text(), r.text())
    check(r.profile.read_bytes() == PROFILE_A, "the profile is never touched")


def a_restart_during_the_swap_is_refused(r: Run) -> None:
    code = r.go()
    check(code == 2 and "restarted during the model swap" in r.text(), r.text())
    check(not (r.out / op.FILES["post_swap_snapshot"]).exists(), "the post-swap snapshot is not saved")
    check(r.profile.read_bytes() == PROFILE_A, "the profile is restored after the failed swap")


def a_second_restart_before_the_snapshot_is_refused(r: Run) -> None:
    code = r.go()
    check(code == 2 and "restarted again before the pre-swap snapshot" in r.text(), r.text())
    check(not (r.out / op.FILES["pre_swap_snapshot"]).exists(), "no pre-swap snapshot is saved")
    check(r.profile.read_bytes() == PROFILE_A, "the profile is never touched")


def an_unobserved_swap_is_refused(r: Run) -> None:
    code = r.go()
    check(code == 2 and "swap was not observed" in r.text(), r.text())
    check(r.profile.read_bytes() == PROFILE_A, "the profile is restored")
    check("consciousness_live_lifecycle_from_snapshots.py" not in r.scripts_called(), "no assembly")


def keep_swapped_profile_leaves_it(r: Run) -> None:
    code = r.go(keep_swapped_profile=True)
    check(code == 0 and r.profile.read_bytes() == PROFILE_B, "--keep-swapped-profile leaves the swap in place")
    check(r.record()["profile_restored"] is False, "and the record says so")


def a_probe_for_another_commit_is_refused(r: Run) -> None:
    r.commands.probe_sha = "e" * 40
    code = r.go()
    check(code == 2 and "another commit" in r.text(), r.text())
    check(r.prompts == 0, "the operator never asks for a restart")


def a_failing_probe_stops(r: Run) -> None:
    r.commands.probe_code = 1
    code = r.go()
    check(code == 2 and "live-cycle probe failed" in r.text(), r.text())


def a_profile_changed_by_someone_else_is_left_alone(r: Run) -> None:
    third = b'{"model": "someone-else"}\n'
    real_prompt = r.prompt

    def prompt(text: str) -> None:
        r.profile.write_bytes(third)
        real_prompt(text)

    r.prompt = prompt  # type: ignore[method-assign]
    code = r.go()
    check(code == 2 and "profile file changed during the run" in r.text(), r.text())
    check(r.profile.read_bytes() == third, "another writer's profile is not overwritten")


def refusals_before_anything_runs(tmp: Path) -> None:
    profile = tmp / "p.json"
    profile.write_bytes(PROFILE_A)
    same = tmp / "same.json"
    same.write_bytes(PROFILE_A)
    swap = tmp / "s.json"
    swap.write_bytes(PROFILE_B)
    bom = tmp / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + PROFILE_B)
    base = dict(out_dir=tmp / "out", profile_file=profile, swap_profile=swap, candidate_sha=SHA, dirty_fn=lambda: [],
                command_fn=lambda c: (_ for _ in ()).throw(AssertionError("ran")), say=lambda _s: None)
    for url in ("http://192.168.1.10:8099", "https://127.0.0.1:8099", "http://127.0.0.1:8099/x",
                "http://user@127.0.0.1:8099", "http://example.com"):
        try:
            op.Operator(worker_url=url, **base)
        except op.OperatorError:
            check(True, f"refuses {url}")
        else:
            check(False, f"refuses {url}")

    def refused(label: str, needle: str, **changes: Any) -> None:
        settings = dict(base, worker_url="http://127.0.0.1:9", fetch_fn=lambda *_a, **_k: (0, b""))
        settings.update(changes)
        said: list[str] = []
        settings["say"] = said.append
        code = op.Operator(**settings).run()
        text = "\n".join(said)
        check(code == 2 and needle in text, f"{label}: {text}")

    refused("same profile", "nothing would change", swap_profile=same)
    refused("BOM swap profile", "byte-order mark", swap_profile=bom)
    refused("short SHA", "40 lowercase hex", candidate_sha="abc")
    refused("worker down", "did not answer HTTP 200")
    refused("dirty checkout", "the checkout is not clean", dirty_fn=lambda: ["?? stray.txt"])
    (tmp / "exists").mkdir()
    refused("reused directory", "every run gets a new directory", out_dir=tmp / "exists")
    check(profile.read_bytes() == PROFILE_A, "a refused run never touches the profile")


def command_lines_match_the_real_scripts(r: Run) -> None:
    r.go()
    for command in r.commands.calls:
        script = Path(command[2])
        check(script.is_file(), f"{script.name} exists")
        check(command[:2] == [sys.executable, "-B"], f"{script.name} runs without bytecode")
        flags = [a for a in command[3:] if a.startswith("--")]
        proc = subprocess.run([sys.executable, "-B", str(script), "--help"], capture_output=True,
                              text=True, cwd=ROOT, timeout=60)
        check(proc.returncode == 0, f"{script.name} --help works")
        missing = [f for f in flags if f not in proc.stdout]
        check(not missing, f"{script.name} accepts {flags}: missing {missing}")


def the_module_runs_without_bytecode(_r: Run) -> None:
    check(op.sys.dont_write_bytecode is True, "the operator sets dont_write_bytecode")
    proc = subprocess.run([sys.executable, str(SCRIPT), "--help"], capture_output=True, text=True,
                          cwd=ROOT, timeout=60)
    check(proc.returncode == 0 and "--swap-profile" in proc.stdout, "--help works")
    check(not list((ROOT / "scripts" / "__pycache__").glob("consciousness_live_lifecycle_operator*")),
          "no bytecode for the operator")


def the_runbook_points_at_the_operator(_r: Run) -> None:
    doc = code_of(ROOT / "docs" / "consciousness-core" / "LIVE_LIFECYCLE_QUALIFICATION.md")
    check("consciousness_live_lifecycle_operator.py" in doc, "the runbook names the operator")
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    check("/validation/consciousness-lifecycle/" in ignored,
          "run directories are ignored, so a second run's probe still sees a clean tree")


def main() -> None:
    case(a_full_run_qualifies_and_saves_raw_bytes)
    case(the_qualifier_decides_the_exit_code)
    case(a_disabled_snapshot_stops_before_the_probe, snapshot_enabled=False)
    case(an_unready_worker_is_named_before_the_probe)
    case(no_live_session_is_named)
    case(no_restart_is_refused)
    case(waiting_for_lived_continuity, continuity_after=3)
    case(continuity_that_never_forms_is_refused, continuity_after=10**9)
    case(a_restart_during_the_swap_is_refused, restart_during_swap=True)
    case(a_second_restart_before_the_snapshot_is_refused, restart_again=True)
    case(an_unobserved_swap_is_refused, ignore_profile=True)
    case(keep_swapped_profile_leaves_it)
    case(a_probe_for_another_commit_is_refused)
    case(a_failing_probe_stops)
    case(a_profile_changed_by_someone_else_is_left_alone)
    with tempfile.TemporaryDirectory() as tmp:
        refusals_before_anything_runs(Path(tmp))
    case(command_lines_match_the_real_scripts)
    case(the_module_runs_without_bytecode)
    case(the_runbook_points_at_the_operator)
    if FAILED:
        print(f"===== CONSCIOUSNESS LIFECYCLE OPERATOR: {CHECKS - len(FAILED)} passed, {len(FAILED)} failed =====")
        raise SystemExit(1)
    print(f"===== CONSCIOUSNESS LIFECYCLE OPERATOR: {CHECKS} passed, 0 failed =====")


if __name__ == "__main__":
    main()

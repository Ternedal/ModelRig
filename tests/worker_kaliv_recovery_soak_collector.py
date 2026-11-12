#!/usr/bin/env python3
"""Contract for scripts/kaliv_recovery_soak_collector.py.

The collector produces the observations file the recovery_soak qualifier
validates. The tests drive it against real loopback HTTP servers and a real
heartbeat file, and every assembled file is handed to the real qualifier,
including through its command line.

Run: python3 tests/worker_kaliv_recovery_soak_collector.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


collector = _load(
    "kaliv_recovery_soak_collector", ROOT / "scripts" / "kaliv_recovery_soak_collector.py"
)
# The qualifier's own contract supplies a Stage-B report the qualifier accepts,
# and stubs for the parts that need a rig (the freeze check, the checkout).
contract = _load(
    "kaliv_recovery_soak_collector_contract_support",
    ROOT / "tests" / "support" / "kaliv_recovery_soak_qualification_contract.py",
)
gate = contract.gate

passed = 0


def check(condition: bool, label: str) -> None:
    global passed
    assert condition, label
    passed += 1


def refused(call, fragment: str, label: str) -> None:
    try:
        call()
    except collector.CollectorError as exc:
        check(fragment in str(exc), f"{label}: wanted {fragment!r}, got {str(exc)!r}")
    else:
        raise AssertionError(f"{label}: accepted, wanted {fragment!r}")


# --------------------------------------------------------------------------
# A fake appliance on loopback
# --------------------------------------------------------------------------

class _Appliance:
    def __init__(self) -> None:
        self.backend = {"status": 200, "body": {"status": "ok", "version": "2.0.14"}}
        self.worker = {"status": 200, "body": {"status": "ok", "version": "2.0.14"}}
        self.full = {
            "status": 200,
            "body": {
                "ok": True,
                "faults": [],
                "build": {"commit_sha": "a" * 40},
                "checks": {"tools": {"ok": True}},
            },
        }
        self.servers: list[ThreadingHTTPServer] = []

    def _serve(self, routes: dict) -> str:
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                answer = routes.get(self.path)
                if answer is None:
                    self.send_error(404)
                    return
                answer = answer()
                raw = answer["body"]
                data = raw if isinstance(raw, bytes) else json.dumps(raw).encode("utf-8")
                self.send_response(answer["status"])
                for key, value in answer.get("headers", {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def start(self) -> tuple[str, str]:
        backend = self._serve({"/healthz": lambda: self.backend})
        worker = self._serve(
            {"/healthz": lambda: self.worker, "/health/full": lambda: self.full}
        )
        return backend, worker

    def stop(self) -> None:
        for server in self.servers:
            server.shutdown()
            server.server_close()


class _Heartbeat:
    """A heartbeat file that advances every time the probe sleeps, the way a
    looping supervisor's does while the probe watches it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.value = 1_700_000_000_000
        self.advancing = True
        self.path.write_text(str(self.value), encoding="ascii")

    def sleep(self, _seconds: float) -> None:
        if self.advancing:
            self.value += 10_000
            self.path.write_text(str(self.value), encoding="ascii")


def test_probe(tmp: Path) -> None:
    appliance = _Appliance()
    backend, worker = appliance.start()
    heartbeat = _Heartbeat(tmp / "supervisor-heartbeat")
    stamp = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)

    def take() -> dict:
        return collector.probe(
            backend_url=backend,
            worker_url=worker,
            heartbeat=heartbeat.path,
            heartbeat_settle_seconds=3,
            now=lambda: stamp,
            sleep=heartbeat.sleep,
        )

    try:
        record = take()
        check(set(record) == collector._PROBE_KEYS, "a probe carries exactly the journal keys")
        check(record["schema"] == collector.PROBE_SCHEMA, "probe schema")
        check(record["observed_at"] == "2026-09-29T10:00:00+00:00", "probe is stamped in UTC")
        check(all(record[name] is True for name in collector.HEALTH_FIELDS), "healthy appliance")
        check(record["detail"]["backend_version"] == "2.0.14", "backend version is recorded")
        check(record["detail"]["worker_commit_sha"] == "a" * 40, "worker commit is recorded")

        appliance.backend = {"status": 503, "body": {"status": "ok"}}
        record = take()
        check(record["backend_healthy"] is False, "a 503 backend is not healthy")
        check(record["worker_healthy"] is True, "the worker is judged on its own")
        appliance.backend = {"status": 200, "body": {"status": "starting", "version": "2.0.14"}}
        check(take()["backend_healthy"] is False, "200 without status ok is not healthy")
        appliance.backend = {"status": 200, "body": b"not json"}
        check(take()["backend_healthy"] is False, "a body that is not JSON is not healthy")
        appliance.backend = {
            "status": 302,
            "body": {"status": "ok"},
            "headers": {"Location": worker + "/healthz"},
        }
        check(take()["backend_healthy"] is False, "a redirect to a healthy service is not health")
        appliance.backend = {"status": 200, "body": {"status": "ok", "version": "2.0.14"}}

        appliance.worker = {"status": 503, "body": {"status": "ok", "version": "2.0.14"}}
        record = take()
        check(record["worker_healthy"] is False, "a worker whose /healthz fails is not healthy")
        check(record["state_error_absent"] is True, "even while /health/full still answers")
        appliance.worker = {"status": 200, "body": {"status": "ok", "version": "2.0.14"}}

        appliance.full["body"] = {
            "ok": False,
            "faults": ["ollama"],
            "build": {"commit_sha": "a" * 40},
            "checks": {"tools": {"ok": True}},
        }
        record = take()
        check(record["worker_healthy"] is False, "a fault in /health/full is not healthy")
        check(record["state_error_absent"] is True, "no state error while tools is ok")
        check(record["detail"]["faults"] == ["ollama"], "the fault is named in the journal")

        appliance.full["body"] = {
            "ok": False,
            "faults": ["tools"],
            "checks": {"tools": {"ok": False}},
        }
        check(take()["state_error_absent"] is False, "a tool-gate state error is recorded")
        appliance.full["body"] = {"ok": True, "faults": [], "checks": {}}
        check(take()["state_error_absent"] is False, "no tools check means it cannot be told")
        appliance.full = {"status": 500, "body": {"ok": True, "checks": {"tools": {"ok": True}}}}
        record = take()
        check(record["state_error_absent"] is False, "a failing /health/full proves nothing")
        check(record["worker_healthy"] is False, "and the worker is not healthy either")
        appliance.full = {
            "status": 200,
            "body": {"ok": True, "faults": [], "checks": {"tools": {"ok": True}}},
        }

        heartbeat.advancing = False
        record = take()
        check(record["supervisor_looping"] is False, "a heartbeat that stands still is red")
        check("did not advance" in record["detail"]["heartbeat"], "and the journal says why")
        heartbeat.path.unlink()
        check(take()["supervisor_looping"] is False, "a missing heartbeat is red")
        heartbeat.path.write_text("", encoding="ascii")
        check(take()["supervisor_looping"] is False, "an empty heartbeat is red")
        heartbeat.advancing = True
        check(take()["supervisor_looping"] is True, "an empty file that then advances is green")
    finally:
        appliance.stop()

    record = take()
    check(
        not any(record[name] for name in ("backend_healthy", "worker_healthy", "state_error_absent")),
        "an appliance that is down is red on every HTTP field",
    )
    check("unreachable" in record["detail"]["backend"], "and the journal says unreachable")


def test_url_and_path_rules(tmp: Path) -> None:
    for raw, fragment in (
        ("https://127.0.0.1:8080", "plain http"),
        ("http://192.168.1.10:8080", "loopback"),
        ("http://example.com:8080", "loopback"),
        ("http://127.0.0.1", "explicit port"),
        ("http://127.0.0.1:8080/api", "without a path"),
        ("http://user:pw@127.0.0.1:8080", "without credentials"),
        ("http://127.0.0.1:8080?x=1", "without credentials or query"),
    ):
        refused(lambda raw=raw: collector.loopback_url(raw, "URL"), fragment, f"URL {raw}")
    check(
        collector.loopback_url("http://127.0.0.1:8080/", "URL") == "http://127.0.0.1:8080",
        "a loopback origin is accepted",
    )

    root = tmp / "checkout"
    (root / "validation").mkdir(parents=True)
    ok = collector.evidence_path(root, "validation/journal.jsonl", "journal")
    check(ok == (root / "validation" / "journal.jsonl").resolve(), "a file below validation/")
    check(
        collector.evidence_path(root, root / "validation" / "a" / "b.json", "journal").name == "b.json",
        "an absolute path below validation/",
    )
    for raw, fragment in (
        ("journal.jsonl", "below validation/"),
        ("scripts/journal.jsonl", "below validation/"),
        ("validation", "below validation/"),
        ("validation/../scripts/x.json", "must not contain '..'"),
        (str(tmp / "elsewhere.jsonl"), "below the repository root"),
    ):
        refused(
            lambda raw=raw: collector.evidence_path(root, raw, "journal"), fragment, f"path {raw}"
        )
    outside = tmp / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, root / "validation" / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        return  # no symlink privilege on this host
    refused(
        lambda: collector.evidence_path(root, "validation/link/journal.jsonl", "journal"),
        "symlinks",
        "a symlink out of validation/",
    )


# --------------------------------------------------------------------------
# Assembly against the real qualifier
# --------------------------------------------------------------------------

DAY = datetime(2026, 9, 29, tzinfo=timezone.utc)
SOURCE_VERSION = "2.0.13"
CANDIDATE_VERSION = "2.0.14"
# The Stage-B fixture's recovery events: reboot 10:05, backend 10:10,
# worker 10:12, interruption 10:14.
REBOOT = DAY + timedelta(hours=10, minutes=5)


def at(hour: int, minute: int, second: int = 0) -> datetime:
    return DAY + timedelta(hours=hour, minutes=minute, seconds=second)


def line(stamp: datetime, *, red: str | None = None, version: str | None = None) -> dict:
    if version is None:
        version = CANDIDATE_VERSION if stamp >= REBOOT else SOURCE_VERSION
    record = {
        "schema": collector.PROBE_SCHEMA,
        "observed_at": stamp.isoformat(),
        **{name: True for name in collector.HEALTH_FIELDS},
        "detail": {
            "backend_version": version,
            "worker_version": version,
            "worker_commit_sha": "a" * 40,
        },
    }
    if red is not None:
        record[red] = False
    return record


def soak(*, until: tuple[int, int] = (12, 20)) -> list[dict]:
    """One probe every ten minutes from 09:50, on the source release until the
    reboot and on the candidate afterwards."""
    probes = []
    stamp = at(9, 50)
    while stamp <= at(*until):
        probes.append(line(stamp))
        stamp += timedelta(minutes=10)
    return probes


def with_extra(probes: list[dict], *extra) -> list:
    """Insert extra journal entries in time order. An entry is a probe dict or
    ``(datetime, raw_bytes)`` for a line that is not a probe."""
    def key(entry) -> datetime:
        if isinstance(entry, tuple):
            return entry[0]
        return datetime.fromisoformat(entry["observed_at"])

    return sorted([*probes, *extra], key=key)


class Rig:
    """A candidate checkout with a Stage-B report the qualifier accepts."""

    def __init__(self) -> None:
        self.root = contract.COMPONENT_ROOT
        gate._candidate_identity_from_checkout = lambda _root: contract._checkout_candidate()
        gate._revalidate_release_freeze = lambda _root, *, candidate_identity: None
        gate._revalidate_stage_b_component = contract._stub_revalidate
        report = contract._stage_b()
        self.report = self.root / "validation" / "stage-b-physical-final-latest.json"
        self.report.write_bytes((json.dumps(report, indent=2) + "\n").encode("utf-8"))
        self.journal = self.root / "validation" / "recovery-soak-journal.jsonl"
        self.output = self.root / "validation" / "recovery-soak-observations.json"
        self.record = self.root / "validation" / "recovery-soak-assembly.json"

    def write(self, entries: list) -> None:
        with self.journal.open("wb") as handle:
            for entry in entries:
                if isinstance(entry, tuple):
                    handle.write(entry[1] + b"\n")
                else:
                    handle.write(json.dumps(entry, sort_keys=True).encode("utf-8") + b"\n")
        for path in (self.output, self.record):
            path.unlink(missing_ok=True)

    def assemble(self, entries: list | None = None, **overrides) -> dict:
        if entries is not None:
            self.write(entries)
        arguments = {
            "repository_root": self.root,
            "journal": self.journal,
            "stage_b_report": Path("validation/stage-b-physical-final-latest.json"),
            "required_duration_seconds": 7200,
            "max_sample_gap_seconds": 900,
            "output": self.output,
            "record": self.record,
            "qualifier": gate,
        }
        arguments.update(overrides)
        return collector.assemble(**arguments)

    def refuses(self, entries: list | None, fragment: str, label: str, **overrides) -> None:
        refused(lambda: self.assemble(entries, **overrides), fragment, label)
        check(not self.output.exists(), f"{label}: no observations file is written")
        check(not self.record.exists(), f"{label}: no assembly record is written")

    def qualifier_cli(self) -> tuple[int, dict]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = gate.main(
                [
                    str(self.output),
                    "--stage-b-report",
                    "validation/stage-b-physical-final-latest.json",
                    "--repository-root",
                    str(self.root),
                ]
            )
        return code, json.loads(stream.getvalue())


def test_assemble() -> None:
    rig = Rig()

    # The reboot at 10:05 was observed after it; the probe at 10:04 caught the
    # appliance down, and one at 10:11:30 caught the worker restarting.
    during_reboot = line(at(10, 4), red="backend_healthy")
    during_restart = line(at(10, 11, 30), red="worker_healthy")
    entries = with_extra(soak(), during_reboot, during_restart)
    healthy = len(soak())

    assembly = rig.assemble(entries)
    observations = json.loads(rig.output.read_text(encoding="utf-8"))
    check(len(observations["samples"]) == healthy, "every healthy probe is a sample")
    check(
        all(set(sample) == {"observed_at", *collector.HEALTH_FIELDS} for sample in observations["samples"]),
        "samples carry exactly the qualifier's fields",
    )
    check(
        at(10, 4).isoformat() not in [s["observed_at"] for s in observations["samples"]],
        "a red probe is never a sample",
    )
    check(len(assembly["red_probes_excluded"]) == 2, "both red probes are in the record")
    check("backend_healthy false" in assembly["red_probes_excluded"][0], "with what was red")
    check(
        [event["kind"] for event in observations["recovery_events"]]
        == list(gate._REQUIRED_RECOVERY_KINDS),
        "the four recovery events come from the Stage-B report",
    )
    check(
        observations["recovery_events"][0]["evidence_ref"]
        == "validation/appliance-lifecycle-evidence/reboot.log#sha256=" + "1" * 64,
        "with the report's own evidence refs",
    )
    check(
        assembly["observed_in_samples"]["backend_versions"] == [SOURCE_VERSION, CANDIDATE_VERSION],
        "the record names the releases the window ran on",
    )
    check(assembly["journal"]["red_probes"] == 2, "the record counts the red probes")
    check(json.loads(rig.record.read_text(encoding="utf-8")) == assembly, "the record is written")

    # The file on disk goes through the qualifier's own command line.
    code, verdict = rig.qualifier_cli()
    check(code == 0 and verdict["qualified"] is True, "the qualifier accepts the written file")
    check(
        verdict["release_evidence_ref"] == assembly["expected_release_evidence_ref"],
        "and derives the reference the record announced",
    )
    check(verdict["sample_count"] == healthy, "over the same samples")

    # Downtime is excused only while Stage B's own trials run.
    rig.refuses(
        with_extra(soak(), line(at(11, 35), red="backend_healthy")),
        "red probes outside the Stage-B trial period",
        "a red probe an hour after Stage B",
    )
    for field in collector.HEALTH_FIELDS:
        rig.refuses(
            with_extra(soak(), line(at(11, 35), red=field)),
            f"{field} false",
            f"{field} red outside the trials",
        )
    rig.refuses(
        entries,
        "red probes outside the Stage-B trial period",
        "no tolerance: the probe a minute before the first recovery stamp",
        trial_tolerance_seconds=0,
    )
    rig.refuses(entries, "must not exceed the max sample gap", "a tolerance above the policy's gap",
                trial_tolerance_seconds=901)
    rig.refuses(entries, "must not be negative", "a negative tolerance", trial_tolerance_seconds=-1)

    # A line that is not a probe is a red probe of unknown time.
    torn = b'{"schema": "kaliv-recovery-soak-probe/v1", "observed_at": "2026-09-29T11:3'
    rig.refuses(
        with_extra(soak(), (at(11, 35), torn)),
        "not valid UTF-8 JSON",
        "a torn line an hour after Stage B",
    )
    assembly = rig.assemble(with_extra(soak(), (at(10, 5), torn)))
    check(len(assembly["red_probes_excluded"]) == 1, "a torn line inside the trials is recorded")
    extra_key = dict(line(at(11, 35)), note="edited")
    rig.refuses(with_extra(soak(), extra_key), "not a probe record", "a line with an unknown field")
    stringly = dict(line(at(11, 35)), backend_healthy="true")
    rig.refuses(with_extra(soak(), stringly), "must be booleans", "a health field that is a string")

    # From the reboot onwards the appliance must be the candidate.
    rig.refuses(
        [*soak(until=(11, 50)), line(at(12, 0), version="2.0.15"), line(at(12, 10))],
        "do not report candidate version 2.0.14",
        "a probe on another release after the reboot",
    )
    unknown = line(at(12, 0))
    unknown["detail"] = {}
    rig.refuses(
        [*soak(until=(11, 50)), unknown, line(at(12, 10))],
        "do not report candidate version",
        "a probe that names no release after the reboot",
    )

    # The qualifier's policy still decides.
    sparse = [p for p in soak() if not at(11, 0) <= datetime.fromisoformat(p["observed_at"]) <= at(11, 10)]
    rig.refuses(sparse, "sample gap", "a gap longer than the policy allows")
    rig.refuses(soak(until=(11, 40)), "below declared policy", "a window shorter than the policy")
    rig.refuses(
        [p for p in soak() if datetime.fromisoformat(p["observed_at"]) >= at(10, 10)],
        "outside the soak sample window",
        "a window that starts after the reboot",
    )
    rig.refuses([line(at(10, 0))], "fewer than two healthy probes", "a single probe")

    # A declared window. A crash after the soak is outside the claim; the same
    # crash inside it is not.
    late = with_extra(soak(), line(at(12, 30), red="backend_healthy"), line(at(12, 40)))
    rig.refuses(late, "red probes outside the Stage-B trial period", "a later crash, no window end")
    assembly = rig.assemble(late, window_end=at(12, 25))
    check(assembly["probes_outside_window"] == 2, "with a window end the later probes are outside")
    check(assembly["declared_window"]["end"] == at(12, 25).isoformat(), "and the record says so")
    check(assembly["observations"]["window_end"] == at(12, 20).isoformat(), "the window ends on a sample")
    early = with_extra(soak(), line(at(9, 30)), line(at(9, 40), red="backend_healthy"))
    rig.refuses(early, "red probes outside the Stage-B trial period", "an earlier crash, no window start")
    assembly = rig.assemble(early, window_start=at(9, 45))
    check(assembly["probes_outside_window"] == 2, "with a window start the earlier probes are outside")
    rig.refuses(late, "window start must be before window end", "an empty window",
                window_start=at(12, 0), window_end=at(11, 0))
    rig.refuses(late, "must carry a UTC offset", "a window end without an offset",
                window_end=datetime(2026, 9, 29, 12, 25))
    # A trailing red probe is outside the claimed window without any flag.
    assembly = rig.assemble([*soak(), line(at(12, 30), red="backend_healthy")])
    check(assembly["probes_outside_window"] == 1, "a trailing red probe is counted, not claimed")

    # The journal itself.
    backwards = [*soak(), line(at(12, 0, 30))]
    rig.refuses(backwards, "journal line", "a journal whose clock runs backwards")
    # A red probe written after 11:30 that claims 10:04 would otherwise be
    # excused as Stage-B downtime. The qualifier never sees red probes, so the
    # journal's own order is the only guard.
    backdated = soak()
    backdated.insert(11, line(at(10, 4), red="backend_healthy"))
    rig.refuses(backdated, "journal line 12: timestamps must be strictly increasing",
                "a red probe backdated into the trial period")
    rig.write([])
    refused(lambda: rig.assemble(), "no probes", "an empty journal")
    rig.journal.unlink()
    refused(lambda: rig.assemble(), "cannot be read", "a missing journal")

    # The Stage-B report is the qualifier's to judge.
    blocked = contract._stage_b()
    blocked["status"] = "blocked"
    rig.report.write_bytes(json.dumps(blocked).encode("utf-8"))
    rig.refuses(entries, "the qualifier refuses the Stage-B report", "a Stage-B report that is not complete")


def test_journal_and_cli(tmp: Path) -> None:
    root = tmp / "checkout"
    (root / "validation").mkdir(parents=True, exist_ok=True)
    journal = root / "validation" / "recovery-soak-journal.jsonl"
    first = line(at(10, 0))
    collector.append_probe(journal, first)
    collector.append_probe(journal, line(at(10, 10), red="worker_healthy"))
    before = journal.read_bytes()
    collector.append_probe(journal, line(at(10, 20)))
    check(journal.read_bytes().startswith(before), "the journal is only ever appended to")
    probes, digest = collector.load_journal(journal)
    check([p.healthy for p in probes] == [True, False, True], "probes are read back in order")
    check(len(digest) == 64, "the journal is hashed")
    summary = collector.summarize(probes)
    check(summary["window_seconds"] == 1200 and summary["red_probes"] == 1, "status summary")
    check(summary["max_healthy_gap_seconds"] == 1200, "the gap is measured between healthy probes")

    # The command line, against a live fake appliance and a heartbeat that a
    # background thread keeps advancing.
    appliance = _Appliance()
    backend, worker = appliance.start()
    heartbeat = tmp / "live-heartbeat"
    stop = threading.Event()

    def beat() -> None:
        value = 1_700_000_000_000
        while not stop.is_set():
            value += 100
            heartbeat.write_text(str(value), encoding="ascii")
            time.sleep(0.1)

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    journal.unlink()
    stream = io.StringIO()
    try:
        with contextlib.redirect_stdout(stream):
            code = collector.main(
                [
                    "sample", "--once",
                    "--repository-root", str(root),
                    "--backend-url", backend,
                    "--worker-url", worker,
                    "--heartbeat", str(heartbeat),
                    "--heartbeat-settle-seconds", "5",
                ]
            )
    finally:
        stop.set()
        thread.join()
        appliance.stop()
    check(code == 0, "sample --once exits 0")
    probes, _ = collector.load_journal(journal)
    check(len(probes) == 1 and probes[0].healthy, "and journals one healthy probe")
    check("supervisor_looping=ok" in stream.getvalue(), "and prints what it saw")

    stream = io.StringIO()
    with contextlib.redirect_stdout(stream):
        code = collector.main(
            ["status", "--repository-root", str(root), "--required-duration-seconds", "21600"]
        )
    status = json.loads(stream.getvalue())
    check(code == 0 and status["seconds_remaining"] == 21600, "status says how long is left")

    for argv, fragment in (
        (["sample", "--once", "--repository-root", str(root), "--backend-url", "http://10.0.0.1:8080"], "loopback"),
        (["sample", "--once", "--repository-root", str(root), "--journal", "journal.jsonl"], "below validation/"),
        (["sample", "--repository-root", str(root), "--interval-seconds", "10"], "at least 30 seconds"),
        (["sample", "--repository-root", str(root), "--interval-seconds", "30",
          "--heartbeat-settle-seconds", "30"], "shorter than the interval"),
        (["assemble", "--repository-root", str(root), "--stage-b-report", "validation/missing.json",
          "--required-duration-seconds", "21600", "--max-sample-gap-seconds", "900",
          "--window-end", "2026-09-29T12:00:00"], "UTC offset"),
    ):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = collector.main(argv)
        answer = json.loads(stream.getvalue())
        check(code == 2 and fragment in answer["error"], f"refused on the command line: {fragment}")


def test_leaves_no_bytecode(tmp: Path) -> None:
    """The collector runs from the candidate checkout, and the freeze gate
    refuses a checkout with stray bytecode. Loading the qualifier must not
    leave any behind."""
    scripts = tmp / "copy" / "scripts"
    scripts.mkdir(parents=True)
    for name in ("kaliv_recovery_soak_collector.py", "kaliv_recovery_soak_qualification.py"):
        shutil.copy(ROOT / "scripts" / name, scripts / name)
    (tmp / "copy" / "validation").mkdir()
    (tmp / "copy" / "validation" / "recovery-soak-journal.jsonl").write_bytes(b"")
    environment = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    completed = subprocess.run(
        [
            sys.executable,
            str(scripts / "kaliv_recovery_soak_collector.py"),
            "assemble",
            "--repository-root", str(tmp / "copy"),
            "--stage-b-report", "validation/missing.json",
            "--required-duration-seconds", "21600",
            "--max-sample-gap-seconds", "900",
        ],
        capture_output=True,
        text=True,
        env=environment,
        timeout=120,
    )
    check(completed.returncode == 2, f"a missing Stage-B report is refused: {completed.stderr[-300:]}")
    check("the qualifier refuses the Stage-B report" in completed.stdout, "by the qualifier, loaded for real")
    check(not list((tmp / "copy").rglob("__pycache__")), "and no bytecode is left in the checkout")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="kaliv-recovery-soak-collector-"))
    originals = (
        gate._revalidate_stage_b_component,
        gate._candidate_identity_from_checkout,
        gate._revalidate_release_freeze,
    )
    try:
        test_probe(tmp)
        test_url_and_path_rules(tmp)
        test_assemble()
        test_journal_and_cli(tmp)
        test_leaves_no_bytecode(tmp)
    finally:
        (
            gate._revalidate_stage_b_component,
            gate._candidate_identity_from_checkout,
            gate._revalidate_release_freeze,
        ) = originals
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(contract.COMPONENT_ROOT, ignore_errors=True)
    print(f"Kaliv recovery soak collector contract: {passed} checks PASS")


if __name__ == "__main__":
    main()

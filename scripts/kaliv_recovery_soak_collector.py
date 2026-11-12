#!/usr/bin/env python3
"""Collect the health samples the recovery_soak release gate qualifies.

``kaliv_recovery_soak_qualification.py`` validates an observations file. Until
now nothing produced one: the samples had to be typed by hand, which is not
evidence. This tool takes them from the running appliance and assembles the
file from the Stage-B report's own recovery events.

Three commands:

``sample``
    Probe the appliance and append one line per probe to an append-only
    journal. ``--once`` takes a single probe (for a scheduled task that
    survives a reboot); without it the command loops.
``status``
    Summarise the journal: how long the window is, the largest gap, the red
    probes.
``assemble``
    Build the observations file from the journal and the Stage-B report, and
    hand it to the qualifier before anything is written.

The tool changes nothing on the appliance. It starts, stops, restarts and
activates nothing, sends GET requests to loopback only, and writes only below
``validation/`` in the candidate checkout.

What a probe records
--------------------
- ``backend_healthy``: ``GET <backend>/healthz`` answers 200 with
  ``status == "ok"``.
- ``worker_healthy``: ``GET <worker>/healthz`` answers 200 with
  ``status == "ok"`` and ``GET <worker>/health/full`` reports ``ok == true``.
- ``supervisor_looping``: the supervisor heartbeat file advances while the
  probe watches it. A file that exists but stands still is a dead supervisor.
- ``state_error_absent``: ``/health/full`` reports the tool-gate check
  (``checks.tools.ok``, i.e. ``GATE.state_error is None``) as true.

Anything the probe cannot determine is recorded as false.

Red probes
----------
Every probe is journalled, including the red ones. The qualifier requires every
sample in the observations file to be healthy *and* requires the reboot and the
restarts to lie inside the sample window, so a probe that lands in that
downtime cannot be a sample.

Stage B takes the appliance down on purpose: the interrupted update, the good
update, the reboot and the two supervisor restarts. Its four hash-bound
recovery timestamps bound that period. ``assemble`` leaves a red probe out only
when it lies inside that period, widened by a declared tolerance that may not
exceed the sample gap the policy allows. A red probe anywhere else fails the
assembly. What was left out is written to the assembly record next to the
observations file; the qualifier does not see it.

From the reboot onwards every healthy probe must report the Stage-B candidate's
version, so a soak cannot quietly continue on another release.
"""
from __future__ import annotations

import sys

# The tool is run from the candidate checkout, and the freeze gate refuses a
# checkout that contains stray bytecode.
sys.dont_write_bytecode = True

import argparse
import hashlib
import importlib.util
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

PROBE_SCHEMA = "kaliv-recovery-soak-probe/v1"
RECORD_SCHEMA = "kaliv-recovery-soak-assembly/v1"
HEALTH_FIELDS = (
    "backend_healthy",
    "worker_healthy",
    "supervisor_looping",
    "state_error_absent",
)
_PROBE_KEYS = {"schema", "observed_at", *HEALTH_FIELDS, "detail"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}
_MAX_BODY = 1024 * 1024
_MAX_JOURNAL_BYTES = 64 * 1024 * 1024
_MAX_DETAIL = 200
_DEFAULT_JOURNAL = "validation/recovery-soak-journal.jsonl"
_DEFAULT_OBSERVATIONS = "validation/recovery-soak-observations.json"
_DEFAULT_RECORD = "validation/recovery-soak-assembly.json"


class CollectorError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

def evidence_path(repository_root: Path, raw: str | Path, label: str) -> Path:
    """Resolve ``raw`` to a file below ``<repository_root>/validation``.

    Only untracked paths below ``validation/`` are sanctioned local evidence
    for the freeze gate. A journal anywhere else would make the candidate
    checkout dirty and block the very gate it is collected for.
    """
    root = repository_root.resolve()
    path = Path(raw)
    if path.is_absolute():
        try:
            relative = path.relative_to(root)
        except ValueError as exc:
            raise CollectorError(f"{label} must be below the repository root") from exc
    else:
        relative = path
    if ".." in relative.parts:
        raise CollectorError(f"{label} must not contain '..'")
    if len(relative.parts) < 2 or relative.parts[0] != "validation":
        raise CollectorError(f"{label} must be a file below validation/")
    probe = root
    for part in relative.parts:
        probe = probe / part
        if probe.is_symlink():
            raise CollectorError(f"{label} must not traverse symlinks")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root / "validation")
    except ValueError as exc:
        raise CollectorError(f"{label} must be a file below validation/") from exc
    return resolved


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Probing
# --------------------------------------------------------------------------

def loopback_url(raw: str, label: str) -> str:
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != "http":
        raise CollectorError(f"{label} must be a plain http URL")
    if parsed.hostname not in _LOOPBACK_HOSTS:
        raise CollectorError(f"{label} must be a loopback URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise CollectorError(f"{label} must be an origin without credentials or query")
    if parsed.path not in ("", "/"):
        raise CollectorError(f"{label} must be an origin without a path")
    try:
        port = parsed.port
    except ValueError as exc:
        raise CollectorError(f"{label} has an invalid port") from exc
    if port is None:
        raise CollectorError(f"{label} must name an explicit port")
    return raw.rstrip("/")


# No proxy and no redirects: a health probe that an environment proxy or a
# redirect can send somewhere else does not describe the local appliance.
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def http_get_json(url: str, timeout: float) -> tuple[int | None, Any, str]:
    """Return ``(status, parsed_json_or_None, short_detail)``. Never raises."""
    try:
        with _OPENER.open(url, timeout=timeout) as response:
            status = response.status
            body = response.read(_MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, None, f"http {exc.code}"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        return None, None, f"unreachable: {str(reason)[:120]}"
    if len(body) > _MAX_BODY:
        return status, None, f"http {status}, body too large"
    try:
        return status, json.loads(body.decode("utf-8")), f"http {status}"
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, None, f"http {status}, body is not JSON"


def read_heartbeat(path: Path) -> int | None:
    """The supervisor heartbeat in unix milliseconds, or None if unreadable.

    The supervisor rewrites the file every tick (truncate, then write), so a
    read can catch it empty. That is "not yet", and the caller reads again.
    """
    try:
        text = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not text.isdigit() or len(text) > 20:
        return None
    return int(text)


def supervisor_looping(
    heartbeat: Path,
    *,
    settle_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    read: Callable[[Path], int | None] = read_heartbeat,
    step_seconds: float = 1.0,
) -> tuple[bool, str]:
    """True only if the heartbeat advances while we watch.

    Freshness alone is not enough: a supervisor that wrote one heartbeat and
    died leaves a file that looks fresh for a while.
    """
    first = read(heartbeat)
    waited = 0.0
    while waited < settle_seconds:
        sleep(step_seconds)
        waited += step_seconds
        current = read(heartbeat)
        if current is None:
            continue
        if first is None:
            first = current
            continue
        if current > first:
            return True, f"advanced after {waited:.0f}s"
    if first is None:
        return False, "heartbeat missing or unreadable"
    return False, f"heartbeat did not advance in {settle_seconds:.0f}s"


def _short(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)[:_MAX_DETAIL]


def probe(
    *,
    backend_url: str,
    worker_url: str,
    heartbeat: Path,
    timeout: float = 5.0,
    heartbeat_settle_seconds: float = 25.0,
    now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Take one probe. Never raises; what cannot be determined is false."""
    detail: dict[str, Any] = {}

    status, body, text = http_get_json(backend_url + "/healthz", timeout)
    backend_ok = status == 200 and isinstance(body, dict) and body.get("status") == "ok"
    detail["backend"] = text
    detail["backend_version"] = _short(body.get("version")) if isinstance(body, dict) else None

    status, body, text = http_get_json(worker_url + "/healthz", timeout)
    worker_up = status == 200 and isinstance(body, dict) and body.get("status") == "ok"
    detail["worker"] = text
    detail["worker_version"] = _short(body.get("version")) if isinstance(body, dict) else None

    status, full, text = http_get_json(worker_url + "/health/full", timeout)
    full = full if status == 200 and isinstance(full, dict) else None
    detail["health_full"] = text
    overall_ok = full is not None and full.get("ok") is True
    checks = full.get("checks") if full is not None else None
    tools = checks.get("tools") if isinstance(checks, dict) else None
    state_ok = isinstance(tools, dict) and tools.get("ok") is True
    faults = full.get("faults") if full is not None else None
    detail["faults"] = (
        [_short(item) for item in faults[:16]] if isinstance(faults, list) else None
    )
    build = full.get("build") if full is not None else None
    detail["worker_commit_sha"] = (
        _short(build.get("commit_sha")) if isinstance(build, dict) else None
    )

    looping, text = supervisor_looping(
        heartbeat, settle_seconds=heartbeat_settle_seconds, sleep=sleep
    )
    detail["heartbeat"] = text

    # Stamped when all four answers are known: the sample says "at this
    # instant these held", not "the probe began then".
    return {
        "schema": PROBE_SCHEMA,
        "observed_at": now().astimezone(timezone.utc).isoformat(),
        "backend_healthy": bool(backend_ok),
        "worker_healthy": bool(worker_up and overall_ok),
        "supervisor_looping": bool(looping),
        "state_error_absent": bool(state_ok),
        "detail": detail,
    }


def append_probe(journal: Path, record: Mapping[str, Any]) -> None:
    """Append one line and force it to disk. The journal is never rewritten."""
    line = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    journal.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(str(journal), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(descriptor, line)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


# --------------------------------------------------------------------------
# Journal
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Probe:
    line: int
    observed_at: datetime | None  # None: the line could not be read as a probe
    healthy: bool
    fields: Mapping[str, bool]
    detail: Mapping[str, Any]
    problem: str | None = None

    def sample(self) -> dict[str, Any]:
        assert self.observed_at is not None and self.healthy
        return {"observed_at": self.observed_at.isoformat(), **{k: True for k in HEALTH_FIELDS}}


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _parse_line(number: int, raw: bytes) -> Probe:
    def torn(problem: str) -> Probe:
        return Probe(number, None, False, {}, {}, problem)

    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return torn("not valid UTF-8 JSON")
    if not isinstance(value, dict) or set(value) != _PROBE_KEYS:
        return torn("not a probe record")
    if value["schema"] != PROBE_SCHEMA:
        return torn("unknown probe schema")
    observed_at = _parse_timestamp(value["observed_at"])
    if observed_at is None:
        return torn("observed_at is not a timezone-aware ISO-8601 timestamp")
    fields = {name: value[name] for name in HEALTH_FIELDS}
    if any(not isinstance(flag, bool) for flag in fields.values()):
        return torn("health fields must be booleans")
    detail = value["detail"] if isinstance(value["detail"], dict) else {}
    return Probe(number, observed_at, all(fields.values()), fields, detail)


def load_journal(journal: Path) -> tuple[list[Probe], str]:
    """Read every line. A line that is not a probe is kept as a red probe of
    unknown time, so a torn write can never hide downtime."""
    try:
        raw = journal.read_bytes()
    except OSError as exc:
        raise CollectorError("journal cannot be read") from exc
    if len(raw) > _MAX_JOURNAL_BYTES:
        raise CollectorError("journal is too large")
    probes = [
        _parse_line(number, line)
        for number, line in enumerate(raw.split(b"\n"), start=1)
        if line.strip()
    ]
    if not probes:
        raise CollectorError("journal contains no probes")
    previous: datetime | None = None
    for item in probes:
        if item.observed_at is None:
            continue
        if previous is not None and item.observed_at <= previous:
            raise CollectorError(
                f"journal line {item.line}: timestamps must be strictly increasing"
            )
        previous = item.observed_at
    return probes, hashlib.sha256(raw).hexdigest()


def summarize(probes: Sequence[Probe]) -> dict[str, Any]:
    healthy = [item for item in probes if item.healthy]
    stamps = [item.observed_at for item in healthy if item.observed_at is not None]
    gaps = [int((b - a).total_seconds()) for a, b in zip(stamps, stamps[1:])]
    return {
        "probes": len(probes),
        "healthy_probes": len(healthy),
        "red_probes": len(probes) - len(healthy),
        "first_healthy": stamps[0].isoformat() if stamps else None,
        "last_healthy": stamps[-1].isoformat() if stamps else None,
        "window_seconds": int((stamps[-1] - stamps[0]).total_seconds()) if stamps else 0,
        "max_healthy_gap_seconds": max(gaps) if gaps else 0,
    }


def describe_red(item: Probe) -> str:
    if item.problem is not None:
        return f"line {item.line}: {item.problem}"
    failed = [name for name in HEALTH_FIELDS if not item.fields[name]]
    when = item.observed_at.isoformat() if item.observed_at is not None else "unknown time"
    return f"line {item.line} at {when}: " + ", ".join(failed) + " false"


def time_bounds(probes: Sequence[Probe], index: int) -> tuple[datetime | None, datetime | None]:
    """When probe ``index`` was taken: its own timestamp, or for an unreadable
    line the timestamps of the nearest readable lines around it."""
    own = probes[index].observed_at
    if own is not None:
        return own, own
    earlier = next(
        (p.observed_at for p in reversed(probes[:index]) if p.observed_at is not None), None
    )
    later = next((p.observed_at for p in probes[index + 1:] if p.observed_at is not None), None)
    return earlier, later


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def load_qualifier() -> Any:
    script = Path(__file__).resolve().parent / "kaliv_recovery_soak_qualification.py"
    spec = importlib.util.spec_from_file_location("_kaliv_recovery_soak_qualification", script)
    if spec is None or spec.loader is None:
        raise CollectorError("the recovery-soak qualifier cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CollectorError(f"{label} must be a positive integer")
    return value


def _aware(value: datetime | None, label: str) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise CollectorError(f"{label} must carry a UTC offset")
    return value


def assemble(
    *,
    repository_root: Path,
    journal: Path,
    stage_b_report: Path,
    required_duration_seconds: int,
    max_sample_gap_seconds: int,
    output: Path,
    record: Path,
    trial_tolerance_seconds: int | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    qualifier: Any | None = None,
) -> dict[str, Any]:
    """Build and write the observations file.

    Raises CollectorError and writes nothing if the soak does not hold.
    """
    qual = load_qualifier() if qualifier is None else qualifier
    root = repository_root.resolve()
    _positive_int(required_duration_seconds, "required duration")
    _positive_int(max_sample_gap_seconds, "max sample gap")
    if trial_tolerance_seconds is None:
        trial_tolerance_seconds = max_sample_gap_seconds
    if isinstance(trial_tolerance_seconds, bool) or not isinstance(trial_tolerance_seconds, int):
        raise CollectorError("trial tolerance must be an integer")
    if trial_tolerance_seconds < 0:
        raise CollectorError("trial tolerance must not be negative")
    if trial_tolerance_seconds > max_sample_gap_seconds:
        # A tolerance longer than the gap the policy accepts would excuse
        # downtime the policy itself would not.
        raise CollectorError("trial tolerance must not exceed the max sample gap")
    _aware(window_start, "window start")
    _aware(window_end, "window end")
    if window_start is not None and window_end is not None and window_start >= window_end:
        raise CollectorError("window start must be before window end")

    try:
        report_file, report_relative = qual._resolve_stage_b_report_path(root, stage_b_report)
        report, report_sha256 = qual._load_stage_b(report_file)
        candidate = report.get("candidate")
        candidate_sha = candidate.get("git_sha") if isinstance(candidate, dict) else None
        candidate_version = candidate.get("version") if isinstance(candidate, dict) else None
        if not isinstance(candidate_sha, str) or not isinstance(candidate_version, str):
            raise CollectorError("Stage-B report names no candidate")
        # The recovery events come from the Stage-B report through the
        # qualifier's own validation, never typed: evidence_ref and observed_at
        # are the ones its hash-bound lifecycle artefacts carry.
        authority = qual._validate_stage_b_report(
            report, candidate_sha=candidate_sha, repository_root=root
        )
    except qual.RecoverySoakError as exc:
        raise CollectorError(f"the qualifier refuses the Stage-B report: {exc}") from exc
    events = {
        kind: datetime.fromisoformat(authority[kind]["observed_at"])
        for kind in qual._REQUIRED_RECOVERY_KINDS
    }
    tolerance = timedelta(seconds=trial_tolerance_seconds)
    span_start = min(events.values()) - tolerance
    span_end = max(events.values()) + tolerance

    probes, journal_sha256 = load_journal(journal)

    def in_window(index: int) -> bool:
        earliest, latest = time_bounds(probes, index)
        if window_start is not None and (latest is None or latest < window_start):
            return False
        if window_end is not None and (earliest is None or earliest > window_end):
            return False
        return True

    chosen = [index for index in range(len(probes)) if in_window(index)]
    healthy_at = [index for index in chosen if probes[index].healthy]
    if len(healthy_at) < 2:
        raise CollectorError("fewer than two healthy probes in the window")
    first, last = healthy_at[0], healthy_at[-1]

    excluded: list[str] = []
    unexplained: list[str] = []
    outside = len(probes) - len(chosen)
    for index in chosen:
        item = probes[index]
        if item.healthy:
            continue
        if index < first or index > last:
            # Before the first or after the last healthy probe: not part of the
            # window this soak claims. Counted, not claimed.
            outside += 1
            continue
        earliest, latest = time_bounds(probes, index)
        if (
            earliest is not None
            and latest is not None
            and span_start <= earliest
            and latest <= span_end
        ):
            excluded.append(describe_red(item))
        else:
            unexplained.append(describe_red(item))
    if unexplained:
        raise CollectorError(
            "red probes outside the Stage-B trial period ("
            + span_start.isoformat()
            + " to "
            + span_end.isoformat()
            + "): "
            + "; ".join(unexplained)
        )

    healthy = [probes[index] for index in healthy_at]
    wrong_version = [
        f"line {item.line}: backend {item.detail.get('backend_version')!r}, "
        f"worker {item.detail.get('worker_version')!r}"
        for item in healthy
        if item.observed_at >= events["reboot"]
        and not (
            item.detail.get("backend_version") == candidate_version
            and item.detail.get("worker_version") == candidate_version
        )
    ]
    if wrong_version:
        raise CollectorError(
            f"healthy probes after the reboot do not report candidate version "
            f"{candidate_version}: " + "; ".join(wrong_version[:8])
        )

    observations = {
        "schema": qual.OBS_SCHEMA,
        "candidate_sha": candidate_sha,
        "production_activation": False,
        "policy": {
            "required_duration_seconds": required_duration_seconds,
            "max_sample_gap_seconds": max_sample_gap_seconds,
        },
        "stage_b_evidence_ref": f"{report_relative}#sha256={report_sha256}",
        "samples": [item.sample() for item in healthy],
        "recovery_events": [
            {
                "kind": kind,
                "observed_at": authority[kind]["observed_at"],
                "passed": True,
                "evidence_ref": authority[kind]["evidence_ref"],
            }
            for kind in qual._REQUIRED_RECOVERY_KINDS
        ],
    }
    rendered = (json.dumps(observations, indent=2, sort_keys=True) + "\n").encode("utf-8")
    observations_sha256 = hashlib.sha256(rendered).hexdigest()

    # The qualifier decides. Nothing is written unless it accepts exactly the
    # bytes that are about to be written.
    try:
        verdict = qual.qualify(
            json.loads(rendered.decode("utf-8")),
            observations_sha256=observations_sha256,
            stage_b_report=report,
            stage_b_sha256=report_sha256,
            stage_b_report_path=report_file,
            stage_b_repository_root=root,
        )
    except qual.RecoverySoakError as exc:
        raise CollectorError(f"the qualifier refuses the observations: {exc}") from exc

    def seen(name: str) -> list[str]:
        return sorted({str(item.detail[name]) for item in healthy if item.detail.get(name)})

    assembly = {
        "schema": RECORD_SCHEMA,
        "candidate_sha": candidate_sha,
        "candidate_version": candidate_version,
        "production_activation": False,
        "journal": {
            "path": journal.resolve().relative_to(root).as_posix(),
            "sha256": journal_sha256,
            **summarize(probes),
        },
        "observations": {
            "path": output.resolve().relative_to(root).as_posix(),
            "sha256": observations_sha256,
            "samples": len(healthy),
            "window_start": healthy[0].observed_at.isoformat(),
            "window_end": healthy[-1].observed_at.isoformat(),
        },
        "policy": dict(observations["policy"]),
        "declared_window": {
            "start": None if window_start is None else window_start.isoformat(),
            "end": None if window_end is None else window_end.isoformat(),
        },
        "stage_b_trial_period": {
            "tolerance_seconds": trial_tolerance_seconds,
            "start": span_start.isoformat(),
            "end": span_end.isoformat(),
        },
        "red_probes_excluded": excluded,
        "probes_outside_window": outside,
        "observed_in_samples": {
            "backend_versions": seen("backend_version"),
            "worker_versions": seen("worker_version"),
            "worker_commit_shas": seen("worker_commit_sha"),
        },
        "expected_release_evidence_ref": verdict.release_evidence_ref,
        "note": (
            "This record is not a qualification verdict. Run "
            "kaliv_recovery_soak_qualification.py on the observations file."
        ),
    }
    _atomic_write(output, rendered)
    _atomic_write(record, (json.dumps(assembly, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return assembly


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _default_heartbeat() -> str:
    # The supervisor writes <rig root>\logs\supervisor-heartbeat; the rig root
    # the operator tools assume is C:\Rig\ModelRig.
    return r"C:\Rig\ModelRig\logs\supervisor-heartbeat"


def _print_probe(record: Mapping[str, Any]) -> None:
    flags = " ".join(
        f"{name}={'ok' if record[name] else 'RED'}" for name in HEALTH_FIELDS
    )
    print(f"{record['observed_at']} {flags}", flush=True)


def _cli_timestamp(raw: str | None, label: str) -> datetime | None:
    if raw is None:
        return None
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = _parse_timestamp(text)
    if parsed is None:
        raise CollectorError(f"{label} must be an ISO-8601 timestamp with a UTC offset")
    return parsed


def _cmd_sample(args: argparse.Namespace) -> int:
    root = args.repository_root.resolve()
    journal = evidence_path(root, args.journal, "journal")
    backend = loopback_url(args.backend_url, "backend URL")
    worker = loopback_url(args.worker_url, "worker URL")
    heartbeat = Path(args.heartbeat)
    if args.interval_seconds < 30:
        raise CollectorError("interval must be at least 30 seconds")
    if args.heartbeat_settle_seconds >= args.interval_seconds:
        raise CollectorError("heartbeat settle time must be shorter than the interval")

    started = time.monotonic()
    while True:
        tick = time.monotonic()
        record = probe(
            backend_url=backend,
            worker_url=worker,
            heartbeat=heartbeat,
            timeout=args.timeout,
            heartbeat_settle_seconds=args.heartbeat_settle_seconds,
        )
        append_probe(journal, record)
        _print_probe(record)
        if args.once:
            return 0
        if args.duration_seconds is not None and (
            time.monotonic() - started >= args.duration_seconds
        ):
            return 0
        remaining = args.interval_seconds - (time.monotonic() - tick)
        if remaining > 0:
            time.sleep(remaining)


def _cmd_status(args: argparse.Namespace) -> int:
    root = args.repository_root.resolve()
    probes, digest = load_journal(evidence_path(root, args.journal, "journal"))
    summary = summarize(probes)
    summary["journal_sha256"] = digest
    summary["red"] = [describe_red(item) for item in probes if not item.healthy]
    if args.required_duration_seconds is not None:
        summary["seconds_remaining"] = max(
            0, args.required_duration_seconds - summary["window_seconds"]
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _cmd_assemble(args: argparse.Namespace) -> int:
    root = args.repository_root.resolve()
    assembly = assemble(
        repository_root=root,
        journal=evidence_path(root, args.journal, "journal"),
        stage_b_report=args.stage_b_report,
        required_duration_seconds=args.required_duration_seconds,
        max_sample_gap_seconds=args.max_sample_gap_seconds,
        trial_tolerance_seconds=args.trial_tolerance_seconds,
        window_start=_cli_timestamp(args.window_start, "--window-start"),
        window_end=_cli_timestamp(args.window_end, "--window-end"),
        output=evidence_path(root, args.output, "output"),
        record=evidence_path(root, args.record, "record"),
    )
    print(json.dumps(assembly, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    def common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--repository-root",
            type=Path,
            default=Path.cwd(),
            help="the candidate ModelRig checkout (default: current directory)",
        )
        sub.add_argument("--journal", default=_DEFAULT_JOURNAL)

    sample = commands.add_parser("sample", help="probe the appliance and journal the result")
    common(sample)
    sample.add_argument("--backend-url", default="http://127.0.0.1:8080")
    sample.add_argument("--worker-url", default="http://127.0.0.1:8099")
    sample.add_argument("--heartbeat", default=_default_heartbeat())
    sample.add_argument("--interval-seconds", type=int, default=300)
    sample.add_argument("--duration-seconds", type=int)
    sample.add_argument("--once", action="store_true", help="take one probe and exit")
    sample.add_argument("--timeout", type=float, default=5.0)
    sample.add_argument("--heartbeat-settle-seconds", type=float, default=25.0)
    sample.set_defaults(handler=_cmd_sample)

    status = commands.add_parser("status", help="summarise the journal")
    common(status)
    status.add_argument("--required-duration-seconds", type=int)
    status.set_defaults(handler=_cmd_status)

    build = commands.add_parser("assemble", help="build the observations file")
    common(build)
    build.add_argument("--stage-b-report", type=Path, required=True)
    # No defaults: the soak policy is declared by the operator, not by the tool.
    build.add_argument("--required-duration-seconds", type=int, required=True)
    build.add_argument("--max-sample-gap-seconds", type=int, required=True)
    build.add_argument(
        "--trial-tolerance-seconds",
        type=int,
        help="widening of the Stage-B trial period (default: the max sample gap)",
    )
    build.add_argument("--window-start", help="ignore probes before this ISO-8601 instant")
    build.add_argument("--window-end", help="ignore probes after this ISO-8601 instant")
    build.add_argument("--output", default=_DEFAULT_OBSERVATIONS)
    build.add_argument("--record", default=_DEFAULT_RECORD)
    build.set_defaults(handler=_cmd_assemble)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        return 0
    except CollectorError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

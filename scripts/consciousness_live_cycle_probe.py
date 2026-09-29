#!/usr/bin/env python3
"""Collect bounded live Consciousness Core cycle evidence from a real worker.

This is an operator-side qualification probe. It exercises the existing C21-A
user-turn admission and C22-C exact-event step surfaces over loopback, validates
their authority-denial receipts, measures request latency, and writes one atomic
machine-readable report.

It deliberately does NOT claim full lived-lifecycle qualification. In
particular, it does not prove sleep/restart/dormancy or model-swap continuity.
Those remain separate evidence gates.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

SCHEMA = "kaliv-consciousness-core/live-cycle-probe/v1"
DEFAULT_WORKER_URL = "http://127.0.0.1:8099"
DEFAULT_REPORT = Path("validation/consciousness-live-cycle-latest.json")
MAX_RESPONSE_BYTES = 256 * 1024
DEFAULT_TIMEOUT_SECONDS = 20.0
MAX_STEP_ATTEMPTS = 6
WAIT_DELAY_SECONDS = 0.6
_EVENT_RE = re.compile(r"^cevt-[a-f0-9]{32}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")


class LiveCycleProbeError(RuntimeError):
    """The probe could not produce trustworthy live-cycle evidence."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    temporary.replace(path)


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LiveCycleProbeError("git identity could not be inspected") from exc
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def git_identity(root: Path) -> dict[str, Any]:
    code, sha = _git(root, "rev-parse", "HEAD")
    if code != 0 or _SHA40.fullmatch(sha) is None:
        raise LiveCycleProbeError("probe requires a Git checkout with exact HEAD")
    _, branch = _git(root, "branch", "--show-current")
    _, dirty = _git(root, "status", "--porcelain")
    if dirty:
        raise LiveCycleProbeError("probe requires a clean working tree")
    return {
        "git_sha": sha,
        "branch": branch or None,
        "working_tree_clean": True,
    }


def normalize_worker_url(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise LiveCycleProbeError("worker URL must be nonblank")
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise LiveCycleProbeError("worker URL must be HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise LiveCycleProbeError("worker URL must not contain userinfo")
    if parsed.query or parsed.fragment:
        raise LiveCycleProbeError("worker URL must not contain query or fragment")
    if parsed.path not in {"", "/"}:
        raise LiveCycleProbeError("worker URL must not contain a path")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise LiveCycleProbeError("worker URL must be loopback")
    return value.strip().rstrip("/")


def _http_json(
    method: str,
    url: str,
    body: Mapping[str, Any] | None,
    *,
    timeout: float,
) -> tuple[int, Mapping[str, Any]]:
    raw = None if body is None else _canonical_json(body)
    headers = {"Accept": "application/json"}
    if raw is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        url,
        data=raw,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
            status = int(response.status)
    except urllib.error.HTTPError as exc:
        raise LiveCycleProbeError(
            f"worker returned HTTP {exc.code} for {urllib.parse.urlsplit(url).path}"
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise LiveCycleProbeError(
            f"worker request failed for {urllib.parse.urlsplit(url).path}"
        ) from exc
    if len(payload) > MAX_RESPONSE_BYTES:
        raise LiveCycleProbeError("worker response exceeded probe bound")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LiveCycleProbeError("worker response was not valid UTF-8 JSON") from exc
    if not isinstance(value, Mapping):
        raise LiveCycleProbeError("worker response must be a JSON object")
    return status, value


def _authority_false(value: Mapping[str, Any], *, label: str) -> None:
    for field in (
        "durable_memory_write_authority",
        "execution_authority",
        "scheduling_authority",
        "production_activation",
    ):
        if value.get(field) is not False:
            raise LiveCycleProbeError(f"{label} overclaimed {field}")


def validate_admission(value: Mapping[str, Any]) -> str:
    if value.get("schema") != "kaliv-consciousness-core/user-turn-admission/v1":
        raise LiveCycleProbeError("user-turn receipt schema mismatch")
    event_id = value.get("cognition_event_id")
    if not isinstance(event_id, str) or _EVENT_RE.fullmatch(event_id) is None:
        raise LiveCycleProbeError("user-turn receipt lacks canonical cognition event id")
    if value.get("world_changed") is not True:
        raise LiveCycleProbeError("probe user turn did not change live WorldState")
    if value.get("replayed") is not False:
        raise LiveCycleProbeError("probe user turn was unexpectedly replayed")
    if value.get("cognition_event_queued") is not True:
        raise LiveCycleProbeError("probe cognition event was not queued")
    if value.get("epistemic_status") != "reported" or value.get("confidence") != 1.0:
        raise LiveCycleProbeError("user-turn epistemic contract mismatch")
    if value.get("model_calls") != 0:
        raise LiveCycleProbeError("user-turn admission unexpectedly called a model")
    _authority_false(value, label="user-turn receipt")
    return event_id


def validate_step(value: Mapping[str, Any], event_id: str) -> str:
    if value.get("schema") != "kaliv-consciousness-core/exact-event-step-receipt/v1":
        raise LiveCycleProbeError("exact-event receipt schema mismatch")
    if value.get("required_event_id") != event_id:
        raise LiveCycleProbeError("exact-event receipt is not bound to admitted event")
    decision = value.get("decision")
    if decision not in {"WAIT", "RUN"}:
        raise LiveCycleProbeError("exact-event receipt has invalid decision")
    _authority_false(value, label="exact-event receipt")
    for field in ("automatic_repeat", "internal_thread_created", "internal_timer_created"):
        if value.get(field) is not False:
            raise LiveCycleProbeError(f"exact-event receipt overclaimed {field}")

    if decision == "WAIT":
        if value.get("model_calls") != 0 or value.get("thought_engine_invoked") is not False:
            raise LiveCycleProbeError("WAIT receipt claimed a ThoughtEngine call")
        if value.get("context_updated") is not False:
            raise LiveCycleProbeError("WAIT receipt claimed a context transition")
        if value.get("selected_event_ids") != []:
            raise LiveCycleProbeError("WAIT receipt exposed selected events")
        return "WAIT"

    selected = value.get("selected_event_ids")
    if not isinstance(selected, list) or event_id not in selected:
        raise LiveCycleProbeError("RUN receipt did not select the admitted event")
    if value.get("required_event_selected") is not True:
        raise LiveCycleProbeError("RUN receipt denied required-event selection")
    if value.get("model_calls") != 1 or value.get("thought_engine_invoked") is not True:
        raise LiveCycleProbeError("RUN receipt did not prove exactly one ThoughtEngine call")
    if value.get("context_updated") is not True:
        raise LiveCycleProbeError("RUN receipt did not prove a context transition")
    transition = value.get("transition_receipt_ref")
    if not isinstance(transition, str) or not transition.strip():
        raise LiveCycleProbeError("RUN receipt lacks transition receipt reference")
    return "RUN"


def run_live_cycle(
    worker_url: str,
    *,
    root: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    max_step_attempts: int = MAX_STEP_ATTEMPTS,
    wait_delay: float = WAIT_DELAY_SECONDS,
    http_json: Callable[..., tuple[int, Mapping[str, Any]]] = _http_json,
    sleep_fn: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.perf_counter,
    identity: Mapping[str, Any] | None = None,
    probe_nonce: str | None = None,
) -> dict[str, Any]:
    base = normalize_worker_url(worker_url)
    if max_step_attempts < 1 or max_step_attempts > 20:
        raise LiveCycleProbeError("max step attempts must be between 1 and 20")
    if wait_delay < 0 or wait_delay > 5:
        raise LiveCycleProbeError("wait delay is outside probe bound")

    candidate = dict(identity if identity is not None else git_identity(root))
    sha = candidate.get("git_sha")
    if not isinstance(sha, str) or _SHA40.fullmatch(sha) is None:
        raise LiveCycleProbeError("candidate identity lacks exact Git SHA")
    if candidate.get("working_tree_clean") is not True:
        raise LiveCycleProbeError("candidate identity is not clean")

    status, health = http_json(
        "GET",
        base + "/healthz",
        None,
        timeout=timeout,
    )
    if status != 200:
        raise LiveCycleProbeError("worker health probe did not return HTTP 200")

    nonce = probe_nonce or uuid.uuid4().hex
    if not re.fullmatch(r"[a-f0-9]{32}", nonce):
        raise LiveCycleProbeError("probe nonce must be lowercase 32-hex")
    turn_id = "live-cycle-" + nonce
    source_ref = "qualification:consciousness-live-cycle:" + nonce
    user_text = "Kaliv live cycle qualification probe " + nonce

    admission_start = clock()
    status, admission = http_json(
        "POST",
        base + "/experimental/consciousness/user-turn",
        {
            "turn_id": turn_id,
            "user_text": user_text,
            "source_ref": source_ref,
        },
        timeout=timeout,
    )
    admission_ms = round((clock() - admission_start) * 1000.0, 3)
    if status != 200:
        raise LiveCycleProbeError("user-turn admission did not return HTTP 200")
    event_id = validate_admission(admission)

    step_latencies: list[float] = []
    wait_count = 0
    final_step: Mapping[str, Any] | None = None
    for attempt in range(1, max_step_attempts + 1):
        step_start = clock()
        status, step = http_json(
            "POST",
            base + "/experimental/consciousness/step-event",
            {"required_event_id": event_id},
            timeout=timeout,
        )
        step_latencies.append(round((clock() - step_start) * 1000.0, 3))
        if status != 200:
            raise LiveCycleProbeError("exact-event step did not return HTTP 200")
        decision = validate_step(step, event_id)
        if decision == "RUN":
            final_step = step
            break
        wait_count += 1
        if attempt < max_step_attempts:
            sleep_fn(wait_delay)

    if final_step is None:
        raise LiveCycleProbeError(
            "bounded exact-event attempts never reached RUN"
        )

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "candidate": candidate,
        "worker": {
            "url": base,
            "health_ok": bool(health.get("ok", True)),
        },
        "admission": {
            "turn_ref": admission.get("turn_ref"),
            "evidence_ref": admission.get("evidence_ref"),
            "cognition_event_id": event_id,
            "observed_sequence": admission.get("observed_sequence"),
            "latency_ms": admission_ms,
            "model_calls": 0,
        },
        "cycle": {
            "attempts": wait_count + 1,
            "wait_count": wait_count,
            "decision": "RUN",
            "latency_ms_by_attempt": step_latencies,
            "profile_ref": final_step.get("profile_ref"),
            "self_state_ref": final_step.get("self_state_ref"),
            "world_state_ref": final_step.get("world_state_ref"),
            "workspace_ref": final_step.get("workspace_ref"),
            "transition_receipt_ref": final_step.get("transition_receipt_ref"),
            "completed_cycles": final_step.get("completed_cycles"),
            "model_calls": 1,
        },
        "authority": {
            "automatic_repeat": False,
            "internal_thread_created": False,
            "internal_timer_created": False,
            "durable_memory_write_authority": False,
            "execution_authority": False,
            "scheduling_authority": False,
            "production_activation": False,
        },
        "gate": {
            "passed": True,
            "live_cycle_proven": True,
            "full_lifecycle_qualified": False,
            "model_swap_qualified": False,
            "dormancy_restart_qualified": False,
            "release_gate_satisfied": False,
            "production_activation": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--worker-url",
        default=os.environ.get("MODELRIG_WORKER_URL", DEFAULT_WORKER_URL),
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--max-step-attempts", type=int, default=MAX_STEP_ATTEMPTS)
    parser.add_argument("--wait-delay", type=float, default=WAIT_DELAY_SECONDS)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    try:
        report = run_live_cycle(
            args.worker_url,
            root=root,
            timeout=args.timeout,
            max_step_attempts=args.max_step_attempts,
            wait_delay=args.wait_delay,
        )
    except LiveCycleProbeError as exc:
        failure = {
            "schema": SCHEMA,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "gate": {
                "passed": False,
                "live_cycle_proven": False,
                "full_lifecycle_qualified": False,
                "model_swap_qualified": False,
                "dormancy_restart_qualified": False,
                "release_gate_satisfied": False,
                "production_activation": False,
            },
            "error": {
                "type": type(exc).__name__,
                "message": str(exc)[:500],
            },
        }
        _write_json_atomic(args.report, failure)
        print(json.dumps(failure, indent=2, sort_keys=True))
        return 1

    _write_json_atomic(args.report, report)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

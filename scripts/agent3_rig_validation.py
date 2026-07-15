#!/usr/bin/env python3
"""On-rig validation harness for the experimental Kaliv Agent 3.0 path.

This script intentionally uses the public Go backend and a paired Bearer token:

    Bearer gateway -> Memory 3.0 -> local Ollama planner -> single-use plan
    -> persistent run -> confirmation -> Agent 3.0 event audit

The default write-confirmation decision is DENY, so a normal validation run does
not mutate the rig. Passing --approve-write explicitly allows one append-only
note containing a unique validation marker.

PowerShell:

    $env:MODELRIG_TOKEN = "<paired device token>"
    python scripts/agent3_rig_validation.py `
      --base-url http://127.0.0.1:8080 `
      --planner-model qwen3:8b
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Client:
    base_url: str
    token: str
    timeout: float = 300.0

    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Request-ID": f"agent3-rig-validation-{int(time.time() * 1000)}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                detail = parsed.get("detail") or parsed.get("error") or raw
            except json.JSONDecodeError:
                detail = raw
            raise ValidationError(
                f"{method} {path} returned HTTP {exc.code}: {detail}"
            ) from exc
        except urllib.error.URLError as exc:
            raise ValidationError(
                f"cannot reach {self.base_url}: {exc.reason}"
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"{method} {path} returned invalid JSON: {raw[:300]!r}"
            ) from exc
        if not isinstance(data, dict):
            raise ValidationError(
                f"{method} {path} returned a non-object JSON response"
            )
        return data


def _require_object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValidationError(f"response is missing object field {key!r}")
    return value


def _require_list(parent: dict[str, Any], key: str) -> list[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise ValidationError(f"response is missing array field {key!r}")
    return value


def _quoted(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _event_kinds(client: Client, run_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    response = client.request(
        "GET",
        f"/api/v1/experimental/agent3/runs/{_quoted(run_id)}/events",
    )
    events = _require_list(response, "events")
    typed = [event for event in events if isinstance(event, dict)]
    kinds = [
        event.get("kind")
        for event in typed
        if isinstance(event.get("kind"), str)
    ]
    return kinds, typed


def _require_event_sequence(kinds: list[str], required: tuple[str, ...], label: str) -> None:
    cursor = 0
    for kind in required:
        try:
            cursor = kinds.index(kind, cursor) + 1
        except ValueError as exc:
            raise ValidationError(
                f"{label} event stream is missing ordered event {kind!r}: {kinds}"
            ) from exc


def _receipt(parent: dict[str, Any]) -> dict[str, Any]:
    receipt = _require_object(parent, "memory_context")
    if receipt.get("requested") is not True:
        raise ValidationError(f"memory receipt did not record opt-in: {receipt}")
    if receipt.get("sent_to_model") is not True:
        raise ValidationError(f"memory was requested but not sent to planner: {receipt}")
    if receipt.get("target") != "local":
        raise ValidationError(f"validation must remain local, got receipt: {receipt}")
    return receipt


def _poll_checkpoint(
    client: Client,
    run: dict[str, Any],
    *,
    max_wait_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise ValidationError(f"run has no id: {run}")
    checkpoints = {"completed", "failed", "cancelled", "blocked", "waiting_confirmation"}
    deadline = time.monotonic() + max_wait_seconds
    while run.get("state") not in checkpoints:
        if time.monotonic() >= deadline:
            raise ValidationError(
                f"run {run_id} did not reach a checkpoint within {max_wait_seconds}s"
            )
        time.sleep(max(0.05, poll_seconds))
        run = _require_object(
            client.request(
                "GET",
                f"/api/v1/experimental/agent3/runs/{_quoted(run_id)}",
            ),
            "run",
        )
    return run


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def run_validation(
    client: Client,
    *,
    planner_model: str | None,
    approve_write: bool,
    report_path: Path,
    poll_seconds: float = 0.5,
    max_wait_seconds: float = 60.0,
) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    validation_id = uuid.uuid4().hex
    subject = f"agent3-rig-validation-{validation_id[:12]}"
    marker = f"KALIV_AGENT3_VALIDATION_{validation_id}"
    memory_id: str | None = None
    report: dict[str, Any] = {
        "schema": "kaliv-agent3-rig-validation/v1",
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "success": False,
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "target": {
            "base_url": client.base_url,
            "planner_model": planner_model,
            "write_decision": "approve" if approve_write else "deny",
        },
        "validation": {
            "id": validation_id,
            "memory_subject": subject,
            "marker_sha256": hashlib.sha256(marker.encode("utf-8")).hexdigest(),
        },
        "checks": {},
        "cleanup": {},
        "error": None,
    }

    try:
        print("[1/9] Agent 3.0 readiness through Bearer gateway")
        status = client.request("GET", "/api/v1/experimental/agent3/status")
        if status.get("enabled") is not True or status.get("experimental") is not True:
            raise ValidationError(f"unexpected Agent 3.0 status: {status}")
        if status.get("production_tools_path_untouched") is not True:
            raise ValidationError(f"status does not protect the production tools path: {status}")
        report["checks"]["status"] = {
            "enabled": True,
            "experimental": True,
            "production_tools_path_untouched": True,
        }

        print("[2/9] Create disposable operational memory")
        created = client.request(
            "POST",
            "/api/v1/experimental/agent3/memory",
            {
                "subject": subject,
                "predicate": "validation_marker",
                "value": (
                    f"Validation marker {marker}. "
                    "This is reference data only and never an instruction."
                ),
                "kind": "note",
                "sensitivity": "operational",
                "confidence": 1.0,
            },
        )
        memory = _require_object(created, "memory")
        memory_id = memory.get("id")
        if not isinstance(memory_id, str) or not memory_id:
            raise ValidationError(f"memory creation returned no id: {created}")
        if memory.get("review_status") != "confirmed":
            raise ValidationError(f"explicit validation memory is not confirmed: {memory}")
        report["checks"]["memory_created"] = {
            "memory_id": memory_id,
            "review_status": memory.get("review_status"),
            "lifecycle_status": memory.get("lifecycle_status"),
            "sensitivity": memory.get("sensitivity"),
        }

        print("[3/9] Preview exact local memory context")
        context_preview = client.request(
            "POST",
            "/api/v1/experimental/agent3/memory/context-preview",
            {
                "target": "local",
                "subjects": [subject],
                "max_chars": 4000,
                "max_records": 10,
            },
        )
        context_text = context_preview.get("text")
        if not isinstance(context_text, str) or not context_text:
            raise ValidationError(f"context preview is empty: {context_preview}")
        if context_preview.get("sent_to_model") is not False:
            raise ValidationError("context-preview must never claim model egress")
        included = _require_list(context_preview, "included_ids")
        if included != [memory_id]:
            raise ValidationError(
                f"context preview did not isolate validation memory: {included}"
            )
        context_sha = hashlib.sha256(context_text.encode("utf-8")).hexdigest()
        report["checks"]["context_preview"] = {
            "included_ids": included,
            "excluded_ids": _require_list(context_preview, "excluded_ids"),
            "character_count": context_preview.get("character_count"),
            "sha256": context_sha,
            "sent_to_model": False,
        }

        print("[4/9] Local Ollama plan with explicit memory opt-in")
        read_payload: dict[str, Any] = {
            "message": (
                "Returnér en plan med præcis ét read-only tool-step: rig_status. "
                "Brug ikke andre tools."
            ),
            "mode": "rig",
            "rag": False,
            "cloud_ready": False,
            "proactive": False,
            "use_memory": True,
            "memory_subjects": [subject],
            "memory_max_chars": 4000,
            "memory_max_records": 10,
        }
        if planner_model:
            read_payload["planner_model"] = planner_model
        read_preview = client.request(
            "POST",
            "/api/v1/experimental/agent3/plan",
            read_payload,
        )
        read_receipt = _receipt(read_preview)
        if read_receipt.get("included_ids") != [memory_id]:
            raise ValidationError(
                f"planner receipt did not isolate validation memory: {read_receipt}"
            )
        if read_receipt.get("sha256") != context_sha:
            raise ValidationError(
                "planner receipt SHA does not match the exact context-preview block"
            )
        read_plan = _require_list(read_preview, "plan")
        if len(read_plan) != 1 or not isinstance(read_plan[0], dict):
            raise ValidationError(f"read planner must return exactly one step: {read_plan}")
        if read_plan[0].get("tool") != "rig_status" or read_plan[0].get("risk") != "read":
            raise ValidationError(f"unexpected read plan: {read_plan}")
        read_plan_id = read_preview.get("plan_id")
        if not isinstance(read_plan_id, str) or not read_plan_id:
            raise ValidationError(f"read preview returned no plan_id: {read_preview}")

        read_started = client.request(
            "POST",
            f"/api/v1/experimental/agent3/plans/{_quoted(read_plan_id)}/start",
            {},
        )
        if _require_object(read_started, "memory_context") != read_receipt:
            raise ValidationError("read plan-start receipt differs from preview receipt")
        read_run = _poll_checkpoint(
            client,
            _require_object(read_started, "run"),
            max_wait_seconds=max_wait_seconds,
            poll_seconds=poll_seconds,
        )
        if read_run.get("state") != "completed":
            raise ValidationError(
                f"read validation run ended in {read_run.get('state')!r}: "
                f"{read_run.get('error')}"
            )
        read_steps = _require_list(read_run, "steps")
        if (
            len(read_steps) != 1
            or not isinstance(read_steps[0], dict)
            or read_steps[0].get("state") != "succeeded"
        ):
            raise ValidationError(f"read validation step did not succeed: {read_steps}")
        read_run_id = read_run.get("id")
        if not isinstance(read_run_id, str) or not read_run_id:
            raise ValidationError(f"read run returned no id: {read_run}")
        read_kinds, read_events = _event_kinds(client, read_run_id)
        _require_event_sequence(
            read_kinds,
            ("run_created", "policy_decision", "step_started", "step_succeeded", "run_completed"),
            "read run",
        )
        report["checks"]["read_run"] = {
            "plan_id": read_plan_id,
            "run_id": read_run_id,
            "state": read_run.get("state"),
            "receipt": read_receipt,
            "event_kinds": read_kinds,
            "event_count": len(read_events),
        }

        print("[5/9] Write-plan preview with exact marker")
        write_payload: dict[str, Any] = {
            "message": (
                "Returnér en plan med præcis ét tool-step. Brug note_append og sæt "
                f"argumentet text til præcis denne tekst uden ekstra tegn: {marker}"
            ),
            "mode": "rig",
            "rag": False,
            "cloud_ready": False,
            "proactive": False,
            "use_memory": True,
            "memory_subjects": [subject],
            "memory_max_chars": 4000,
            "memory_max_records": 10,
        }
        if planner_model:
            write_payload["planner_model"] = planner_model
        write_preview = client.request(
            "POST",
            "/api/v1/experimental/agent3/plan",
            write_payload,
        )
        write_receipt = _receipt(write_preview)
        if write_receipt.get("sha256") != context_sha:
            raise ValidationError("write preview receipt differs from reviewed memory block")
        write_plan = _require_list(write_preview, "plan")
        if len(write_plan) != 1 or not isinstance(write_plan[0], dict):
            raise ValidationError(f"write planner must return exactly one step: {write_plan}")
        write_step = write_plan[0]
        if write_step.get("tool") != "note_append" or write_step.get("risk") != "write":
            raise ValidationError(f"unexpected write plan: {write_plan}")
        args = write_step.get("args")
        if not isinstance(args, dict) or args.get("text") != marker:
            raise ValidationError(
                "planner did not preserve the exact harmless validation marker; "
                "refusing to start the write plan"
            )
        write_plan_id = write_preview.get("plan_id")
        if not isinstance(write_plan_id, str) or not write_plan_id:
            raise ValidationError(f"write preview returned no plan_id: {write_preview}")
        report["checks"]["write_preview"] = {
            "plan_id": write_plan_id,
            "tool": write_step.get("tool"),
            "risk": write_step.get("risk"),
            "sensitivity": write_step.get("sensitivity"),
            "egress": write_step.get("egress"),
            "receipt": write_receipt,
        }

        print("[6/9] Start reviewed write plan and inspect confirmation card")
        write_started = client.request(
            "POST",
            f"/api/v1/experimental/agent3/plans/{_quoted(write_plan_id)}/start",
            {},
        )
        if _require_object(write_started, "memory_context") != write_receipt:
            raise ValidationError("write plan-start receipt differs from preview receipt")
        write_run = _poll_checkpoint(
            client,
            _require_object(write_started, "run"),
            max_wait_seconds=max_wait_seconds,
            poll_seconds=poll_seconds,
        )
        if write_run.get("state") != "waiting_confirmation":
            raise ValidationError(f"write run did not stop for confirmation: {write_run}")
        write_steps = _require_list(write_run, "steps")
        current_index = write_run.get("current_step")
        if not isinstance(current_index, int) or current_index != 0:
            raise ValidationError(f"unexpected current write step: {current_index}")
        current = write_steps[current_index]
        if not isinstance(current, dict):
            raise ValidationError("current write step is not an object")
        step_id = current.get("id")
        digest = current.get("confirmation_digest")
        expires_at = current.get("confirmation_expires_at")
        if not isinstance(step_id, str) or not step_id:
            raise ValidationError("confirmation card has no step id")
        if not isinstance(digest, str) or len(digest) < 32:
            raise ValidationError("confirmation card has no immutable digest")
        if not isinstance(expires_at, (int, float)) or expires_at <= time.time():
            raise ValidationError("confirmation card is already expired")
        write_run_id = write_run.get("id")
        if not isinstance(write_run_id, str) or not write_run_id:
            raise ValidationError("write run has no id")

        pre_kinds, _ = _event_kinds(client, write_run_id)
        _require_event_sequence(
            pre_kinds,
            ("run_created", "policy_decision", "confirmation_required"),
            "write pre-confirmation",
        )
        if "step_started" in pre_kinds or "step_succeeded" in pre_kinds:
            raise ValidationError(f"write executed before confirmation: {pre_kinds}")
        report["checks"]["confirmation_card"] = {
            "run_id": write_run_id,
            "step_id": step_id,
            "summary": current.get("summary"),
            "expires_at": expires_at,
            "digest_sha256": hashlib.sha256(digest.encode("utf-8")).hexdigest(),
            "pre_confirmation_events": pre_kinds,
        }

        decision = "approve" if approve_write else "deny"
        print(
            "[7/9] "
            + (
                "APPROVE explicit append-only validation write"
                if approve_write
                else "DENY validation write (default, no mutation)"
            )
        )
        confirmed = client.request(
            "POST",
            f"/api/v1/experimental/agent3/runs/{_quoted(write_run_id)}/confirm",
            {
                "step_id": step_id,
                "decision": decision,
                "digest": digest,
            },
        )
        final_write_run = _poll_checkpoint(
            client,
            _require_object(confirmed, "run"),
            max_wait_seconds=max_wait_seconds,
            poll_seconds=poll_seconds,
        )
        write_kinds, write_events = _event_kinds(client, write_run_id)

        if approve_write:
            if final_write_run.get("state") != "completed":
                raise ValidationError(f"approved write did not complete: {final_write_run}")
            final_steps = _require_list(final_write_run, "steps")
            if (
                len(final_steps) != 1
                or not isinstance(final_steps[0], dict)
                or final_steps[0].get("state") != "succeeded"
            ):
                raise ValidationError(f"approved write step did not succeed: {final_steps}")
            _require_event_sequence(
                write_kinds,
                (
                    "run_created",
                    "policy_decision",
                    "confirmation_required",
                    "confirmation_approved",
                    "step_started",
                    "step_succeeded",
                    "run_completed",
                ),
                "approved write",
            )
        else:
            if final_write_run.get("state") != "cancelled":
                raise ValidationError(f"denied write did not cancel: {final_write_run}")
            final_steps = _require_list(final_write_run, "steps")
            if (
                len(final_steps) != 1
                or not isinstance(final_steps[0], dict)
                or final_steps[0].get("state") != "denied"
            ):
                raise ValidationError(f"denied write step is not denied: {final_steps}")
            _require_event_sequence(
                write_kinds,
                (
                    "run_created",
                    "policy_decision",
                    "confirmation_required",
                    "confirmation_denied",
                ),
                "denied write",
            )
            if "step_started" in write_kinds or "step_succeeded" in write_kinds:
                raise ValidationError(f"denied write still executed: {write_kinds}")

        report["checks"]["write_confirmation"] = {
            "decision": decision,
            "run_id": write_run_id,
            "state": final_write_run.get("state"),
            "event_kinds": write_kinds,
            "event_count": len(write_events),
            "mutation_expected": approve_write,
        }

        print("[8/9] Single-use plan replay is refused")
        replay_blocked = False
        try:
            client.request(
                "POST",
                f"/api/v1/experimental/agent3/plans/{_quoted(write_plan_id)}/start",
                {},
            )
        except ValidationError as exc:
            if "HTTP 409" in str(exc):
                replay_blocked = True
            else:
                raise
        if not replay_blocked:
            raise ValidationError("single-use write plan could be started twice")
        report["checks"]["single_use"] = {"replay_blocked": True}

        report["success"] = True
        print("[9/9] Validation checks passed; cleaning disposable memory")
        return report

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise

    finally:
        if memory_id:
            try:
                deleted = client.request(
                    "DELETE",
                    f"/api/v1/experimental/agent3/memory/{_quoted(memory_id)}",
                )
                tombstone = _require_object(deleted, "memory")
                cleanup_ok = (
                    tombstone.get("lifecycle_status") == "deleted"
                    and tombstone.get("review_status") == "rejected"
                    and tombstone.get("value") == ""
                    and tombstone.get("source_ref") is None
                )
                report["cleanup"] = {
                    "memory_id": memory_id,
                    "deleted": cleanup_ok,
                    "lifecycle_status": tombstone.get("lifecycle_status"),
                    "content_erased": tombstone.get("value") == "",
                    "source_ref_erased": tombstone.get("source_ref") is None,
                }
                if not cleanup_ok and report.get("success"):
                    report["success"] = False
                    report["error"] = (
                        "Memory cleanup did not produce a content-free tombstone"
                    )
            except Exception as cleanup_exc:
                report["cleanup"] = {
                    "memory_id": memory_id,
                    "deleted": False,
                    "error": f"{type(cleanup_exc).__name__}: {cleanup_exc}",
                }
                if report.get("success"):
                    report["success"] = False
                    report["error"] = (
                        "Validation passed but disposable memory cleanup failed"
                    )

        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        _write_report(report_path, report)
        print(f"      report={report_path}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("MODELRIG_BASE_URL", "http://127.0.0.1:8080"),
        help="ModelRig Go backend URL (default: MODELRIG_BASE_URL or localhost:8080)",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("MODELRIG_TOKEN", ""),
        help="paired device token (prefer MODELRIG_TOKEN instead of command history)",
    )
    parser.add_argument(
        "--planner-model",
        default=os.getenv("KALIV_AGENT3_PLANNER_MODEL") or None,
        help="local Ollama model used for real planner validation",
    )
    parser.add_argument(
        "--approve-write",
        action="store_true",
        help=(
            "approve one append-only note containing a unique marker; without this "
            "flag the write confirmation is denied and no mutation is expected"
        ),
    )
    parser.add_argument(
        "--report",
        default=os.getenv(
            "KALIV_AGENT3_VALIDATION_REPORT",
            "validation/agent3-rig-validation-latest.json",
        ),
        help="JSON report path; token and memory value are never written",
    )
    parser.add_argument("--http-timeout", type=float, default=300.0)
    parser.add_argument("--run-timeout", type=float, default=60.0)
    parser.add_argument("--poll-seconds", type=float, default=0.5)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.token:
        print("ERROR: MODELRIG_TOKEN/--token is required", file=sys.stderr)
        return 2
    report_path = Path(args.report)
    try:
        report = run_validation(
            Client(args.base_url, args.token, args.http_timeout),
            planner_model=args.planner_model,
            approve_write=args.approve_write,
            report_path=report_path,
            poll_seconds=args.poll_seconds,
            max_wait_seconds=args.run_timeout,
        )
    except ValidationError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"FAIL: unexpected {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    if not report.get("success"):
        print(
            f"FAIL: validation report recorded failure: {report.get('error')}",
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: Agent 3.0 memory/planner/plan/confirmation/audit validation "
        f"completed ({'write approved' if args.approve_write else 'write denied safely'})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

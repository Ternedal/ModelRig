#!/usr/bin/env python3
"""End-to-end smoke test for the experimental Kaliv Agent 3.0 path.

The test intentionally goes through the public Go backend, not directly to the
loopback-only worker:

    Bearer gateway -> local planner -> single-use plan -> persistent run -> V2 gate

It uses a read-only rig_status plan by default, so it cannot mutate the rig.

Example (PowerShell):

    $env:MODELRIG_TOKEN = "<device token>"
    python scripts/agent3_smoke.py --base-url http://127.0.0.1:8080
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class SmokeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Client:
    base_url: str
    token: str
    timeout: float = 300.0

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self.base_url.rstrip("/") + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Request-ID": f"agent3-smoke-{int(time.time() * 1000)}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail = json.loads(raw).get("detail") or json.loads(raw).get("error") or raw
            except json.JSONDecodeError:
                detail = raw
            raise SmokeError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SmokeError(f"cannot reach {self.base_url}: {exc.reason}") from exc
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SmokeError(f"{method} {path} returned invalid JSON: {raw[:300]!r}") from exc
        if not isinstance(data, dict):
            raise SmokeError(f"{method} {path} returned a non-object JSON response")
        return data


def _require_object(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise SmokeError(f"response is missing object field {key!r}")
    return value


def _require_list(parent: dict[str, Any], key: str) -> list[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise SmokeError(f"response is missing array field {key!r}")
    return value


def run_smoke(
    client: Client,
    *,
    message: str,
    planner_model: str | None = None,
    expected_tool: str = "rig_status",
    poll_seconds: float = 0.5,
    max_wait_seconds: float = 30.0,
) -> dict[str, Any]:
    print("[1/5] Agent 3.0 status")
    status = client.request("GET", "/api/v1/experimental/agent3/status")
    if status.get("enabled") is not True or status.get("experimental") is not True:
        raise SmokeError(f"unexpected status response: {status}")

    print("[2/5] Plan preview (read-only)")
    plan_payload: dict[str, Any] = {
        "message": message,
        "mode": "rig",
        "rag": False,
        "cloud_ready": False,
        "proactive": False,
    }
    if planner_model:
        plan_payload["planner_model"] = planner_model
    preview = client.request("POST", "/api/v1/experimental/agent3/plan", plan_payload)
    if preview.get("executed") is not False:
        raise SmokeError("plan preview claimed to execute work")
    plan_id = preview.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise SmokeError(f"planner returned no single-use plan_id: {preview}")
    plan = _require_list(preview, "plan")
    if not plan:
        raise SmokeError("planner returned an empty plan")
    tools = [step.get("tool") for step in plan if isinstance(step, dict)]
    if expected_tool and expected_tool not in tools:
        raise SmokeError(f"expected tool {expected_tool!r}, planner proposed {tools!r}")
    if any(isinstance(step, dict) and step.get("risk") != "read" for step in plan):
        raise SmokeError(f"default smoke plan is not read-only: {plan}")
    print(f"      plan_id={plan_id} tools={tools}")

    print("[3/5] Start the exact reviewed plan")
    started = client.request(
        "POST",
        f"/api/v1/experimental/agent3/plans/{urllib.parse.quote(plan_id, safe='')}/start",
        {},
    )
    run = _require_object(started, "run")
    run_id = run.get("id")
    if not isinstance(run_id, str) or not run_id:
        raise SmokeError(f"plan start returned no run id: {started}")

    print("[4/5] Poll persistent run")
    deadline = time.monotonic() + max_wait_seconds
    terminal = {"completed", "failed", "cancelled", "blocked"}
    while run.get("state") not in terminal:
        if run.get("state") == "waiting_confirmation":
            raise SmokeError("read-only smoke unexpectedly requires confirmation")
        if time.monotonic() >= deadline:
            raise SmokeError(f"run {run_id} did not finish within {max_wait_seconds}s")
        time.sleep(max(0.05, poll_seconds))
        run = _require_object(
            client.request("GET", f"/api/v1/experimental/agent3/runs/{urllib.parse.quote(run_id, safe='')}"),
            "run",
        )
    if run.get("state") != "completed":
        raise SmokeError(f"run ended in {run.get('state')!r}: {run.get('error')}")
    steps = _require_list(run, "steps")
    if not steps or any(not isinstance(step, dict) or step.get("state") != "succeeded" for step in steps):
        raise SmokeError(f"not every step succeeded: {steps}")

    print("[5/5] Verify audit events")
    event_response = client.request(
        "GET",
        f"/api/v1/experimental/agent3/runs/{urllib.parse.quote(run_id, safe='')}/events",
    )
    events = _require_list(event_response, "events")
    kinds = [event.get("kind") for event in events if isinstance(event, dict)]
    for required in ("run_created", "step_started", "step_succeeded", "run_completed"):
        if required not in kinds:
            raise SmokeError(f"event stream is missing {required!r}: {kinds}")

    print(f"PASS: run={run_id} state=completed events={len(events)}")
    return {"preview": preview, "run": run, "events": events}


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
        help="optional local Ollama model used for planning",
    )
    parser.add_argument(
        "--message",
        default="Brug værktøjet rig_status til at læse riggens aktuelle status.",
        help="read-only request sent to the planner",
    )
    parser.add_argument("--expected-tool", default="rig_status")
    parser.add_argument("--http-timeout", type=float, default=300.0)
    parser.add_argument("--run-timeout", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not args.token:
        print("ERROR: MODELRIG_TOKEN/--token is required", file=sys.stderr)
        return 2
    try:
        run_smoke(
            Client(args.base_url, args.token, args.http_timeout),
            message=args.message,
            planner_model=args.planner_model,
            expected_tool=args.expected_tool,
            max_wait_seconds=args.run_timeout,
        )
    except SmokeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

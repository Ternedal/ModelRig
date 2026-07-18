#!/usr/bin/env python3
"""Plan-only baseline harness for the experimental Kaliv Agent 3 planner.

The harness measures whether a local planner chooses the right tools, preserves
exact arguments and stays within the requested number of steps. It deliberately
stops at the preview boundary: it never starts a plan, confirms a write or calls
a tool. That makes the harness safe to prepare and review without a physical rig;
only the later measurement run needs the rig, Ollama and a paired-device token.

PowerShell, from the repository root:

    $env:MODELRIG_TOKEN = "<paired device token>"
    python scripts/agent3_model_eval.py `
      --planner-model qwen3:14b `
      --report validation/agent3-model-eval-latest.json

Exit code is 0 when every request completed and the aggregate exact-match score
meets --fail-under. No bearer token or full backend error body is written to the
report.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import socket
import statistics
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

SCHEMA = "kaliv-agent3-model-eval/v1"
TASK_SET_SCHEMA = "kaliv-agent3-model-eval-task-set/v1"
DEFAULT_TASK_SET = Path(__file__).resolve().parents[1] / "eval" / "agent3_model_tasks.json"
DEFAULT_REPORT = Path("validation/agent3-model-eval-latest.json")


class EvalError(RuntimeError):
    """The harness cannot produce a trustworthy result."""


class Requester(Protocol):
    def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


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
                "X-Request-ID": f"agent3-model-eval-{int(time.time() * 1000)}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raw = exc.read(2048).decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
                detail = parsed.get("detail") or parsed.get("error") or "request refused"
            except json.JSONDecodeError:
                detail = "non-JSON error response"
            raise EvalError(f"{method} {path} returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EvalError(f"cannot reach {self.base_url}: {exc.reason}") from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvalError(f"{method} {path} returned invalid JSON") from exc
        if not isinstance(data, dict):
            raise EvalError(f"{method} {path} returned a non-object JSON response")
        return data


def _require_str(obj: dict[str, Any], key: str, *, where: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalError(f"{where} is missing non-empty string {key!r}")
    return value


def _validate_expected_step(step: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(step, dict):
        raise EvalError(f"{where} must be an object")
    tool = _require_str(step, "tool", where=where)
    risk = _require_str(step, "risk", where=where)
    if risk not in {"read", "write", "desktop"}:
        raise EvalError(f"{where}.risk has unsupported value {risk!r}")
    args = step.get("args", {})
    if not isinstance(args, dict):
        raise EvalError(f"{where}.args must be an object")
    return {"tool": tool, "risk": risk, "args": args}


def load_task_set(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EvalError(f"task set does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EvalError(f"task set is invalid JSON: {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != TASK_SET_SCHEMA:
        raise EvalError(f"task set must use schema {TASK_SET_SCHEMA!r}")
    tasks = raw.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise EvalError("task set must contain a non-empty tasks array")

    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(tasks):
        where = f"tasks[{index}]"
        if not isinstance(item, dict):
            raise EvalError(f"{where} must be an object")
        task_id = _require_str(item, "id", where=where)
        if task_id in seen:
            raise EvalError(f"duplicate task id {task_id!r}")
        seen.add(task_id)
        prompt = _require_str(item, "prompt", where=where)
        category = _require_str(item, "category", where=where)
        expected = item.get("expected")
        if not isinstance(expected, dict):
            raise EvalError(f"{where}.expected must be an object")
        steps = expected.get("steps")
        if not isinstance(steps, list):
            raise EvalError(f"{where}.expected.steps must be an array")
        normalized_steps = [
            _validate_expected_step(step, where=f"{where}.expected.steps[{i}]")
            for i, step in enumerate(steps)
        ]
        max_steps = expected.get("max_steps", len(normalized_steps))
        if not isinstance(max_steps, int) or max_steps < 0:
            raise EvalError(f"{where}.expected.max_steps must be a non-negative integer")
        forbidden = expected.get("forbidden_tools", [])
        if not isinstance(forbidden, list) or not all(
            isinstance(value, str) and value for value in forbidden
        ):
            raise EvalError(f"{where}.expected.forbidden_tools must be a string array")
        normalized.append(
            {
                "id": task_id,
                "prompt": prompt,
                "category": category,
                "expected": {
                    "steps": normalized_steps,
                    "max_steps": max_steps,
                    "forbidden_tools": sorted(set(forbidden)),
                },
            }
        )

    return {
        "schema": TASK_SET_SCHEMA,
        "name": str(raw.get("name") or path.stem),
        "version": str(raw.get("version") or "unversioned"),
        "tasks": normalized,
    }


def _actual_steps(response: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    plan = response.get("plan")
    if not isinstance(plan, list):
        return [], "response is missing array field 'plan'"
    steps: list[dict[str, Any]] = []
    for index, raw in enumerate(plan):
        if not isinstance(raw, dict):
            return [], f"plan[{index}] is not an object"
        tool = raw.get("tool")
        risk = raw.get("risk")
        args = raw.get("args", {})
        if not isinstance(tool, str) or not tool:
            return [], f"plan[{index}] has no tool"
        if not isinstance(risk, str) or not risk:
            return [], f"plan[{index}] has no risk"
        if not isinstance(args, dict):
            return [], f"plan[{index}].args is not an object"
        steps.append({"tool": tool, "risk": risk, "args": args})
    return steps, None


def compare_plan(task: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    expected = task["expected"]
    wanted: list[dict[str, Any]] = expected["steps"]
    actual, structural_error = _actual_steps(response)
    findings: list[str] = []
    if structural_error:
        findings.append(structural_error)

    max_steps = expected["max_steps"]
    if len(actual) > max_steps:
        findings.append(f"step budget exceeded: {len(actual)} > {max_steps}")

    actual_tools = [step["tool"] for step in actual]
    forbidden = sorted(set(actual_tools).intersection(expected["forbidden_tools"]))
    if forbidden:
        findings.append("forbidden tools proposed: " + ", ".join(forbidden))

    if len(actual) != len(wanted):
        findings.append(f"expected {len(wanted)} steps, got {len(actual)}")

    compared = min(len(actual), len(wanted))
    tool_matches = 0
    risk_matches = 0
    args_matches = 0
    for index in range(compared):
        got = actual[index]
        want = wanted[index]
        if got["tool"] == want["tool"]:
            tool_matches += 1
        else:
            findings.append(
                f"step {index}: expected tool {want['tool']!r}, got {got['tool']!r}"
            )
        if got["risk"] == want["risk"]:
            risk_matches += 1
        else:
            findings.append(
                f"step {index}: expected risk {want['risk']!r}, got {got['risk']!r}"
            )
        if got["args"] == want["args"]:
            args_matches += 1
        else:
            findings.append(
                f"step {index}: expected args {want['args']!r}, got {got['args']!r}"
            )

    denominator = max(1, len(wanted))
    tool_score = tool_matches / denominator
    risk_score = risk_matches / denominator
    args_score = args_matches / denominator
    discipline_pass = structural_error is None and len(actual) <= max_steps and not forbidden
    exact_match = discipline_pass and actual == wanted
    return {
        "exact_match": exact_match,
        "tool_score": round(tool_score, 6),
        "risk_score": round(risk_score, 6),
        "args_score": round(args_score, 6),
        "discipline_pass": discipline_pass,
        "expected_steps": wanted,
        "actual_steps": actual,
        "findings": findings,
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [item for item in results if item.get("request_error") is None]
    latencies = [float(item["latency_ms"]) for item in completed]
    exact = [item for item in completed if item["evaluation"]["exact_match"]]
    disciplined = [item for item in completed if item["evaluation"]["discipline_pass"]]
    category_counts: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = category_counts.setdefault(item["category"], {"total": 0, "exact": 0})
        bucket["total"] += 1
        if item.get("request_error") is None and item["evaluation"]["exact_match"]:
            bucket["exact"] += 1

    total = len(results)
    return {
        "tasks": total,
        "requests_completed": len(completed),
        "request_errors": total - len(completed),
        "exact_matches": len(exact),
        "exact_match_rate": round(len(exact) / max(1, total), 6),
        "discipline_passes": len(disciplined),
        "discipline_rate": round(len(disciplined) / max(1, total), 6),
        "latency_ms": {
            "min": round(min(latencies), 3) if latencies else None,
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
        "categories": category_counts,
    }


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
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
        temp = Path(handle.name)
    temp.replace(path)


def run_eval(
    client: Requester,
    task_set: dict[str, Any],
    *,
    planner_model: str | None,
    repetitions: int = 1,
) -> dict[str, Any]:
    if repetitions < 1:
        raise EvalError("repetitions must be at least 1")
    started_at = datetime.now(timezone.utc)
    status = client.request("GET", "/api/v1/experimental/agent3/status")
    if status.get("experimental") is not True:
        raise EvalError("Agent 3 status does not report experimental=true")

    results: list[dict[str, Any]] = []
    for repetition in range(1, repetitions + 1):
        for task in task_set["tasks"]:
            payload: dict[str, Any] = {
                "message": task["prompt"],
                "mode": "rig",
                "rag": False,
                "cloud_ready": False,
                "proactive": False,
                "use_memory": False,
            }
            if planner_model:
                payload["planner_model"] = planner_model
            begin = time.perf_counter()
            request_error: str | None = None
            response: dict[str, Any] = {}
            try:
                response = client.request(
                    "POST",
                    "/api/v1/experimental/agent3/plan",
                    payload,
                )
                evaluation = compare_plan(task, response)
            except EvalError as exc:
                request_error = str(exc)
                evaluation = {
                    "exact_match": False,
                    "tool_score": 0.0,
                    "risk_score": 0.0,
                    "args_score": 0.0,
                    "discipline_pass": False,
                    "expected_steps": task["expected"]["steps"],
                    "actual_steps": [],
                    "findings": ["planner request failed"],
                }
            latency_ms = (time.perf_counter() - begin) * 1000
            results.append(
                {
                    "task_id": task["id"],
                    "category": task["category"],
                    "repetition": repetition,
                    "latency_ms": round(latency_ms, 3),
                    "plan_id_present": isinstance(response.get("plan_id"), str),
                    "request_error": request_error,
                    "evaluation": evaluation,
                }
            )

    summary = summarize(results)
    return {
        "schema": SCHEMA,
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "host": {
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python": platform.python_version(),
        },
        "target": {
            "planner_model": planner_model,
            "repetitions": repetitions,
            "execution_mode": "plan-only",
            "starts_plans": False,
            "executes_tools": False,
        },
        "backend": {
            "enabled": status.get("enabled"),
            "experimental": status.get("experimental"),
            "code_sha256": status.get("code_sha256"),
            "version": status.get("version"),
        },
        "task_set": {
            "schema": task_set["schema"],
            "name": task_set["name"],
            "version": task_set["version"],
            "task_count": len(task_set["tasks"]),
        },
        "summary": summary,
        "results": results,
    }


def _print_summary(report: dict[str, Any], *, fail_under: float) -> None:
    summary = report["summary"]
    latency = summary["latency_ms"]
    print()
    print("  Agent 3 model-eval — plan-only baseline")
    print("  " + "-" * 58)
    print(
        f"  exact: {summary['exact_matches']}/{summary['tasks']} "
        f"({summary['exact_match_rate']:.1%})"
    )
    print(
        f"  discipline: {summary['discipline_passes']}/{summary['tasks']} "
        f"({summary['discipline_rate']:.1%})"
    )
    print(
        "  latency ms: "
        f"p50={latency['p50']} p95={latency['p95']} mean={latency['mean']}"
    )
    print(f"  gate: exact_match_rate >= {fail_under:.1%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("MODELRIG_BASE_URL", "http://127.0.0.1:8080"),
        help="backend base URL (default: MODELRIG_BASE_URL or loopback :8080)",
    )
    parser.add_argument(
        "--planner-model",
        default=os.getenv("KALIV_AGENT3_PLANNER_MODEL") or None,
        help="local Ollama planner model (default: KALIV_AGENT3_PLANNER_MODEL)",
    )
    parser.add_argument("--task-set", type=Path, default=DEFAULT_TASK_SET)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument(
        "--fail-under",
        type=float,
        default=1.0,
        help="minimum exact-match rate from 0.0 to 1.0 (default: 1.0)",
    )
    args = parser.parse_args(argv)
    if not 0.0 <= args.fail_under <= 1.0:
        parser.error("--fail-under must be between 0.0 and 1.0")
    token = os.getenv("MODELRIG_TOKEN", "").strip()
    if not token:
        parser.error("MODELRIG_TOKEN is required; keep it in the environment")

    try:
        task_set = load_task_set(args.task_set)
        report = run_eval(
            Client(args.base_url, token, timeout=args.timeout),
            task_set,
            planner_model=args.planner_model,
            repetitions=args.repetitions,
        )
        _write_json_atomic(args.report, report)
    except EvalError as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2

    _print_summary(report, fail_under=args.fail_under)
    print(f"  report: {args.report}")
    summary = report["summary"]
    if summary["request_errors"]:
        return 1
    return 0 if summary["exact_match_rate"] >= args.fail_under else 1


if __name__ == "__main__":
    raise SystemExit(main())

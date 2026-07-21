#!/usr/bin/env python3
"""Apply only T-018 runtime/API concurrency status fields. Temporary transport."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:180]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


RUNTIME = "worker/app/schedule_runtime.py"
replace_once(
    RUNTIME,
    '''class RuntimeStatus:\n    configured: bool\n    running: bool\n    resources_open: bool\n    last_error: str | None\n''',
    '''class RuntimeStatus:\n    configured: bool\n    running: bool\n    resources_open: bool\n    last_error: str | None\n    max_concurrency: int\n    queue_capacity: int\n    active_executions: int\n    accepted_ticks: int\n    overlap_rejections: int\n''',
)
replace_once(
    RUNTIME,
    '''            return RuntimeStatus(\n                configured=configured,\n                running=running,\n                resources_open=any(\n                    resource is not None\n                    for resource in (self._service, self._jobs, self._schedules)\n                ),\n                last_error=self._last_error,\n            )\n''',
    '''            single_flight = None\n            if self._service is not None:\n                runner = getattr(self._service, "runner", None)\n                status_fn = getattr(runner, "single_flight_status", None)\n                if callable(status_fn):\n                    try:\n                        single_flight = status_fn()\n                    except Exception:\n                        single_flight = None\n            return RuntimeStatus(\n                configured=configured,\n                running=running,\n                resources_open=any(\n                    resource is not None\n                    for resource in (self._service, self._jobs, self._schedules)\n                ),\n                last_error=self._last_error,\n                max_concurrency=int(getattr(single_flight, "max_concurrency", 1)),\n                queue_capacity=int(getattr(single_flight, "queue_capacity", 0)),\n                active_executions=int(getattr(single_flight, "active", 0)),\n                accepted_ticks=int(getattr(single_flight, "accepted", 0)),\n                overlap_rejections=int(\n                    getattr(single_flight, "overlap_rejections", 0)\n                ),\n            )\n''',
)

API = "worker/app/schedule_api.py"
replace_once(
    API,
    '''        return {\n            "configured": enabled(),\n            "running": False,\n            "resources_open": False,\n            "last_error": None,\n        }\n''',
    '''        return {\n            "configured": enabled(),\n            "running": False,\n            "resources_open": False,\n            "last_error": None,\n            "max_concurrency": 1,\n            "queue_capacity": 0,\n            "active_executions": 0,\n            "accepted_ticks": 0,\n            "overlap_rejections": 0,\n        }\n''',
)
replace_once(
    API,
    '''        return {\n            "configured": enabled(),\n            "running": False,\n            "resources_open": True,\n            "last_error": f"{type(exc).__name__}: {exc}"[:500],\n        }\n''',
    '''        return {\n            "configured": enabled(),\n            "running": False,\n            "resources_open": True,\n            "last_error": f"{type(exc).__name__}: {exc}"[:500],\n            "max_concurrency": 1,\n            "queue_capacity": 0,\n            "active_executions": 0,\n            "accepted_ticks": 0,\n            "overlap_rejections": 0,\n        }\n''',
)
replace_once(
    API,
    '''    return {\n        "configured": bool(state.configured),\n        "running": bool(state.running),\n        "resources_open": bool(state.resources_open),\n        "last_error": state.last_error,\n    }\n''',
    '''    return {\n        "configured": bool(state.configured),\n        "running": bool(state.running),\n        "resources_open": bool(state.resources_open),\n        "last_error": state.last_error,\n        "max_concurrency": int(getattr(state, "max_concurrency", 1)),\n        "queue_capacity": int(getattr(state, "queue_capacity", 0)),\n        "active_executions": int(getattr(state, "active_executions", 0)),\n        "accepted_ticks": int(getattr(state, "accepted_ticks", 0)),\n        "overlap_rejections": int(getattr(state, "overlap_rejections", 0)),\n    }\n''',
)

TEST = "tests/worker_scheduler_single_flight.py"
replace_once(
    TEST,
    '''from app.schedule_service import SchedulerService  # noqa: E402\nfrom app.scheduler_single_flight import install_single_flight  # noqa: E402\n''',
    '''from app.schedule_api import _runtime_status  # noqa: E402\nfrom app.schedule_runtime import SchedulerRuntime  # noqa: E402\nfrom app.schedule_service import SchedulerService  # noqa: E402\nfrom app.scheduler_single_flight import install_single_flight  # noqa: E402\n''',
)
replace_once(
    TEST,
    '''check(service_runner.calls == 1, "service overlap never enters underlying execution")\ncheck(not service.stop(timeout=0.05), "shutdown timeout reports active tick honestly")\n''',
    '''check(service_runner.calls == 1, "service overlap never enters underlying execution")\nruntime = SchedulerRuntime(enabled_fn=lambda: True)\nruntime._service = service\nruntime._jobs = object()\nruntime._schedules = object()\nruntime._started = True\nruntime_state = runtime.status()\ncheck(runtime_state.max_concurrency == 1, "runtime exposes max concurrency")\ncheck(runtime_state.queue_capacity == 0, "runtime exposes zero queue capacity")\ncheck(runtime_state.active_executions == 1, "runtime exposes active execution")\ncheck(runtime_state.overlap_rejections == 1, "runtime exposes rejection count")\nrequest = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(scheduler_runtime=runtime)))\npayload = _runtime_status(request)\ncheck(payload["max_concurrency"] == 1, "operator API exposes max concurrency")\ncheck(payload["queue_capacity"] == 0, "operator API exposes zero queue")\ncheck(payload["active_executions"] == 1, "operator API exposes active execution")\ncheck(payload["overlap_rejections"] == 1, "operator API exposes rejection count")\ncheck(not service.stop(timeout=0.05), "shutdown timeout reports active tick honestly")\n''',
)

print("T-018 stage 2 status patch applied")

#!/usr/bin/env python3
"""Contract for the Stage-B admission driver's side-by-side phases.

The shared-provenance child (phase 1b) and the nonce-reuse guard (phase 2a) run as
two isolated processes started together. This drives the driver's own functions
with the contract runner replaced, so it is fast and says nothing about the
contracts themselves - only about what the driver starts, when, and with which
environment.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))

import rsi_pilot_exact_task_execution_admission_stage_b_driver as driver  # noqa: E402

CACHE = "MODELRIG_STAGE_B_ADMISSION_PROOF_CACHE"
LEDGER = "MODELRIG_STAGE_B_START_LEDGER_ROOT"
CHILD = driver._SHARED_DEEP_CHAIN_FILE
GUARD = driver._NONCE_REUSE_FILE
SHALLOW = set(driver._SHALLOW_CONTRACT_FILES)
passed = 0


def check(name: str, condition: bool, detail: object = "") -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL: {name} {detail}")
    passed += 1
    print(f"PASS: {name}")


class Runner:
    """Stands in for _run_contract_file and records what the driver asked for."""

    def __init__(self, *, failing: frozenset[str] = frozenset(), publish: bool = True):
        self.failing = failing
        self.publish = publish
        self.lock = threading.Lock()
        self.events: list[tuple[str, str]] = []
        self.envs: dict[str, dict[str, str]] = {}
        # Only passes if the child and the guard are in flight at the same time.
        self.together = threading.Barrier(2)
        self.met = False

    def __call__(self, filename, base_env=None):
        env = dict(os.environ if base_env is None else base_env)
        with self.lock:
            self.events.append(("start", filename))
            self.envs[filename] = env
        if filename in (CHILD, GUARD) and base_env is not None:
            try:
                self.together.wait(timeout=20)
                self.met = True
            except threading.BrokenBarrierError:
                pass
        if filename == GUARD and self.publish and filename not in self.failing:
            Path(env[CACHE]).write_text("{}", encoding="utf-8")
        with self.lock:
            self.events.append(("end", filename))
        return filename, (1 if filename in self.failing else 0), 0.0, f"output of {filename}"

    def started(self) -> list[str]:
        return [name for kind, name in self.events if kind == "start"]


def with_runner(runner: Runner, fn, env: dict[str, str | None]):
    original = driver._run_contract_file
    saved = {name: os.environ.get(name) for name in (CACHE, LEDGER, driver._STAGE_B_SLICE_ENV,
                                                      driver._CACHE_ROOT_ENV, driver._CONTRACT_SHARD_ENV)}
    for name in saved:
        os.environ.pop(name, None)
    for name, value in env.items():
        if value is not None:
            os.environ[name] = value
    driver._run_contract_file = runner
    try:
        try:
            fn()
            return None
        except AssertionError as exc:
            return exc
    finally:
        driver._run_contract_file = original
        after = {name: os.environ.get(name) for name in (CACHE, LEDGER)}
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        runner.environment_after = after


# 1. The admission slice: shallow contracts first, then child and guard together.
runner = Runner()
error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "admission"})
check("admission slice passes when every contract passes", error is None, error)
check("the child and the guard were in flight at the same time", runner.met)
order = runner.started()
check("both shallow contracts start before the child and the guard",
      set(order[:2]) == SHALLOW and set(order[2:]) == {CHILD, GUARD}, order)
last_shallow_end = max(i for i, e in enumerate(runner.events) if e[0] == "end" and e[1] in SHALLOW)
first_deep_start = min(i for i, e in enumerate(runner.events) if e[0] == "start" and e[1] in (CHILD, GUARD))
check("the shallow phase has ended before either deep phase starts", last_shallow_end < first_deep_start)
check("each contract ran exactly once", sorted(order) == sorted(SHALLOW | {CHILD, GUARD}), order)

# 2. The environment each of the two gets.
guard_env, child_env = runner.envs[GUARD], runner.envs[CHILD]
check("the guard is given the proof-cache and start-ledger targets", CACHE in guard_env and LEDGER in guard_env)
check("the guard's cache target sits beside its start ledger",
      Path(guard_env[CACHE]).parent == Path(guard_env[LEDGER]).parent)
check("the child is given no proof-cache target", CACHE not in child_env, child_env.get(CACHE))
check("the child is given no start-ledger target", LEDGER not in child_env, child_env.get(LEDGER))
check("the driver leaves no cache target behind in its own environment",
      runner.environment_after == {CACHE: None, LEDGER: None}, runner.environment_after)

# 3. Targets that were already set belong to the caller: the child sees those, not the new ones.
runner = Runner(publish=False)  # the paths are names only; nothing is written to them
with_runner(runner, lambda: driver._run_shared_child_beside_nonce_guard("/outer/proofs.json", "/outer/ledger"),
            {CACHE: "/inner/proofs.json", LEDGER: "/inner/ledger"})
check("the child sees the caller's earlier cache target",
      runner.envs[CHILD][CACHE] == "/outer/proofs.json" and runner.envs[CHILD][LEDGER] == "/outer/ledger")
check("the guard sees the target set for this run",
      runner.envs[GUARD][CACHE] == "/inner/proofs.json" and runner.envs[GUARD][LEDGER] == "/inner/ledger")

# 4. Either one failing fails admission, and the other still ran to its end.
for failing, other in ((CHILD, GUARD), (GUARD, CHILD)):
    runner = Runner(failing=frozenset({failing}))
    error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "admission"})
    check(f"a failing {failing.split('execution_')[-1]} fails admission", error is not None)
    check("the failure names the contract that failed and carries its output",
          failing in str(error) and f"output of {failing}" in str(error), error)
    check("the failure does not blame the contract that passed", f"{other}: exit" not in str(error))
    check("the other contract ran to its end", ("end", other) in runner.events)
runner = Runner(failing=frozenset({CHILD, GUARD}))
error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "admission"})
check("both failing reports both", CHILD in str(error) and f"{GUARD}: exit" in str(error))

# 5. A guard that passes without publishing the cache is still a failed admission.
runner = Runner(publish=False)
error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "admission"})
check("no published proof cache fails admission", error is not None and "did not publish" in str(error), error)

# 6. A failing shallow contract stops admission before the deep phases start.
shallow = sorted(SHALLOW)[0]
runner = Runner(failing=frozenset({shallow}))
error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "admission"})
check("a failing shallow contract fails admission", error is not None and shallow in str(error))
check("neither deep phase starts after a failed shallow phase",
      CHILD not in runner.started() and GUARD not in runner.started(), runner.started())

# 7. A midchain slice without a published cache runs the guard alone; the child is admission's.
runner = Runner()
error = with_runner(runner, driver.run_contract, {driver._STAGE_B_SLICE_ENV: "midchain"})
check("midchain slice without a cache passes", error is None, error)
check("it runs the guard, then the midchain driver, and never the child",
      runner.started() == [GUARD, driver._MIDCHAIN_DRIVER_FILE], runner.started())

print(f"{passed} passed, 0 failed")

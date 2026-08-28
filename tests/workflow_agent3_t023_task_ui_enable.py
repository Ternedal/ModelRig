#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "scripts" / "agent3_termination_ui_physical_one_click.py"
READINESS = ROOT / "worker" / "app" / "agent3" / "task_readiness.py"

operator = OPERATOR.read_text(encoding="utf-8")
readiness = READINESS.read_text(encoding="utf-8")

function_start = operator.index("def ensure_stack_and_readiness")
function_end = operator.index("\ndef find_adb", function_start)
stack_setup = operator[function_start:function_end]

enable = 'os.environ["KALIV_AGENT3_TASK_UI"] = "1"'
# The worker cmd builds an explicit env, so the flag must travel as a switch;
# a bare env set never reaches the child stack (#753).
stack_start = "stage.start_stack(planner, enable_task_ui=True)"
required_gate = '(env.get("KALIV_AGENT3_TASK_UI") or "").strip() == "1"'

stack_positions = []
offset = 0
while True:
    try:
        position = stack_setup.index(stack_start, offset)
    except ValueError:
        break
    stack_positions.append(position)
    offset = position + len(stack_start)

checks = {
    "readiness remains explicit default-off": required_gate in readiness,
    "T-023 explicitly enables its qualification child stack": enable in stack_setup,
    "T-023 enables task UI before starting any child stack": (
        enable in stack_setup
        and bool(stack_positions)
        and all(stack_setup.index(enable) < position for position in stack_positions)
    ),
    "every T-023 stack start carries the task-ui switch": (
        "stage.start_stack(planner)" not in operator
    ),
    "T-023 does not enable production activation": (
        '"production_activation": True' not in operator
        and "production_activation=true" not in operator.lower()
    ),
}

failed = [label for label, ok in checks.items() if not ok]
for label, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== T-023 TASK-UI OPERATOR ENABLE: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)

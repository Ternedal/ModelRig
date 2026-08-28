#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "scripts" / "agent3_termination_ui_physical_one_click.py"
READINESS = ROOT / "worker" / "app" / "agent3" / "task_readiness.py"

operator = OPERATOR.read_text(encoding="utf-8")
readiness = READINESS.read_text(encoding="utf-8")

enable = 'os.environ["KALIV_AGENT3_TASK_UI"] = "1"'
first_stack_start = "stage.start_stack(planner)"
required_gate = '(env.get("KALIV_AGENT3_TASK_UI") or "").strip() == "1"'

checks = {
    "readiness remains explicit default-off": required_gate in readiness,
    "T-023 explicitly enables its qualification child stack": enable in operator,
    "T-023 enables task UI before starting any child stack": (
        enable in operator
        and first_stack_start in operator
        and operator.index(enable) < operator.index(first_stack_start)
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

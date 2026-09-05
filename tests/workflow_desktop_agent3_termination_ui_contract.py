import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

root = Path(__file__).resolve().parents[1]
policy = code_of(root / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3TaskUiPolicy.kt")
screen = code_of(root / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/Agent3TaskApp.kt")

checks = {
    "policy uses server-authored plan permission": (
        "fun canStopPlan(planCanRequest: Boolean?, busy: Boolean)" in policy
        and "planCanRequest == true && !busy" in policy
    ),
    "policy polls terminal plan while active tool executes": (
        'activeToolState == "executing"' in policy
        and 'activeToolRequestState == "pending"' in policy
    ),
    "screen passes exact termination receipt into plan stop policy": (
        "current.termination.plan.canRequest" in screen
        and "Agent3TaskUiPolicy.canStopPlan" in screen
    ),
    "screen polls from run and active-tool truth": (
        "snapshot?.termination?.activeTool?.state" in screen
        and "snapshot?.termination?.activeTool?.requestState" in screen
    ),
    "screen labels the only current action as plan stop": (
        '"Stop plan"' in screen
        and '"Stopper plan…"' in screen
        and 'Text("Stop")' not in screen
    ),
    "screen renders all three termination scopes": (
        'Text("Plan"' in screen
        and 'Text("Modelstream"' in screen
        and 'Text("Aktivt tool"' in screen
    ),
    "screen explains active tool continuation": (
        "prevent_future_steps_active_tool_continues" in screen
        and "det aktive tool fortsætter" in screen
    ),
    "screen exposes no invented active-tool stop route": (
        "cancelTool" not in screen
        and "stopTool" not in screen
        and "/tool/cancel" not in screen
    ),
}

failed = [label for label, ok in checks.items() if not ok]
for label, ok in checks.items():
    print(f"  {'PASS' if ok else 'FAIL'}: {label}")
print(
    f"\n===== DESKTOP AGENT3 TERMINATION UI: "
    f"{len(checks) - len(failed)} passed, {len(failed)} failed ====="
)
raise SystemExit(1 if failed else 0)

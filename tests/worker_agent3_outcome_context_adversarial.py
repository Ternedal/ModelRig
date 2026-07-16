from __future__ import annotations

from app.agent3.core import AgentStep, EgressClass, RiskClass, Sensitivity, StepState
from app.agent3.outcome_context import OutcomeContextCompiler


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class Hostile:
    def __repr__(self):
        raise AssertionError("repr must not be called")

    def __str__(self):
        raise AssertionError("str must not be called")


hostile = Hostile()
item = AgentStep(
    tool="hostile_result",
    args={},
    risk=RiskClass.READ,
    sensitivity=Sensitivity.OPERATIONAL,
    egress=EgressClass.LOCAL,
    state=StepState.SUCCEEDED,
)
item.result = {
    hostile: "dict-key-value",
    "set": {hostile, "safe"},
    "nan": float("nan"),
    "inf": float("inf"),
}

compiler = OutcomeContextCompiler()
context = compiler.compile([item], max_chars=12_000)
check(context.included_step_ids == (item.id,), "hostile values cannot crash compilation")
check("unsupported-key:Hostile" in context.text, "hostile dictionary keys expose type only")
check("unsupported_type" in context.text and "Hostile" in context.text, "hostile set values expose type only")
check("NaN" not in context.text and "Infinity" not in context.text, "non-finite floats do not emit invalid JSON numbers")

bounded = OutcomeContextCompiler(max_depth=2, max_collection_items=2, max_string_chars=32)
bounded_step = AgentStep(
    tool="bounded",
    args={},
    risk=RiskClass.READ,
    sensitivity=Sensitivity.OPERATIONAL,
    egress=EgressClass.LOCAL,
    state=StepState.SUCCEEDED,
)
bounded_step.result = {
    "long": "y" * 200,
    "list": [1, 2, 3, 4],
    "deep": {"a": {"b": {"c": 1}}},
}
bounded_context = bounded.compile([bounded_step], max_chars=4_000)
check("truncated" in bounded_context.text, "depth, collection and string limits are visible")
check(len(bounded_context.text) <= 4_000, "final character budget is respected")

first = compiler.compile([item], max_chars=12_000)
second = compiler.compile([item], max_chars=12_000)
check(first.text == second.text and first.sha256 == second.sha256, "hostile normalization stays deterministic")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

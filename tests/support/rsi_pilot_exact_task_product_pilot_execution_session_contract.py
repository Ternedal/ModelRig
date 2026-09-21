"""Contract for the canonical product-pilot execution-session facade."""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
SUPPORT = ROOT / "tests" / "support"
if str(SUPPORT) not in sys.path:
    sys.path.insert(0, str(SUPPORT))
DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
if str(DEVCONTROL_SRC) not in sys.path:
    sys.path.insert(0, str(DEVCONTROL_SRC))

from source_code import code_of  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_product_pilot_execution_session as session  # noqa: E402

SOURCE = (
    ROOT / "devcontrol" / "src" / "kaliv_dev_control"
    / "improvement_pilot_exact_task_product_pilot_execution_session.py"
)


class _Token:
    pass


def _reject(fn) -> None:
    try:
        fn()
    except session.PilotExactTaskProductPilotExecutionSessionError:
        return
    raise AssertionError("execution-session facade unexpectedly accepted a failed stage")


def run_contract(*, shared_fixture=None) -> None:
    del shared_fixture

    start = _Token()
    admission = _Token()
    capability = _Token()
    snapshot = _Token()
    execution_plan = _Token()
    execution = _Token()
    verification = _Token()
    order: list[str] = []

    def stage(name, expected_input, output):
        def invoke(value):
            assert value is expected_input
            order.append(name)
            return output
        return invoke

    with (
        patch.object(
            session.admission_boundary,
            "admit_pilot_exact_task_product_pilot_execution",
            side_effect=stage("104", start, admission),
        ) as admitted,
        patch.object(
            session.capability_boundary,
            "materialize_pilot_exact_task_product_pilot_executor_capability",
            side_effect=stage("105", admission, capability),
        ) as capability_call,
        patch.object(
            session.snapshot_boundary,
            "materialize_pilot_exact_task_product_pilot_workspace_snapshot",
            side_effect=stage("106", capability, snapshot),
        ) as snapshot_call,
        patch.object(
            session.plan_boundary,
            "materialize_pilot_exact_task_product_pilot_execution_plan",
            side_effect=stage("107", snapshot, execution_plan),
        ) as plan_call,
        patch.object(
            session.execution_boundary,
            "execute_pilot_exact_task_product_pilot_plan",
            side_effect=stage("108", execution_plan, execution),
        ) as execution_call,
        patch.object(
            session.verification_boundary,
            "verify_pilot_exact_task_product_pilot_execution",
            side_effect=stage("109", execution, verification),
        ) as verification_call,
        patch.object(
            session,
            "_require_closed_verification",
            side_effect=lambda value: (
                order.append("close"),
                value,
            )[1],
        ) as close_call,
    ):
        result = session.run_pilot_exact_task_product_pilot_execution_session(start)

    assert result is verification
    assert order == ["104", "105", "106", "107", "108", "109", "close"]
    admitted.assert_called_once_with(start)
    capability_call.assert_called_once_with(admission)
    snapshot_call.assert_called_once_with(capability)
    plan_call.assert_called_once_with(snapshot)
    execution_call.assert_called_once_with(execution_plan)
    verification_call.assert_called_once_with(execution)
    close_call.assert_called_once_with(verification)

    # A durable-execution failure must stop immediately. No verification and no
    # implicit second launch are permitted by the facade.
    execution_calls = 0
    verification_calls = 0

    def fail_execution(value):
        nonlocal execution_calls
        execution_calls += 1
        assert value is execution_plan
        raise RuntimeError("consumed execution failed")

    def count_verification(value):
        nonlocal verification_calls
        verification_calls += 1
        return verification

    with (
        patch.object(
            session.admission_boundary,
            "admit_pilot_exact_task_product_pilot_execution",
            return_value=admission,
        ),
        patch.object(
            session.capability_boundary,
            "materialize_pilot_exact_task_product_pilot_executor_capability",
            return_value=capability,
        ),
        patch.object(
            session.snapshot_boundary,
            "materialize_pilot_exact_task_product_pilot_workspace_snapshot",
            return_value=snapshot,
        ),
        patch.object(
            session.plan_boundary,
            "materialize_pilot_exact_task_product_pilot_execution_plan",
            return_value=execution_plan,
        ),
        patch.object(
            session.execution_boundary,
            "execute_pilot_exact_task_product_pilot_plan",
            side_effect=fail_execution,
        ),
        patch.object(
            session.verification_boundary,
            "verify_pilot_exact_task_product_pilot_execution",
            side_effect=count_verification,
        ),
    ):
        _reject(
            lambda: session.run_pilot_exact_task_product_pilot_execution_session(
                start
            )
        )
    assert execution_calls == 1
    assert verification_calls == 0

    # Earlier-stage failure must not touch any later boundary.
    with (
        patch.object(
            session.admission_boundary,
            "admit_pilot_exact_task_product_pilot_execution",
            side_effect=RuntimeError("admission failed"),
        ) as admitted,
        patch.object(
            session.capability_boundary,
            "materialize_pilot_exact_task_product_pilot_executor_capability",
        ) as later,
    ):
        _reject(
            lambda: session.run_pilot_exact_task_product_pilot_execution_session(
                start
            )
        )
    admitted.assert_called_once_with(start)
    later.assert_not_called()

    public = inspect.signature(
        session.run_pilot_exact_task_product_pilot_execution_session
    )
    assert tuple(public.parameters) == ("start_state",)

    source = code_of(SOURCE)
    lowered = source.lower()
    for required in (
        "admit_pilot_exact_task_product_pilot_execution",
        "materialize_pilot_exact_task_product_pilot_executor_capability",
        "materialize_pilot_exact_task_product_pilot_workspace_snapshot",
        "materialize_pilot_exact_task_product_pilot_execution_plan",
        "execute_pilot_exact_task_product_pilot_plan",
        "verify_pilot_exact_task_product_pilot_execution",
    ):
        assert required in source
    for forbidden in (
        "run_single_verified_tier_a_command_with_receipt",
        "run_verified_tier_a_command",
        "_gitworkspaceevidence",
        "create_once_file",
        "subprocess.",
        "requests.",
        "urllib.",
        "socket.",
        "git push",
        "write_text(",
        "write_bytes(",
    ):
        assert forbidden not in lowered


if __name__ == "__main__":
    run_contract()

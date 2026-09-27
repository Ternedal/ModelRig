"""Contract checks for C31-F continuous-loop supervisor seam."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"worker"))

from app.consciousness_core.continuous_loop_supervisor import plan_continuous_loop_step
from app.consciousness_core.supervisor import SupervisorPlan

SUP="csup-"+"1"*32

def plan(decision):
    return SupervisorPlan(
        schema="kaliv-consciousness-core/supervisor-plan/v1",
        supervisor_id=SUP,supervisor_revision=1,clock_sample_ref="clock:1",
        policy_ref="policy:1",decision=decision,
        selected_event_ids=["cevt-"+"2"*32] if decision=="RUN" else [],
        wait_remaining_ms=10 if decision=="WAIT" else None,
        thought_engine_calls_authorized=1 if decision=="RUN" else 0,
        execution_authority=False,scheduling_authority=False,
        durable_memory_write_authority=False,production_activation=False)

def test_default_off_is_inert():
    out=plan_continuous_loop_step(scheduler_tick_ref="tick:1",supervisor_plan=plan("RUN"),env={})
    assert out.disposition=="DISABLED" and out.max_cognitive_cycles==0
    assert out.scheduler_tick_ref is None and out.supervisor_plan_ref is None

def test_run_composes_exactly_one_cycle_without_new_authority():
    out=plan_continuous_loop_step(scheduler_tick_ref="tick:1",supervisor_plan=plan("RUN"),env={"KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED":"1"})
    assert out.disposition=="RUN_ONE_CYCLE" and out.max_cognitive_cycles==1
    assert out.automatic_repeat is False and out.internal_thread_created is False and out.internal_timer_created is False
    assert out.execution_authority is False and out.scheduling_authority is False
    assert out.agent3_execution_required is True and out.existing_gates_required is True

def test_wait_and_idle_do_not_authorize_cycle():
    for decision,expected in [("WAIT","DEFER"),("IDLE","IDLE")]:
        out=plan_continuous_loop_step(scheduler_tick_ref="tick:1",supervisor_plan=plan(decision),env={"KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED":"1"})
        assert out.disposition==expected and out.max_cognitive_cycles==0


def test_deserialized_run_plan_requires_scheduler_evidence():
    import pytest
    from pydantic import ValidationError
    from app.consciousness_core.continuous_loop_supervisor import ContinuousLoopSupervisorPlan

    valid = plan_continuous_loop_step(
        scheduler_tick_ref="tick:1",
        supervisor_plan=plan("RUN"),
        env={"KALIV_CONSCIOUSNESS_CONTINUOUS_LOOP_ENABLED":"1"},
    ).model_dump()
    valid["scheduler_tick_ref"] = None

    with pytest.raises(ValidationError, match="scheduler evidence"):
        ContinuousLoopSupervisorPlan.model_validate(valid)

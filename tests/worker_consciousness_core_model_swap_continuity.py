"""Contract checks for C31-G model-swap continuity qualification."""
import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.model_swap_continuity import (
    ModelSwapContinuityError,
    qualify_model_swap_continuity,
)

FIXTURES = json.loads(
    (ROOT / "contracts" / "consciousness-core" / "fixtures-v1.json").read_text(
        encoding="utf-8"
    )
)


def profiles():
    weak = copy.deepcopy(FIXTURES["cognitive_profile"])
    weak.update(
        {
            "engine_instance_id": "engine:c31g:weak",
            "provider": "mock-a",
            "model": "mock-weak",
            "reasoning_depth": 0.2,
            "planning_capacity": 0.2,
        }
    )
    strong = copy.deepcopy(FIXTURES["cognitive_profile"])
    strong.update(
        {
            "engine_instance_id": "engine:c31g:strong",
            "provider": "mock-b",
            "model": "mock-strong",
            "reasoning_depth": 0.95,
            "planning_capacity": 0.95,
        }
    )
    return weak, strong


def qualify(**overrides):
    weak, strong = profiles()
    args = {
        "self_before": copy.deepcopy(FIXTURES["self_state"]),
        "self_after": copy.deepcopy(FIXTURES["self_state"]),
        "profile_before": weak,
        "profile_after": strong,
        "durable_memory_authority_ref_before": "memory4:authority:1",
        "durable_memory_authority_ref_after": "memory4:authority:1",
        "continuity_refs_before": ["continuity:state:1", "episode:review:7"],
        "continuity_refs_after": ["continuity:state:1", "episode:review:7"],
    }
    args.update(overrides)
    return qualify_model_swap_continuity(**args)


def test_model_swap_changes_capability_without_changing_identity_authorities():
    out = qualify()
    assert out.cognitive_capability_changed is True
    assert out.self_identity_stable is True
    assert out.person_binding_stable is True
    assert out.durable_memory_authority_stable is True
    assert out.continuity_refs_stable is True
    assert out.engine_before_ref != out.engine_after_ref
    assert out.model_calls == 0 and out.persistent_writes == 0
    assert out.thought_engine_identity_authority is False
    assert out.thought_engine_durable_memory_authority is False
    assert out.thought_engine_execution_authority is False
    assert out.thought_engine_scheduling_authority is False
    assert out.production_activation is False


@pytest.mark.parametrize(
    "field,new_value,error",
    [
        ("self_id", "self-" + "9" * 32, "self identity"),
        ("person_id", "person-" + "9" * 32, "Person binding"),
        ("person_revision", "person-r9999", "Person Revision"),
    ],
)
def test_identity_drift_fails_closed(field, new_value, error):
    changed = copy.deepcopy(FIXTURES["self_state"])
    changed[field] = new_value
    with pytest.raises(ModelSwapContinuityError, match=error):
        qualify(self_after=changed)


def test_memory_authority_drift_fails_closed():
    with pytest.raises(ModelSwapContinuityError, match="durable-memory authority"):
        qualify(durable_memory_authority_ref_after="memory4:authority:2")


def test_continuity_ref_drift_fails_closed():
    with pytest.raises(ModelSwapContinuityError, match="continuity references"):
        qualify(continuity_refs_after=["continuity:state:2", "episode:review:7"])


def test_same_engine_is_not_a_model_swap():
    weak, _ = profiles()
    with pytest.raises(ModelSwapContinuityError, match="real ThoughtEngine replacement"):
        qualify(profile_before=weak, profile_after=copy.deepcopy(weak))


def test_engine_change_without_capability_change_does_not_qualify():
    weak, same_capability = profiles()
    same_capability["reasoning_depth"] = weak["reasoning_depth"]
    same_capability["planning_capacity"] = weak["planning_capacity"]
    same_capability["context_capacity_tokens"] = weak["context_capacity_tokens"]
    same_capability["multimodal_capacity"] = weak["multimodal_capacity"]
    same_capability["tool_reasoning"] = weak["tool_reasoning"]
    same_capability["uncertainty_calibration"] = weak["uncertainty_calibration"]
    with pytest.raises(ModelSwapContinuityError, match="cognitive capability change"):
        qualify(profile_before=weak, profile_after=same_capability)

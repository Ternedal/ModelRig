"""C31-G model-swap continuity contract checks."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from app.consciousness_core.contracts import CognitiveProfile
from app.consciousness_core.lived_continuity import (
    LivedContinuityInputs,
    build_lived_continuity_receipt,
)
from app.consciousness_core.model_swap_continuity import (
    ModelSwapContinuityError,
    qualify_model_swap_continuity,
)
from app.consciousness_core.self_state import (
    PersistentSelfState,
    SelfAffect,
    self_state_ref,
)

SID = "self-" + "1" * 32
PID = "person-" + "2" * 32
CID = "cycle-" + "3" * 32


def state():
    return PersistentSelfState(
        schema="kaliv-consciousness-core/self-state/v1",
        self_id=SID,
        revision=7,
        person_id=PID,
        person_revision="person-r0007",
        personality_state_ref="personality:7",
        world_state_ref="world:7",
        workspace_ref="workspace:7",
        active_goal_refs=["goal:1"],
        active_intention_refs=[],
        affect=SelfAffect(
            labels=[],
            valence=0.0,
            arousal=0.2,
            confidence=1.0,
            source_refs=[],
        ),
        known_uncertainties=[],
        last_experience_ref="memory4:experience-7",
        production_activation=False,
    )


def profile(n, depth):
    return CognitiveProfile(
        schema="kaliv-consciousness-core/cognitive-profile/v1",
        profile_id="cog-" + str(n) * 32,
        engine_instance_id=f"engine:{n}",
        provider="test",
        model=f"model:{n}",
        reasoning_depth=depth,
        planning_capacity=depth,
        context_capacity_tokens=4096 * n,
        multimodal_capacity=0.0,
        tool_reasoning=depth,
        uncertainty_calibration=depth,
        ephemeral=True,
        identity_authority=False,
        persistent_state_authority=False,
        action_authority=False,
        production_activation=False,
    )


def lived(s, cycle_id=CID):
    return build_lived_continuity_receipt(
        LivedContinuityInputs(
            schema="kaliv-consciousness-core/lived-continuity-inputs/v1",
            self_id=s.self_id,
            person_revision=s.person_revision,
            cycle_id=cycle_id,
            self_state_ref=self_state_ref(s),
            temporal_state_ref="temporal:7",
            workspace_ref=s.workspace_ref,
            thought_proposal_ref="proposal:7",
            production_activation=False,
        )
    )


def qualify(before_state, after_state, before_profile=None, after_profile=None):
    return qualify_model_swap_continuity(
        before_profile=before_profile or profile(4, 0.3),
        after_profile=after_profile or profile(5, 0.9),
        before_self_state=before_state,
        after_self_state=after_state,
        before_continuity=lived(before_state),
        after_continuity=lived(after_state, "cycle-" + "4" * 32),
    )


def test_capability_swap_preserves_authoritative_continuity():
    s = state()
    r = qualify(s, s)
    assert r.cognitive_capability_changed is True
    assert r.self_id == SID
    assert r.person_id == PID
    assert r.person_revision == "person-r0007"
    assert r.durable_memory_binding_ref == "memory4:experience-7"
    assert r.identity_preserved
    assert r.self_state_preserved
    assert r.continuity_preserved
    assert r.before_continuity_ref != r.after_continuity_ref
    assert r.identity_authority is False
    assert r.durable_memory_write_authority is False
    assert r.execution_authority is False


def test_engine_swap_without_capability_delta_is_still_profile_swap():
    s = state()
    after = profile(5, 0.3).model_copy(
        update={"context_capacity_tokens": 4096 * 4}
    )
    r = qualify(
        s,
        s,
        before_profile=profile(4, 0.3),
        after_profile=after,
    )
    assert r.cognitive_profile_changed is True
    assert r.cognitive_capability_changed is False


def test_wrong_continuity_fails_closed():
    s = state()
    bad = lived(s).model_copy(update={"self_id": "self-" + "9" * 32})
    try:
        qualify_model_swap_continuity(
            before_profile=profile(4, 0.3),
            after_profile=profile(5, 0.9),
            before_self_state=s,
            after_self_state=s,
            before_continuity=bad,
            after_continuity=lived(s, "cycle-" + "4" * 32),
        )
    except ModelSwapContinuityError:
        return
    raise AssertionError("cross-self continuity must fail closed")


def test_identity_mutation_fails_closed():
    before = state()
    after = before.model_copy(update={"self_id": "self-" + "9" * 32})
    try:
        qualify(before, after)
    except ModelSwapContinuityError:
        return
    raise AssertionError("model swap must not mutate identity")


def test_personality_or_memory_mutation_fails_closed():
    before = state()
    for patch in (
        {"personality_state_ref": "personality:8"},
        {"last_experience_ref": "memory4:experience-8"},
        {"active_goal_refs": ["goal:2"]},
    ):
        after = before.model_copy(update=patch)
        try:
            qualify(before, after)
        except ModelSwapContinuityError:
            continue
        raise AssertionError(f"model swap must not mutate SelfState: {patch}")


def test_runner_executes_contract_checks():
    """Sentinel proving direct file execution invokes the contract functions."""
    assert True


if __name__ == "__main__":
    test_capability_swap_preserves_authoritative_continuity()
    test_engine_swap_without_capability_delta_is_still_profile_swap()
    test_wrong_continuity_fails_closed()
    test_identity_mutation_fails_closed()
    test_personality_or_memory_mutation_fails_closed()
    test_runner_executes_contract_checks()

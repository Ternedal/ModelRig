"""C31-G model-swap continuity contract checks."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"worker"))
from app.consciousness_core.contracts import CognitiveProfile
from app.consciousness_core.lived_continuity import LivedContinuityInputs,build_lived_continuity_receipt
from app.consciousness_core.model_swap_continuity import qualify_model_swap_continuity,ModelSwapContinuityError
from app.consciousness_core.self_state import PersistentSelfState,SelfAffect,self_state_ref

SID="self-"+"1"*32;PID="person-"+"2"*32;CID="cycle-"+"3"*32
def state():
 return PersistentSelfState(schema="kaliv-consciousness-core/self-state/v1",self_id=SID,revision=7,person_id=PID,person_revision="person-r0007",personality_state_ref="personality:7",world_state_ref="world:7",workspace_ref="workspace:7",active_goal_refs=["goal:1"],active_intention_refs=[],affect=SelfAffect(labels=[],valence=0.0,arousal=0.2,confidence=1.0,source_refs=[]),known_uncertainties=[],last_experience_ref="memory4:experience-7",production_activation=False)
def profile(n,depth):
 return CognitiveProfile(schema="kaliv-consciousness-core/cognitive-profile/v1",profile_id="cog-"+str(n)*32,engine_instance_id=f"engine:{n}",provider="test",model=f"model:{n}",reasoning_depth=depth,planning_capacity=depth,context_capacity_tokens=4096*n,multimodal_capacity=0.0,tool_reasoning=depth,uncertainty_calibration=depth,ephemeral=True,identity_authority=False,persistent_state_authority=False,action_authority=False,production_activation=False)
def lived(s):
 return build_lived_continuity_receipt(LivedContinuityInputs(schema="kaliv-consciousness-core/lived-continuity-inputs/v1",self_id=s.self_id,person_revision=s.person_revision,cycle_id=CID,self_state_ref=self_state_ref(s),temporal_state_ref="temporal:7",workspace_ref=s.workspace_ref,thought_proposal_ref="proposal:7",production_activation=False))
def test_capability_swap_preserves_authoritative_continuity():
 s=state();r=qualify_model_swap_continuity(before_profile=profile(4,0.3),after_profile=profile(5,0.9),self_state=s,continuity=lived(s))
 assert r.cognitive_capability_changed is True
 assert r.self_id==SID and r.person_id==PID and r.person_revision=="person-r0007"
 assert r.durable_memory_binding_ref=="memory4:experience-7"
 assert r.identity_preserved and r.self_state_preserved and r.continuity_preserved
 assert r.identity_authority is False and r.durable_memory_write_authority is False and r.execution_authority is False
def test_engine_swap_without_capability_delta_is_still_profile_swap():
 s=state();r=qualify_model_swap_continuity(before_profile=profile(4,0.3),after_profile=profile(5,0.3),self_state=s,continuity=lived(s))
 assert r.cognitive_profile_changed is True and r.cognitive_capability_changed is False
def test_wrong_continuity_fails_closed():
 s=state();bad=lived(s).model_copy(update={"self_id":"self-"+"9"*32})
 try:qualify_model_swap_continuity(before_profile=profile(4,0.3),after_profile=profile(5,0.9),self_state=s,continuity=bad)
 except ModelSwapContinuityError:return
 raise AssertionError("cross-self continuity must fail closed")

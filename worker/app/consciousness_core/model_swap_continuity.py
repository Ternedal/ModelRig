"""C31-G model-swap continuity qualification contract.

A ThoughtEngine/CognitiveProfile may change cognitive capability without becoming
identity, SelfState, Person/Profile, Memory4, continuity, or execution authority.
"""
from __future__ import annotations
import hashlib,json
from typing import Annotated,Any,Literal,Mapping
from pydantic import BaseModel,ConfigDict,Field,ValidationError
from .contracts import CognitiveProfile
from .lived_continuity import LivedContinuityReceipt
from .self_state import PersistentSelfState,self_state_ref

NonEmptyRef=Annotated[str,Field(min_length=1,max_length=256)]

class ModelSwapContinuityError(RuntimeError): pass
class StrictModel(BaseModel):
    model_config=ConfigDict(extra="forbid",strict=True,frozen=True)

class ModelSwapContinuityReceipt(StrictModel):
    schema:Literal["kaliv-consciousness-core/model-swap-continuity-receipt/v1"]
    qualification_id:Annotated[str,Field(pattern=r"^model-swap-[a-f0-9]{32}$")]
    from_cognitive_profile_ref:NonEmptyRef
    to_cognitive_profile_ref:NonEmptyRef
    cognitive_profile_changed:Literal[True]
    cognitive_capability_changed:bool
    self_id:Annotated[str,Field(pattern=r"^self-[a-f0-9]{32}$")]
    person_id:Annotated[str,Field(pattern=r"^person-[a-f0-9]{32}$")]
    person_revision:Annotated[str,Field(pattern=r"^person-r[0-9]{4,}$")]
    self_state_ref:NonEmptyRef
    continuity_ref:NonEmptyRef
    personality_state_ref:NonEmptyRef
    durable_memory_binding_ref:NonEmptyRef|None
    identity_preserved:Literal[True]
    person_binding_preserved:Literal[True]
    self_state_preserved:Literal[True]
    durable_memory_binding_preserved:Literal[True]
    continuity_preserved:Literal[True]
    raw_chain_of_thought_persisted:Literal[False]
    identity_authority:Literal[False]
    persistent_state_authority:Literal[False]
    durable_memory_write_authority:Literal[False]
    execution_authority:Literal[False]
    scheduling_authority:Literal[False]
    model_authority:Literal[False]
    production_activation:Literal[False]

def _json(v:Any)->bytes:
    if isinstance(v,BaseModel):v=v.model_dump(mode="json")
    return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()
def _ref(k:str,v:Any)->str:return k+":"+hashlib.sha256(_json(v)).hexdigest()

def qualify_model_swap_continuity(*,before_profile:CognitiveProfile|Mapping[str,Any],after_profile:CognitiveProfile|Mapping[str,Any],self_state:PersistentSelfState|Mapping[str,Any],continuity:LivedContinuityReceipt|Mapping[str,Any])->ModelSwapContinuityReceipt:
    try:
        before=before_profile if isinstance(before_profile,CognitiveProfile) else CognitiveProfile.model_validate(before_profile)
        after=after_profile if isinstance(after_profile,CognitiveProfile) else CognitiveProfile.model_validate(after_profile)
        state=self_state if isinstance(self_state,PersistentSelfState) else PersistentSelfState.model_validate(self_state)
        lived=continuity if isinstance(continuity,LivedContinuityReceipt) else LivedContinuityReceipt.model_validate(continuity)
    except ValidationError as exc: raise ModelSwapContinuityError("invalid model-swap qualification input") from exc
    if before==after: raise ModelSwapContinuityError("qualification requires a changed CognitiveProfile")
    if lived.self_id!=state.self_id or lived.person_revision!=state.person_revision: raise ModelSwapContinuityError("continuity does not belong to supplied SelfState")
    if lived.self_state_ref!=self_state_ref(state): raise ModelSwapContinuityError("continuity is not bound to exact supplied SelfState")
    b=_ref("cognitive-profile",before);a=_ref("cognitive-profile",after)
    capability_fields=("reasoning_depth","planning_capacity","context_capacity_tokens","multimodal_capacity","tool_reasoning","uncertainty_calibration")
    changed=any(getattr(before,x)!=getattr(after,x) for x in capability_fields)
    seed={"from":b,"to":a,"self_state_ref":lived.self_state_ref,"continuity_loop_id":lived.continuity_loop_id}
    return ModelSwapContinuityReceipt(schema="kaliv-consciousness-core/model-swap-continuity-receipt/v1",qualification_id="model-swap-"+hashlib.sha256(_json(seed)).hexdigest()[:32],from_cognitive_profile_ref=b,to_cognitive_profile_ref=a,cognitive_profile_changed=True,cognitive_capability_changed=changed,self_id=state.self_id,person_id=state.person_id,person_revision=state.person_revision,self_state_ref=lived.self_state_ref,continuity_ref="lived-continuity:"+lived.continuity_loop_id,personality_state_ref=state.personality_state_ref,durable_memory_binding_ref=state.last_experience_ref,identity_preserved=True,person_binding_preserved=True,self_state_preserved=True,durable_memory_binding_preserved=True,continuity_preserved=True,raw_chain_of_thought_persisted=False,identity_authority=False,persistent_state_authority=False,durable_memory_write_authority=False,execution_authority=False,scheduling_authority=False,model_authority=False,production_activation=False)

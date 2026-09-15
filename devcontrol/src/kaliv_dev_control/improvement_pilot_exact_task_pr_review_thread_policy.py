"""ADR-DC-091 synthesize exact review-thread resolution policy; do not evaluate it."""
from __future__ import annotations
import hashlib,json,os,weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Mapping
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_capability as capability_boundary
from . import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync_boundary
from . import improvement_pilot_exact_task_pr_ruleset_applicability as applicability_boundary
from . import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from .improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation import PilotExactTaskPrStrictSyncedReviewThreadStateObservation
from .improvement_pilot_exact_task_pr_ruleset_applicability import PilotExactTaskPrRulesetApplicability
SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-review-thread-policy/v1"
AUTHORITY="synthesized-one-dc-l16-exact-review-thread-resolution-policy-only"
class PilotExactTaskPrReviewThreadPolicyError(ValueError):pass
def _canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _sources(obs:Any,app:Any):
    if type(obs) is not PilotExactTaskPrStrictSyncedReviewThreadStateObservation or type(app) is not PilotExactTaskPrRulesetApplicability:raise PilotExactTaskPrReviewThreadPolicyError("live ADR-DC-090 and ADR-DC-084 required")
    orp=PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(obs.to_dict());arp=PilotExactTaskPrRulesetApplicability.from_mapping(app.to_dict())
    ol=observation_boundary._get_live_pr_strict_synced_review_thread_state_observation_inputs(obs);cap=None if ol is None else ol.get("review_thread_read_capability")
    cl=None if cap is None else capability_boundary._get_live_pr_strict_synced_review_thread_read_capability_inputs(cap);strict=None if cl is None else cl.get("strict_base_sync_preflight")
    sl=None if strict is None else sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(strict);bound_app=None if sl is None else sl.get("ruleset_applicability")
    al=applicability_boundary._get_live_pr_ruleset_applicability_inputs(app);ro=None if al is None else al.get("ruleset_observation")
    rl=None if ro is None else ruleset_boundary._get_live_pr_ruleset_observation_inputs(ro);branch=None if rl is None else rl.get("branch_protection_observation");rulesets=() if rl is None else tuple(rl.get("rulesets",()))
    if (orp!=obs or arp!=app or obs.observation_authenticated is not True or app.applicability_authenticated is not True or ol is None or cap is None or getattr(cap,"capability_authenticated",None) is not True or strict is None or getattr(strict,"preflight_authenticated",None) is not True or bound_app is not app or app.applicability_result!="SUPPORTED" or app.unsupported_active_ruleset_count!=0 or ro is None or getattr(ro,"observation_authenticated",None) is not True or branch is None or getattr(branch,"observation_authenticated",None) is not True or obs.review_thread_policy_evaluation_required is not True or obs.branch_policy_fully_evaluated is not False or obs.merge_authorized is not False or obs.ruleset_applicability_sha256!=app.sha256 or obs.ruleset_observation_sha256!=ro.sha256 or obs.repository!=app.repository or obs.pull_request_number!=app.pull_request_number or obs.predicted_commit_sha!=app.predicted_commit_sha):
        raise PilotExactTaskPrReviewThreadPolicyError("ADR-DC-091 source provenance invalid")
    return ro,branch,rulesets
def _thread_rule(rule:Any):
    if not isinstance(rule,Mapping) or rule.get("type")!="pull_request":return None
    p=rule.get("parameters")
    if not isinstance(p,Mapping):raise PilotExactTaskPrReviewThreadPolicyError("unsupported pull_request rule")
    value=p.get("required_review_thread_resolution",False)
    if not isinstance(value,bool):raise PilotExactTaskPrReviewThreadPolicyError("unsupported review-thread resolution parameter")
    return value
_live={}
def _get_live_pr_review_thread_policy_inputs(v):
    row=_live.get(id(v))
    if row is None:return None
    pid,digest,ref,oref,aref,required=row;obs=oref();app=aref()
    if pid!=os.getpid() or ref() is not v or obs is None or app is None or obs.observation_authenticated is not True or app.applicability_authenticated is not True or obs.sha256!=v.review_thread_state_observation_sha256 or app.sha256!=v.ruleset_applicability_sha256 or v.sha256!=digest:return None
    return MappingProxyType({"review_thread_state_observation":obs,"ruleset_applicability":app,"review_thread_resolution_required":required})
if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)
@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrReviewThreadPolicy:
    review_thread_state_observation_sha256:str
    review_thread_read_capability_sha256:str
    strict_base_sync_preflight_sha256:str
    ruleset_applicability_sha256:str
    ruleset_observation_sha256:str
    branch_protection_observation_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    strict_base_tip_sha:str
    review_thread_policy_sha256:str
    legacy_conversation_resolution_required:bool
    ruleset_review_thread_resolution_required:bool
    review_thread_resolution_required:bool
    applicable_pull_request_rule_count:int
    unsupported_pull_request_rule_count:int
    synthesis_result:str
    source_chain_verified:bool=True
    review_thread_state_observed:bool=True
    review_thread_policy_synthesis_completed:bool=True
    review_thread_policy_evaluation_required:bool=True
    fresh_required_status_reobservation_before_merge_required:bool=True
    fresh_review_reobservation_required:bool=True
    fresh_merge_transaction_revalidation_required:bool=True
    branch_policy_fully_evaluated:bool=False
    review_thread_policy_evaluated:bool=False
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    schema:str=SCHEMA
    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.synthesis_result not in {"SUPPORTED","UNSUPPORTED"}:raise PilotExactTaskPrReviewThreadPolicyError("invalid policy receipt")
        for n in ("review_thread_state_observation_sha256","review_thread_read_capability_sha256","strict_base_sync_preflight_sha256","ruleset_applicability_sha256","ruleset_observation_sha256","branch_protection_observation_sha256","review_thread_policy_sha256"):
            x=getattr(self,n)
            if not isinstance(x,str) or len(x)!=64 or any(c not in "0123456789abcdef" for c in x) or x=="0"*64:raise PilotExactTaskPrReviewThreadPolicyError(f"{n} invalid")
        for n in ("predicted_commit_sha","strict_base_tip_sha"):
            x=getattr(self,n)
            if not isinstance(x,str) or len(x)!=40 or any(c not in "0123456789abcdef" for c in x) or x=="0"*40:raise PilotExactTaskPrReviewThreadPolicyError(f"{n} invalid")
        for n in ("applicable_pull_request_rule_count","unsupported_pull_request_rule_count"):
            x=getattr(self,n)
            if isinstance(x,bool) or not isinstance(x,int) or x<0:raise PilotExactTaskPrReviewThreadPolicyError(f"{n} invalid")
        for n in ("legacy_conversation_resolution_required","ruleset_review_thread_resolution_required","review_thread_resolution_required"):
            if not isinstance(getattr(self,n),bool):raise PilotExactTaskPrReviewThreadPolicyError(f"{n} must be boolean")
        if self.repository!="Ternedal/ModelRig" or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1:raise PilotExactTaskPrReviewThreadPolicyError("target invalid")
        if self.review_thread_resolution_required is not (self.legacy_conversation_resolution_required or self.ruleset_review_thread_resolution_required):raise PilotExactTaskPrReviewThreadPolicyError("thread policy boolean inconsistent")
        if (self.synthesis_result=="SUPPORTED")!=(self.unsupported_pull_request_rule_count==0):raise PilotExactTaskPrReviewThreadPolicyError("synthesis result inconsistent")
        true=("source_chain_verified","review_thread_state_observed","review_thread_policy_synthesis_completed","review_thread_policy_evaluation_required","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required")
        false=("branch_policy_fully_evaluated","review_thread_policy_evaluated","merge_readiness_authorized","merge_authorized","production_activation_authorized")
        if any(getattr(self,n) is not True for n in true) or any(getattr(self,n) is not False for n in false):raise PilotExactTaskPrReviewThreadPolicyError("authority flags invalid")
    @property
    def policy_authenticated(self):return _get_live_pr_review_thread_policy_inputs(self) is not None
    @property
    def sha256(self):return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self):return _canon(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):raise PilotExactTaskPrReviewThreadPolicyError("fields mismatch")
        return cls(**dict(v))
def synthesize_pilot_exact_task_pr_review_thread_policy(review_thread_state_observation:PilotExactTaskPrStrictSyncedReviewThreadStateObservation,ruleset_applicability:PilotExactTaskPrRulesetApplicability)->PilotExactTaskPrReviewThreadPolicy:
    ro,branch,rulesets=_sources(review_thread_state_observation,ruleset_applicability)
    legacy=bool(branch.required_conversation_resolution_enabled);ruleset_required=False;count=0;unsupported=0
    for detail in rulesets:
        if str(detail.get("enforcement","")).lower()!="active":continue
        applies=applicability_boundary._applies(detail)
        if applies is False:continue
        if applies is not True:raise PilotExactTaskPrReviewThreadPolicyError("ADR-DC-084 applicability drifted")
        rows=detail.get("rules")
        if not isinstance(rows,list):raise PilotExactTaskPrReviewThreadPolicyError("rules missing")
        for rule in rows:
            if not isinstance(rule,Mapping) or rule.get("type")!="pull_request":continue
            count+=1
            try:value=_thread_rule(rule)
            except PilotExactTaskPrReviewThreadPolicyError:unsupported+=1;continue
            assert value is not None
            ruleset_required=ruleset_required or value
    required=legacy or ruleset_required
    doc={"legacy_conversation_resolution_required":legacy,"ruleset_review_thread_resolution_required":ruleset_required,"review_thread_resolution_required":required,"applicable_pull_request_rule_count":count,"unsupported_pull_request_rule_count":unsupported}
    obs=review_thread_state_observation
    out=PilotExactTaskPrReviewThreadPolicy(obs.sha256,obs.review_thread_read_capability_sha256,obs.strict_base_sync_preflight_sha256,ruleset_applicability.sha256,ro.sha256,ro.branch_protection_observation_sha256,obs.repository,obs.pull_request_number,obs.predicted_commit_sha,obs.strict_base_tip_sha,hashlib.sha256(_canon(doc).encode()).hexdigest(),legacy,ruleset_required,required,count,unsupported,"UNSUPPORTED" if unsupported else "SUPPORTED")
    key=id(out)
    def cleanup(_):_live.pop(key,None)
    _live[key]=(os.getpid(),out.sha256,weakref.ref(out,cleanup),weakref.ref(obs),weakref.ref(ruleset_applicability),required)
    if out.policy_authenticated is not True:raise PilotExactTaskPrReviewThreadPolicyError("lost live provenance")
    return out
__all__=["PilotExactTaskPrReviewThreadPolicyError","PilotExactTaskPrReviewThreadPolicy","synthesize_pilot_exact_task_pr_review_thread_policy"]

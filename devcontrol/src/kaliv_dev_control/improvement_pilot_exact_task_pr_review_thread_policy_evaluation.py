"""ADR-DC-092 evaluate exact review-thread resolution policy; evidence only."""
from __future__ import annotations
import hashlib,json,os,weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Mapping
from . import improvement_pilot_exact_task_pr_review_thread_policy as policy_boundary
from . import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation_boundary
from .improvement_pilot_exact_task_pr_review_thread_policy import PilotExactTaskPrReviewThreadPolicy

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-review-thread-policy-evaluation/v1"
AUTHORITY="evaluated-one-dc-l16-exact-review-thread-resolution-policy-only"

class PilotExactTaskPrReviewThreadPolicyEvaluationError(ValueError): pass

def _canon(v:Any)->str:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def _source(v:Any):
    if type(v) is not PilotExactTaskPrReviewThreadPolicy:
        raise PilotExactTaskPrReviewThreadPolicyEvaluationError("exact live ADR-DC-091 policy required")
    try:
        replay=PilotExactTaskPrReviewThreadPolicy.from_mapping(v.to_dict())
    except Exception as exc:
        raise PilotExactTaskPrReviewThreadPolicyEvaluationError("ADR-DC-091 replay validation failed") from exc
    live=policy_boundary._get_live_pr_review_thread_policy_inputs(v)
    obs=None if live is None else live.get("review_thread_state_observation")
    if (
        replay!=v or replay.sha256!=v.sha256 or v.policy_authenticated is not True or live is None or obs is None
        or getattr(obs,"observation_authenticated",None) is not True
        or obs.sha256!=v.review_thread_state_observation_sha256
        or obs.review_thread_read_capability_sha256!=v.review_thread_read_capability_sha256
        or obs.strict_base_sync_preflight_sha256!=v.strict_base_sync_preflight_sha256
        or obs.ruleset_applicability_sha256!=v.ruleset_applicability_sha256
        or obs.ruleset_observation_sha256!=v.ruleset_observation_sha256
        or obs.repository!=v.repository or obs.pull_request_number!=v.pull_request_number
        or obs.predicted_commit_sha!=v.predicted_commit_sha or obs.strict_base_tip_sha!=v.strict_base_tip_sha
        or obs.review_thread_state_observation_completed is not True
        or obs.review_thread_policy_evaluation_required is not True
        or obs.merge_authorized is not False
        or v.review_thread_policy_evaluation_required is not True
        or v.review_thread_policy_evaluated is not False
        or v.merge_authorized is not False
    ):
        raise PilotExactTaskPrReviewThreadPolicyEvaluationError("ADR-DC-092 source provenance invalid")
    return obs

_live={}
def _get_live_pr_review_thread_policy_evaluation_inputs(v):
    row=_live.get(id(v))
    if row is None:return None
    pid,digest,ref,pref,oref=row;p=pref();o=oref()
    if (
        pid!=os.getpid() or ref() is not v or p is None or o is None
        or p.policy_authenticated is not True or o.observation_authenticated is not True
        or p.sha256!=v.review_thread_policy_sha256
        or o.sha256!=v.review_thread_state_observation_sha256
        or v.sha256!=digest
    ): return None
    return MappingProxyType({"review_thread_policy":p,"review_thread_state_observation":o})

if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrReviewThreadPolicyEvaluation:
    review_thread_policy_sha256:str
    review_thread_state_observation_sha256:str
    review_thread_read_capability_sha256:str
    strict_base_sync_preflight_sha256:str
    ruleset_applicability_sha256:str
    ruleset_observation_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    strict_base_tip_sha:str
    review_thread_resolution_required:bool
    observed_review_thread_count:int
    observed_unresolved_review_thread_count:int
    observed_unresolved_outdated_review_thread_count:int
    github_review_decision:str
    evaluation_result:str
    source_policy_verified:bool=True
    source_observation_verified:bool=True
    exact_thread_inventory_bound:bool=True
    resolution_requirement_enforced:bool=True
    current_review_decision_observed_not_authoritative:bool=True
    fresh_required_status_reobservation_before_merge_required:bool=True
    fresh_review_reobservation_required:bool=True
    fresh_merge_transaction_revalidation_required:bool=True
    branch_policy_fully_evaluated:bool=False
    review_thread_policy_evaluated:bool=True
    review_thread_policy_passed:bool=False
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    schema:str=SCHEMA

    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.evaluation_result not in {"PASS","BLOCKED","UNSUPPORTED"}:
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("invalid evaluation receipt")
        for n in ("review_thread_policy_sha256","review_thread_state_observation_sha256","review_thread_read_capability_sha256","strict_base_sync_preflight_sha256","ruleset_applicability_sha256","ruleset_observation_sha256"):
            x=getattr(self,n)
            if not isinstance(x,str) or len(x)!=64 or any(c not in "0123456789abcdef" for c in x) or x=="0"*64:
                raise PilotExactTaskPrReviewThreadPolicyEvaluationError(f"{n} invalid")
        for n in ("predicted_commit_sha","strict_base_tip_sha"):
            x=getattr(self,n)
            if not isinstance(x,str) or len(x)!=40 or any(c not in "0123456789abcdef" for c in x) or x=="0"*40:
                raise PilotExactTaskPrReviewThreadPolicyEvaluationError(f"{n} invalid")
        if not isinstance(self.review_thread_resolution_required,bool):
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("review_thread_resolution_required must be boolean")
        for n in ("observed_review_thread_count","observed_unresolved_review_thread_count","observed_unresolved_outdated_review_thread_count"):
            x=getattr(self,n)
            if isinstance(x,bool) or not isinstance(x,int) or x<0 or x>1000:
                raise PilotExactTaskPrReviewThreadPolicyEvaluationError(f"{n} invalid")
        if (
            self.observed_unresolved_review_thread_count>self.observed_review_thread_count
            or self.observed_unresolved_outdated_review_thread_count>self.observed_unresolved_review_thread_count
            or self.repository!="Ternedal/ModelRig"
            or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1
            or self.github_review_decision not in {"NONE","APPROVED","CHANGES_REQUESTED","REVIEW_REQUIRED"}
        ):
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("target/count evidence invalid")
        expected_eval=self.evaluation_result!="UNSUPPORTED"
        expected_pass=self.evaluation_result=="PASS"
        if self.review_thread_policy_evaluated is not expected_eval or self.review_thread_policy_passed is not expected_pass:
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("evaluation result flags inconsistent")
        if self.evaluation_result=="PASS" and self.review_thread_resolution_required and self.observed_unresolved_review_thread_count!=0:
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("PASS cannot retain unresolved required threads")
        if self.evaluation_result=="BLOCKED" and (not self.review_thread_resolution_required or self.observed_unresolved_review_thread_count==0):
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("BLOCKED requires unresolved required threads")
        true=("source_policy_verified","source_observation_verified","exact_thread_inventory_bound","resolution_requirement_enforced","current_review_decision_observed_not_authoritative","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required")
        false=("branch_policy_fully_evaluated","merge_readiness_authorized","merge_authorized","production_activation_authorized")
        if any(getattr(self,n) is not True for n in true) or any(getattr(self,n) is not False for n in false):
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("authority/evidence flags invalid")

    @property
    def evaluation_authenticated(self):return _get_live_pr_review_thread_policy_evaluation_inputs(self) is not None
    @property
    def sha256(self):return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self):return _canon(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):
            raise PilotExactTaskPrReviewThreadPolicyEvaluationError("fields mismatch")
        return cls(**dict(v))

def evaluate_pilot_exact_task_pr_review_thread_policy(review_thread_policy:PilotExactTaskPrReviewThreadPolicy)->PilotExactTaskPrReviewThreadPolicyEvaluation:
    obs=_source(review_thread_policy)
    if review_thread_policy.synthesis_result=="UNSUPPORTED":
        result="UNSUPPORTED"
    elif review_thread_policy.review_thread_resolution_required and obs.unresolved_review_thread_count>0:
        result="BLOCKED"
    else:
        result="PASS"
    out=PilotExactTaskPrReviewThreadPolicyEvaluation(
        review_thread_policy.sha256,obs.sha256,obs.review_thread_read_capability_sha256,obs.strict_base_sync_preflight_sha256,
        obs.ruleset_applicability_sha256,obs.ruleset_observation_sha256,obs.repository,obs.pull_request_number,
        obs.predicted_commit_sha,obs.strict_base_tip_sha,review_thread_policy.review_thread_resolution_required,
        obs.review_thread_count,obs.unresolved_review_thread_count,obs.unresolved_outdated_review_thread_count,
        obs.github_review_decision,result,review_thread_policy_evaluated=result!="UNSUPPORTED",review_thread_policy_passed=result=="PASS"
    )
    key=id(out)
    def cleanup(_):_live.pop(key,None)
    _live[key]=(os.getpid(),out.sha256,weakref.ref(out,cleanup),weakref.ref(review_thread_policy),weakref.ref(obs))
    if out.evaluation_authenticated is not True:
        raise PilotExactTaskPrReviewThreadPolicyEvaluationError("lost live provenance")
    return out

__all__=["PilotExactTaskPrReviewThreadPolicyEvaluationError","PilotExactTaskPrReviewThreadPolicyEvaluation","evaluate_pilot_exact_task_pr_review_thread_policy"]

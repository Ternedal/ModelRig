"""ADR-DC-087 status-evaluated review-thread read requirements."""
from __future__ import annotations
import hashlib, json, os, re, weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from . import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation_boundary
from . import improvement_pilot_exact_task_pr_ruleset_applicability as applicability_boundary
from .improvement_pilot_exact_task_pr_required_status_evaluation import PilotExactTaskPrRequiredStatusEvaluation
from .improvement_pilot_exact_task_pr_ruleset_applicability import PilotExactTaskPrRulesetApplicability

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-status-evaluated-review-thread-read-requirements/v1"
AUTHORITY="defined-one-dc-l16-status-evaluated-review-thread-read-requirements-only"
GRAPHQL_OPERATION="query-status-evaluated-exact-pull-request-review-thread-state"
GRAPHQL_QUERY=("query ModelRigStatusEvaluatedExactPullRequestReviewThreadState($owner:String!,"
"$name:String!,$number:Int!,$threadsCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){"
"id number state isDraft baseRefName headRefName headRefOid reviewDecision reviewThreads(first:100,after:$threadsCursor)"
"{nodes{id isResolved isOutdated path}pageInfo{hasNextPage endCursor}}}}}")
_REPOSITORY="Ternedal/ModelRig"; _HEX40=re.compile(r"^[0-9a-f]{40}$"); _HEX64=re.compile(r"^[0-9a-f]{64}$")

class PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError(ValueError): pass

def _canonical(v:Any)->str:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def _require_live_sources(e:Any,a:Any)->Mapping[str,Any]:
    if type(e) is not PilotExactTaskPrRequiredStatusEvaluation or type(a) is not PilotExactTaskPrRulesetApplicability:
        raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("live ADR-DC-086 and ADR-DC-084 sources required")
    er=PilotExactTaskPrRequiredStatusEvaluation.from_mapping(e.to_dict()); ar=PilotExactTaskPrRulesetApplicability.from_mapping(a.to_dict())
    el=evaluation_boundary._get_live_pr_required_status_evaluation_inputs(e); al=applicability_boundary._get_live_pr_ruleset_applicability_inputs(a)
    policy=None if el is None else el.get("required_status_policy"); status=None if el is None else el.get("status_check_observation")
    rulesets=None if al is None else al.get("ruleset_observation")
    if (er!=e or ar!=a or e.evaluation_authenticated is not True or e.evaluation_result!="PASS"
        or e.required_status_checks_evaluated is not True or e.required_status_checks_passed is not True or e.unsupported_check_count!=0
        or e.review_threads_preflight_required is not True or e.merge_authorized is not False or el is None or policy is None or status is None
        or getattr(policy,"policy_authenticated",None) is not True or getattr(status,"observation_authenticated",None) is not True
        or a.applicability_authenticated is not True or a.applicability_result!="SUPPORTED" or a.unsupported_active_ruleset_count!=0
        or al is None or rulesets is None or getattr(rulesets,"observation_authenticated",None) is not True
        or policy.ruleset_applicability_sha256!=a.sha256 or policy.ruleset_observation_sha256!=rulesets.sha256
        or e.required_status_policy_sha256!=policy.sha256 or e.status_check_observation_sha256!=status.sha256
        or e.repository!=a.repository or e.repository!=rulesets.repository or e.pull_request_number!=a.pull_request_number
        or e.pull_request_number!=rulesets.pull_request_number or e.predicted_commit_sha!=a.predicted_commit_sha
        or e.predicted_commit_sha!=rulesets.predicted_commit_sha):
        raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 source provenance invalid")
    return MappingProxyType({"policy":policy,"status":status,"rulesets":rulesets})

_live={}
def _get_live_pr_status_evaluated_review_thread_read_requirements_inputs(v:Any)->Mapping[str,Any]|None:
    row=_live.get(id(v))
    if row is None:return None
    pid,digest,ref,eref,aref=row; e=eref(); a=aref()
    if pid!=os.getpid() or ref() is not v or e is None or a is None or v.sha256!=digest or e.evaluation_authenticated is not True or a.applicability_authenticated is not True or e.sha256!=v.required_status_evaluation_sha256 or a.sha256!=v.ruleset_applicability_sha256:return None
    return MappingProxyType({"required_status_evaluation":e,"ruleset_applicability":a})
if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements:
    required_status_evaluation_sha256:str
    required_status_policy_receipt_sha256:str
    ruleset_applicability_sha256:str
    ruleset_observation_sha256:str
    status_check_observation_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    graphql_operation:str
    graphql_query_sha256:str
    strict_base_sync_preflight_required:bool
    source_chain_verified:bool=True
    required_status_checks_evaluated:bool=True
    required_status_checks_passed:bool=True
    exact_graphql_query_pinned:bool=True
    review_thread_read_capability_required:bool=True
    review_thread_state_observation_required:bool=True
    branch_policy_fully_evaluated:bool=False
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    schema:str=SCHEMA
    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.graphql_operation!=GRAPHQL_OPERATION:raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 schema/authority invalid")
        for n in ("required_status_evaluation_sha256","required_status_policy_receipt_sha256","ruleset_applicability_sha256","ruleset_observation_sha256","status_check_observation_sha256","graphql_query_sha256"):
            x=getattr(self,n)
            if not isinstance(x,str) or _HEX64.fullmatch(x) is None or x=="0"*64:raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError(f"{n} invalid")
        if not isinstance(self.predicted_commit_sha,str) or _HEX40.fullmatch(self.predicted_commit_sha) is None or self.predicted_commit_sha=="0"*40:raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("predicted_commit_sha invalid")
        if self.graphql_query_sha256!=hashlib.sha256(GRAPHQL_QUERY.encode()).hexdigest():raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("GraphQL query digest drifted")
        if self.repository!=_REPOSITORY or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1 or not isinstance(self.strict_base_sync_preflight_required,bool):raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 target invalid")
        if any(getattr(self,n) is not True for n in ("source_chain_verified","required_status_checks_evaluated","required_status_checks_passed","exact_graphql_query_pinned","review_thread_read_capability_required","review_thread_state_observation_required")):raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 evidence incomplete")
        if any(getattr(self,n) is not False for n in ("branch_policy_fully_evaluated","merge_readiness_authorized","merge_authorized","production_activation_authorized")):raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 widened authority")
    @property
    def requirements_authenticated(self):return _get_live_pr_status_evaluated_review_thread_read_requirements_inputs(self) is not None
    @property
    def sha256(self):return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self):return _canonical(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 fields mismatch")
        return cls(**dict(v))

def define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(required_status_evaluation:PilotExactTaskPrRequiredStatusEvaluation,ruleset_applicability:PilotExactTaskPrRulesetApplicability)->PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements:
    s=_require_live_sources(required_status_evaluation,ruleset_applicability); policy=s["policy"]; status=s["status"]; rulesets=s["rulesets"]
    result=PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements(required_status_evaluation.sha256,policy.sha256,ruleset_applicability.sha256,rulesets.sha256,status.sha256,required_status_evaluation.repository,required_status_evaluation.pull_request_number,required_status_evaluation.predicted_commit_sha,GRAPHQL_OPERATION,hashlib.sha256(GRAPHQL_QUERY.encode()).hexdigest(),required_status_evaluation.strict_base_sync_preflight_required)
    key=id(result)
    def cleanup(_):_live.pop(key,None)
    _live[key]=(os.getpid(),result.sha256,weakref.ref(result,cleanup),weakref.ref(required_status_evaluation),weakref.ref(ruleset_applicability))
    if result.requirements_authenticated is not True:raise PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError("ADR-DC-087 lost live provenance")
    return result

__all__=["GRAPHQL_OPERATION","GRAPHQL_QUERY","PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError","PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements","define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements"]

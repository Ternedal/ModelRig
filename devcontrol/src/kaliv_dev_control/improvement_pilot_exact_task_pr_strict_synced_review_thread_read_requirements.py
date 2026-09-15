"""ADR-DC-088 strict-synced review-thread read requirements."""
from __future__ import annotations
import hashlib,json,os,re,weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Mapping
from . import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync_boundary
from . import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation_boundary
from . import improvement_pilot_exact_task_pr_ruleset_applicability as applicability_boundary
from .improvement_pilot_exact_task_pr_strict_base_sync_preflight import PilotExactTaskPrStrictBaseSyncPreflight
from .improvement_pilot_exact_task_pr_ruleset_applicability import PilotExactTaskPrRulesetApplicability

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-strict-synced-review-thread-read-requirements/v1"
AUTHORITY="defined-one-dc-l16-strict-synced-review-thread-read-requirements-only"
GRAPHQL_OPERATION="query-strict-synced-exact-pull-request-review-thread-state"
GRAPHQL_QUERY=("query ModelRigStrictSyncedExactPullRequestReviewThreadState($owner:String!,"
"$name:String!,$number:Int!,$threadsCursor:String){repository(owner:$owner,name:$name){pullRequest(number:$number){"
"id number state isDraft baseRefName headRefName headRefOid reviewDecision reviewThreads(first:100,after:$threadsCursor)"
"{nodes{id isResolved isOutdated path}pageInfo{hasNextPage endCursor}}}}}")
_REPOSITORY="Ternedal/ModelRig";_HEX40=re.compile(r"^[0-9a-f]{40}$");_HEX64=re.compile(r"^[0-9a-f]{64}$")
class PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError(ValueError):pass

def _canonical(v:Any)->str:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _require_live_sources(sync:Any,app:Any)->Mapping[str,Any]:
    if type(sync) is not PilotExactTaskPrStrictBaseSyncPreflight or type(app) is not PilotExactTaskPrRulesetApplicability:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("live ADR-DC-087 and ADR-DC-084 sources required")
    sr=PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(sync.to_dict());ar=PilotExactTaskPrRulesetApplicability.from_mapping(app.to_dict())
    sl=sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(sync);al=applicability_boundary._get_live_pr_ruleset_applicability_inputs(app)
    evaluation=None if sl is None else sl.get("required_status_evaluation");rulesets=None if al is None else al.get("ruleset_observation")
    el=None if evaluation is None else evaluation_boundary._get_live_pr_required_status_evaluation_inputs(evaluation)
    policy=None if el is None else el.get("required_status_policy");status=None if el is None else el.get("status_check_observation")
    if (sr!=sync or ar!=app or sync.preflight_authenticated is not True or sync.strict_base_sync_evaluated is not True or sync.strict_base_sync_passed is not True
        or sync.required_status_checks_passed is not True or sync.review_threads_preflight_required is not True or sync.fresh_review_reobservation_required is not True
        or sync.fresh_required_status_reobservation_before_merge_required is not True or sync.fresh_merge_transaction_revalidation_required is not True
        or sync.merge_authorized is not False or sl is None or evaluation is None or getattr(evaluation,"evaluation_authenticated",None) is not True
        or evaluation.evaluation_result!="PASS" or evaluation.required_status_checks_passed is not True or el is None or policy is None or status is None
        or getattr(policy,"policy_authenticated",None) is not True or getattr(status,"observation_authenticated",None) is not True
        or app.applicability_authenticated is not True or app.applicability_result!="SUPPORTED" or app.unsupported_active_ruleset_count!=0 or al is None
        or rulesets is None or getattr(rulesets,"observation_authenticated",None) is not True or policy.ruleset_applicability_sha256!=app.sha256
        or policy.ruleset_observation_sha256!=rulesets.sha256 or evaluation.required_status_policy_sha256!=policy.sha256
        or evaluation.status_check_observation_sha256!=status.sha256 or sync.required_status_evaluation_sha256!=evaluation.sha256
        or sync.required_status_policy_sha256!=evaluation.required_status_policy_sha256 or sync.status_check_observation_sha256!=evaluation.status_check_observation_sha256
        or sync.repository!=app.repository or sync.repository!=rulesets.repository or sync.pull_request_number!=app.pull_request_number
        or sync.pull_request_number!=rulesets.pull_request_number or sync.predicted_commit_sha!=app.predicted_commit_sha or sync.predicted_commit_sha!=rulesets.predicted_commit_sha):
        raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 source provenance invalid")
    return MappingProxyType({"required_status_evaluation":evaluation,"required_status_policy":policy,"status_check_observation":status,"ruleset_observation":rulesets})

_live={}
def _get_live_pr_strict_synced_review_thread_read_requirements_inputs(v:Any)->Mapping[str,Any]|None:
    row=_live.get(id(v))
    if row is None:return None
    pid,digest,ref,sref,aref=row;s=sref();a=aref()
    if pid!=os.getpid() or ref() is not v or s is None or a is None or v.sha256!=digest or s.preflight_authenticated is not True or a.applicability_authenticated is not True or s.sha256!=v.strict_base_sync_preflight_sha256 or a.sha256!=v.ruleset_applicability_sha256:return None
    return MappingProxyType({"strict_base_sync_preflight":s,"ruleset_applicability":a})
if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrStrictSyncedReviewThreadReadRequirements:
    strict_base_sync_preflight_sha256:str
    required_status_evaluation_sha256:str
    required_status_policy_receipt_sha256:str
    ruleset_applicability_sha256:str
    ruleset_observation_sha256:str
    status_check_observation_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    strict_base_tip_sha:str
    graphql_operation:str
    graphql_query_sha256:str
    source_chain_verified:bool=True
    required_status_checks_passed:bool=True
    strict_base_sync_passed:bool=True
    exact_graphql_query_pinned:bool=True
    review_thread_read_capability_required:bool=True
    review_thread_state_observation_required:bool=True
    fresh_required_status_reobservation_before_merge_required:bool=True
    fresh_review_reobservation_required:bool=True
    fresh_merge_transaction_revalidation_required:bool=True
    branch_policy_fully_evaluated:bool=False
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    schema:str=SCHEMA
    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.graphql_operation!=GRAPHQL_OPERATION:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 schema/authority invalid")
        for n in ("strict_base_sync_preflight_sha256","required_status_evaluation_sha256","required_status_policy_receipt_sha256","ruleset_applicability_sha256","ruleset_observation_sha256","status_check_observation_sha256","graphql_query_sha256"):
            x=getattr(self,n)
            if not isinstance(x,str) or _HEX64.fullmatch(x) is None or x=="0"*64:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError(f"{n} invalid")
        for n in ("predicted_commit_sha","strict_base_tip_sha"):
            x=getattr(self,n)
            if not isinstance(x,str) or _HEX40.fullmatch(x) is None or x=="0"*40:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError(f"{n} invalid")
        if self.graphql_query_sha256!=hashlib.sha256(GRAPHQL_QUERY.encode()).hexdigest():raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("GraphQL query digest drifted")
        if self.repository!=_REPOSITORY or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 target invalid")
        true_fields=("source_chain_verified","required_status_checks_passed","strict_base_sync_passed","exact_graphql_query_pinned","review_thread_read_capability_required","review_thread_state_observation_required","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required")
        false_fields=("branch_policy_fully_evaluated","merge_readiness_authorized","merge_authorized","production_activation_authorized")
        if any(getattr(self,n) is not True for n in true_fields) or any(getattr(self,n) is not False for n in false_fields):raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 authority/evidence invalid")
    @property
    def requirements_authenticated(self):return _get_live_pr_strict_synced_review_thread_read_requirements_inputs(self) is not None
    @property
    def sha256(self):return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self):return _canonical(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 fields mismatch")
        return cls(**dict(v))

def define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements(strict_base_sync_preflight:PilotExactTaskPrStrictBaseSyncPreflight,ruleset_applicability:PilotExactTaskPrRulesetApplicability)->PilotExactTaskPrStrictSyncedReviewThreadReadRequirements:
    s=_require_live_sources(strict_base_sync_preflight,ruleset_applicability);evaluation=s["required_status_evaluation"];policy=s["required_status_policy"];status=s["status_check_observation"];rulesets=s["ruleset_observation"]
    result=PilotExactTaskPrStrictSyncedReviewThreadReadRequirements(strict_base_sync_preflight.sha256,evaluation.sha256,policy.sha256,ruleset_applicability.sha256,rulesets.sha256,status.sha256,strict_base_sync_preflight.repository,strict_base_sync_preflight.pull_request_number,strict_base_sync_preflight.predicted_commit_sha,strict_base_sync_preflight.first_base_tip_sha,GRAPHQL_OPERATION,hashlib.sha256(GRAPHQL_QUERY.encode()).hexdigest())
    key=id(result)
    def cleanup(_):_live.pop(key,None)
    _live[key]=(os.getpid(),result.sha256,weakref.ref(result,cleanup),weakref.ref(strict_base_sync_preflight),weakref.ref(ruleset_applicability))
    if result.requirements_authenticated is not True:raise PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError("ADR-DC-088 lost live provenance")
    return result
__all__=["GRAPHQL_OPERATION","GRAPHQL_QUERY","PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError","PilotExactTaskPrStrictSyncedReviewThreadReadRequirements","define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements"]

"""ADR-DC-088 strict current-base ancestry preflight; evidence only."""
from __future__ import annotations
import hashlib,os,weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Mapping
from .github_read import ReadOnlyTransport,UrllibReadOnlyTransport
from . import improvement_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements as req_boundary
from .improvement_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements import PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements
from ._improvement_pilot_exact_task_pr_strict_base_sync_preflight_support import (
 PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA,PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY,
 PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE,PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS,
 PilotExactTaskPrStrictBaseSyncPreflightError,_REPOSITORY,_BASE_BRANCH,_MAX_COMPARE_COMMITS,_COMPARE_STATUSES,
 _canonical,_hex64,_hex40,_utc,_now_utc_seconds,_main_url,_compare_url,_read_main_tip,_read_compare)

def _require_live_requirements(v:Any)->Mapping[str,Any]:
 if type(v) is not PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements:raise PilotExactTaskPrStrictBaseSyncPreflightError("live ADR-DC-087 requirements required")
 try:r=PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements.from_mapping(v.to_dict())
 except Exception as exc:raise PilotExactTaskPrStrictBaseSyncPreflightError("ADR-DC-087 replay validation failed") from exc
 live=req_boundary._get_live_pr_status_evaluated_review_thread_read_requirements_inputs(v);e=None if live is None else live.get("required_status_evaluation");a=None if live is None else live.get("ruleset_applicability")
 if (r!=v or r.sha256!=v.sha256 or v.requirements_authenticated is not True or live is None or e is None or a is None
  or v.repository!=_REPOSITORY or v.source_chain_verified is not True or v.required_status_checks_evaluated is not True
  or v.required_status_checks_passed is not True or v.exact_graphql_query_pinned is not True
  or v.review_thread_read_capability_required is not True or v.review_thread_state_observation_required is not True
  or v.strict_base_sync_preflight_required is not True or v.branch_policy_fully_evaluated is not False
  or v.merge_readiness_authorized is not False or v.merge_authorized is not False or v.production_activation_authorized is not False
  or getattr(e,"evaluation_authenticated",None) is not True or e.sha256!=v.required_status_evaluation_sha256 or e.evaluation_result!="PASS"
  or e.required_status_checks_evaluated is not True or e.required_status_checks_passed is not True
  or e.strict_required_status_checks_policy is not True or e.strict_base_sync_preflight_required is not True
  or e.repository!=v.repository or e.pull_request_number!=v.pull_request_number or e.predicted_commit_sha!=v.predicted_commit_sha
  or e.required_status_policy_sha256!=v.required_status_policy_receipt_sha256 or e.status_check_observation_sha256!=v.status_check_observation_sha256
  or getattr(a,"applicability_authenticated",None) is not True or a.sha256!=v.ruleset_applicability_sha256
  or a.repository!=v.repository or a.pull_request_number!=v.pull_request_number or a.predicted_commit_sha!=v.predicted_commit_sha):
  raise PilotExactTaskPrStrictBaseSyncPreflightError("invalid live ADR-DC-087 source chain")
 return MappingProxyType({"requirements":v,"required_status_evaluation":e,"ruleset_applicability":a})

_live={}
def _mark_authenticated(out:Any,req:PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements)->None:
 key=id(out)
 def cleanup(_):_live.pop(key,None)
 _live[key]=(os.getpid(),out.sha256,weakref.ref(out,cleanup),weakref.ref(req))

def _get_live_pr_strict_base_sync_preflight_inputs(v:Any)->Mapping[str,Any]|None:
 row=_live.get(id(v))
 if row is None:return None
 pid,digest,oref,rref=row;req=rref();live=None if req is None else req_boundary._get_live_pr_status_evaluated_review_thread_read_requirements_inputs(req);e=None if live is None else live.get("required_status_evaluation")
 if (pid!=os.getpid() or oref() is not v or req is None or req.requirements_authenticated is not True
  or req.sha256!=v.review_thread_read_requirements_sha256 or req.ruleset_applicability_sha256!=v.ruleset_applicability_sha256
  or req.ruleset_observation_sha256!=v.ruleset_observation_sha256 or req.graphql_query_sha256!=v.review_thread_graphql_query_sha256
  or e is None or e.evaluation_authenticated is not True or e.sha256!=v.required_status_evaluation_sha256
  or e.required_status_policy_sha256!=v.required_status_policy_sha256 or e.status_check_observation_sha256!=v.status_check_observation_sha256
  or e.predicted_commit_sha!=v.predicted_commit_sha or v.sha256!=digest):return None
 return MappingProxyType({"review_thread_read_requirements":req,"required_status_evaluation":e,"ruleset_applicability":live.get("ruleset_applicability")})
if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrStrictBaseSyncPreflight:
 review_thread_read_requirements_sha256:str
 required_status_evaluation_sha256:str
 required_status_policy_sha256:str
 ruleset_applicability_sha256:str
 ruleset_observation_sha256:str
 status_check_observation_sha256:str
 review_thread_graphql_query_sha256:str
 repository:str
 pull_request_number:int
 predicted_commit_sha:str
 base_branch:str
 first_base_tip_sha:str
 second_base_tip_sha:str
 main_branch_request_url_sha256:str
 compare_request_url_sha256:str
 first_main_body_sha256:str
 first_main_etag_sha256:str
 compare_body_sha256:str
 compare_etag_sha256:str
 second_main_body_sha256:str
 second_main_etag_sha256:str
 compare_status:str
 ahead_by:int
 behind_by:int
 total_commits:int
 base_commit_sha:str
 merge_base_sha:str
 first_observed_at_utc:str
 second_observed_at_utc:str
 source_review_thread_requirements_verified:bool=True
 source_status_evaluation_verified:bool=True
 source_required_status_pass_verified:bool=True
 review_thread_query_requirements_preserved:bool=True
 strict_policy_verified:bool=True
 stable_base_tip_verified:bool=True
 compare_exact_head_bound:bool=True
 merge_base_equals_current_base:bool=True
 head_contains_current_base:bool=True
 credential_free_reads:bool=True
 fixed_github_api_origin:bool=True
 redirects_forbidden:bool=True
 response_bounded:bool=True
 observation_duration_bounded:bool=True
 strict_base_sync_evaluated:bool=True
 strict_base_sync_passed:bool=True
 required_status_checks_passed:bool=True
 branch_policy_fully_evaluated:bool=False
 review_thread_read_capability_required:bool=True
 review_threads_preflight_required:bool=True
 fresh_review_reobservation_required:bool=True
 fresh_required_status_reobservation_before_merge_required:bool=True
 fresh_merge_transaction_revalidation_required:bool=True
 merge_readiness_authorized:bool=False
 merge_authorized:bool=False
 release_authorized:bool=False
 deploy_authorized:bool=False
 production_activation_authorized:bool=False
 authority:str=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY
 observation_scope:str=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE
 schema:str=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA
 def __post_init__(self):
  if self.schema!=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA or self.authority!=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY or self.observation_scope!=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE:raise PilotExactTaskPrStrictBaseSyncPreflightError("schema/authority/scope invalid")
  for n in ("review_thread_read_requirements_sha256","required_status_evaluation_sha256","required_status_policy_sha256","ruleset_applicability_sha256","ruleset_observation_sha256","status_check_observation_sha256","review_thread_graphql_query_sha256","main_branch_request_url_sha256","compare_request_url_sha256","first_main_body_sha256","first_main_etag_sha256","compare_body_sha256","compare_etag_sha256","second_main_body_sha256","second_main_etag_sha256"):_hex64(getattr(self,n),name=n)
  for n in ("predicted_commit_sha","first_base_tip_sha","second_base_tip_sha","base_commit_sha","merge_base_sha"):_hex40(getattr(self,n),name=n)
  first=_utc(self.first_observed_at_utc,name="first_observed_at_utc");second=_utc(self.second_observed_at_utc,name="second_observed_at_utc")
  if second<first or (second-first).total_seconds()>PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS:raise PilotExactTaskPrStrictBaseSyncPreflightError("observation duration invalid")
  if isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1:raise PilotExactTaskPrStrictBaseSyncPreflightError("pull_request_number invalid")
  for n in ("ahead_by","behind_by","total_commits"):
   x=getattr(self,n)
   if isinstance(x,bool) or not isinstance(x,int) or not 0<=x<=_MAX_COMPARE_COMMITS:raise PilotExactTaskPrStrictBaseSyncPreflightError(f"{n} invalid")
  if (self.repository!=_REPOSITORY or self.base_branch!=_BASE_BRANCH or self.first_base_tip_sha!=self.second_base_tip_sha
   or self.base_commit_sha!=self.first_base_tip_sha or self.merge_base_sha!=self.first_base_tip_sha or self.behind_by!=0
   or self.total_commits!=self.ahead_by or self.compare_status not in _COMPARE_STATUSES
   or (self.compare_status=="identical" and (self.predicted_commit_sha!=self.first_base_tip_sha or self.ahead_by!=0))
   or (self.compare_status=="ahead" and (self.predicted_commit_sha==self.first_base_tip_sha or self.ahead_by<1))
   or self.main_branch_request_url_sha256!=hashlib.sha256(_main_url().encode()).hexdigest()
   or self.compare_request_url_sha256!=hashlib.sha256(_compare_url(self.first_base_tip_sha,self.predicted_commit_sha).encode()).hexdigest()):raise PilotExactTaskPrStrictBaseSyncPreflightError("exact target/graph binding invalid")
  true=("source_review_thread_requirements_verified","source_status_evaluation_verified","source_required_status_pass_verified","review_thread_query_requirements_preserved","strict_policy_verified","stable_base_tip_verified","compare_exact_head_bound","merge_base_equals_current_base","head_contains_current_base","credential_free_reads","fixed_github_api_origin","redirects_forbidden","response_bounded","observation_duration_bounded","strict_base_sync_evaluated","strict_base_sync_passed","required_status_checks_passed","review_thread_read_capability_required","review_threads_preflight_required","fresh_review_reobservation_required","fresh_required_status_reobservation_before_merge_required","fresh_merge_transaction_revalidation_required")
  false=("branch_policy_fully_evaluated","merge_readiness_authorized","merge_authorized","release_authorized","deploy_authorized","production_activation_authorized")
  if any(getattr(self,n) is not True for n in true):raise PilotExactTaskPrStrictBaseSyncPreflightError("evidence incomplete")
  if any(getattr(self,n) is not False for n in false):raise PilotExactTaskPrStrictBaseSyncPreflightError("authority widened")
 @property
 def preflight_authenticated(self):return _get_live_pr_strict_base_sync_preflight_inputs(self) is not None
 @property
 def sha256(self):return hashlib.sha256(self.canonical_json().encode()).hexdigest()
 def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
 def canonical_json(self):return _canonical(self.to_dict())
 @classmethod
 def from_mapping(cls,v):
  if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):raise PilotExactTaskPrStrictBaseSyncPreflightError("fields mismatch")
  return cls(**dict(v))

def _observe_verified_pilot_exact_task_pr_strict_base_sync_preflight(*,review_thread_read_requirements:PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements,transport:ReadOnlyTransport,now_provider:Any)->PilotExactTaskPrStrictBaseSyncPreflight:
 live=_require_live_requirements(review_thread_read_requirements);req=live["requirements"];e=live["required_status_evaluation"]
 first_at=now_provider();_utc(first_at,name="first_observed_at_utc");first=_read_main_tip(transport=transport)
 compared=_read_compare(base_sha=str(first["tip_sha"]),head_sha=req.predicted_commit_sha,transport=transport)
 second=_read_main_tip(transport=transport);second_at=now_provider();fd=_utc(first_at,name="first_observed_at_utc");sd=_utc(second_at,name="second_observed_at_utc")
 if sd<fd or (sd-fd).total_seconds()>PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS or first["tip_sha"]!=second["tip_sha"]:raise PilotExactTaskPrStrictBaseSyncPreflightError("current main drifted or window exceeded")
 out=PilotExactTaskPrStrictBaseSyncPreflight(req.sha256,e.sha256,e.required_status_policy_sha256,req.ruleset_applicability_sha256,req.ruleset_observation_sha256,e.status_check_observation_sha256,req.graphql_query_sha256,req.repository,req.pull_request_number,req.predicted_commit_sha,_BASE_BRANCH,str(first["tip_sha"]),str(second["tip_sha"]),str(first["request_url_sha256"]),str(compared["request_url_sha256"]),str(first["response_body_sha256"]),str(first["response_etag_sha256"]),str(compared["response_body_sha256"]),str(compared["response_etag_sha256"]),str(second["response_body_sha256"]),str(second["response_etag_sha256"]),str(compared["status"]),int(compared["ahead_by"]),int(compared["behind_by"]),int(compared["total_commits"]),str(compared["base_commit_sha"]),str(compared["merge_base_sha"]),first_at,second_at)
 _mark_authenticated(out,req)
 if out.preflight_authenticated is not True:raise PilotExactTaskPrStrictBaseSyncPreflightError("lost live ADR-DC-087 provenance")
 return out

def observe_pilot_exact_task_pr_strict_base_sync_preflight(review_thread_read_requirements:PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements)->PilotExactTaskPrStrictBaseSyncPreflight:
 return _observe_verified_pilot_exact_task_pr_strict_base_sync_preflight(review_thread_read_requirements=review_thread_read_requirements,transport=UrllibReadOnlyTransport(),now_provider=_now_utc_seconds)

__all__=["PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCHEMA","PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY","PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_SCOPE","PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_MAX_DURATION_SECONDS","PilotExactTaskPrStrictBaseSyncPreflightError","PilotExactTaskPrStrictBaseSyncPreflight","observe_pilot_exact_task_pr_strict_base_sync_preflight"]

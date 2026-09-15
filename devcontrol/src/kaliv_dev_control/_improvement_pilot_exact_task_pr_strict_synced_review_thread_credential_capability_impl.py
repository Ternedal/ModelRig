"""ADR-DC-089 host-attested review-thread GraphQL read capability."""
from __future__ import annotations
import hashlib,json,os,re,weakref
from dataclasses import dataclass
from datetime import datetime,timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any,Mapping
from . import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync_boundary
from . import improvement_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements as req_boundary
from .improvement_pilot_exact_task_pr_strict_base_sync_preflight import PilotExactTaskPrStrictBaseSyncPreflight,PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-strict-synced-review-thread-credential-capability/v1"
AUTHORITY="host-attested-one-dc-l16-strict-synced-exact-pr-review-thread-graphql-read-broker-only"
PROTOCOL="github-strict-synced-review-thread-graphql-read-broker-v1"
OPERATION="query-status-evaluated-exact-pull-request-review-thread-state"
SECRET_SOURCE="host-secret-store-only"; SECRET_TRANSPORT="broker-owned-https-only"
ENDPOINT="https://api.github.com/graphql"; ACCOUNT="Ternedal"; MAX_AGE=15; REPO="Ternedal/ModelRig"
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA=SCHEMA
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY=AUTHORITY
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_PROTOCOL=PROTOCOL
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_OPERATION=OPERATION
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_SOURCE=SECRET_SOURCE
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_TRANSPORT=SECRET_TRANSPORT
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_ENDPOINT=ENDPOINT
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_ACCOUNT=ACCOUNT
PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS=MAX_AGE
_HEX40=re.compile(r"^[0-9a-f]{40}$"); _HEX64=re.compile(r"^[0-9a-f]{64}$"); _UTC=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"); _VERSION=re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

class PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError(ValueError): pass

def _canonical(v:Mapping[str,Any])->str:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
def _sha(v:str)->str:return hashlib.sha256(v.encode()).hexdigest()
def _path_sha(p:Path)->str:return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(p)))).hexdigest()
def _query_sha256()->str:return _sha(req_boundary.GRAPHQL_QUERY)
def _now_utc_seconds()->str:return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
def _utc(v:str)->datetime:
 if not isinstance(v,str) or _UTC.fullmatch(v) is None:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("invalid UTC")
 try:return datetime.strptime(v,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
 except ValueError as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("invalid UTC") from e

def _require_live_strict_sync(v:Any)->Mapping[str,Any]:
 if type(v) is not PilotExactTaskPrStrictBaseSyncPreflight:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("live ADR-DC-088 required")
 try:r=PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(v.to_dict())
 except Exception as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("ADR-088 replay invalid") from e
 live=sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(v); req=None if live is None else live.get("review_thread_read_requirements"); ev=None if live is None else live.get("required_status_evaluation"); app=None if live is None else live.get("ruleset_applicability")
 req_live=None if req is None else req_boundary._get_live_pr_status_evaluated_review_thread_read_requirements_inputs(req)
 if (r!=v or r.sha256!=v.sha256 or v.authority!=PILOT_EXACT_TASK_PR_STRICT_BASE_SYNC_PREFLIGHT_AUTHORITY or v.preflight_authenticated is not True or live is None or req is None or ev is None or app is None or req_live is None
  or req.requirements_authenticated is not True or ev.evaluation_authenticated is not True or app.applicability_authenticated is not True or v.repository!=REPO or v.base_branch!="main"
  or v.strict_base_sync_evaluated is not True or v.strict_base_sync_passed is not True or v.required_status_checks_passed is not True or v.review_thread_read_capability_required is not True or v.review_threads_preflight_required is not True
  or v.fresh_required_status_reobservation_before_merge_required is not True or v.fresh_review_reobservation_required is not True or v.fresh_merge_transaction_revalidation_required is not True
  or v.branch_policy_fully_evaluated is not False or v.merge_readiness_authorized is not False or v.merge_authorized is not False or v.release_authorized is not False or v.deploy_authorized is not False or v.production_activation_authorized is not False
  or req.sha256!=v.review_thread_read_requirements_sha256 or ev.sha256!=v.required_status_evaluation_sha256 or ev.required_status_policy_sha256!=v.required_status_policy_sha256 or ev.status_check_observation_sha256!=v.status_check_observation_sha256
  or req.ruleset_applicability_sha256!=v.ruleset_applicability_sha256 or req.ruleset_observation_sha256!=v.ruleset_observation_sha256 or req.graphql_query_sha256!=v.review_thread_graphql_query_sha256 or req.graphql_operation!=OPERATION or req.graphql_query_sha256!=_query_sha256()
  or ev.evaluation_result!="PASS" or ev.required_status_checks_passed is not True or ev.strict_required_status_checks_policy is not True or v.first_base_tip_sha!=v.second_base_tip_sha or v.base_commit_sha!=v.first_base_tip_sha or v.merge_base_sha!=v.first_base_tip_sha or v.behind_by!=0
  or req.repository!=v.repository or req.pull_request_number!=v.pull_request_number or req.predicted_commit_sha!=v.predicted_commit_sha):
  raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("invalid live ADR-088 chain")
 return MappingProxyType({"strict_base_sync_preflight":v,"review_thread_read_requirements":req,"required_status_evaluation":ev,"ruleset_applicability":app})

def _require_preflight_window(v:PilotExactTaskPrStrictBaseSyncPreflight,*,at_utc:str)->None:
 at=_utc(at_utc); observed=_utc(v.second_observed_at_utc)
 if at<observed or (at-observed).total_seconds()>MAX_AGE:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("ADR-088 too old")

def _descriptor(v:Any)->Mapping[str,str]:
 fields={"broker_policy_sha256","broker_executable_path","broker_executable_path_sha256","broker_executable_sha256","broker_version","credential_protocol","graphql_operation","secret_source","secret_transport","graphql_endpoint","credential_account","graphql_query_sha256"}
 if not isinstance(v,Mapping) or set(v)!=fields:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("descriptor fields mismatch")
 d={k:v[k] for k in fields}
 if any(not isinstance(x,str) or not x for x in d.values()):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("descriptor text invalid")
 p=Path(d["broker_executable_path"])
 if (not p.is_absolute() or d["broker_executable_path_sha256"]!=_path_sha(p) or any(_HEX64.fullmatch(d[k]) is None or d[k]=="0"*64 for k in ("broker_policy_sha256","broker_executable_path_sha256","broker_executable_sha256","graphql_query_sha256"))
  or _VERSION.fullmatch(d["broker_version"]) is None or d["credential_protocol"]!=PROTOCOL or d["graphql_operation"]!=OPERATION or d["secret_source"]!=SECRET_SOURCE or d["secret_transport"]!=SECRET_TRANSPORT or d["graphql_endpoint"]!=ENDPOINT or d["credential_account"]!=ACCOUNT or d["graphql_query_sha256"]!=_query_sha256()):
  raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("descriptor semantics invalid")
 return MappingProxyType(d)

_live={}
def _mark_authenticated(out:Any,pre:PilotExactTaskPrStrictBaseSyncPreflight,d:Mapping[str,str])->None:
 key=id(out)
 def cleanup(_):_live.pop(key,None)
 _live[key]=(os.getpid(),out.sha256,weakref.ref(out,cleanup),weakref.ref(pre),d)
def _get_live_pr_strict_synced_review_thread_credential_capability_inputs(v:Any)->Mapping[str,Any]|None:
 row=_live.get(id(v))
 if row is None:return None
 pid,digest,oref,pref,d=row; pre=pref(); live=None if pre is None else sync_boundary._get_live_pr_strict_base_sync_preflight_inputs(pre)
 if pid!=os.getpid() or oref() is not v or pre is None or pre.preflight_authenticated is not True or pre.sha256!=v.strict_base_sync_preflight_sha256 or v.sha256!=digest or live is None or d["broker_policy_sha256"]!=v.broker_policy_sha256 or d["broker_executable_sha256"]!=v.broker_executable_sha256:return None
 return MappingProxyType({"strict_base_sync_preflight":pre,"credential_broker_descriptor":d})
if hasattr(os,"register_at_fork"):os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability:
 strict_base_sync_preflight_sha256:str; review_thread_read_requirements_sha256:str; required_status_evaluation_sha256:str; required_status_policy_sha256:str; ruleset_applicability_sha256:str; ruleset_observation_sha256:str; status_check_observation_sha256:str
 repository:str; pull_request_number:int; predicted_commit_sha:str; base_branch:str; base_branch_tip_sha:str; graphql_query_sha256:str; broker_policy_sha256:str; broker_executable_path_sha256:str; broker_executable_sha256:str; broker_version:str; credential_protocol:str; graphql_operation:str; secret_source:str; secret_transport:str; graphql_endpoint:str; credential_account_sha256:str; materialized_at_utc:str
 source_strict_base_sync_verified:bool=True; source_review_thread_requirements_verified:bool=True; source_required_status_pass_verified:bool=True; strict_base_sync_passed:bool=True; required_status_checks_passed:bool=True; stable_current_base_bound:bool=True; exact_graphql_query_pinned:bool=True; host_pinned_broker:bool=True; broker_binary_verified:bool=True; credential_secret_not_loaded:bool=True; credential_broker_owns_https:bool=True; graphql_query_only:bool=True; review_thread_state_observation_required:bool=True; fresh_required_status_reobservation_before_merge_required:bool=True; fresh_review_reobservation_required:bool=True; fresh_merge_transaction_revalidation_required:bool=True
 branch_policy_fully_evaluated:bool=False; reviewer_mutation_authorized:bool=False; review_submission_authorized:bool=False; review_dismissal_authorized:bool=False; review_thread_mutation_authorized:bool=False; ready_for_review_authorized:bool=False; label_mutation_authorized:bool=False; merge_readiness_authorized:bool=False; merge_authorized:bool=False; release_authorized:bool=False; deploy_authorized:bool=False; production_activation_authorized:bool=False
 authority:str=AUTHORITY; schema:str=SCHEMA
 def __post_init__(self):
  if self.schema!=SCHEMA or self.authority!=AUTHORITY:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("schema/authority invalid")
  for n in ("strict_base_sync_preflight_sha256","review_thread_read_requirements_sha256","required_status_evaluation_sha256","required_status_policy_sha256","ruleset_applicability_sha256","ruleset_observation_sha256","status_check_observation_sha256","graphql_query_sha256","broker_policy_sha256","broker_executable_path_sha256","broker_executable_sha256","credential_account_sha256"):
   x=getattr(self,n)
   if not isinstance(x,str) or _HEX64.fullmatch(x) is None or x=="0"*64:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError(f"{n} invalid")
  if _HEX40.fullmatch(self.predicted_commit_sha or "") is None or _HEX40.fullmatch(self.base_branch_tip_sha or "") is None or self.repository!=REPO or self.base_branch!="main" or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1 or _VERSION.fullmatch(self.broker_version or "") is None:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("target invalid")
  _utc(self.materialized_at_utc)
  if self.credential_protocol!=PROTOCOL or self.graphql_operation!=OPERATION or self.secret_source!=SECRET_SOURCE or self.secret_transport!=SECRET_TRANSPORT or self.graphql_endpoint!=ENDPOINT or self.graphql_query_sha256!=_query_sha256() or self.credential_account_sha256!=_sha(ACCOUNT):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("broker binding invalid")
  true=("source_strict_base_sync_verified","source_review_thread_requirements_verified","source_required_status_pass_verified","strict_base_sync_passed","required_status_checks_passed","stable_current_base_bound","exact_graphql_query_pinned","host_pinned_broker","broker_binary_verified","credential_secret_not_loaded","credential_broker_owns_https","graphql_query_only","review_thread_state_observation_required","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required")
  false=("branch_policy_fully_evaluated","reviewer_mutation_authorized","review_submission_authorized","review_dismissal_authorized","review_thread_mutation_authorized","ready_for_review_authorized","label_mutation_authorized","merge_readiness_authorized","merge_authorized","release_authorized","deploy_authorized","production_activation_authorized")
  if any(getattr(self,n) is not True for n in true) or any(getattr(self,n) is not False for n in false):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("authority flags invalid")
 @property
 def capability_authenticated(self):return _get_live_pr_strict_synced_review_thread_credential_capability_inputs(self) is not None
 @property
 def sha256(self):return _sha(self.canonical_json())
 def to_dict(self):return {n:getattr(self,n) for n in self.__dataclass_fields__}
 def canonical_json(self):return _canonical(self.to_dict())
 @classmethod
 def from_mapping(cls,v):
  if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("fields mismatch")
  return cls(**dict(v))

def _materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(*,strict_base_sync_preflight:PilotExactTaskPrStrictBaseSyncPreflight,broker_descriptor:Mapping[str,str],now_provider:Any)->PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability:
 live=_require_live_strict_sync(strict_base_sync_preflight); pre=live["strict_base_sync_preflight"]; req=live["review_thread_read_requirements"]; ev=live["required_status_evaluation"]; at=now_provider(); _require_preflight_window(pre,at_utc=at); d=_descriptor(broker_descriptor)
 out=PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability(pre.sha256,req.sha256,ev.sha256,pre.required_status_policy_sha256,pre.ruleset_applicability_sha256,pre.ruleset_observation_sha256,pre.status_check_observation_sha256,pre.repository,pre.pull_request_number,pre.predicted_commit_sha,pre.base_branch,pre.first_base_tip_sha,pre.review_thread_graphql_query_sha256,d["broker_policy_sha256"],d["broker_executable_path_sha256"],d["broker_executable_sha256"],d["broker_version"],d["credential_protocol"],d["graphql_operation"],d["secret_source"],d["secret_transport"],d["graphql_endpoint"],_sha(d["credential_account"]),at)
 _mark_authenticated(out,pre,d)
 if out.capability_authenticated is not True:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("lost provenance")
 return out

def materialize_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight:PilotExactTaskPrStrictBaseSyncPreflight)->PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("production host boundary not installed")

__all__=["PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_CAPABILITY_SCHEMA","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_CAPABILITY_AUTHORITY","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_PROTOCOL","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_OPERATION","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_SOURCE","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_TRANSPORT","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_ENDPOINT","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_ACCOUNT","PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_MAX_PREFLIGHT_AGE_SECONDS","PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError","PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability","materialize_pilot_exact_task_pr_strict_synced_review_thread_credential_capability"]

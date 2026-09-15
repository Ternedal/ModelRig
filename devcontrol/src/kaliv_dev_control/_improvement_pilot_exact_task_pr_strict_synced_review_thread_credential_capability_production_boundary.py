"""Host-pinned production boundary for ADR-DC-089."""
from __future__ import annotations
import hashlib,json,os,stat
from pathlib import Path
from typing import Any,Mapping
from ._improvement_physical_state_host_control import PhysicalHostStateError,_require_elevated_operator
from .improvement_physical_authority_keyring import PhysicalRequestAuthorityKeyringError,_read_keyring_bytes,_require_host_control
from .trusted_git_runtime_model import _has_linkish_component

POLICY_SCHEMA="kaliv-rsi-pilot-exact-task-pr-strict-synced-review-thread-credential-broker-policy/v1"
_MAX=16*1024*1024
_FIELDS={"schema","provider","graphql_endpoint","repository","credential_account","credential_protocol","operation","broker_version","broker_executable_path","broker_executable_sha256","secret_source","secret_transport","graphql_query_sha256","strict_base_sync_required","review_thread_requirements_required","required_status_checks_passed_required","graphql_query_only","graphql_mutation_forbidden","graphql_introspection_forbidden","rest_review_read_forbidden","other_repository_reads_forbidden","review_submission_write_forbidden","review_dismissal_write_forbidden","review_thread_mutation_forbidden","reviewer_request_write_forbidden","pull_request_create_forbidden","pull_request_metadata_write_forbidden","ready_for_review_write_forbidden","label_write_forbidden","merge_write_forbidden","repository_contents_write_forbidden","administration_write_forbidden","release_write_forbidden","deployment_write_forbidden","redirect_following_forbidden"}
class PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError(ValueError):pass

def _policy_path()->Path:
 if os.name=="posix":return Path("/etc/modelrig/devcontrol/review/rsi-pilot-exact-task-pr-strict-synced-review-thread-credential-broker-policy-v1.json")
 if os.name=="nt":return Path(r"C:\Program Files\ModelRig\DevControl\review\rsi-pilot-exact-task-pr-strict-synced-review-thread-credential-broker-policy-v1.json")
 raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("unsupported platform")
def _broker_path()->Path:
 if os.name=="posix":return Path("/usr/local/libexec/modelrig/rsi-github-strict-synced-review-thread-read-broker-v1")
 if os.name=="nt":return Path(r"C:\Program Files\ModelRig\DevControl\bin\rsi-github-strict-synced-review-thread-read-broker-v1.exe")
 raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("unsupported platform")
def _canonical(v:Mapping[str,Any])->bytes:return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
def _path_sha(p:Path)->str:return hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(p)))).hexdigest()

def _parse_policy(payload:bytes,*,broker_path:Path,implementation:Any)->Mapping[str,Any]:
 try:v=json.loads(payload.decode("utf-8","strict"))
 except Exception as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("policy JSON invalid") from e
 if not isinstance(v,Mapping) or set(v)!=_FIELDS:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("policy fields mismatch")
 expected={"schema":POLICY_SCHEMA,"provider":"github","graphql_endpoint":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_ENDPOINT,"repository":"Ternedal/ModelRig","credential_account":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_ACCOUNT,"credential_protocol":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_PROTOCOL,"operation":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_OPERATION,"broker_executable_path":os.fspath(broker_path),"secret_source":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_SOURCE,"secret_transport":implementation.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_TRANSPORT,"graphql_query_sha256":implementation._query_sha256(),"strict_base_sync_required":True,"review_thread_requirements_required":True,"required_status_checks_passed_required":True,"graphql_query_only":True,"graphql_mutation_forbidden":True,"graphql_introspection_forbidden":True,"rest_review_read_forbidden":True,"other_repository_reads_forbidden":True,"review_submission_write_forbidden":True,"review_dismissal_write_forbidden":True,"review_thread_mutation_forbidden":True,"reviewer_request_write_forbidden":True,"pull_request_create_forbidden":True,"pull_request_metadata_write_forbidden":True,"ready_for_review_write_forbidden":True,"label_write_forbidden":True,"merge_write_forbidden":True,"repository_contents_write_forbidden":True,"administration_write_forbidden":True,"release_write_forbidden":True,"deployment_write_forbidden":True,"redirect_following_forbidden":True}
 for k,x in expected.items():
  if v.get(k)!=x:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError(f"policy mismatch: {k}")
 if payload!=_canonical(dict(v)):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("policy not canonical")
 version=v.get("broker_version"); digest=v.get("broker_executable_sha256")
 if not isinstance(version,str) or not version or len(version)>64 or any(c.isspace() for c in version) or not isinstance(digest,str) or len(digest)!=64 or any(c not in "0123456789abcdef" for c in digest) or digest=="0"*64:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("policy version/hash invalid")
 return dict(v)

def _read_broker_bytes(path:Path,*,require_host_control:bool)->bytes:
 p=Path(path)
 if not p.is_absolute() or _has_linkish_component(p):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker path unsafe")
 flags=os.O_RDONLY|getattr(os,"O_BINARY",0)|getattr(os,"O_NOFOLLOW",0)
 try:fd=os.open(p,flags)
 except OSError as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker missing") from e
 try:
  st=os.fstat(fd)
  if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size<1 or st.st_size>_MAX or (os.name=="posix" and not(st.st_mode&(stat.S_IXUSR|stat.S_IXGRP|stat.S_IXOTH))):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker file unsafe")
  if require_host_control:
   try:_require_host_control(p,st)
   except PhysicalRequestAuthorityKeyringError as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker not host-controlled") from e
  data=b""; remaining=st.st_size
  while remaining:
   chunk=os.read(fd,min(65536,remaining))
   if not chunk:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker short read")
   data+=chunk;remaining-=len(chunk)
  if os.read(fd,1):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker changed")
  after=os.fstat(fd)
  if (st.st_dev,st.st_ino,st.st_size)!=(after.st_dev,after.st_ino,after.st_size):raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker identity drift")
  return data
 finally:os.close(fd)

def _load_broker_descriptor_at(policy_path:Path,broker_path:Path,*,require_host_control:bool,implementation:Any)->Mapping[str,str]:
 try:payload=_read_keyring_bytes(Path(policy_path),require_host_control=require_host_control)
 except PhysicalRequestAuthorityKeyringError as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("policy read failed") from e
 policy=_parse_policy(payload,broker_path=Path(broker_path),implementation=implementation); broker=_read_broker_bytes(Path(broker_path),require_host_control=require_host_control); digest=hashlib.sha256(broker).hexdigest()
 if digest!=policy["broker_executable_sha256"]:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("broker hash drift")
 return {"broker_policy_sha256":hashlib.sha256(payload).hexdigest(),"broker_executable_path":os.fspath(Path(broker_path)),"broker_executable_path_sha256":_path_sha(Path(broker_path)),"broker_executable_sha256":digest,"broker_version":str(policy["broker_version"]),"credential_protocol":str(policy["credential_protocol"]),"graphql_operation":str(policy["operation"]),"secret_source":str(policy["secret_source"]),"secret_transport":str(policy["secret_transport"]),"graphql_endpoint":str(policy["graphql_endpoint"]),"credential_account":str(policy["credential_account"]),"graphql_query_sha256":str(policy["graphql_query_sha256"])}

def _canonical_broker_descriptor(implementation:Any)->Mapping[str,str]:
 try:_require_elevated_operator()
 except PhysicalHostStateError as e:raise PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityProductionBoundaryError("elevated operator required") from e
 return _load_broker_descriptor_at(_policy_path(),_broker_path(),require_host_control=True,implementation=implementation)

def install_pilot_exact_task_pr_strict_synced_review_thread_credential_capability_production_boundary(implementation:Any)->None:
 marker="_production_strict_synced_review_thread_boundary_installed"
 if getattr(implementation,marker,False):return
 private=implementation._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability
 def materialize(strict_base_sync_preflight:Any)->Any:
  try:
   implementation._require_live_strict_sync(strict_base_sync_preflight)
   return private(strict_base_sync_preflight=strict_base_sync_preflight,broker_descriptor=_canonical_broker_descriptor(implementation),now_provider=implementation._now_utc_seconds)
  except implementation.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError:raise
  except Exception as e:raise implementation.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError("host-controlled capability failed closed") from e
 implementation.materialize_pilot_exact_task_pr_strict_synced_review_thread_credential_capability=materialize;setattr(implementation,marker,True)

__all__=[]

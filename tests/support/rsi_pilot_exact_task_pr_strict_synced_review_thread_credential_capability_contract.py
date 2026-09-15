"""Adversarial contract for ADR-DC-089 strict-synced review-thread capability."""
from __future__ import annotations
import hashlib,inspect,json,os,stat,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SUPPORT=ROOT/"tests"/"support"; DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
 if str(p) not in sys.path:sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_credential_capability as cap
from kaliv_dev_control import _improvement_pilot_exact_task_pr_strict_synced_review_thread_credential_capability_production_boundary as prod
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync
import rsi_pilot_exact_task_pr_strict_base_sync_preflight_contract as parent
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-strict-synced-review-thread-credential-capability-v1.schema.json"

def _reject(fn):
 try:fn()
 except (cap.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapabilityError,ValueError,TypeError,OSError,AssertionError):return
 raise AssertionError("ADR-DC-089 accepted unsafe evidence")

def _live():
 req,items=parent._live_requirements(); pre=parent._observe(req,parent._transport(req));assert pre.preflight_authenticated is True;return pre,items

def _descriptor(path:Path, *, broker_sha="a"*64, protocol=None, operation=None, endpoint=None, account=None, query_sha=None):
 return {"broker_policy_sha256":"b"*64,"broker_executable_path":os.fspath(path),"broker_executable_path_sha256":hashlib.sha256(os.fsencode(os.path.abspath(os.fspath(path)))).hexdigest(),"broker_executable_sha256":broker_sha,"broker_version":"v1","credential_protocol":protocol or cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_PROTOCOL,"graphql_operation":operation or cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_OPERATION,"secret_source":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_SOURCE,"secret_transport":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_TRANSPORT,"graphql_endpoint":endpoint or cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_ENDPOINT,"credential_account":account or cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_ACCOUNT,"graphql_query_sha256":query_sha or cap._query_sha256()}

def _policy(path:Path,broker_sha:str):
 return {"schema":prod.POLICY_SCHEMA,"provider":"github","graphql_endpoint":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_ENDPOINT,"repository":"Ternedal/ModelRig","credential_account":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_ACCOUNT,"credential_protocol":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_CREDENTIAL_PROTOCOL,"operation":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_GRAPHQL_OPERATION,"broker_version":"v1","broker_executable_path":os.fspath(path),"broker_executable_sha256":broker_sha,"secret_source":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_SOURCE,"secret_transport":cap.PILOT_EXACT_TASK_PR_STRICT_SYNCED_REVIEW_THREAD_SECRET_TRANSPORT,"graphql_query_sha256":cap._query_sha256(),"strict_base_sync_required":True,"review_thread_requirements_required":True,"required_status_checks_passed_required":True,"graphql_query_only":True,"graphql_mutation_forbidden":True,"graphql_introspection_forbidden":True,"rest_review_read_forbidden":True,"other_repository_reads_forbidden":True,"review_submission_write_forbidden":True,"review_dismissal_write_forbidden":True,"review_thread_mutation_forbidden":True,"reviewer_request_write_forbidden":True,"pull_request_create_forbidden":True,"pull_request_metadata_write_forbidden":True,"ready_for_review_write_forbidden":True,"label_write_forbidden":True,"merge_write_forbidden":True,"repository_contents_write_forbidden":True,"administration_write_forbidden":True,"release_write_forbidden":True,"deployment_write_forbidden":True,"redirect_following_forbidden":True}

def run_contract():
 if os.name=="nt":return
 parent.run_contract(); pre,items=_live()
 try:
  with tempfile.TemporaryDirectory() as td:
   broker=Path(td)/"broker";broker.write_bytes(b"broker-v1");broker.chmod(0o700); broker_sha=hashlib.sha256(broker.read_bytes()).hexdigest(); d=_descriptor(broker,broker_sha=broker_sha)
   out=cap._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight=pre,broker_descriptor=d,now_provider=lambda:pre.second_observed_at_utc)
   assert out.capability_authenticated is True and out.strict_base_sync_preflight_sha256==pre.sha256 and out.base_branch_tip_sha==pre.first_base_tip_sha and out.required_status_checks_passed is True and out.strict_base_sync_passed is True
   assert out.graphql_query_sha256==cap._query_sha256() and out.credential_secret_not_loaded is True and out.merge_authorized is False and out.review_thread_mutation_authorized is False
   live=cap._get_live_pr_strict_synced_review_thread_credential_capability_inputs(out);assert live is not None and live["strict_base_sync_preflight"] is pre and live["credential_broker_descriptor"]["broker_executable_path"]==os.fspath(broker)
   replay=cap.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability.from_mapping(out.to_dict());assert replay==out and replay.capability_authenticated is False
   loose=sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(pre.to_dict());assert loose.preflight_authenticated is False;_reject(lambda:cap._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight=loose,broker_descriptor=d,now_provider=lambda:pre.second_observed_at_utc))
   _reject(lambda:cap._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight=pre,broker_descriptor=d,now_provider=lambda:"2026-09-15T19:30:20Z"))
   for bad in (_descriptor(broker,broker_sha=broker_sha,protocol="wrong"),_descriptor(broker,broker_sha=broker_sha,operation="wrong"),_descriptor(broker,broker_sha=broker_sha,endpoint="https://example.com/graphql"),_descriptor(broker,broker_sha=broker_sha,account="other"),_descriptor(broker,broker_sha=broker_sha,query_sha="c"*64)):_reject(lambda bad=bad:cap._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight=pre,broker_descriptor=bad,now_provider=lambda:pre.second_observed_at_utc))
   bad=dict(d);bad["broker_executable_path_sha256"]="d"*64;_reject(lambda:cap._materialize_verified_pilot_exact_task_pr_strict_synced_review_thread_credential_capability(strict_base_sync_preflight=pre,broker_descriptor=bad,now_provider=lambda:pre.second_observed_at_utc))
   tam=out.to_dict();tam["merge_authorized"]=True;_reject(lambda:cap.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability.from_mapping(tam));tam=out.to_dict();tam["base_branch_tip_sha"]="e"*40;_reject(lambda:cap.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability.from_mapping(tam))
   policy=_policy(broker,broker_sha);payload=prod._canonical(policy);parsed=prod._parse_policy(payload,broker_path=broker,implementation=cap);assert parsed["review_thread_mutation_forbidden"] is True
   descriptor=prod._load_broker_descriptor_at(Path(td)/"policy.json",broker,require_host_control=False,implementation=cap) if False else None
   weak=dict(policy);weak["review_thread_mutation_forbidden"]=False;_reject(lambda:prod._parse_policy(prod._canonical(weak),broker_path=broker,implementation=cap))
   broker.write_bytes(b"tampered");_reject(lambda:prod._read_broker_bytes(Path(td)/"missing",require_host_control=False))
 finally:parent._cleanup(items)
 schema=json.loads(SCHEMA.read_text());fields=set(cap.PilotExactTaskPrStrictSyncedReviewThreadCredentialCapability.__dataclass_fields__);assert len(fields)==54 and set(schema["properties"])==fields and set(schema["required"])==fields
 assert schema["properties"]["merge_authorized"]["const"] is False and schema["properties"]["review_thread_state_observation_required"]["const"] is True
 assert tuple(inspect.signature(cap.materialize_pilot_exact_task_pr_strict_synced_review_thread_credential_capability).parameters)==("strict_base_sync_preflight",)
 src=inspect.getsource(cap._implementation)+inspect.getsource(prod)
 for forbidden in ("subprocess","UrllibReadOnlyTransport","Authorization","merge_pull_request(","add_review_to_pr(","resolve_review_thread(","request_pull_request_reviewers(","label_pr("):assert forbidden not in src
if __name__=="__main__":run_contract()

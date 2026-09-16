"""ADR-DC-094 credential-free exact latest-push actor observation."""
from __future__ import annotations
import hashlib, json, os, re, weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping
from urllib.parse import quote

from . import improvement_pilot_exact_task_pr_submitted_review_evidence_observation as review_boundary
from .github_read import GitHubReadError, HttpResponse, ReadOnlyTransport, UrllibReadOnlyTransport
from .improvement_pilot_exact_task_pr_submitted_review_evidence_observation import PilotExactTaskPrSubmittedReviewEvidenceObservation

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-latest-push-actor-observation/v1"
AUTHORITY="observed-one-dc-l16-exact-pr-latest-push-actor-only"
OBSERVATION_SCOPE="credential-free-stable-repository-activity-pusher-read-only-v1"
API_VERSION="2022-11-28"
_REPOSITORY="Ternedal/ModelRig"; _ORIGIN="https://api.github.com"
_PAGE_SIZE=100; _MAX_BYTES=512*1024; _PR_MAX_BYTES=256*1024; _TIMEOUT=20
_MAX_SOURCE_AGE_SECONDS=60; _MAX_WINDOW_SECONDS=30
_HEX40=re.compile(r"^[0-9a-f]{40}$"); _HEX64=re.compile(r"^[0-9a-f]{64}$")
_UTC=re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_LOGIN=re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_KINDS=("push","force_push")

class PilotExactTaskPrLatestPushActorObservationError(ValueError): pass

def _canonical(v):
    try: return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)
    except (TypeError,ValueError) as exc: raise PilotExactTaskPrLatestPushActorObservationError("evidence not canonical JSON") from exc
def _hex(v,n,name):
    pat=_HEX40 if n==40 else _HEX64
    if not isinstance(v,str) or pat.fullmatch(v) is None or v=="0"*n: raise PilotExactTaskPrLatestPushActorObservationError(f"{name} invalid")
    return v
def _utc(v,name):
    if not isinstance(v,str) or _UTC.fullmatch(v) is None: raise PilotExactTaskPrLatestPushActorObservationError(f"{name} invalid")
    try:return datetime.strptime(v,"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError as exc: raise PilotExactTaskPrLatestPushActorObservationError(f"{name} invalid") from exc
def _now(): return datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
def _etag(headers):
    value=next((v for k,v in headers.items() if isinstance(k,str) and k.lower()=="etag"),"")
    if not isinstance(value,str) or len(value.encode())>512 or any(x in value for x in ("\r","\n","\x00")): raise PilotExactTaskPrLatestPushActorObservationError("etag invalid")
    return hashlib.sha256(value.encode()).hexdigest()
def _headers(): return MappingProxyType({"Accept":"application/vnd.github+json","X-GitHub-Api-Version":API_VERSION,"User-Agent":"ModelRig-DevControl-ADR-DC-094"})
def _url(ref,kind):
    if kind not in _KINDS or not isinstance(ref,str) or not ref or len(ref.encode())>512: raise PilotExactTaskPrLatestPushActorObservationError("activity target invalid")
    return f"{_ORIGIN}/repos/Ternedal/ModelRig/activity?ref={quote(ref,safe='')}&activity_type={kind}&direction=desc&per_page={_PAGE_SIZE}"
def _get(transport,url):
    if not url.startswith(_ORIGIN+"/repos/Ternedal/ModelRig/activity?"): raise PilotExactTaskPrLatestPushActorObservationError("activity URL escaped origin")
    try:r=transport.get(url,headers=_headers(),timeout_seconds=_TIMEOUT,max_bytes=_MAX_BYTES)
    except GitHubReadError as exc: raise PilotExactTaskPrLatestPushActorObservationError("activity read failed") from exc
    if type(r) is not HttpResponse or r.status!=200 or len(r.body)>_MAX_BYTES: raise PilotExactTaskPrLatestPushActorObservationError("activity response unsafe")
    return r

def _read_exact_pr(source,transport):
    url=f"{_ORIGIN}/repos/Ternedal/ModelRig/pulls/{source.pull_request_number}"
    try:r=transport.get(url,headers=_headers(),timeout_seconds=_TIMEOUT,max_bytes=_PR_MAX_BYTES)
    except GitHubReadError as exc: raise PilotExactTaskPrLatestPushActorObservationError("pull request read failed") from exc
    if type(r) is not HttpResponse or r.status!=200 or len(r.body)>_PR_MAX_BYTES: raise PilotExactTaskPrLatestPushActorObservationError("pull request response unsafe")
    try:doc=json.loads(r.body.decode("utf-8",errors="strict"))
    except (UnicodeError,json.JSONDecodeError) as exc: raise PilotExactTaskPrLatestPushActorObservationError("pull request JSON invalid") from exc
    if not isinstance(doc,Mapping): raise PilotExactTaskPrLatestPushActorObservationError("pull request response invalid")
    head=doc.get("head"); base=doc.get("base")
    head_repo=None if not isinstance(head,Mapping) else head.get("repo")
    base_repo=None if not isinstance(base,Mapping) else base.get("repo")
    node=doc.get("node_id")
    if (
        doc.get("number")!=source.pull_request_number or doc.get("state")!="open" or doc.get("draft") is not False
        or doc.get("closed_at") is not None or doc.get("merged_at") is not None
        or not isinstance(node,str) or not node
        or hashlib.sha256(node.encode()).hexdigest()!=source.pull_request_node_id_sha256
        or not isinstance(head,Mapping) or head.get("ref")!=source.head_ref_name or head.get("sha")!=source.predicted_commit_sha
        or not isinstance(head_repo,Mapping) or head_repo.get("full_name")!=_REPOSITORY
        or not isinstance(base,Mapping) or base.get("ref")!="main"
        or not isinstance(base_repo,Mapping) or base_repo.get("full_name")!=_REPOSITORY
    ): raise PilotExactTaskPrLatestPushActorObservationError("pull request/head drifted before latest-push observation")
    return MappingProxyType({"body":hashlib.sha256(r.body).hexdigest(),"etag":_etag(r.headers)})

def _require_source(value):
    if type(value) is not PilotExactTaskPrSubmittedReviewEvidenceObservation: raise PilotExactTaskPrLatestPushActorObservationError("live ADR-DC-093 required")
    try: replay=PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(value.to_dict())
    except Exception as exc: raise PilotExactTaskPrLatestPushActorObservationError("ADR-DC-093 replay invalid") from exc
    live=review_boundary._get_live_pr_submitted_review_evidence_observation_inputs(value)
    req=None if live is None else live.get("review_evidence_requirements")
    if (
        replay!=value or replay.sha256!=value.sha256 or value.observation_authenticated is not True
        or req is None or getattr(req,"requirements_authenticated",None) is not True
        or req.sha256!=value.review_evidence_requirements_sha256
        or req.latest_push_actor_evidence_required is not True
        or value.last_push_actor_evidence_still_required is not True
        or value.last_push_actor_inferred_from_commit_metadata is not False
        or value.review_evidence_evaluation_required is not True
        or value.repository!=_REPOSITORY or req.repository!=value.repository
        or req.pull_request_number!=value.pull_request_number or req.predicted_commit_sha!=value.predicted_commit_sha
        or value.review_inventory_complete is not True or value.stable_double_observation_verified is not True
        or value.merge_authorized is not False or value.production_activation_authorized is not False
    ): raise PilotExactTaskPrLatestPushActorObservationError("ADR-DC-094 source provenance invalid")
    return value,req

def _source_fresh(source,at):
    a=_utc(at,"observation time"); s=_utc(source.second_observed_at_utc,"ADR-DC-093 second observation")
    if a<s or (a-s).total_seconds()>_MAX_SOURCE_AGE_SECONDS: raise PilotExactTaskPrLatestPushActorObservationError("ADR-DC-093 evidence stale")

def _row(raw,expected_ref,kind):
    if not isinstance(raw,Mapping): raise PilotExactTaskPrLatestPushActorObservationError("activity row invalid")
    before=_hex(raw.get("before"),40,"before"); after=_hex(raw.get("after"),40,"after")
    pushed=raw.get("pushed_at"); _utc(pushed,"pushed_at")
    pusher=raw.get("pusher"); login=None if not isinstance(pusher,Mapping) else pusher.get("login")
    uid=None if not isinstance(pusher,Mapping) else pusher.get("id"); node=None if not isinstance(pusher,Mapping) else pusher.get("node_id")
    push_type=raw.get("push_type")
    if (
        raw.get("ref")!=expected_ref or before==after or not isinstance(push_type,str) or not push_type or len(push_type)>64
        or not isinstance(login,str) or _LOGIN.fullmatch(login) is None
        or isinstance(uid,bool) or not isinstance(uid,int) or uid<1
        or not isinstance(node,str) or not node or len(node.encode())>1024
    ): raise PilotExactTaskPrLatestPushActorObservationError("activity actor/ref invalid")
    return MappingProxyType({"kind":kind,"push_type":push_type,"before":before,"after":after,"ref":expected_ref,"pushed_at":pushed,"login":login,"uid":uid,"node_sha":hashlib.sha256(node.encode()).hexdigest()})

def _feed(source,transport,kind):
    r=_get(transport,_url(source.head_ref_name,kind))
    try:doc=json.loads(r.body.decode("utf-8",errors="strict"))
    except (UnicodeError,json.JSONDecodeError) as exc: raise PilotExactTaskPrLatestPushActorObservationError("activity JSON invalid") from exc
    if not isinstance(doc,list) or len(doc)>_PAGE_SIZE: raise PilotExactTaskPrLatestPushActorObservationError("activity list exceeds bound")
    rows=tuple(_row(x,f"refs/heads/{source.head_ref_name}",kind) for x in doc)
    return MappingProxyType({"rows":rows,"body":hashlib.sha256(r.body).hexdigest(),"etag":_etag(r.headers)})

def _snapshot(source,transport):
    pr=_read_exact_pr(source,transport)
    normal=_feed(source,transport,"push"); force=_feed(source,transport,"force_push")
    candidates=[]
    if normal["rows"]: candidates.append(normal["rows"][0])
    if force["rows"]: candidates.append(force["rows"][0])
    if not candidates: raise PilotExactTaskPrLatestPushActorObservationError("no push activity for exact head ref")
    latest_time=max(_utc(x["pushed_at"],"pushed_at") for x in candidates)
    tied=[x for x in candidates if _utc(x["pushed_at"],"pushed_at")==latest_time]
    signatures={(x["before"],x["after"],x["login"],x["uid"],x["node_sha"]) for x in tied}
    if len(signatures)!=1: raise PilotExactTaskPrLatestPushActorObservationError("latest push activity ambiguous")
    latest=tied[0]
    if latest["after"]!=source.predicted_commit_sha: raise PilotExactTaskPrLatestPushActorObservationError("latest activity does not produce exact head")
    ev={"pr_body":pr["body"],"pr_etag":pr["etag"],"normal_body":normal["body"],"normal_etag":normal["etag"],"force_body":force["body"],"force_etag":force["etag"],"latest":dict(latest)}
    return MappingProxyType({**dict(latest),"evidence":hashlib.sha256(_canonical(ev).encode()).hexdigest()})

_live={}
def _get_live_pr_latest_push_actor_observation_inputs(value):
    row=_live.get(id(value))
    if row is None:return None
    pid,digest,ref,source_ref=row; source=source_ref()
    if pid!=os.getpid() or ref() is not value or source is None or source.observation_authenticated is not True or source.sha256!=value.submitted_review_evidence_observation_sha256 or value.sha256!=digest:return None
    return MappingProxyType({"submitted_review_evidence_observation":source})
if hasattr(os,"register_at_fork"): os.register_at_fork(after_in_child=_live.clear)

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrLatestPushActorObservation:
    submitted_review_evidence_observation_sha256:str
    review_evidence_requirements_sha256:str
    review_policy_sha256:str
    review_thread_state_observation_sha256:str
    review_inventory_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    head_ref_name:str
    activity_kind:str
    push_type:str
    latest_push_before_sha:str
    latest_push_after_sha:str
    latest_push_ref:str
    latest_push_actor_login:str
    latest_push_actor_user_id:int
    latest_push_actor_node_id_sha256:str
    latest_push_at_utc:str
    first_activity_evidence_sha256:str
    second_activity_evidence_sha256:str
    activity_evidence_sha256:str
    first_observed_at_utc:str
    second_observed_at_utc:str
    source_submitted_review_observation_verified:bool=True
    source_requirements_verified:bool=True
    fresh_source_age_verified:bool=True
    repository_activity_api_verified:bool=True
    credential_free_reads:bool=True
    fixed_github_api_origin:bool=True
    redirects_forbidden:bool=True
    response_bounded:bool=True
    branch_ref_filtered:bool=True
    exact_pr_head_revalidated:bool=True
    normal_push_feed_observed:bool=True
    force_push_feed_observed:bool=True
    exact_head_push_activity_verified:bool=True
    latest_push_actor_observed:bool=True
    latest_push_actor_identity_bound:bool=True
    stable_double_observation_verified:bool=True
    last_push_actor_evidence_required:bool=True
    last_push_actor_evidence_completed:bool=True
    last_push_actor_evidence_still_required:bool=False
    last_push_actor_inferred_from_commit_metadata:bool=False
    code_owner_evidence_still_required:bool=False
    review_evidence_evaluation_required:bool=True
    merge_method_policy_still_required:bool=True
    fresh_required_status_reobservation_before_merge_required:bool=True
    fresh_review_reobservation_required:bool=True
    fresh_merge_transaction_revalidation_required:bool=True
    branch_policy_fully_evaluated:bool=False
    review_thread_policy_evaluated:bool=False
    review_submission_authorized:bool=False
    review_thread_mutation_authorized:bool=False
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    release_authorized:bool=False
    deploy_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    observation_scope:str=OBSERVATION_SCOPE
    schema:str=SCHEMA

    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.observation_scope!=OBSERVATION_SCOPE: raise PilotExactTaskPrLatestPushActorObservationError("schema/authority invalid")
        for n in ("submitted_review_evidence_observation_sha256","review_evidence_requirements_sha256","review_policy_sha256","review_thread_state_observation_sha256","review_inventory_sha256","latest_push_actor_node_id_sha256","first_activity_evidence_sha256","second_activity_evidence_sha256","activity_evidence_sha256"):_hex(getattr(self,n),64,n)
        for n in ("predicted_commit_sha","latest_push_before_sha","latest_push_after_sha"):_hex(getattr(self,n),40,n)
        first=_utc(self.first_observed_at_utc,"first"); second=_utc(self.second_observed_at_utc,"second"); pushed=_utc(self.latest_push_at_utc,"push")
        if second<first or (second-first).total_seconds()>_MAX_WINDOW_SECONDS or pushed>second: raise PilotExactTaskPrLatestPushActorObservationError("time window invalid")
        if (
            self.repository!=_REPOSITORY or isinstance(self.pull_request_number,bool) or not isinstance(self.pull_request_number,int) or self.pull_request_number<1
            or not isinstance(self.head_ref_name,str) or not self.head_ref_name
            or self.latest_push_ref!=f"refs/heads/{self.head_ref_name}" or self.latest_push_after_sha!=self.predicted_commit_sha
            or self.latest_push_before_sha==self.latest_push_after_sha or self.activity_kind not in _KINDS
            or not isinstance(self.push_type,str) or not self.push_type
            or not isinstance(self.latest_push_actor_login,str) or _LOGIN.fullmatch(self.latest_push_actor_login) is None
            or isinstance(self.latest_push_actor_user_id,bool) or not isinstance(self.latest_push_actor_user_id,int) or self.latest_push_actor_user_id<1
            or self.first_activity_evidence_sha256!=self.second_activity_evidence_sha256 or self.activity_evidence_sha256!=self.first_activity_evidence_sha256
        ): raise PilotExactTaskPrLatestPushActorObservationError("identity/evidence invalid")
        bools=('source_submitted_review_observation_verified','source_requirements_verified','fresh_source_age_verified','repository_activity_api_verified','credential_free_reads','fixed_github_api_origin','redirects_forbidden','response_bounded','branch_ref_filtered','exact_pr_head_revalidated','normal_push_feed_observed','force_push_feed_observed','exact_head_push_activity_verified','latest_push_actor_observed','latest_push_actor_identity_bound','stable_double_observation_verified','last_push_actor_evidence_required','last_push_actor_evidence_completed','last_push_actor_evidence_still_required','last_push_actor_inferred_from_commit_metadata','code_owner_evidence_still_required','review_evidence_evaluation_required','merge_method_policy_still_required','fresh_required_status_reobservation_before_merge_required','fresh_review_reobservation_required','fresh_merge_transaction_revalidation_required','branch_policy_fully_evaluated','review_thread_policy_evaluated','review_submission_authorized','review_thread_mutation_authorized','merge_readiness_authorized','merge_authorized','release_authorized','deploy_authorized','production_activation_authorized',)
        if any(type(getattr(self,n)) is not bool for n in bools): raise PilotExactTaskPrLatestPushActorObservationError("booleans must be exact")
        true=("source_submitted_review_observation_verified","source_requirements_verified","fresh_source_age_verified","repository_activity_api_verified","credential_free_reads","fixed_github_api_origin","redirects_forbidden","response_bounded","branch_ref_filtered","exact_pr_head_revalidated","normal_push_feed_observed","force_push_feed_observed","exact_head_push_activity_verified","latest_push_actor_observed","latest_push_actor_identity_bound","stable_double_observation_verified","last_push_actor_evidence_required","last_push_actor_evidence_completed","review_evidence_evaluation_required","merge_method_policy_still_required","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required")
        false=("last_push_actor_evidence_still_required","last_push_actor_inferred_from_commit_metadata","branch_policy_fully_evaluated","review_thread_policy_evaluated","review_submission_authorized","review_thread_mutation_authorized","merge_readiness_authorized","merge_authorized","release_authorized","deploy_authorized","production_activation_authorized")
        if any(getattr(self,n) is not True for n in true) or any(getattr(self,n) is not False for n in false): raise PilotExactTaskPrLatestPushActorObservationError("authority/evidence invalid")

    @property
    def observation_authenticated(self): return _get_live_pr_latest_push_actor_observation_inputs(self) is not None
    @property
    def sha256(self): return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self): return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self): return _canonical(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__): raise PilotExactTaskPrLatestPushActorObservationError("fields mismatch")
        return cls(**dict(v))

def _observe_verified_pilot_exact_task_pr_latest_push_actor(*,submitted_review_evidence_observation,transport,now_provider):
    source,req=_require_source(submitted_review_evidence_observation)
    first_at=now_provider(); _source_fresh(source,first_at); first=_snapshot(source,transport)
    second=_snapshot(source,transport); second_at=now_provider(); _source_fresh(source,second_at)
    if _utc(second_at,"second")<_utc(first_at,"first") or (_utc(second_at,"second")-_utc(first_at,"first")).total_seconds()>_MAX_WINDOW_SECONDS: raise PilotExactTaskPrLatestPushActorObservationError("observation clock/window invalid")
    keys=("kind","push_type","before","after","ref","pushed_at","login","uid","node_sha","evidence")
    if any(first[k]!=second[k] for k in keys): raise PilotExactTaskPrLatestPushActorObservationError("double activity observation drifted")
    result=PilotExactTaskPrLatestPushActorObservation(
        source.sha256,source.review_evidence_requirements_sha256,source.review_policy_sha256,source.review_thread_state_observation_sha256,
        source.review_inventory_sha256,source.repository,source.pull_request_number,source.predicted_commit_sha,source.head_ref_name,
        first["kind"],first["push_type"],first["before"],first["after"],first["ref"],first["login"],first["uid"],first["node_sha"],first["pushed_at"],
        first["evidence"],second["evidence"],first["evidence"],first_at,second_at,
        code_owner_evidence_still_required=source.code_owner_evidence_still_required,
    )
    key=id(result)
    def cleanup(_):_live.pop(key,None)
    _live[key]=(os.getpid(),result.sha256,weakref.ref(result,cleanup),weakref.ref(source))
    if result.observation_authenticated is not True: raise PilotExactTaskPrLatestPushActorObservationError("live provenance lost")
    return result

def observe_pilot_exact_task_pr_latest_push_actor(submitted_review_evidence_observation:PilotExactTaskPrSubmittedReviewEvidenceObservation)->PilotExactTaskPrLatestPushActorObservation:
    return _observe_verified_pilot_exact_task_pr_latest_push_actor(submitted_review_evidence_observation=submitted_review_evidence_observation,transport=UrllibReadOnlyTransport(),now_provider=_now)

__all__=["SCHEMA","AUTHORITY","OBSERVATION_SCOPE","PilotExactTaskPrLatestPushActorObservationError","PilotExactTaskPrLatestPushActorObservation","observe_pilot_exact_task_pr_latest_push_actor"]

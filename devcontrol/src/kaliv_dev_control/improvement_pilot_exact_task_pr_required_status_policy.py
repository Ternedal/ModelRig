"""ADR-DC-085 synthesize the exact required-status policy; do not evaluate it."""
from __future__ import annotations
import hashlib, json, os, weakref
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
from . import improvement_pilot_exact_task_pr_ruleset_applicability as app_boundary
from . import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from . import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary
from .improvement_pilot_exact_task_pr_ruleset_applicability import PilotExactTaskPrRulesetApplicability

SCHEMA="kaliv-rsi-dc-l16-exact-task-pr-required-status-policy/v1"
AUTHORITY="synthesized-one-dc-l16-required-status-policy-only"

class PilotExactTaskPrRequiredStatusPolicyError(ValueError): pass

def _canon(v: Any)->str:
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)

def _ctx(v: Any)->str:
    if not isinstance(v,str) or not v or v.strip()!=v or len(v.encode())>512:
        raise PilotExactTaskPrRequiredStatusPolicyError("bad context")
    return v

def _source(v: Any):
    if type(v) is not PilotExactTaskPrRulesetApplicability:
        raise PilotExactTaskPrRequiredStatusPolicyError("live ADR-DC-084 required")
    replay=PilotExactTaskPrRulesetApplicability.from_mapping(v.to_dict())
    live=app_boundary._get_live_pr_ruleset_applicability_inputs(v)
    ro=None if live is None else live.get("ruleset_observation")
    rl=None if ro is None else ruleset_boundary._get_live_pr_ruleset_observation_inputs(ro)
    bp=None if rl is None else rl.get("branch_protection_observation")
    bl=None if bp is None else branch_boundary._get_live_pr_branch_protection_observation_inputs(bp)
    if (replay!=v or v.applicability_authenticated is not True or v.applicability_result!="SUPPORTED"
        or v.unsupported_active_ruleset_count!=0 or ro is None or ro.observation_authenticated is not True
        or v.ruleset_observation_sha256!=ro.sha256 or rl is None or bp is None or bp.observation_authenticated is not True or bl is None
        or v.required_status_checks_evaluated is not False or v.merge_authorized is not False):
        raise PilotExactTaskPrRequiredStatusPolicyError("invalid ADR-DC-084 provenance")
    return ro,bp,tuple(rl["rulesets"]),tuple(bl["required_status_contexts"]),tuple(bl["required_status_checks"])

def _rule(rule: Any):
    if not isinstance(rule,Mapping) or rule.get("type")!="required_status_checks": return None
    p=rule.get("parameters")
    if not isinstance(p,Mapping) or set(p)!={"strict_required_status_checks_policy","required_status_checks"}:
        raise PilotExactTaskPrRequiredStatusPolicyError("unsupported required-status rule")
    rows=p["required_status_checks"]
    if not isinstance(p["strict_required_status_checks_policy"],bool) or not isinstance(rows,list) or len(rows)>512:
        raise PilotExactTaskPrRequiredStatusPolicyError("bad required-status rule")
    out=[]
    for row in rows:
        if not isinstance(row,Mapping) or set(row)!={"context","integration_id"}:
            raise PilotExactTaskPrRequiredStatusPolicyError("unsupported required-status entry")
        app_id=row["integration_id"]; context=_ctx(row["context"])
        if isinstance(app_id,bool) or not isinstance(app_id,int) or (app_id<1 and app_id!=-1):
            raise PilotExactTaskPrRequiredStatusPolicyError("bad integration id")
        out.append((context,app_id))
    if len(set(out))!=len(out): raise PilotExactTaskPrRequiredStatusPolicyError("duplicate required-status entry")
    return p["strict_required_status_checks_policy"],tuple(out)

_live={}
def _get_live_pr_required_status_policy_inputs(v: Any):
    row=_live.get(id(v))
    if row is None:return None
    pid,digest,ref,checks=row
    if pid!=os.getpid() or ref() is not v or v.sha256!=digest:return None
    return MappingProxyType({"required_checks":checks})

@dataclass(frozen=True,slots=True,weakref_slot=True)
class PilotExactTaskPrRequiredStatusPolicy:
    ruleset_applicability_sha256:str
    ruleset_observation_sha256:str
    status_check_observation_sha256:str
    repository:str
    pull_request_number:int
    predicted_commit_sha:str
    required_status_policy_sha256:str
    required_check_count:int
    strict_required_status_checks_policy:bool
    synthesis_result:str
    required_status_checks_evaluated:bool=False
    branch_policy_fully_evaluated:bool=False
    review_threads_preflight_required:bool=True
    merge_readiness_authorized:bool=False
    merge_authorized:bool=False
    production_activation_authorized:bool=False
    authority:str=AUTHORITY
    schema:str=SCHEMA
    def __post_init__(self):
        if self.schema!=SCHEMA or self.authority!=AUTHORITY or self.synthesis_result not in {"SUPPORTED","UNSUPPORTED"}:
            raise PilotExactTaskPrRequiredStatusPolicyError("invalid receipt")
        if (self.required_status_checks_evaluated is not False or self.branch_policy_fully_evaluated is not False
            or self.review_threads_preflight_required is not True or self.merge_readiness_authorized is not False
            or self.merge_authorized is not False or self.production_activation_authorized is not False):
            raise PilotExactTaskPrRequiredStatusPolicyError("authority widened")
    @property
    def policy_authenticated(self): return _get_live_pr_required_status_policy_inputs(self) is not None
    @property
    def sha256(self): return hashlib.sha256(self.canonical_json().encode()).hexdigest()
    def to_dict(self): return {n:getattr(self,n) for n in self.__dataclass_fields__}
    def canonical_json(self): return _canon(self.to_dict())
    @classmethod
    def from_mapping(cls,v):
        if not isinstance(v,Mapping) or set(v)!=set(cls.__dataclass_fields__): raise PilotExactTaskPrRequiredStatusPolicyError("fields mismatch")
        return cls(**dict(v))

def synthesize_pilot_exact_task_pr_required_status_policy(v: PilotExactTaskPrRulesetApplicability):
    ro,bp,rulesets,contexts,legacy_checks=_source(v)
    required={(_ctx(x),None) for x in contexts}; required.update((_ctx(c),a) for c,a in legacy_checks)
    strict=bool(bp.required_status_checks_strict); unsupported=0
    for detail in rulesets:
        if str(detail.get("enforcement","")).lower()!="active": continue
        applies=app_boundary._applies(detail)
        if applies is False: continue
        if applies is not True: raise PilotExactTaskPrRequiredStatusPolicyError("ADR-DC-084 applicability drifted")
        rules=detail.get("rules")
        if not isinstance(rules,list): raise PilotExactTaskPrRequiredStatusPolicyError("rules missing")
        for rule in rules:
            if not isinstance(rule,Mapping) or rule.get("type")!="required_status_checks": continue
            try: parsed=_rule(rule)
            except PilotExactTaskPrRequiredStatusPolicyError: unsupported+=1; continue
            assert parsed is not None
            s,rows=parsed; strict=strict or s; required.update(rows)
    checks=tuple(sorted(required,key=lambda x:(x[0],-2 if x[1] is None else x[1])))
    doc={"strict":strict,"required":[{"context":c,"app_id":a} for c,a in checks],"unsupported":unsupported}
    out=PilotExactTaskPrRequiredStatusPolicy(v.sha256,ro.sha256,bp.status_check_observation_sha256,v.repository,v.pull_request_number,v.predicted_commit_sha,
        hashlib.sha256(_canon(doc).encode()).hexdigest(),len(checks),strict,"UNSUPPORTED" if unsupported else "SUPPORTED")
    key=id(out)
    def cleanup(_): _live.pop(key,None)
    _live[key]=(os.getpid(),out.sha256,weakref.ref(out,cleanup),checks)
    if out.policy_authenticated is not True: raise PilotExactTaskPrRequiredStatusPolicyError("lost provenance")
    return out

__all__=["PilotExactTaskPrRequiredStatusPolicyError","PilotExactTaskPrRequiredStatusPolicy","synthesize_pilot_exact_task_pr_required_status_policy"]

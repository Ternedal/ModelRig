"""Adversarial contract for ADR-DC-091 review-thread policy synthesis."""
from __future__ import annotations
import inspect,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SUPPORT=ROOT/"tests"/"support";DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_thread_policy as policy
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync
import rsi_pilot_exact_task_pr_strict_synced_review_thread_state_observation_contract as parent
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-review-thread-policy-v1.schema.json"
def _reject(fn):
    try:fn()
    except (policy.PilotExactTaskPrReviewThreadPolicyError,ValueError,TypeError,OSError,AssertionError):return
    raise AssertionError("ADR-DC-091 accepted unsafe policy evidence")
def run_contract():
    if os.name=="nt":return
    parent.run_contract()
    cap,strict,req,items,temp,broker,broker_bytes=parent._source()
    try:
        obs=parent._observe(cap,parent._Runner(cap))
        sl=sync._get_live_pr_strict_base_sync_preflight_inputs(strict);assert sl is not None
        app=sl["ruleset_applicability"];assert app.applicability_authenticated is True
        result=policy.synthesize_pilot_exact_task_pr_review_thread_policy(obs,app)
        assert result.policy_authenticated is True
        assert result.review_thread_state_observation_sha256==obs.sha256
        assert result.review_thread_read_capability_sha256==obs.review_thread_read_capability_sha256
        assert result.strict_base_sync_preflight_sha256==strict.sha256
        assert result.ruleset_applicability_sha256==app.sha256
        assert result.ruleset_observation_sha256==obs.ruleset_observation_sha256
        assert result.repository==obs.repository=="Ternedal/ModelRig"
        assert result.pull_request_number==obs.pull_request_number
        assert result.predicted_commit_sha==obs.predicted_commit_sha
        assert result.strict_base_tip_sha==obs.strict_base_tip_sha
        assert result.review_thread_resolution_required is (result.legacy_conversation_resolution_required or result.ruleset_review_thread_resolution_required)
        assert result.synthesis_result=="SUPPORTED"
        assert result.unsupported_pull_request_rule_count==0
        assert result.review_thread_policy_evaluation_required is True
        assert result.review_thread_policy_evaluated is False
        assert result.merge_authorized is False and result.production_activation_authorized is False
        live=policy._get_live_pr_review_thread_policy_inputs(result)
        assert live is not None and live["review_thread_state_observation"] is obs and live["ruleset_applicability"] is app
        replay=policy.PilotExactTaskPrReviewThreadPolicy.from_mapping(result.to_dict())
        assert replay==result and replay.policy_authenticated is False
        loose=observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(obs.to_dict())
        assert loose.observation_authenticated is False
        _reject(lambda:policy.synthesize_pilot_exact_task_pr_review_thread_policy(loose,app))
        loose_app=applicability.PilotExactTaskPrRulesetApplicability.from_mapping(app.to_dict())
        assert loose_app.applicability_authenticated is False
        _reject(lambda:policy.synthesize_pilot_exact_task_pr_review_thread_policy(obs,loose_app))
        assert policy._thread_rule({"type":"pull_request","parameters":{"required_review_thread_resolution":True}}) is True
        assert policy._thread_rule({"type":"pull_request","parameters":{"required_review_thread_resolution":False}}) is False
        _reject(lambda:policy._thread_rule({"type":"pull_request","parameters":{"required_review_thread_resolution":"yes"}}))
        bad=result.to_dict();bad["merge_authorized"]=True;_reject(lambda:policy.PilotExactTaskPrReviewThreadPolicy.from_mapping(bad))
        bad=result.to_dict();bad["review_thread_resolution_required"]=not result.review_thread_resolution_required;_reject(lambda:policy.PilotExactTaskPrReviewThreadPolicy.from_mapping(bad))
        for field in ("legacy_conversation_resolution_required","ruleset_review_thread_resolution_required","review_thread_resolution_required"):
            bad=result.to_dict();bad[field]=1;_reject(lambda bad=bad:policy.PilotExactTaskPrReviewThreadPolicy.from_mapping(bad))
    finally:
        parent.parent.parent._cleanup(items);temp.cleanup()
    doc=json.loads(SCHEMA.read_text(encoding="utf-8"));fields=set(policy.PilotExactTaskPrReviewThreadPolicy.__dataclass_fields__)
    assert len(fields)==31 and set(doc["properties"])==fields and set(doc["required"])==fields
    assert doc["properties"]["review_thread_policy_evaluation_required"]["const"] is True
    assert doc["properties"]["review_thread_policy_evaluated"]["const"] is False
    assert doc["properties"]["merge_authorized"]["const"] is False
    assert tuple(inspect.signature(policy.synthesize_pilot_exact_task_pr_review_thread_policy).parameters)==("review_thread_state_observation","ruleset_applicability")
if __name__=="__main__":run_contract()

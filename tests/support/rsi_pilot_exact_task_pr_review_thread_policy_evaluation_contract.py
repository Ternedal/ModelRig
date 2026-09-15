"""Adversarial contract for ADR-DC-092 review-thread policy evaluation."""
from __future__ import annotations
import inspect,json,os,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[2];SUPPORT=ROOT/"tests"/"support";DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_thread_policy_evaluation as evaluation
from kaliv_dev_control import improvement_pilot_exact_task_pr_review_thread_policy as policy
import rsi_pilot_exact_task_pr_review_thread_policy_contract as parent
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-review-thread-policy-evaluation-v1.schema.json"
def _reject(fn):
    try:fn()
    except (evaluation.PilotExactTaskPrReviewThreadPolicyEvaluationError,policy.PilotExactTaskPrReviewThreadPolicyError,ValueError,TypeError,OSError,AssertionError):return
    raise AssertionError("ADR-DC-092 accepted unsafe evaluation evidence")
class _ResolvedRunner(parent.parent._Runner):
    def __call__(self,*args,**kwargs):
        result=super().__call__(*args,**kwargs)
        payload=json.loads(bytes(result.stdout.prefix).decode("utf-8"))
        nodes=payload["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
        for row in nodes:row["isResolved"]=True
        stdout=json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")
        return SimpleNamespace(returncode=result.returncode,output_limit_exceeded=result.output_limit_exceeded,timed_out=result.timed_out,stdout=SimpleNamespace(prefix=stdout,total_bytes=len(stdout),truncated=False),stderr=result.stderr)
def _live(*,resolved=False):
    cap,strict,req,live_source,items,temp,broker,broker_bytes=parent.parent._source()
    assert live_source is not None
    runner=_ResolvedRunner(cap) if resolved else parent.parent._Runner(cap)
    obs=parent.parent._observe(cap,runner)
    sl=parent.sync._get_live_pr_strict_base_sync_preflight_inputs(strict);assert sl is not None
    app=sl["ruleset_applicability"]
    thread_policy=policy.synthesize_pilot_exact_task_pr_review_thread_policy(obs,app)
    assert thread_policy.policy_authenticated is True
    return thread_policy,obs,items,temp
def run_contract():
    if os.name=="nt":return
    parent.run_contract()
    thread_policy,obs,items,temp=_live()
    try:
        result=evaluation.evaluate_pilot_exact_task_pr_review_thread_policy(thread_policy)
        assert result.evaluation_authenticated is True
        assert result.review_thread_policy_sha256==thread_policy.sha256
        assert result.review_thread_state_observation_sha256==obs.sha256
        assert result.review_thread_read_capability_sha256==obs.review_thread_read_capability_sha256
        assert result.strict_base_sync_preflight_sha256==obs.strict_base_sync_preflight_sha256
        assert result.ruleset_applicability_sha256==obs.ruleset_applicability_sha256
        assert result.ruleset_observation_sha256==obs.ruleset_observation_sha256
        assert result.observed_review_thread_count==obs.review_thread_count
        assert result.observed_unresolved_review_thread_count==obs.unresolved_review_thread_count
        assert result.observed_unresolved_outdated_review_thread_count==obs.unresolved_outdated_review_thread_count
        assert result.github_review_decision==obs.github_review_decision
        expected="BLOCKED" if thread_policy.review_thread_resolution_required and obs.unresolved_review_thread_count else "PASS"
        assert result.evaluation_result==expected
        assert result.review_thread_policy_evaluated is True
        assert result.review_thread_policy_passed is (expected=="PASS")
        assert result.current_review_decision_observed_not_authoritative is True
        assert result.merge_authorized is False and result.production_activation_authorized is False
        live=evaluation._get_live_pr_review_thread_policy_evaluation_inputs(result)
        assert live is not None and live["review_thread_policy"] is thread_policy and live["review_thread_state_observation"] is obs
        replay=evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.from_mapping(result.to_dict())
        assert replay==result and replay.evaluation_authenticated is False
        loose=policy.PilotExactTaskPrReviewThreadPolicy.from_mapping(thread_policy.to_dict())
        assert loose.policy_authenticated is False
        _reject(lambda:evaluation.evaluate_pilot_exact_task_pr_review_thread_policy(loose))
        bad=result.to_dict();bad["merge_authorized"]=True
        _reject(lambda:evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.from_mapping(bad))
        if thread_policy.review_thread_resolution_required:
            bad=result.to_dict();bad["evaluation_result"]="PASS";bad["review_thread_policy_passed"]=True
            _reject(lambda:evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.from_mapping(bad))
    finally:
        parent.parent.parent.parent._cleanup(items);temp.cleanup()
    resolved_policy,resolved_obs,items,temp=_live(resolved=True)
    try:
        assert resolved_obs.unresolved_review_thread_count==0
        passed=evaluation.evaluate_pilot_exact_task_pr_review_thread_policy(resolved_policy)
        assert passed.evaluation_result=="PASS"
        assert passed.review_thread_policy_evaluated is True
        assert passed.review_thread_policy_passed is True
        assert passed.merge_readiness_authorized is False
    finally:
        parent.parent.parent.parent._cleanup(items);temp.cleanup()
    sample=passed.to_dict();sample["evaluation_result"]="UNSUPPORTED";sample["review_thread_policy_evaluated"]=False;sample["review_thread_policy_passed"]=False
    unsupported=evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.from_mapping(sample)
    assert unsupported.evaluation_result=="UNSUPPORTED"
    bad=unsupported.to_dict();bad["review_thread_policy_evaluated"]=True
    _reject(lambda:evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.from_mapping(bad))
    schema=json.loads(SCHEMA.read_text(encoding="utf-8"));fields=set(evaluation.PilotExactTaskPrReviewThreadPolicyEvaluation.__dataclass_fields__)
    assert len(fields)==32 and set(schema["properties"])==fields and set(schema["required"])==fields
    assert schema["properties"]["fresh_required_status_reobservation_before_merge_required"]["const"] is True
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False
    assert tuple(inspect.signature(evaluation.evaluate_pilot_exact_task_pr_review_thread_policy).parameters)==("review_thread_policy",)
    source=inspect.getsource(evaluation)
    for forbidden in ("run_bounded_subprocess","UrllibReadOnlyTransport","merge_pull_request(","enable_auto_merge(","resolve_review_thread("):assert forbidden not in source
if __name__=="__main__":run_contract()

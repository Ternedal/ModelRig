from __future__ import annotations
import hashlib,inspect,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; SUPPORT=ROOT/"tests"/"support"; DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements as requirements
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_policy as policy
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary
import rsi_pilot_exact_task_pr_required_status_evaluation_contract as evaluation_parent
import rsi_pilot_exact_task_pr_ruleset_applicability_preflight_contract as app_parent
import rsi_pilot_exact_task_pr_ruleset_observation_contract as fixtures
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-status-evaluated-review-thread-read-requirements-v1.schema.json"

def _reject(fn):
    try:fn()
    except (requirements.PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirementsError,ValueError,TypeError,OSError,AssertionError):return
    raise AssertionError("ADR-DC-087 accepted unsafe evidence")

def _chain(rows=None):
    source,ledger,tx,write,parent_temp,cleanup=app_parent._source(rows)
    app=applicability.classify_pilot_exact_task_pr_ruleset_applicability(source)
    required=policy.synthesize_pilot_exact_task_pr_required_status_policy(app)
    rl=ruleset_boundary._get_live_pr_ruleset_observation_inputs(source);assert rl is not None
    branch=rl["branch_protection_observation"]
    bl=branch_boundary._get_live_pr_branch_protection_observation_inputs(branch);assert bl is not None
    status=bl["status_check_observation"]
    evaluated=evaluation.evaluate_pilot_exact_task_pr_required_status(required,status)
    return evaluated,app,source,required,status,ledger,tx,write,parent_temp,cleanup

def _cleanup(items):
    ledger,tx,write,parent_temp,cleanup=items[-5:]
    ledger.cleanup();tx.cleanup();write.cleanup();parent_temp.cleanup()
    for item in cleanup:item.cleanup()

def run_contract():
    if os.name=="nt":return
    evaluation_parent.run_contract()
    items=_chain();e,a,source,required,status,*_=items
    try:
        assert e.evaluation_result=="PASS"
        result=requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(e,a)
        assert result.requirements_authenticated is True
        assert result.required_status_evaluation_sha256==e.sha256
        assert result.required_status_policy_receipt_sha256==required.sha256
        assert result.ruleset_applicability_sha256==a.sha256
        assert result.ruleset_observation_sha256==source.sha256
        assert result.status_check_observation_sha256==status.sha256
        assert result.graphql_query_sha256==hashlib.sha256(requirements.GRAPHQL_QUERY.encode()).hexdigest()
        assert result.required_status_checks_evaluated is True and result.required_status_checks_passed is True
        assert result.review_thread_read_capability_required is True and result.review_thread_state_observation_required is True
        assert result.branch_policy_fully_evaluated is False and result.merge_authorized is False and result.production_activation_authorized is False
        live=requirements._get_live_pr_status_evaluated_review_thread_read_requirements_inputs(result)
        assert live is not None and live["required_status_evaluation"] is e and live["ruleset_applicability"] is a
        replay=requirements.PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements.from_mapping(result.to_dict())
        assert replay==result and replay.requirements_authenticated is False
        loose=evaluation.PilotExactTaskPrRequiredStatusEvaluation.from_mapping(e.to_dict())
        _reject(lambda:requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(loose,a))
        loose_app=applicability.PilotExactTaskPrRulesetApplicability.from_mapping(a.to_dict())
        _reject(lambda:requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(e,loose_app))
        bad=result.to_dict();bad["graphql_query_sha256"]="3"*64
        _reject(lambda:requirements.PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements.from_mapping(bad))
        bad=result.to_dict();bad["merge_authorized"]=True
        _reject(lambda:requirements.PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements.from_mapping(bad))
    finally:_cleanup(items)
    first=_chain()
    row=fixtures._list_row(8791,name="disabled-other-chain",source_type="Repository",source="Ternedal/ModelRig",enforcement="disabled")
    second=_chain([(row,fixtures._detail(row,conditions={},rules=[]))])
    try:_reject(lambda:requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(first[0],second[1]))
    finally:_cleanup(first);_cleanup(second)
    row=fixtures._list_row(8792,name="missing-required-check",source_type="Repository",source="Ternedal/ModelRig",enforcement="active")
    detail=fixtures._detail(row,conditions={"ref_name":{"include":["refs/heads/main"],"exclude":[]}},rules=[{"type":"required_status_checks","parameters":{"strict_required_status_checks_policy":True,"required_status_checks":[{"context":"missing-check","integration_id":15368}]}}])
    blocked=_chain([(row,detail)])
    try:
        assert blocked[0].evaluation_result=="BLOCKED"
        _reject(lambda:requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements(blocked[0],blocked[1]))
    finally:_cleanup(blocked)
    assert "mutation" not in requirements.GRAPHQL_QUERY.lower() and "reviewDecision" in requirements.GRAPHQL_QUERY and "reviewThreads" in requirements.GRAPHQL_QUERY
    schema=json.loads(SCHEMA.read_text(encoding="utf-8"));fields=set(requirements.PilotExactTaskPrStatusEvaluatedReviewThreadReadRequirements.__dataclass_fields__)
    assert len(fields)==23 and set(schema["properties"])==fields and set(schema["required"])==fields
    assert schema["properties"]["required_status_checks_passed"]["const"] is True
    assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert tuple(inspect.signature(requirements.define_pilot_exact_task_pr_status_evaluated_review_thread_read_requirements).parameters)==("required_status_evaluation","ruleset_applicability")
if __name__=="__main__":run_contract()

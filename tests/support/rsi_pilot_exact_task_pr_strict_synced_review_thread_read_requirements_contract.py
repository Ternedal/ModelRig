from __future__ import annotations
import hashlib,inspect,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SUPPORT=ROOT/"tests"/"support";DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path:sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_read_requirements as requirements
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_base_sync_preflight as sync
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_evaluation as evaluation
from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_policy as policy
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_observation as ruleset_boundary
from kaliv_dev_control import improvement_pilot_exact_task_pr_branch_protection_observation as branch_boundary
import rsi_pilot_exact_task_pr_strict_base_sync_preflight_contract as sync_parent
import rsi_pilot_exact_task_pr_ruleset_applicability_preflight_contract as app_parent
import rsi_pilot_exact_task_pr_ruleset_observation_contract as fixtures
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-strict-synced-review-thread-read-requirements-v1.schema.json"

def _reject(fn):
    try:fn()
    except (requirements.PilotExactTaskPrStrictSyncedReviewThreadReadRequirementsError,ValueError,TypeError,OSError,AssertionError):return
    raise AssertionError("ADR-DC-088 accepted unsafe evidence")

def _chain(rows=None):
    source,ledger,tx,write,parent_temp,cleanup=app_parent._source(rows)
    app=applicability.classify_pilot_exact_task_pr_ruleset_applicability(source)
    required=policy.synthesize_pilot_exact_task_pr_required_status_policy(app)
    rl=ruleset_boundary._get_live_pr_ruleset_observation_inputs(source);assert rl is not None
    branch=rl["branch_protection_observation"]
    bl=branch_boundary._get_live_pr_branch_protection_observation_inputs(branch);assert bl is not None
    status=bl["status_check_observation"]
    evaluated=evaluation.evaluate_pilot_exact_task_pr_required_status(required,status)
    assert evaluated.evaluation_result=="PASS" and evaluated.evaluation_authenticated is True
    strict=sync_parent._observe(evaluated,sync_parent._transport(evaluated))
    assert strict.preflight_authenticated is True and strict.strict_base_sync_passed is True
    return strict,app,source,required,status,evaluated,ledger,tx,write,parent_temp,cleanup

def _cleanup(items):
    ledger,tx,write,parent_temp,cleanup=items[-5:]
    ledger.cleanup();tx.cleanup();write.cleanup();parent_temp.cleanup()
    for item in cleanup:item.cleanup()

def run_contract():
    if os.name=="nt":return
    sync_parent.run_contract()
    items=_chain();strict,app,source,required,status,evaluated,*_=items
    try:
        result=requirements.define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements(strict,app)
        assert result.requirements_authenticated is True
        assert result.strict_base_sync_preflight_sha256==strict.sha256
        assert result.required_status_evaluation_sha256==evaluated.sha256
        assert result.required_status_policy_receipt_sha256==required.sha256
        assert result.ruleset_applicability_sha256==app.sha256
        assert result.ruleset_observation_sha256==source.sha256
        assert result.status_check_observation_sha256==status.sha256
        assert result.repository==strict.repository=="Ternedal/ModelRig"
        assert result.pull_request_number==strict.pull_request_number
        assert result.predicted_commit_sha==strict.predicted_commit_sha
        assert result.strict_base_tip_sha==strict.first_base_tip_sha==strict.second_base_tip_sha
        assert result.graphql_operation==requirements.GRAPHQL_OPERATION
        assert result.graphql_query_sha256==hashlib.sha256(requirements.GRAPHQL_QUERY.encode()).hexdigest()
        for field in ("source_chain_verified","required_status_checks_passed","strict_base_sync_passed","exact_graphql_query_pinned","review_thread_read_capability_required","review_thread_state_observation_required","fresh_required_status_reobservation_before_merge_required","fresh_review_reobservation_required","fresh_merge_transaction_revalidation_required"):
            assert getattr(result,field) is True
        for field in ("branch_policy_fully_evaluated","merge_readiness_authorized","merge_authorized","production_activation_authorized"):
            assert getattr(result,field) is False
        live=requirements._get_live_pr_strict_synced_review_thread_read_requirements_inputs(result)
        assert live is not None and live["strict_base_sync_preflight"] is strict and live["ruleset_applicability"] is app
        replay=requirements.PilotExactTaskPrStrictSyncedReviewThreadReadRequirements.from_mapping(result.to_dict())
        assert replay==result and replay.requirements_authenticated is False
        loose_sync=sync.PilotExactTaskPrStrictBaseSyncPreflight.from_mapping(strict.to_dict())
        assert loose_sync.preflight_authenticated is False
        _reject(lambda:requirements.define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements(loose_sync,app))
        loose_app=applicability.PilotExactTaskPrRulesetApplicability.from_mapping(app.to_dict())
        assert loose_app.applicability_authenticated is False
        _reject(lambda:requirements.define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements(strict,loose_app))
        bad=result.to_dict();bad["graphql_query_sha256"]="3"*64
        _reject(lambda:requirements.PilotExactTaskPrStrictSyncedReviewThreadReadRequirements.from_mapping(bad))
        bad=result.to_dict();bad["merge_authorized"]=True
        _reject(lambda:requirements.PilotExactTaskPrStrictSyncedReviewThreadReadRequirements.from_mapping(bad))
    finally:_cleanup(items)

    first=_chain()
    row=fixtures._list_row(8891,name="disabled-other-chain",source_type="Repository",source="Ternedal/ModelRig",enforcement="disabled")
    second=_chain([(row,fixtures._detail(row,conditions={},rules=[]))])
    try:
        strict_a=first[0];app_b=second[1]
        _reject(lambda:requirements.define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements(strict_a,app_b))
    finally:_cleanup(first);_cleanup(second)

    assert "mutation" not in requirements.GRAPHQL_QUERY.lower()
    assert "__schema" not in requirements.GRAPHQL_QUERY
    assert "reviewDecision" in requirements.GRAPHQL_QUERY and "reviewThreads" in requirements.GRAPHQL_QUERY
    schema=json.loads(SCHEMA.read_text(encoding="utf-8"));fields=set(requirements.PilotExactTaskPrStrictSyncedReviewThreadReadRequirements.__dataclass_fields__)
    assert len(fields)==27 and set(schema["properties"])==fields and set(schema["required"])==fields
    assert schema["properties"]["strict_base_sync_passed"]["const"] is True
    assert schema["properties"]["fresh_required_status_reobservation_before_merge_required"]["const"] is True
    assert schema["properties"]["review_thread_read_capability_required"]["const"] is True
    assert schema["properties"]["merge_authorized"]["const"] is False
    assert schema["properties"]["production_activation_authorized"]["const"] is False
    assert tuple(inspect.signature(requirements.define_pilot_exact_task_pr_strict_synced_review_thread_read_requirements).parameters)==("strict_base_sync_preflight","ruleset_applicability")
    source_text=inspect.getsource(requirements)
    for forbidden in ("UrllibReadOnlyTransport","subprocess.run(","Popen(","merge_pull_request(","enable_auto_merge","resolve_review_thread"):
        assert forbidden not in source_text
if __name__=="__main__":run_contract()

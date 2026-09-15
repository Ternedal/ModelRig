"""Adversarial contract for ADR-DC-085 required-status policy synthesis."""
from __future__ import annotations
import inspect, json, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SUPPORT=ROOT/"tests"/"support"; DEVCONTROL_SRC=ROOT/"devcontrol"/"src"
for item in (SUPPORT,DEVCONTROL_SRC):
    if str(item) not in sys.path: sys.path.insert(0,str(item))

from kaliv_dev_control import improvement_pilot_exact_task_pr_required_status_policy as policy  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_ruleset_applicability as applicability  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_applicability_preflight_contract as parent  # noqa: E402
import rsi_pilot_exact_task_pr_ruleset_observation_contract as ruleset_parent  # noqa: E402

SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-required-status-policy-v1.schema.json"

def _reject(fn):
    try: fn()
    except (policy.PilotExactTaskPrRequiredStatusPolicyError,ValueError,TypeError,OSError,AssertionError): return
    raise AssertionError("ADR-DC-085 accepted unsafe evidence")

def run_contract():
    if os.name=="nt": return
    parent.run_contract()
    source,ledger,tx,write,parent_temp,cleanup=parent._source()
    try:
        app=applicability.classify_pilot_exact_task_pr_ruleset_applicability(source)
        result=policy.synthesize_pilot_exact_task_pr_required_status_policy(app)
        assert result.policy_authenticated is True
        assert result.ruleset_applicability_sha256==app.sha256
        assert result.ruleset_observation_sha256==source.sha256
        assert result.status_check_observation_sha256==source.status_check_observation_sha256
        assert result.required_check_count==3
        assert result.strict_required_status_checks_policy is True
        assert result.synthesis_result=="SUPPORTED"
        live=policy._get_live_pr_required_status_policy_inputs(result)
        assert live is not None
        assert live["required_checks"]==(("ci",None),("ci",15368),("legacy/security",None))
        assert result.required_status_checks_evaluated is False
        assert result.branch_policy_fully_evaluated is False
        assert result.review_threads_preflight_required is True
        assert result.merge_readiness_authorized is False
        assert result.merge_authorized is False
        assert result.production_activation_authorized is False

        replay=policy.PilotExactTaskPrRequiredStatusPolicy.from_mapping(result.to_dict())
        assert replay==result and replay.policy_authenticated is False
        loose=applicability.PilotExactTaskPrRulesetApplicability.from_mapping(app.to_dict())
        assert loose.applicability_authenticated is False
        _reject(lambda: policy.synthesize_pilot_exact_task_pr_required_status_policy(loose))

        row=ruleset_parent._list_row(8591,name="unsupported-status-shape",source_type="Repository",source="Ternedal/ModelRig",enforcement="active")
        detail=ruleset_parent._detail(row,conditions={"ref_name":{"include":["refs/heads/main"],"exclude":[]}},rules=[{
            "type":"required_status_checks",
            "parameters":{"strict_required_status_checks_policy":True,"required_status_checks":[{"context":"ci","integration_id":15368}],"future_field":True},
        }])
        other,a,b,c,d,extra=parent._source([(row,detail)])
        try:
            other_app=applicability.classify_pilot_exact_task_pr_ruleset_applicability(other)
            unsupported=policy.synthesize_pilot_exact_task_pr_required_status_policy(other_app)
            assert unsupported.policy_authenticated is True
            assert unsupported.synthesis_result=="UNSUPPORTED"
            assert unsupported.required_status_checks_evaluated is False
            assert unsupported.merge_authorized is False
        finally:
            a.cleanup(); b.cleanup(); c.cleanup(); d.cleanup()
            for item in extra: item.cleanup()

        schema=json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields=set(policy.PilotExactTaskPrRequiredStatusPolicy.__dataclass_fields__)
        assert len(fields)==18
        assert set(schema["properties"])==fields
        assert set(schema["required"])==fields
        assert schema["properties"]["required_status_checks_evaluated"]["const"] is False
        assert schema["properties"]["branch_policy_fully_evaluated"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(policy.synthesize_pilot_exact_task_pr_required_status_policy).parameters)==("v",)
        module_source=inspect.getsource(policy)
        for forbidden in ("UrllibReadOnlyTransport","run_bounded_subprocess","merge_pull_request(","enable_auto_merge","resolve_review_thread","label_pr("):
            assert forbidden not in module_source
    finally:
        ledger.cleanup(); tx.cleanup(); write.cleanup(); parent_temp.cleanup()
        for item in cleanup: item.cleanup()

if __name__=="__main__": run_contract()

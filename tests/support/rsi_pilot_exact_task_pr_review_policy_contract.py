"""Adversarial contract for ADR-DC-091 exact review-policy synthesis."""
from __future__ import annotations
import inspect, json, os, sys
from pathlib import Path
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[2]
SUPPORT=ROOT/'tests'/'support'; DEV=ROOT/'devcontrol'/'src'
for p in (SUPPORT,DEV):
    if str(p) not in sys.path: sys.path.insert(0,str(p))

from kaliv_dev_control import improvement_pilot_exact_task_pr_review_policy as policy
from kaliv_dev_control import improvement_pilot_exact_task_pr_strict_synced_review_thread_state_observation as observation
import rsi_pilot_exact_task_pr_strict_synced_review_thread_state_observation_contract as parent

SCHEMA=ROOT/'devcontrol'/'schemas'/'rsi-pilot-exact-task-pr-review-policy-v1.schema.json'

def _reject(fn):
    try: fn()
    except (policy.PilotExactTaskPrReviewPolicyError, ValueError, TypeError, OSError, AssertionError): return
    raise AssertionError('ADR-DC-091 accepted unsafe review policy')

def _source():
    cap, strict, req, upstream_live, items, temp, broker, broker_bytes = parent._source()
    observed = parent._observe(cap, parent._Runner(cap))
    assert observed.observation_authenticated is True
    return observed, cap, strict, req, upstream_live, items, temp

def _pull_rule(*, count=2, dismiss=True, codeowners=True, last_push=True, resolution=True, methods=None, restriction=None, reviewers=None, extra=None):
    params={
        'required_approving_review_count':count,
        'dismiss_stale_reviews_on_push':dismiss,
        'require_code_owner_review':codeowners,
        'require_last_push_approval':last_push,
        'required_review_thread_resolution':resolution,
    }
    if methods is not None: params['allowed_merge_methods']=methods
    if restriction is not None: params['dismissal_restriction']=restriction
    if reviewers is not None: params['required_reviewers']=reviewers
    if extra is not None: params['future_unknown']=extra
    return {'type':'pull_request','parameters':params}

def run_contract():
    if os.name=='nt': return
    parent.run_contract()
    observed, cap, strict, req, upstream_live, items, temp = _source()
    try:
        result=policy.synthesize_pilot_exact_task_pr_review_policy(observed)
        assert result.policy_authenticated is True
        assert result.review_thread_state_observation_sha256==observed.sha256
        assert result.review_thread_read_capability_sha256==cap.sha256
        assert result.strict_base_sync_preflight_sha256==strict.sha256
        assert result.repository=='Ternedal/ModelRig'
        assert result.pull_request_number==observed.pull_request_number
        assert result.predicted_commit_sha==observed.predicted_commit_sha
        assert result.synthesis_result=='SUPPORTED'
        assert result.applicable_active_ruleset_count==1
        # Default active ruleset is required-status only; the fixture's pull_request rule is evaluate-only.
        assert result.applicable_pull_request_rule_count==0
        assert result.unsupported_pull_request_rule_count==0
        assert result.legacy_required_pull_request_reviews_present is True
        assert result.legacy_required_approving_review_count==1
        assert result.legacy_dismiss_stale_reviews is True
        assert result.legacy_require_code_owner_reviews is False
        assert result.legacy_require_last_push_approval is True
        assert result.legacy_required_conversation_resolution is True
        assert result.effective_required_approving_review_count==1
        assert result.effective_dismiss_stale_reviews is True
        assert result.effective_require_code_owner_reviews is False
        assert result.effective_require_last_push_approval is True
        assert result.effective_required_conversation_resolution is True
        assert result.merge_method_policy_present is False
        live=policy._get_live_pr_review_policy_inputs(result)
        assert live is not None and live['review_thread_state_observation'] is observed
        assert dict(live['effective_review_policy'])=={
            'required_approving_review_count':1,
            'dismiss_stale_reviews':True,
            'require_code_owner_reviews':False,
            'require_last_push_approval':True,
            'required_conversation_resolution':True,
        }
        replay=policy.PilotExactTaskPrReviewPolicy.from_mapping(result.to_dict())
        assert replay==result and replay.policy_authenticated is False
        loose=observation.PilotExactTaskPrStrictSyncedReviewThreadStateObservation.from_mapping(observed.to_dict())
        assert loose.observation_authenticated is False
        _reject(lambda: policy.synthesize_pilot_exact_task_pr_review_policy(loose))

        parsed=policy._parse_pull_request_rule(_pull_rule(methods=['squash','rebase']))
        assert parsed is not None and parsed['supported'] is True
        assert parsed['required_approving_review_count']==2
        assert parsed['require_code_owner_reviews'] is True
        assert parsed['merge_method_policy_present'] is True
        for bad in (
            _pull_rule(restriction={'users':['octocat']}),
            _pull_rule(reviewers=[{'type':'Team','id':1}]),
            _pull_rule(extra=True),
            _pull_rule(count=11),
            _pull_rule(methods=['squash','future-method']),
        ):
            parsed=policy._parse_pull_request_rule(bad)
            assert parsed is not None and parsed['supported'] is False

        branch=SimpleNamespace(
            required_pull_request_reviews_present=True, required_approving_review_count=1,
            dismiss_stale_reviews=False, require_code_owner_reviews=False,
            require_last_push_approval=False, required_conversation_resolution_enabled=False,
        )
        app=SimpleNamespace(applicable_active_ruleset_count=1)
        active={'enforcement':'active','conditions':{'ref_name':{'include':['refs/heads/main'],'exclude':[]}},'rules':[_pull_rule(count=3,dismiss=True,codeowners=True,last_push=True,resolution=True,methods=['squash'])]}
        evaluate={'enforcement':'evaluate','conditions':{'ref_name':{'include':['refs/heads/main'],'exclude':[]}},'rules':[_pull_rule(count=6)]}
        synthetic=policy._synthesize({'branch_protection_observation':branch,'ruleset_applicability':app,'rulesets':(active,evaluate)})
        assert synthetic['synthesis_result']=='SUPPORTED'
        assert synthetic['applicable_pull_request_rule_count']==1
        assert synthetic['policy']['required_approving_review_count']==3
        assert synthetic['policy']['dismiss_stale_reviews'] is True
        assert synthetic['policy']['require_code_owner_reviews'] is True
        assert synthetic['policy']['require_last_push_approval'] is True
        assert synthetic['policy']['required_conversation_resolution'] is True
        assert synthetic['merge_method_policy_present'] is True
        unsupported_active=dict(active); unsupported_active['rules']=[_pull_rule(reviewers=[{'type':'User','id':7}])]
        unsupported=policy._synthesize({'branch_protection_observation':branch,'ruleset_applicability':app,'rulesets':(unsupported_active,)})
        assert unsupported['synthesis_result']=='UNSUPPORTED'
        assert unsupported['unsupported_pull_request_rule_count']==1

        tampered=result.to_dict(); tampered['merge_authorized']=True
        _reject(lambda: policy.PilotExactTaskPrReviewPolicy.from_mapping(tampered))
        tampered=result.to_dict(); tampered['effective_review_policy_sha256']='4'*64
        inert=policy.PilotExactTaskPrReviewPolicy.from_mapping(tampered)
        assert inert.policy_authenticated is False

        schema=json.loads(SCHEMA.read_text(encoding='utf-8'))
        fields=set(policy.PilotExactTaskPrReviewPolicy.__dataclass_fields__)
        assert len(fields)==48 and set(schema['properties'])==fields and set(schema['required'])==fields
        assert schema['properties']['review_policy_evaluation_required']['const'] is True
        assert schema['properties']['branch_policy_fully_evaluated']['const'] is False
        assert schema['properties']['merge_authorized']['const'] is False
        assert tuple(inspect.signature(policy.synthesize_pilot_exact_task_pr_review_policy).parameters)==('review_thread_state_observation',)
        source=inspect.getsource(policy)
        for forbidden in ('run_bounded_subprocess','urllib.request','requests.','merge_pull_request(','resolve_review_thread(','add_review_to_pr(','label_pr('):
            assert forbidden not in source
    finally:
        parent.parent.parent._cleanup(items)
        temp.cleanup()

if __name__=='__main__': run_contract()

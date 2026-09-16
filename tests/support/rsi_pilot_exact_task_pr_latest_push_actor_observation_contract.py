"""Adversarial contract for ADR-DC-094 latest-push actor observation."""
from __future__ import annotations
import inspect, json, os, sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SUPPORT=ROOT/"tests"/"support"; DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path: sys.path.insert(0,str(p))

from kaliv_dev_control import github_read
from kaliv_dev_control import improvement_pilot_exact_task_pr_latest_push_actor_observation as pushobs
from kaliv_dev_control import improvement_pilot_exact_task_pr_submitted_review_evidence_observation as reviews_boundary
import rsi_pilot_exact_task_pr_submitted_review_evidence_observation_contract as parent

SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-latest-push-actor-observation-v1.schema.json"

def _reject(fn):
    try: fn()
    except (pushobs.PilotExactTaskPrLatestPushActorObservationError,ValueError,TypeError,OSError,AssertionError): return
    raise AssertionError("ADR-DC-094 accepted unsafe latest-push evidence")

def _response(value,etag):
    body=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    return github_read.HttpResponse(status=200,headers={"ETag":etag},body=body)

class _Transport:
    def __init__(self,responses): self.responses=list(responses); self.calls=[]
    def get(self,url,*,headers,timeout_seconds,max_bytes):
        assert (
            url.startswith("https://api.github.com/repos/Ternedal/ModelRig/activity?")
            or url.startswith("https://api.github.com/repos/Ternedal/ModelRig/pulls/")
        )
        assert "Authorization" not in headers and "Cookie" not in headers
        assert timeout_seconds==20 and max_bytes in {256*1024,512*1024}
        self.calls.append(url)
        if not self.responses: raise AssertionError("unexpected activity read")
        return self.responses.pop(0)

def _source():
    requirements,policy,thread_obs,cap,strict,req,upstream_live,items,temp=parent._source()
    reviews=[
        parent._review(requirements,review_id=9401,node_id="PRR_9401",login="reviewer-a",user_id=1001,user_node_id="U_review_a",state="APPROVED"),
        parent._review(requirements,review_id=9402,node_id="PRR_9402",login="reviewer-b",user_id=1002,user_node_id="U_review_b",state="COMMENTED"),
    ]
    submitted=parent._observe(requirements,thread_obs,parent._stable_transport(requirements,thread_obs,reviews))
    assert submitted.observation_authenticated is True
    assert submitted.last_push_actor_evidence_still_required is True
    return submitted,requirements,policy,thread_obs,upstream_live,items,temp

def _pr(source,*,head_sha=None,node_id=None):
    return {
        "number":source.pull_request_number,
        "node_id":parent.PR_NODE_ID if node_id is None else node_id,
        "state":"open","draft":False,"closed_at":None,"merged_at":None,
        "head":{"ref":source.head_ref_name,"sha":source.predicted_commit_sha if head_sha is None else head_sha,"repo":{"full_name":"Ternedal/ModelRig"}},
        "base":{"ref":"main","repo":{"full_name":"Ternedal/ModelRig"}},
    }

def _activity(source,*,before="2"*40,after=None,pushed_at="2026-09-15T19:30:20Z",login="pusher",uid=5001,node="U_pusher",push_type="normal"):
    return {
        "id":123,
        "node_id":"ACT_123",
        "before":before,
        "after":source.predicted_commit_sha if after is None else after,
        "ref":f"refs/heads/{source.head_ref_name}",
        "pushed_at":pushed_at,
        "push_type":push_type,
        "pusher":{"login":login,"id":uid,"node_id":node},
    }

def _stable(source,normal,force=()):
    pr=_pr(source)
    return _Transport([
        _response(pr,'W/"pr-094"'),_response(list(normal),'W/"normal-094"'),_response(list(force),'W/"force-094"'),
        _response(pr,'W/"pr-094"'),_response(list(normal),'W/"normal-094"'),_response(list(force),'W/"force-094"'),
    ])

def _observe(source,transport,times=("2026-09-15T19:30:23Z","2026-09-15T19:30:24Z")):
    clock=iter(times)
    return pushobs._observe_verified_pilot_exact_task_pr_latest_push_actor(
        submitted_review_evidence_observation=source,transport=transport,now_provider=clock.__next__,
    )

def run_contract():
    if os.name=="nt": return
    parent.run_contract()
    source,requirements,policy,thread_obs,upstream_live,items,temp=_source()
    try:
        normal=[_activity(source)]
        transport=_stable(source,normal)
        result=_observe(source,transport)
        assert result.observation_authenticated is True
        assert result.submitted_review_evidence_observation_sha256==source.sha256
        assert result.review_evidence_requirements_sha256==requirements.sha256
        assert result.review_policy_sha256==policy.sha256
        assert result.review_thread_state_observation_sha256==thread_obs.sha256
        assert result.predicted_commit_sha==source.predicted_commit_sha
        assert result.head_ref_name==source.head_ref_name
        assert result.activity_kind=="push"
        assert result.latest_push_after_sha==source.predicted_commit_sha
        assert result.latest_push_actor_login=="pusher"
        assert result.latest_push_actor_user_id==5001
        assert result.last_push_actor_evidence_completed is True
        assert result.exact_pr_head_revalidated is True
        assert result.last_push_actor_evidence_still_required is False
        assert result.last_push_actor_inferred_from_commit_metadata is False
        assert result.code_owner_evidence_still_required is False
        assert len(transport.calls)==6
        assert "/pulls/" in transport.calls[0]
        assert "activity_type=push" in transport.calls[1] and "activity_type=force_push" in transport.calls[2]

        live=pushobs._get_live_pr_latest_push_actor_observation_inputs(result)
        assert live is not None and live["submitted_review_evidence_observation"] is source
        replay=pushobs.PilotExactTaskPrLatestPushActorObservation.from_mapping(result.to_dict())
        assert replay==result and replay.observation_authenticated is False

        loose=reviews_boundary.PilotExactTaskPrSubmittedReviewEvidenceObservation.from_mapping(source.to_dict())
        untouched=_stable(source,normal)
        _reject(lambda:_observe(loose,untouched))
        assert untouched.calls==[]

        force=[_activity(source,before="3"*40,pushed_at="2026-09-15T19:30:21Z",login="force-pusher",uid=5002,node="U_force",push_type="force")]
        forced=_observe(source,_stable(source,normal,force))
        assert forced.activity_kind=="force_push" and forced.latest_push_actor_login=="force-pusher"

        wrong=[_activity(source,after="f"*40)]
        _reject(lambda:_observe(source,_stable(source,wrong)))
        missing=[dict(_activity(source))]; missing[0]["pusher"]=None
        _reject(lambda:_observe(source,_stable(source,missing)))
        pr_drift=_Transport([_response(_pr(source,head_sha="f"*40),'W/"pr-drift"')])
        _reject(lambda:_observe(source,pr_drift))

        force_tie=[_activity(source,before="4"*40,pushed_at="2026-09-15T19:30:20Z",login="other",uid=5003,node="U_other",push_type="force")]
        _reject(lambda:_observe(source,_stable(source,normal,force_tie)))

        drift=_Transport([
            _response(_pr(source),'W/"pr1"'),_response(normal,'W/"n1"'),_response([],'W/"f1"'),
            _response(_pr(source),'W/"pr2"'),_response([_activity(source,login="changed",uid=5004,node="U_changed")],'W/"n2"'),_response([],'W/"f2"'),
        ])
        _reject(lambda:_observe(source,drift))
        _reject(lambda:_observe(source,_stable(source,normal),times=("2026-09-15T19:31:23Z","2026-09-15T19:31:24Z")))
        _reject(lambda:_observe(source,_stable(source,normal),times=("2026-09-15T19:30:24Z","2026-09-15T19:30:23Z")))

        tampered=result.to_dict(); tampered["merge_authorized"]=True
        _reject(lambda:pushobs.PilotExactTaskPrLatestPushActorObservation.from_mapping(tampered))
        tampered=result.to_dict(); tampered["latest_push_actor_evidence_still_required"]=1
        _reject(lambda:pushobs.PilotExactTaskPrLatestPushActorObservation.from_mapping(tampered))
        tampered=result.to_dict(); tampered["latest_push_after_sha"]="f"*40
        _reject(lambda:pushobs.PilotExactTaskPrLatestPushActorObservation.from_mapping(tampered))

        schema=json.loads(SCHEMA.read_text(encoding="utf-8"))
        fields=set(pushobs.PilotExactTaskPrLatestPushActorObservation.__dataclass_fields__)
        assert len(fields)==61 and set(schema["properties"])==fields and set(schema["required"])==fields
        assert schema["properties"]["exact_pr_head_revalidated"]["const"] is True
        assert schema["properties"]["last_push_actor_evidence_completed"]["const"] is True
        assert schema["properties"]["last_push_actor_evidence_still_required"]["const"] is False
        assert schema["properties"]["last_push_actor_inferred_from_commit_metadata"]["const"] is False
        assert schema["properties"]["merge_authorized"]["const"] is False
        assert tuple(inspect.signature(pushobs.observe_pilot_exact_task_pr_latest_push_actor).parameters)==("submitted_review_evidence_observation",)
        src=inspect.getsource(pushobs)
        assert "/activity?" in src and "activity_type=" in src and "UrllibReadOnlyTransport" in src
        for forbidden in ('method="POST"','method="PATCH"','method="PUT"','method="DELETE"',"run_bounded_subprocess","merge_pull_request(","add_review_to_pr(","resolve_review_thread(","request_pull_request_reviewers("):
            assert forbidden not in src
    finally:
        parent.parent.parent.parent.parent.parent._cleanup(items)
        temp.cleanup()

if __name__=="__main__": run_contract()

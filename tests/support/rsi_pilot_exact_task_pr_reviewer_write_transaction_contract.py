"""Adversarial contract for ADR-DC-075 exact reviewer-write transaction."""
from __future__ import annotations
import hashlib, inspect, json, os, sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT=Path(__file__).resolve().parents[2]; SUPPORT=ROOT/"tests"/"support"; DEV=ROOT/"devcontrol"/"src"
for p in (SUPPORT,DEV):
    if str(p) not in sys.path: sys.path.insert(0,str(p))
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_credential_capability as cap_boundary  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_write_transaction as tx  # noqa: E402
from kaliv_dev_control.bounded_subprocess import BoundedStreamEvidence, BoundedSubprocessResult  # noqa: E402
import rsi_pilot_exact_task_pr_reviewer_write_credential_capability_contract as parent  # noqa: E402
SCHEMA=ROOT/"devcontrol"/"schemas"/"rsi-pilot-exact-task-pr-reviewer-write-transaction-v1.schema.json"
UPDATED="2026-09-15T06:25:42Z"

def _reject(fn):
    try: fn()
    except (tx.PilotExactTaskPrReviewerWriteTransactionError,cap_boundary.PilotExactTaskPrReviewerWriteCredentialCapabilityError,ValueError,TypeError,OSError,AssertionError): return
    raise AssertionError("ADR-DC-075 unexpectedly accepted unsafe reviewer-write transaction")

def _stream(b): return BoundedStreamEvidence(prefix=b,total_bytes=len(b),sha256=hashlib.sha256(b).hexdigest(),truncated=False)

def _live_cap():
    pf,parent_temp,cleanup=parent._live_preflight(); write_temp=TemporaryDirectory(prefix="rsi-write-075-cap-")
    path=Path(write_temp.name)/"reviewer-write-broker"; raw=b"reviewer-write-broker-075-fixture"; path.write_bytes(raw); path.chmod(0o755)
    cap=parent._materialize(pf,parent._descriptor(path,raw),at="2026-09-15T06:25:39Z"); assert cap.capability_authenticated is True
    return cap,path,raw,write_temp,parent_temp,cleanup

def _fresh(cap):
    def read(*,reservation_receipt,reviewer_target,reviewer_handoff_requirements):
        del reviewer_handoff_requirements
        assert reservation_receipt.pull_request_number==cap.pull_request_number
        return {"pr_request_url_sha256":hashlib.sha256(cap.pull_request_api_url.encode()).hexdigest(),"pr_response_body_sha256":hashlib.sha256(b"fresh-075").hexdigest(),"pr_response_etag_sha256":hashlib.sha256(b"etag-075").hexdigest(),"pull_request_author_login":cap.pull_request_author_login,"pull_request_author_user_id":cap.pull_request_author_user_id,"observed_updated_at_utc":reviewer_target.ready_updated_at_utc,"requested_reviewer_count":0,"requested_team_count":0}
    return read

def _runner(cap,calls):
    def run(command,*,cwd,env,stdin_bytes,timeout_seconds,max_output_bytes,stdout_prefix_bytes,stderr_prefix_bytes):
        del cwd,timeout_seconds,max_output_bytes,stdout_prefix_bytes,stderr_prefix_bytes
        args=tuple(command); req=json.loads(stdin_bytes.decode()); calls.append((args,dict(env),req)); req_sha=hashlib.sha256(stdin_bytes).hexdigest()
        assert args[1:]==("--protocol","github-rest-reviewer-write-broker-v1","--request-stdin-json","--response-stdout-json")
        assert req["operation"]=="request-pull-request-reviewer" and req["reviewers"]==[cap.reviewer_login] and req["team_reviewers"]==[] and req["head_sha"]==cap.predicted_commit_sha
        assert not any(m in k.upper() for k in env for m in ("TOKEN","PASSWORD","AUTHORIZATION","BEARER"))
        out=json.dumps({"schema":tx.PILOT_EXACT_TASK_PR_REVIEWER_WRITE_BROKER_RESPONSE_SCHEMA,"status":"reviewer-requested","operation":"request-pull-request-reviewer","request_sha256":req_sha,"repository":cap.repository,"pull_request_number":cap.pull_request_number,"head_sha":cap.predicted_commit_sha,"reviewer_login":cap.reviewer_login,"reviewer_user_id":cap.reviewer_user_id,"reviewer_request_nonce_sha256":cap.reviewer_request_nonce_sha256,"requested_reviewer_count":1,"requested_team_count":0,"updated_at_utc":UPDATED},sort_keys=True,separators=(",",":")).encode()
        return BoundedSubprocessResult(args=args,returncode=0,stdout=_stream(out),stderr=_stream(b""),total_output_bytes=len(out),output_limit_exceeded=False,timed_out=False,process_tree_terminated=False)
    return run

def _readback(**kw):
    assert kw["expected_updated_at_utc"]==UPDATED
    return {"response_body_sha256":hashlib.sha256(b"post-075").hexdigest(),"response_etag_sha256":hashlib.sha256(b"post-etag-075").hexdigest(),"updated_at_utc":UPDATED,"requested_reviewer_count":1,"requested_team_count":0}

def _times(): return iter(("2026-09-15T06:25:40Z","2026-09-15T06:25:40Z","2026-09-15T06:25:42Z","2026-09-15T06:25:43Z")).__next__

def _execute(cap,ledger,calls,readback=_readback):
    return tx._execute_verified_pilot_exact_task_pr_reviewer_write(reviewer_write_credential_capability=cap,ledger=ledger,pr_state_reader=_fresh(cap),subprocess_runner=_runner(cap,calls),readback_reader=readback,now_provider=_times(),broker_host_control_required=False)

def run_contract():
    if os.name=="nt": return
    parent.run_contract(); cap,path,raw,write_temp,parent_temp,cleanup=_live_cap()
    ok_temp=TemporaryDirectory(prefix="rsi-write-075-ok-"); crash_temp=TemporaryDirectory(prefix="rsi-write-075-crash-")
    try:
        calls=[]; ledger=tx._TransactionLedger(Path(ok_temp.name)); result=_execute(cap,ledger,calls)
        assert result.transaction_authenticated is True and result.reviewer_write_credential_capability_sha256==cap.sha256 and result.reviewer_request_nonce_sha256==cap.reviewer_request_nonce_sha256
        assert result.reviewer_request_performed is True and result.exact_reviewer_set_verified is True and result.team_reviewers_absent_verified is True and result.nonce_reusable is False and result.reviewer_mutation_authorized is False and len(calls)==1
        reloaded=tx.PilotExactTaskPrReviewerWriteTransaction.from_mapping(result.to_dict()); assert reloaded==result and reloaded.sha256==result.sha256 and reloaded.transaction_authenticated is False
        _reject(lambda:_execute(cap,ledger,[]))
        cap2=cap_boundary.PilotExactTaskPrReviewerWriteCredentialCapability.from_mapping(cap.to_dict()); assert cap2.capability_authenticated is False; _reject(lambda:tx._require_live_capability(cap2))
        _reject(lambda:tx._require_transaction_window(cap,at_utc="2026-09-15T06:25:55Z"))
        path.write_bytes(raw+b"-tampered"); path.chmod(0o755); tamper=TemporaryDirectory(prefix="rsi-write-075-tamper-"); tamper_calls=[]
        try: _reject(lambda:_execute(cap,tx._TransactionLedger(Path(tamper.name)),tamper_calls)); assert tamper_calls==[]
        finally: tamper.cleanup()
        path.write_bytes(raw); path.chmod(0o755)
        crash_calls=[]; crash=tx._TransactionLedger(Path(crash_temp.name))
        def fail(**kw): del kw; raise tx.PilotExactTaskPrReviewerWriteTransactionError("simulated ambiguous post-write readback failure")
        _reject(lambda:_execute(cap,crash,crash_calls,fail)); assert len(crash_calls)==1 and crash._start_path(cap.reviewer_request_nonce_sha256).is_file() and not crash._final_path(cap.reviewer_request_nonce_sha256).exists()
        _reject(lambda:_execute(cap,crash,crash_calls)); assert len(crash_calls)==1
        schema=json.loads(SCHEMA.read_text()); fields=set(tx.PilotExactTaskPrReviewerWriteTransaction.__dataclass_fields__); assert len(fields)==71 and set(schema["properties"])==fields and set(schema["required"])==fields
        assert schema["properties"]["reviewer_request_performed"]["const"] is True and schema["properties"]["nonce_reusable"]["const"] is False and schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(tx.execute_pilot_exact_task_pr_reviewer_write).parameters)==("reviewer_write_credential_capability",)
        source=inspect.getsource(tx); assert '"reviewers": [capability.reviewer_login]' in source and '"team_reviewers": []' in source and "create_once_file" in source and "merge_pull_request(" not in source and "label_pr(" not in source
    finally:
        crash_temp.cleanup(); ok_temp.cleanup(); write_temp.cleanup(); parent_temp.cleanup()
        for x in cleanup: x.cleanup()
if __name__=="__main__": run_contract()

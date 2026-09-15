"""Adversarial contract for ADR-DC-073 exact reviewer-request transaction."""
from __future__ import annotations
import hashlib, inspect, json, os, sys
from pathlib import Path
from tempfile import TemporaryDirectory
ROOT = Path(__file__).resolve().parents[2]; SUPPORT = ROOT / "tests" / "support"; DEVCONTROL_SRC = ROOT / "devcontrol" / "src"
for item in (SUPPORT, DEVCONTROL_SRC):
    if str(item) not in sys.path: sys.path.insert(0, str(item))
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_request_transaction as transaction  # noqa: E402
from kaliv_dev_control import improvement_pilot_exact_task_pr_reviewer_requestability_preflight as preflight  # noqa: E402
from kaliv_dev_control.bounded_subprocess import BoundedStreamEvidence, BoundedSubprocessResult  # noqa: E402
from rsi_pilot_exact_task_pr_reviewer_requestability_preflight_contract import _live_capability, _broker_runner  # noqa: E402
SCHEMA = ROOT / "devcontrol" / "schemas" / "rsi-pilot-exact-task-pr-reviewer-request-transaction-v1.schema.json"
UPDATED = "2026-09-15T06:25:44Z"
def _reject(fn):
    try: fn()
    except (transaction.PilotExactTaskPrReviewerRequestTransactionError, preflight.PilotExactTaskPrReviewerRequestabilityPreflightError, ValueError, TypeError, OSError, AssertionError): return
    raise AssertionError("ADR-DC-073 unexpectedly accepted unsafe reviewer transaction")
def _stream(payload): return BoundedStreamEvidence(prefix=payload,total_bytes=len(payload),sha256=hashlib.sha256(payload).hexdigest(),truncated=False)
def _live_preflight():
    cap, broker_path, cleanup = _live_capability(); result = preflight._observe_verified_pilot_exact_task_pr_reviewer_requestability(reviewer_request_credential_capability=cap, subprocess_runner=_broker_runner(cap=cap,calls=[]), now_provider=lambda:"2026-09-15T06:25:42Z", broker_host_control_required=False); return result, broker_path, cleanup
def _fresh_state(*, reservation_receipt, reviewer_target, reviewer_handoff_requirements):
    return {"pr_request_url_sha256":hashlib.sha256(reservation_receipt.pull_request_api_url.encode()).hexdigest(),"pr_response_body_sha256":hashlib.sha256(b"fresh-073").hexdigest(),"pr_response_etag_sha256":hashlib.sha256(b"etag-073").hexdigest(),"pull_request_author_login":"modelrig-author","pull_request_author_user_id":97531,"observed_updated_at_utc":reviewer_target.ready_updated_at_utc,"requested_reviewer_count":0,"requested_team_count":0}
def _runner(*, pf, calls):
    def run(command, *, cwd, env, stdin_bytes, timeout_seconds, max_output_bytes, stdout_prefix_bytes, stderr_prefix_bytes):
        args=tuple(command); request=json.loads(stdin_bytes.decode()); calls.append((args,dict(env),request)); request_sha=hashlib.sha256(stdin_bytes).hexdigest()
        assert args[0].endswith("rsi-github-pr-reviewer-request-broker-v1") and args[1:]==("--protocol","github-rest-reviewer-request-broker-v1","--request-stdin-json","--response-stdout-json")
        assert request["operation"]=="request-exact-reviewer" and request["reviewers"]==[pf.reviewer_login] and request["team_reviewers"]==[] and request["head_sha"]==pf.predicted_commit_sha
        assert not any(marker in key.upper() for key in env for marker in ("TOKEN","PASSWORD","AUTHORIZATION","BEARER"))
        response={"schema":transaction.PILOT_EXACT_TASK_PR_REVIEWER_REQUEST_BROKER_RESPONSE_SCHEMA,"status":"reviewer-requested","operation":"request-exact-reviewer","request_sha256":request_sha,"repository":"Ternedal/ModelRig","pull_request_number":pf.pull_request_number,"head_sha":pf.predicted_commit_sha,"reviewer_login":pf.reviewer_login,"reviewer_user_id":pf.reviewer_user_id,"reviewer_request_nonce_sha256":pf.reviewer_request_nonce_sha256,"requested_reviewer_count":1,"requested_team_count":0,"updated_at_utc":UPDATED}
        stdout=json.dumps(response,sort_keys=True,separators=(",",":")).encode(); return BoundedSubprocessResult(args=args,returncode=0,stdout=_stream(stdout),stderr=_stream(b""),total_output_bytes=len(stdout),output_limit_exceeded=False,timed_out=False,process_tree_terminated=False)
    return run
def _readback(**kwargs): return {"response_body_sha256":hashlib.sha256(b"post-073").hexdigest(),"response_etag_sha256":hashlib.sha256(b"post-etag-073").hexdigest(),"updated_at_utc":UPDATED,"requested_reviewer_count":1,"requested_team_count":0}
def run_contract():
    if os.name=="nt": return
    pf, broker_path, cleanup = _live_preflight(); ledger_temp=TemporaryDirectory(prefix="rsi-reviewer-tx-073-")
    try:
        calls=[]; ledger=transaction._TransactionLedger(Path(ledger_temp.name)); result=transaction._execute_verified_pilot_exact_task_pr_reviewer_request(reviewer_requestability_preflight=pf,ledger=ledger,pr_state_reader=_fresh_state,subprocess_runner=_runner(pf=pf,calls=calls),readback_reader=_readback,now_provider=iter(["2026-09-15T06:25:43Z","2026-09-15T06:25:43Z","2026-09-15T06:25:44Z","2026-09-15T06:25:45Z"]).__next__,broker_host_control_required=False)
        assert result.transaction_authenticated is True and result.requestability_preflight_sha256==pf.sha256 and result.reviewer_request_nonce_sha256==pf.reviewer_request_nonce_sha256 and result.reviewer_request_performed is True and result.exact_reviewer_set_verified is True and result.team_reviewers_absent_verified is True and len(calls)==1
        assert result.reviewer_mutation_authorized is False and result.label_mutation_authorized is False and result.merge_authorized is False and result.production_activation_authorized is False
        assert transaction.PilotExactTaskPrReviewerRequestTransaction.from_mapping(result.to_dict()).transaction_authenticated is False
        _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_reviewer_request(reviewer_requestability_preflight=pf,ledger=ledger,pr_state_reader=_fresh_state,subprocess_runner=_runner(pf=pf,calls=[]),readback_reader=_readback,now_provider=lambda:"2026-09-15T06:25:43Z",broker_host_control_required=False))
        reloaded=preflight.PilotExactTaskPrReviewerRequestabilityPreflight.from_mapping(pf.to_dict()); assert reloaded.preflight_authenticated is False; _reject(lambda: transaction._require_live_preflight(reloaded))
        original=broker_path.read_bytes(); broker_path.write_bytes(original+b"tampered"); _reject(lambda: transaction._execute_verified_pilot_exact_task_pr_reviewer_request(reviewer_requestability_preflight=pf,ledger=transaction._TransactionLedger(Path(TemporaryDirectory(prefix="rsi-073-tamper-").name)),pr_state_reader=_fresh_state,subprocess_runner=_runner(pf=pf,calls=[]),readback_reader=_readback,now_provider=lambda:"2026-09-15T06:25:43Z",broker_host_control_required=False)); broker_path.write_bytes(original); broker_path.chmod(0o700)
        schema=json.loads(SCHEMA.read_text()); assert set(schema["properties"])==set(transaction.PilotExactTaskPrReviewerRequestTransaction.__dataclass_fields__); assert set(schema["required"])==set(schema["properties"]); assert schema["properties"]["reviewer_request_performed"]["const"] is True; assert schema["properties"]["reviewer_mutation_authorized"]["const"] is False; assert schema["properties"]["production_activation_authorized"]["const"] is False
        assert tuple(inspect.signature(transaction.execute_pilot_exact_task_pr_reviewer_request).parameters)==("reviewer_requestability_preflight",)
        source=inspect.getsource(transaction); assert "team_reviewers\": []" in source and "reviewers\": [preflight.reviewer_login]" in source and "merge_pull_request(" not in source and "label_pr(" not in source
    finally:
        ledger_temp.cleanup()
        for item in cleanup: item.cleanup()
if __name__=="__main__": run_contract()

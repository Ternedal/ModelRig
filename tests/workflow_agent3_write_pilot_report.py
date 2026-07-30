from __future__ import annotations
import copy
import hashlib
import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

spec = importlib.util.spec_from_file_location("t022_report", Path(__file__).resolve().parents[1] / "scripts" / "agent3_write_pilot_report.py")
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
assert spec.loader
spec.loader.exec_module(mod)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
NOW_TS = NOW.timestamp()
PILOT_ID = "a" * 32
PREFIX = f"KALIV-T022:{PILOT_ID}:P:"
IDENTITY = {
    "version": "1.58.146",
    "git_sha": "b" * 40,
    "code_sha256": "c" * 64,
    "identity_source": "git",
    "working_tree_clean": True,
    "version_stamps_consistent": True,
}
RIG_SHA = "d" * 64

def manifest():
    return {
        "schema": mod.MANIFEST_SCHEMA,
        "pilot_id": PILOT_ID,
        "created_at": mod._iso(datetime.fromtimestamp(NOW_TS - 600, timezone.utc)),
        "operator": "Anders",
        "target": {
            "version": IDENTITY["version"],
            "git_sha": IDENTITY["git_sha"],
            "code_sha256": IDENTITY["code_sha256"],
            "identity_source": IDENTITY["identity_source"],
            "rig_validation_report_sha256": RIG_SHA,
        },
        "marker_prefix": PREFIX,
        "runs": [
            {
                "ordinal": i,
                "marker": f"{PREFIX}{i:02d}:" + f"{i:032x}",
                "run_id": f"run-{i}",
                "bound_at": mod._iso(datetime.fromtimestamp(NOW_TS - 500 + i, timezone.utc)),
            }
            for i in range(1, 21)
        ],
    }

def success_record(run_id, marker, index, device="device-1"):
    step_id = f"step-{run_id}"
    digest = hashlib.sha256(f"digest-{run_id}".encode()).hexdigest()
    action = mod._action_sha(run_id, step_id, digest, 0)
    token = hashlib.sha256(f"token-{run_id}".encode()).hexdigest()
    nonce = hashlib.sha256(f"nonce-{run_id}".encode()).hexdigest()
    issued = NOW_TS - 400 + index
    used = issued + 1
    expires = issued + 60
    receipt = {
        "step_id": step_id,
        "tool": "note_append",
        "device_id": device,
        "issued_at": int(issued),
        "expires_at": int(expires),
        "plan_revision": 0,
        "args_sha256": hashlib.sha256(marker.encode()).hexdigest(),
        "confirmation_digest": digest,
        "approval_action_sha256": action,
        "approval_nonce_sha256": nonce,
        "approval_token_sha256": token,
    }
    kinds = [
        "run_created", "policy_decision", "confirmation_required",
        "approval_consumed", "confirmation_approved", "policy_decision",
        "step_started", "step_succeeded", "run_completed",
    ]
    events = []
    for j, kind in enumerate(kinds):
        payload = receipt if kind == "approval_consumed" else {"step_id": step_id, "tool": "note_append"}
        events.append({"ts": issued + j / 10, "kind": kind, "payload": payload})
    payload = {
        "id": run_id,
        "state": "completed",
        "created_at": issued - 1,
        "updated_at": used + 1,
        "route": {"kind": "rig_tools_local"},
        "steps": [{
            "id": step_id,
            "tool": "note_append",
            "args": {"text": marker},
            "risk": "write",
            "egress": "local",
            "idempotent": False,
            "state": "succeeded",
        }],
    }
    record = {"id": run_id, "state": "completed", "payload": payload, "updated_at": used + 1, "events": events}
    approval = {
        "nonce_sha256": nonce,
        "action_sha256": action,
        "used_at": used,
        "run_id": run_id,
        "step_id": step_id,
        "device_id": device,
        "plan_revision": 0,
        "token_sha256": token,
    }
    audit = {
        "tool": "note_append", "args_json": json.dumps({"text": marker}),
        "risk": "write", "outcome": "executed", "origin": "local",
    }
    return record, approval, audit

def blocked_record(run_id, marker, kind):
    step_id = f"step-{run_id}"
    state = "cancelled"
    payload = {
        "id": run_id, "state": state, "created_at": NOW_TS - 300,
        "updated_at": NOW_TS - 299, "route": {"kind": "rig_tools_local"},
        "steps": [{"id": step_id, "tool": "note_append", "args": {"text": marker}, "risk": "write", "egress": "local", "idempotent": False, "state": "denied"}],
    }
    events = [
        {"ts": NOW_TS - 300, "kind": "run_created", "payload": {}},
        {"ts": NOW_TS - 299.8, "kind": "policy_decision", "payload": {}},
        {"ts": NOW_TS - 299.7, "kind": "confirmation_required", "payload": {}},
        {"ts": NOW_TS - 299.6, "kind": kind, "payload": {"step_id": step_id}},
    ]
    return {"id": run_id, "state": state, "payload": payload, "updated_at": NOW_TS - 299, "events": events}

def negative(m):
    positives = [item["marker"] for item in m["runs"]]
    neg_prefix = f"KALIV-T022:{PILOT_ID}:N:"
    def case(name, statuses, before, after, ab, aa, run_ids, marker):
        return {
            "name": name,
            "observed_at": mod._iso(datetime.fromtimestamp(NOW_TS - 100, timezone.utc)),
            "marker": marker,
            "request_statuses": statuses,
            "response_sha256s": [hashlib.sha256(f"{name}-{i}".encode()).hexdigest() for i in range(len(statuses))],
            "note_count_before": before,
            "note_count_after": after,
            "approval_use_count_before": ab,
            "approval_use_count_after": aa,
            "run_ids": run_ids,
        }
    return {
        "schema": mod.NEGATIVE_SCHEMA,
        "pilot_id": PILOT_ID,
        "generated_at": mod._iso(datetime.fromtimestamp(NOW_TS - 90, timezone.utc)),
        "cases": [
            case("deny", [200], 0, 0, 0, 0, ["neg-deny"], neg_prefix + "deny"),
            case("timeout", [409], 0, 0, 0, 0, ["neg-timeout"], neg_prefix + "timeout"),
            case("changed_args", [409], 0, 0, 0, 0, ["run-1"], neg_prefix + "changed"),
            case("stale_revision", [409], 0, 0, 0, 0, ["run-2"], neg_prefix + "stale"),
            case("replay", [409], 1, 1, 1, 1, ["run-3"], positives[2]),
            case("concurrent_approval", [200, 409], 0, 1, 0, 1, ["neg-concurrent"], neg_prefix + "concurrent"),
            case("stop_retry_replan", [200, 202, 409], 1, 1, 1, 1, ["run-4", "run-5", "run-6"], positives[3]),
        ],
    }

def fixture():
    m = manifest()
    n = negative(m)
    records=[]; approvals=[]; audits=[]; note_lines=[]
    for i, item in enumerate(m["runs"], start=1):
        r,a,u = success_record(item["run_id"], item["marker"], i)
        records.append(r); approvals.append(a); audits.append(u); note_lines.append(item["marker"])
    records.append(blocked_record("neg-deny", n["cases"][0]["marker"], "confirmation_denied"))
    records.append(blocked_record("neg-timeout", n["cases"][1]["marker"], "confirmation_expired"))
    cr,ca,cu = success_record("neg-concurrent", n["cases"][5]["marker"], 50)
    records.append(cr); approvals.append(ca); audits.append(cu); note_lines.append(n["cases"][5]["marker"])
    return m,n,records,approvals,audits,"\n".join(note_lines)+"\n"

def judge_all(m,n,r,a,u,notes):
    return mod.judge(
        manifest=m, negative=n, run_records=r, approval_rows=a, audit_rows=u,
        notes_text=notes, identity=copy.deepcopy(IDENTITY),
        rig_validation_assessment={"eligible_for_write_pilot": True},
        rig_validation_sha256=RIG_SHA, now=NOW,
    )[0]

passed=failed=0
def check(cond,label):
    global passed,failed
    if cond:
        passed+=1; print("  PASS:", label)
    else:
        failed+=1; print("  FAIL:", label)

m,n,r,a,u,notes = fixture()
errors=judge_all(m,n,r,a,u,notes)
check(errors == [], "complete exact evidence is green")

# The real CLI supplies no synthetic clock. Exercise that branch so a missing
# default-time import cannot hide behind deterministic fixtures.
try:
    mod.judge(
        manifest=m, negative=n, run_records=r, approval_rows=a, audit_rows=u,
        notes_text=notes, identity=copy.deepcopy(IDENTITY),
        rig_validation_assessment={"eligible_for_write_pilot": True},
        rig_validation_sha256=RIG_SHA, now=None,
    )
    default_clock_ok = True
except NameError:
    default_clock_ok = False
check(default_clock_ok, "collector default clock path is wired")

m2,n2,r2,a2,u2,notes2 = fixture()
errors=judge_all(m2,n2,r2,a2,u2,notes2 + m2["runs"][0]["marker"] + "\n")
check(any("marker occurs 2" in e or "duplicated" in e for e in errors), "duplicate append is red")

m2,n2,r2,a2,u2,notes2 = fixture()
r2[0]["events"] = [e for e in r2[0]["events"] if e["kind"] != "approval_consumed"]
errors=judge_all(m2,n2,r2,a2,u2,notes2)
check(any("approval_consumed" in e for e in errors), "missing approval attribution is red")

m2,n2,r2,a2,u2,notes2 = fixture()
r2.append(copy.deepcopy(r2[0])); r2[-1]["id"]="hidden-retry"; r2[-1]["payload"]["id"]="hidden-retry"
errors=judge_all(m2,n2,r2,a2,u2,notes2)
check(any("inventory mismatch" in e for e in errors), "unlisted retry run is red")

m2,n2,r2,a2,u2,notes2 = fixture()
n2["cases"] = [c for c in n2["cases"] if c["name"] != "stale_revision"]
errors=judge_all(m2,n2,r2,a2,u2,notes2)
check(any("missing" in e and "stale_revision" in e for e in errors), "missing negative case is red")

m2,n2,r2,a2,u2,notes2 = fixture()
n2["cases"][2]["run_ids"] = ["fictional-run"]
errors=judge_all(m2,n2,r2,a2,u2,notes2)
check(any("fictional-run does not exist" in e for e in errors), "fictional negative run is red")

m2,n2,r2,a2,u2,notes2 = fixture()
identity = copy.deepcopy(IDENTITY); identity["git_sha"]="e"*40
errors = mod.judge(manifest=m2,negative=n2,run_records=r2,approval_rows=a2,audit_rows=u2,notes_text=notes2,identity=identity,rig_validation_assessment={"eligible_for_write_pilot":True},rig_validation_sha256=RIG_SHA,now=NOW)[0]
check(any("git_sha changed" in e for e in errors), "candidate SHA drift is red")

print(f"\n===== AGENT3 WRITE PILOT EVIDENCE: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

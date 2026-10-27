"""Contract for scripts/t038_operator_read.py, the operator entry for one live read.

The script is run as a real subprocess with the worker's deployment settings
and its own data root, against the loopback fixture Home Assistant from
tests/worker_home_rig_e2e_fixture.py. Grant and T-032 permission are created
in the same stores first, exactly as the loopback operator API would.

Pinned: it refuses (zero requests) when the pilot is off or the live-read
confirmation is missing; an approved read returns the receipt and exit 0 with
exactly one GET; the one-use permission cannot be reused; an unscoped entity
is denied with zero requests; an unreachable Home Assistant gives exit 3 and
state unknown; the evidence file carries no bearer or HA attributes; the
script itself has no HTTP client, write or rig path of its own.
"""
from __future__ import annotations

import importlib.util
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

import app.home_rig_tool as runtime_module  # noqa: E402
from app.data_sharing import DataSharingLedger  # noqa: E402
from app.home_rig_connector_contract import HomeRigAuditLog, HomeRigGrantStore, HomeRigScope  # noqa: E402
from source_code import code_of  # noqa: E402
from worker_home_rig_e2e_fixture import SENTINEL, FixtureHomeAssistant, write_token  # noqa: E402

SCRIPT = ROOT / "scripts" / "t038_operator_read.py"
_spec = importlib.util.spec_from_file_location("t038_operator_read_contract", SCRIPT)
operator_read = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(operator_read)
passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class UUIDs:
    def __init__(self, start: int) -> None:
        self.value = start

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    bearer = "fixture-" + secrets.token_urlsafe(30)
    with tempfile.TemporaryDirectory(prefix="modelrig-t038-operator-") as td, FixtureHomeAssistant(bearer) as ha:
        root = Path(td)
        token_file = write_token(root / "ha.token", bearer)
        env = {k: v for k, v in os.environ.items() if not k.startswith("KALIV_")}
        env.update({
            "PYTHONDONTWRITEBYTECODE": "1",
            "KALIV_DATA_DIR": str(root / "data"),
            "KALIV_HOME_RIG_GRANTS_DB": str(root / "grants.db"),
            "KALIV_HOME_RIG_AUDIT_DB": str(root / "audit.db"),
            "KALIV_DATA_SHARING_DB": str(root / "sharing.db"),
            "KALIV_HOME_ASSISTANT_ORIGIN": ha.origin,
            "KALIV_HOME_ASSISTANT_TOKEN_FILE": str(token_file),
            "KALIV_HOME_ASSISTANT_ALLOW_INSECURE_HTTP": "1",
            "KALIV_HOME_RIG_PILOT": "1",
        })
        grants = HomeRigGrantStore(env["KALIV_HOME_RIG_GRANTS_DB"], uuid_factory=UUIDs(0))
        audit = HomeRigAuditLog(env["KALIV_HOME_RIG_AUDIT_DB"])
        sharing = DataSharingLedger(env["KALIV_DATA_SHARING_DB"], uuid_factory=UUIDs(100))
        operator = runtime_module.HomeRigRuntime(grants=grants, audit=audit, sharing=sharing)
        grants.create(HomeRigScope(rig_ids=(), entity_ids=("sensor.gpu_temp",), operations=("entity_state",)),
                      actor="operator", now=operator.now())

        def permit() -> str:
            claim = operator.prepare_claim(target_kind="entity", target_id="sensor.gpu_temp",
                                           operation="entity_state")
            proposal = sharing.propose(operator.sharing_request(claim), now=operator.now())
            sharing.approve(proposal.permission_id, actor="operator", now=operator.now())
            return proposal.permission_id

        def run(*args: str, **overrides: str) -> subprocess.CompletedProcess:
            run_env = dict(env, **overrides)
            for key in [k for k, v in overrides.items() if v is None]:
                run_env.pop(key, None)
            return subprocess.run([sys.executable, "-B", str(SCRIPT), *args], capture_output=True,
                                  text=True, env=run_env, timeout=60)

        try:
            permission = permit()

            print("== refusals touch nothing")
            start = ha.count()
            off = run("--entity", "sensor.gpu_temp", "--permission-id", permission, "--confirm-live-read",
                      KALIV_HOME_RIG_PILOT="0")
            check(off.returncode == 2 and "REFUSED" in off.stdout, "pilot off -> refused (exit 2)")
            unconfirmed = run("--entity", "sensor.gpu_temp", "--permission-id", permission)
            check(unconfirmed.returncode == 2 and "REFUSED" in unconfirmed.stdout,
                  "missing --confirm-live-read -> refused (exit 2)")
            check(ha.count() == start, "refusals sent zero requests")

            print("== one approved read")
            evidence = root / "evidence" / "live-read.json"
            start = ha.count()
            ok = run("--entity", "sensor.gpu_temp", "--permission-id", permission, "--confirm-live-read",
                     "--evidence", str(evidence))
            seen = ha.since(start)
            check(ok.returncode == 0, f"approved read exits 0 (got {ok.returncode}: {ok.stdout[-200:]} {ok.stderr[-300:]})")
            check([(r["method"], r["path"], r["auth"]) for r in seen] ==
                  [("GET", "/api/states/sensor.gpu_temp", "matched")],
                  "exactly one bearer GET for the granted entity")
            receipt = {}
            if evidence.exists():
                # Evidence is data, not source: substring checks on it are the point.
                text = evidence.read_bytes().decode("utf-8")
                doc = json.loads(text)
                receipt = doc.get("receipt", {})
                check(doc.get("schema") == "kaliv-home-rig-live-read/v1" and doc.get("result") == "observed"
                      and doc.get("production_activation") is False and doc.get("origin_scheme") == "http",
                      "evidence file records the observed result, scheme only, activation false")
                check(bearer not in text and SENTINEL not in text and "127.0.0.1" not in text
                      and f":{ha.port}" not in text,
                      "evidence carries no bearer, HA attributes or origin host:port")
            else:
                check(False, "evidence file was written")
            obs = receipt.get("observation", {})
            check(obs.get("state") == "61" and obs.get("freshness") == "fresh"
                  and obs.get("source_id") == "home_assistant:sensor.gpu_temp",
                  "receipt is the fresh, source-bound T-038 observation")
            check(bearer not in ok.stdout + ok.stderr and SENTINEL not in ok.stdout + ok.stderr,
                  "script output carries no bearer or HA attributes")
            check(receipt.get("omitted_fields") == [] and set(obs) == set(operator_read.OBSERVATION_FIELDS),
                  "the allowlist covers today's whole receipt (nothing omitted, nothing missing)")

            print("== an existing evidence file is never overwritten by accident")
            before = evidence.read_bytes() if evidence.exists() else b""
            start = ha.count()
            fresh_permission = permit()
            again_evidence = run("--entity", "sensor.gpu_temp", "--permission-id", fresh_permission,
                                 "--confirm-live-read", "--evidence", str(evidence))
            check(again_evidence.returncode == 2 and "REFUSED" in again_evidence.stdout and ha.count() == start
                  and evidence.read_bytes() == before,
                  "existing evidence -> refused (exit 2), zero requests, file unchanged")
            replaced = run("--entity", "sensor.gpu_temp", "--permission-id", fresh_permission,
                           "--confirm-live-read", "--evidence", str(evidence), "--overwrite")
            check(replaced.returncode == 0 and ha.count() == start + 1,
                  "the refusal did not burn the permission; --overwrite then reads once and replaces it")

            print("== the permission is single use, the scope is exact")
            start = ha.count()
            again = run("--entity", "sensor.gpu_temp", "--permission-id", permission, "--confirm-live-read")
            check(again.returncode == 1 and "DENIED" in again.stdout and ha.count() == start,
                  "reusing the permission is denied with zero requests")
            unscoped = run("--entity", "sensor.not_granted", "--permission-id", permit(), "--confirm-live-read")
            check(unscoped.returncode == 1 and "DENIED" in unscoped.stdout and ha.count() == start,
                  "an entity outside the grant is denied with zero requests")

            print("== an unreachable Home Assistant is unknown, not ready")
            down = run("--entity", "sensor.gpu_temp", "--permission-id", permit(), "--confirm-live-read",
                       KALIV_HOME_ASSISTANT_ORIGIN=f"http://127.0.0.1:{closed_port()}")
            check(down.returncode == 3 and '"state": "unknown"' in down.stdout,
                  "connection refused -> exit 3, state unknown")
            check(all(r["method"] == "GET" for r in ha.since(0)), "the fixture only ever saw GET")
        finally:
            grants.close()
            audit.close()
            sharing.close()

    print("== only allowlisted receipt fields reach the terminal or evidence (review 5660163195)")
    future = {
        "schema": "kaliv-home-rig-read-receipt/v1", "grant_id": "g", "scope_sha256": "s" * 64,
        "fulfilled_at": 1, "authority_rechecked": True, "production_activation": False,
        "future_debug": SENTINEL,
        "observation": {"schema": "x", "source": "home_assistant", "source_id": "home_assistant:sensor.x",
                        "capability_id": "c", "target_kind": "entity", "target_id": "sensor.x",
                        "operation": "entity_state", "state": "1", "checked_at": "t", "observed_at": "t",
                        "freshness": "fresh", "freshness_seconds": 0, "max_freshness_seconds": 120,
                        "production_activation": False, "attributes": {"secret": SENTINEL}, "peer": "127.0.0.1"},
    }
    projected = operator_read.project_receipt(future)
    check(SENTINEL not in json.dumps(projected) and "127.0.0.1" not in json.dumps(projected),
          "a field the runtime might add later never reaches output or evidence")
    check(projected["omitted_fields"] == ["future_debug", "observation.attributes", "observation.peer"],
          "dropped fields are named, not silently copied")
    check(projected["observation"]["state"] == "1" and projected["grant_id"] == "g",
          "allowlisted fields are kept")
    check(operator_read.project_receipt("not a dict") == {"omitted_fields": ["<receipt is not an object>"]},
          "a malformed receipt projects to nothing")

    source = code_of(SCRIPT)
    check(source.count("json.loads(raw)") == 1 and "project_receipt(json.loads(raw))" in source,
          "the raw receipt is parsed once, straight into the projection")
    for forbidden in ("urllib.request", "http.client", "requests.", "socket.", "preview(", '"rig"',
                      "production_activation=True", "subprocess.Popen", "os.system"):
        check(forbidden not in source, f"script has no own network, rig, preview or shell path: {forbidden}")
    check('operation="entity_state"' in source and source.count("runtime.read(") == 1,
          "script performs exactly one T-038 entity_state read")

    print(f"\n===== T-038 OPERATOR READ: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

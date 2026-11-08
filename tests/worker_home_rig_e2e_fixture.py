"""T-038 Home Assistant read, end to end on the real wire (KalivNexus #1, ModelRig #2264).

Every other T-038 test replaces one link of the chain: the runtime tests patch
``execute_home_assistant_state_read``, and the transport tests inject a fake
``socket_factory``. This test patches nothing in ModelRig. Only Home Assistant
itself is a fixture: a stdlib HTTP server on 127.0.0.1.

    runtime.read -> T-038 grant -> T-032 one-use permission -> deployment env
    -> default DNS resolver -> PinnedHomeAssistantTransport (real TCP socket)
    -> strict state parser -> fulfill_read -> receipt + audit + sharing ledger

It checks the read-only journey and its negative edges:

* scoped read: source, timestamps, freshness, exactly one GET with the bearer;
* a T-032 permission is single use;
* an unscoped entity, plaintext without opt-in and a broadly readable token
  file never reach the server;
* 401, timeout and an entity-mismatched body are never reported as state;
* wake and control previews never reach the server;
* the server never sees anything but GET (no write path exists);
* the bearer and Home Assistant attributes never appear in the receipt,
  audit log, sharing ledger, log output or the report.

``--report PATH`` writes a JSON report bound to the checkout that produced it.
``--check PATH`` re-checks a stored report against the current checkout: its
summary must match its cases, its candidate commit must equal ``HEAD``, and
every file-under-test hash must equal the file on disk. The report is **not
signed**. Anyone who can rerun the test can produce a new one, so it is
consistency evidence for an exact commit, not proof of who produced it.
Production activation stays false; nothing here contacts a real Home
Assistant. The consented live read is a separate, PENDING step.
"""
from __future__ import annotations

import hashlib
import http.server
import io
import json
import logging
import os
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import app.home_rig_tool as runtime_module  # noqa: E402
from app import tools  # noqa: E402
from app.data_sharing import DataSharingLedger  # noqa: E402
from app.home_rig_connector_contract import (  # noqa: E402
    HomeRigAuditLog,
    HomeRigGrantStore,
    HomeRigScope,
)

SCHEMA = "kaliv-home-rig-e2e-report/v1"
REQUIRED_CASES = (
    "scoped_read",
    "permission_single_use",
    "unscoped_entity",
    "wrong_bearer",
    "timeout",
    "entity_mismatch",
    "plaintext_without_opt_in",
    "token_file_too_broad",
    "previews_offline",
    "no_write_requests",
    "redaction",
)
UNDER_TEST = (
    "worker/app/home_rig_tool.py",
    "worker/app/home_rig_read_boundary.py",
    "worker/app/home_rig_provider_gate.py",
    "worker/app/home_rig_connector_contract.py",
    "worker/app/home_assistant_provider_transport.py",
    "worker/app/home_assistant_state_contract.py",
    "worker/app/data_sharing.py",
)
SENTINEL = "kaliv-attr-sentinel-" + "7" * 12
TRANSPORT_TIMEOUT_SECONDS = 5.0  # execute_home_assistant_state_read default

passed = failed = 0
cases: list[dict] = []


def check(condition: bool, name: str) -> bool:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")
    return bool(condition)


def record_case(case_id: str, ok: bool, expected: str, observed: dict) -> None:
    cases.append({
        "id": case_id,
        "result": "pass" if ok else "fail",
        "expected": expected,
        "observed": observed,
    })


class UUIDs:
    def __init__(self, start: int = 0) -> None:
        self.value = start

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


# --------------------------------------------------------------------------
# Fixture Home Assistant: GET /api/states/<entity> only, everything recorded.
# --------------------------------------------------------------------------

def _iso(seconds: int) -> str:
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


class FixtureHomeAssistant:
    def __init__(self, bearer: str) -> None:
        self.bearer = bearer
        self.requests: list[dict] = []
        self._lock = threading.Lock()
        changed = int(time.time()) - 300
        self.states = {
            "sensor.gpu_temp": {"state": "61", "body_entity": "sensor.gpu_temp"},
            "sensor.slow": {"state": "1", "body_entity": "sensor.slow", "delay": TRANSPORT_TIMEOUT_SECONDS + 1.5},
            "sensor.wrong_body": {"state": "999", "body_entity": "sensor.someone_else"},
        }
        self.changed_iso = _iso(changed)
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # keep test output clean
                pass

            def _record(self) -> dict:
                auth = self.headers.get("Authorization")
                entry = {
                    "method": self.command,
                    "path": self.path,
                    "host": self.headers.get("Host"),
                    "auth": "absent" if auth is None else (
                        "matched" if auth == "Bearer " + fixture.bearer else "mismatched"
                    ),
                }
                with fixture._lock:
                    fixture.requests.append(entry)
                return entry

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self) -> None:
                entry = self._record()
                prefix = "/api/states/"
                entity = self.path[len(prefix):] if self.path.startswith(prefix) else None
                spec = fixture.states.get(entity) if entity else None
                if entry["auth"] != "matched":
                    self._send(401, {"message": "Unauthorized"})
                    return
                if spec is None:
                    self._send(404, {"message": "Entity not found."})
                    return
                if spec.get("delay"):
                    time.sleep(spec["delay"])
                self._send(200, {
                    "entity_id": spec["body_entity"],
                    "state": spec["state"],
                    "attributes": {"friendly_name": "Fixture " + entity, "kaliv_sentinel": SENTINEL},
                    "last_changed": fixture.changed_iso,
                    "last_updated": fixture.changed_iso,
                    "context": {"id": "fixture", "user_id": SENTINEL},
                })

            def _refuse(self) -> None:
                self._record()
                self._send(405, {"message": "fixture is read-only"})

            do_POST = do_PUT = do_PATCH = do_DELETE = _refuse

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        self.origin = f"http://127.0.0.1:{self.port}"
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> "FixtureHomeAssistant":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()

    def count(self) -> int:
        with self._lock:
            return len(self.requests)

    def since(self, start: int) -> list[dict]:
        with self._lock:
            return list(self.requests[start:])

    def states_sha256(self) -> str:
        canonical = json.dumps(
            {k: {kk: vv for kk, vv in v.items()} for k, v in sorted(self.states.items())},
            sort_keys=True, separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Deployment environment, exactly as a rig would set it.
# --------------------------------------------------------------------------

_ENV = (
    "KALIV_HOME_ASSISTANT_ORIGIN",
    "KALIV_HOME_ASSISTANT_TOKEN_FILE",
    "KALIV_HOME_ASSISTANT_ALLOW_INSECURE_HTTP",
)


class DeploymentEnv:
    def __init__(self) -> None:
        self.saved = {name: os.environ.get(name) for name in _ENV}

    def set(self, *, origin: str, token_file: Path, insecure: bool) -> None:
        os.environ["KALIV_HOME_ASSISTANT_ORIGIN"] = origin
        os.environ["KALIV_HOME_ASSISTANT_TOKEN_FILE"] = str(token_file)
        os.environ["KALIV_HOME_ASSISTANT_ALLOW_INSECURE_HTTP"] = "1" if insecure else "0"

    def restore(self) -> None:
        for name, value in self.saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def write_token(path: Path, token: str, mode: int = 0o600) -> Path:
    path.write_text(token + "\n", encoding="ascii")
    os.chmod(path, mode)
    return path


def permit(runtime, entity_id: str) -> str:
    claim = runtime.prepare_claim(target_kind="entity", target_id=entity_id, operation="entity_state")
    request = runtime.sharing_request(claim)
    proposal = runtime.sharing.propose(request, now=runtime.now())
    runtime.sharing.approve(proposal.permission_id, actor="operator", now=runtime.now())
    return proposal.permission_id


def read(runtime, entity_id: str, permission_id: str):
    """Return (receipt dict | None, exception class name | None)."""
    try:
        return json.loads(runtime.read(
            target_kind="entity", target_id=entity_id,
            operation="entity_state", permission_id=permission_id,
        )), None
    except (tools.ToolDenied, tools.ToolError) as exc:
        return None, type(exc).__name__


def checkout_head() -> str | None:
    """The commit actually checked out, not what the environment claims."""
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def git_sha() -> str | None:
    return checkout_head() or os.environ.get("GITHUB_SHA") or None


def files_sha256() -> dict[str, str]:
    return {rel: hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() for rel in UNDER_TEST}


# --------------------------------------------------------------------------
# The run
# --------------------------------------------------------------------------

def run() -> dict:
    bearer = "fixture-" + secrets.token_urlsafe(30)
    log_buffer = io.StringIO()
    log_handler = logging.StreamHandler(log_buffer)
    log_handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    old_level = root_logger.level
    root_logger.addHandler(log_handler)
    root_logger.setLevel(logging.DEBUG)
    env = DeploymentEnv()

    with tempfile.TemporaryDirectory(prefix="modelrig-t038-e2e-") as td, FixtureHomeAssistant(bearer) as ha:
        root = Path(td)
        token_file = write_token(root / "ha.token", bearer)
        wrong_token_file = write_token(root / "ha-wrong.token", "fixture-" + secrets.token_urlsafe(30))
        grants = HomeRigGrantStore(str(root / "grants.db"), uuid_factory=UUIDs())
        audit = HomeRigAuditLog(str(root / "audit.db"))
        sharing = DataSharingLedger(str(root / "sharing.db"), uuid_factory=UUIDs(100))
        runtime = runtime_module.HomeRigRuntime(grants=grants, audit=audit, sharing=sharing)
        grants.create(
            HomeRigScope(
                rig_ids=("render-rig-1",),
                entity_ids=("sensor.gpu_temp", "sensor.slow", "sensor.wrong_body"),
                operations=("entity_state", "wake_preview", "control_preview"),
            ),
            actor="operator",
            now=runtime.now(),
        )
        receipts: list[dict] = []
        try:
            env.set(origin=ha.origin, token_file=token_file, insecure=True)

            print("== scoped read over the real transport")
            start = ha.count()
            permission = permit(runtime, "sensor.gpu_temp")
            receipt, error = read(runtime, "sensor.gpu_temp", permission)
            seen = ha.since(start)
            obs = (receipt or {}).get("observation", {})
            ok = all([
                check(error is None and receipt is not None, "scoped read returns a receipt"),
                check(obs.get("state") == "61", "receipt carries the fixture state"),
                check(obs.get("source") == "home_assistant", "receipt names its source"),
                check(obs.get("source_id") == "home_assistant:sensor.gpu_temp", "receipt has an exact source id"),
                check(obs.get("freshness") == "fresh" and obs.get("observed_at") is not None,
                      "receipt is fresh and timestamped"),
                check(receipt is not None and receipt.get("authority_rechecked") is True,
                      "authority was re-checked at fulfilment"),
                check(receipt is not None and receipt.get("production_activation") is False,
                      "production activation stays false"),
                check([(r["method"], r["path"]) for r in seen] == [("GET", "/api/states/sensor.gpu_temp")],
                      "exactly one GET for exactly that entity reached Home Assistant"),
                check(bool(seen) and seen[0]["auth"] == "matched", "the deployment bearer was sent"),
                check(bool(seen) and seen[0]["host"] == f"127.0.0.1:{ha.port}", "Host header is the pinned origin"),
            ])
            if receipt:
                receipts.append(receipt)
            record_case("scoped_read", ok, "fresh receipt with source and one bearer GET",
                        {"state": obs.get("state"), "freshness": obs.get("freshness"),
                         "source_id": obs.get("source_id"), "requests": seen})

            print("== the T-032 permission is single use")
            start = ha.count()
            again, error = read(runtime, "sensor.gpu_temp", permission)
            ok = check(again is None and error == "ToolDenied" and ha.count() == start,
                       "reusing the permission is denied before any request")
            record_case("permission_single_use", ok, "ToolDenied, zero requests",
                        {"error": error, "requests": ha.since(start)})

            print("== an unscoped entity never reaches Home Assistant")
            start = ha.count()
            result, error = read(runtime, "sensor.not_granted", "dsp_" + "0" * 32)
            ok = check(result is None and error == "ToolDenied" and ha.count() == start,
                       "unscoped entity is denied with zero requests")
            record_case("unscoped_entity", ok, "ToolDenied, zero requests",
                        {"error": error, "requests": ha.since(start)})

            print("== a rejected bearer is never reported as state")
            env.set(origin=ha.origin, token_file=wrong_token_file, insecure=True)
            start = ha.count()
            receipt, error = read(runtime, "sensor.gpu_temp", permit(runtime, "sensor.gpu_temp"))
            seen = ha.since(start)
            obs = (receipt or {}).get("observation", {})
            ok = all([
                check(obs.get("state") == "unknown" and obs.get("freshness") == "unavailable",
                      "401 normalizes to unknown/unavailable"),
                check([r["auth"] for r in seen] == ["mismatched"], "the server saw one request with a wrong bearer"),
            ])
            if receipt:
                receipts.append(receipt)
            record_case("wrong_bearer", ok, "unknown/unavailable after HTTP 401",
                        {"state": obs.get("state"), "freshness": obs.get("freshness"), "requests": seen})
            env.set(origin=ha.origin, token_file=token_file, insecure=True)

            print("== a slow server is bounded by the transport timeout")
            start = ha.count()
            began = time.monotonic()
            receipt, error = read(runtime, "sensor.slow", permit(runtime, "sensor.slow"))
            elapsed = time.monotonic() - began
            obs = (receipt or {}).get("observation", {})
            ok = all([
                check(obs.get("state") == "unknown" and obs.get("freshness") == "unavailable",
                      "timeout normalizes to unknown/unavailable"),
                check(elapsed < TRANSPORT_TIMEOUT_SECONDS + 1.0, f"read returned within the timeout ({elapsed:.1f}s)"),
            ])
            if receipt:
                receipts.append(receipt)
            record_case("timeout", ok, f"unknown/unavailable within {TRANSPORT_TIMEOUT_SECONDS + 1.0:.0f}s",
                        {"state": obs.get("state"), "elapsed_seconds": round(elapsed, 2), "requests": ha.since(start)})

            print("== a body for another entity is never accepted")
            start = ha.count()
            receipt, error = read(runtime, "sensor.wrong_body", permit(runtime, "sensor.wrong_body"))
            state = (receipt or {}).get("observation", {}).get("state")
            ok = check(state in (None, "unknown") and state != "999",
                       "entity-mismatched response is rejected, its state never surfaces")
            record_case("entity_mismatch", ok, "no state from a response for another entity",
                        {"error": error, "state": state, "requests": ha.since(start)})

            print("== plaintext without explicit opt-in is a configuration failure")
            env.set(origin=ha.origin, token_file=token_file, insecure=False)
            start = ha.count()
            result, error = read(runtime, "sensor.gpu_temp", permit(runtime, "sensor.gpu_temp"))
            ok = check(result is None and error == "ToolError" and ha.count() == start,
                       "http:// without opt-in fails before any request")
            record_case("plaintext_without_opt_in", ok, "ToolError, zero requests",
                        {"error": error, "requests": ha.since(start)})
            env.set(origin=ha.origin, token_file=token_file, insecure=True)

            print("== a group/world-readable token file is refused")
            if os.name == "posix":
                broad = write_token(root / "ha-broad.token", bearer, mode=0o644)
                env.set(origin=ha.origin, token_file=broad, insecure=True)
                start = ha.count()
                receipt, error = read(runtime, "sensor.gpu_temp", permit(runtime, "sensor.gpu_temp"))
                obs = (receipt or {}).get("observation", {})
                ok = check(obs.get("state") == "unknown" and ha.count() == start,
                           "0644 token file yields unknown with zero requests")
                if receipt:
                    receipts.append(receipt)
                record_case("token_file_too_broad", ok, "unknown, zero requests",
                            {"state": obs.get("state"), "requests": ha.since(start)})
                env.set(origin=ha.origin, token_file=token_file, insecure=True)
            else:
                record_case("token_file_too_broad", True, "posix-only permission check",
                            {"skipped": f"os.name={os.name}"})

            print("== wake and control are previews that never reach Home Assistant")
            start = ha.count()
            wake = json.loads(runtime.preview(target_kind="rig", target_id="render-rig-1", action="wake"))
            control = json.loads(runtime.preview(target_kind="entity", target_id="sensor.gpu_temp", action="turn_off"))
            ok = check(wake.get("would_execute") is False and control.get("would_execute") is False
                       and ha.count() == start, "previews are inert and offline")
            record_case("previews_offline", ok, "would_execute=false, zero requests",
                        {"wake": wake.get("would_execute"), "control": control.get("would_execute"),
                         "requests": ha.since(start)})

            all_requests = ha.since(0)
            ok = check(all_requests and all(r["method"] == "GET" for r in all_requests),
                       "Home Assistant never received anything but GET")
            record_case("no_write_requests", ok, "every request is GET",
                        {"methods": sorted({r["method"] for r in all_requests}), "count": len(all_requests)})

            audit_rows = audit.recent(limit=100)
            sharing_rows = sharing.recent_events(limit=200)
        finally:
            env.restore()
            grants.close()
            audit.close()
            sharing.close()
            root_logger.removeHandler(log_handler)
            root_logger.setLevel(old_level)

        print("== the bearer and HA attributes never leave the transport boundary")
        stored = b"".join(p.read_bytes() for p in root.iterdir() if p.is_file() and not p.name.endswith(".token"))
        surfaces = {
            "receipts": json.dumps(receipts),
            "audit_rows": json.dumps(audit_rows, default=str),
            "sharing_events": json.dumps(sharing_rows, default=str),
            "logs": log_buffer.getvalue(),
        }
        leaks = {name: [s for s in (bearer, SENTINEL) if s in text] for name, text in surfaces.items()}
        leaks["databases"] = [s for s in (bearer, SENTINEL) if s.encode() in stored]
        ok = all([
            check(not any(leaks.values()), "no bearer or attribute sentinel in receipts, audit, ledger, DBs or logs"),
            check(any(r.get("connector") == "home_assistant" for r in audit_rows),
                  "the audit log records the Home Assistant connector"),
        ])
        record_case("redaction", ok, "bearer and attributes absent from every surface",
                    {name: bool(found) for name, found in leaks.items()})

    report = {
        "schema": SCHEMA,
        "candidate": {"git_sha": git_sha(), "files_sha256": files_sha256()},
        "fixture": {"kind": "loopback-http", "origin_scheme": "http", "peer": "127.0.0.1",
                    "states_sha256": ha.states_sha256()},
        "production_activation": False,
        "live_provider": False,
        "live_test": "PENDING",
        "cases": cases,
        "summary": summarize(cases),
    }
    text = json.dumps(report, sort_keys=True)
    if not check(bearer not in text and SENTINEL not in text, "the report itself carries no bearer or attribute"):
        report["summary"] = {"status": "FAIL", "passed": 0, "failed": len(cases), "reason": "report leak"}
    return report


def summarize(items: list[dict]) -> dict:
    ids = [c.get("id") for c in items]
    missing = [c for c in REQUIRED_CASES if c not in ids]
    bad = [c.get("id") for c in items if c.get("result") != "pass"]
    status = "FAIL" if (bad or missing or len(ids) != len(set(ids))) else "PASS"
    return {"status": status, "passed": len(items) - len(bad), "failed": len(bad), "missing": missing}


def validate(report: dict, *, against_checkout: bool = False) -> list[str]:
    """Return problems with a report; empty means it is consistent.

    With ``against_checkout`` the report must also describe THIS checkout: the
    recorded commit equals ``HEAD`` and every recorded file hash equals the
    file on disk. Without it, only internal consistency is checked.
    """
    problems = []
    if report.get("schema") != SCHEMA:
        problems.append("unexpected schema")
    if report.get("production_activation") is not False:
        problems.append("production_activation must be false")
    if report.get("live_provider") is not False:
        problems.append("a fixture report must not claim a live provider")
    if report.get("live_test") != "PENDING":
        problems.append("the live test is not part of this report and must stay PENDING")
    items = report.get("cases")
    if not isinstance(items, list):
        return problems + ["cases missing"]
    if report.get("summary") != summarize(items):
        problems.append("stored summary does not match the cases")
    for item in items:
        if item.get("result") not in ("pass", "fail"):
            problems.append(f"case {item.get('id')} has no pass/fail result")
    candidate = report.get("candidate") or {}
    files = candidate.get("files_sha256") or {}
    if sorted(files) != sorted(UNDER_TEST):
        problems.append("candidate does not pin every file under test")
    if against_checkout:
        head = checkout_head()
        if head is None or not candidate.get("git_sha"):
            problems.append("report cannot be bound to a commit (no git HEAD or no recorded sha)")
        elif candidate["git_sha"] != head:
            problems.append(f"report was produced at {candidate['git_sha'][:12]}, checkout is {head[:12]}")
        else:
            dirty = subprocess.run(["git", "-C", str(ROOT), "diff", "--quiet", "HEAD", "--", *UNDER_TEST],
                                   capture_output=True, timeout=10).returncode
            if dirty != 0:
                problems.append("files under test have uncommitted changes, so HEAD does not describe them")
        actual = files_sha256()
        for rel in UNDER_TEST:
            if files.get(rel) != actual[rel]:
                problems.append(f"file hash differs from the checkout: {rel}")
    return problems


def tamper_self_test(report: dict) -> None:
    """Each forgery of a real report must be rejected by --check."""
    bindable = checkout_head() is not None
    check(not validate(report, against_checkout=bindable),
          "the fresh report validates against this checkout" if bindable else
          "the fresh report is internally consistent (no git HEAD to bind to)")
    forgeries = {
        "a summary flipped to PASS over a failed case":
            lambda r: (r["cases"][0].update(result="fail")),
        "a live result claimed": lambda r: r.update(live_test="PASS"),
        "a production activation claimed": lambda r: r.update(production_activation=True),
        "a file hash that does not match the checkout":
            lambda r: r["candidate"]["files_sha256"].update({UNDER_TEST[0]: "0" * 64}),
        "a file under test dropped from the candidate":
            lambda r: r["candidate"]["files_sha256"].pop(UNDER_TEST[-1]),
    }
    if bindable:
        forgeries["a report from another commit"] = lambda r: r["candidate"].update(git_sha="f" * 40)
    for name, forge in forgeries.items():
        forged = json.loads(json.dumps(report))
        forge(forged)
        check(bool(validate(forged, against_checkout=bindable)), f"--check rejects {name}")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--check":
        report = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
        problems = validate(report, against_checkout=True)
        for problem in problems:
            print(f"  INVALID: {problem}")
        status = report.get("summary", {}).get("status")
        print(f"===== T-038 E2E REPORT CHECK: {'OK' if not problems else 'INVALID'} (status {status}) =====")
        return 0 if not problems and status == "PASS" else 1
    report_path = None
    if len(argv) == 2 and argv[0] == "--report":
        report_path = Path(argv[1])
    elif argv:
        print("usage: worker_home_rig_e2e_fixture.py [--report PATH | --check PATH]")
        return 2
    report = run()
    tamper_self_test(report)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"  report: {report_path}")
    print(f"\n===== T-038 HOME ASSISTANT E2E (real wire, fixture HA): {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

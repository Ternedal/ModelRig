"""Standing-grant administration remains loopback-only under every worker setting.

This suite covers both schedules and the T-036 GitHub connector admin surface.
Run: PYTHONPATH=worker python3 tests/worker_schedule_api_guard.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.github_connector_admin import (  # noqa: E402
    _operator_allowed as github_operator_allowed,
    build_github_connector_admin_router,
)
from app.github_connector_contract import GitHubConnectorGrantStore  # noqa: E402
from app.schedule_admin import ScheduleAdmin  # noqa: E402
from app.schedule_api import (  # noqa: E402
    _loopback_operator_allowed,
    build_schedule_router,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def request_from(host):
    client = None if host is None else SimpleNamespace(host=host)
    return SimpleNamespace(client=client)


# Both standing-grant surfaces share the same stronger-than-LAN admission rule.
for name, allowed in (
    ("schedule", _loopback_operator_allowed),
    ("github", github_operator_allowed),
):
    check(allowed(request_from("127.0.0.1")), f"{name}: IPv4 loopback is admitted")
    check(allowed(request_from("::1")), f"{name}: IPv6 loopback is admitted")
    check(allowed(request_from("testclient")), f"{name}: in-process TestClient alias is admitted")
    check(not allowed(request_from("192.168.1.20")), f"{name}: LAN peer is refused")
    check(not allowed(request_from("10.0.0.8")), f"{name}: private network peer is refused")
    check(not allowed(request_from(None)), f"{name}: missing peer identity fails closed")

calls = []


def bomb():
    calls.append("resource")
    raise AssertionError("guarded request must not reach a store or registry")


admin = ScheduleAdmin(
    store_factory=bomb,
    registry_factory=bomb,
)
app = FastAPI()
app.include_router(build_schedule_router(admin, operator_allowed=lambda _request: False))
client = TestClient(app)

old_allow_lan = os.environ.get("KALIV_WORKER_ALLOW_LAN")
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
try:
    status = client.get("/schedules/status")
    check(status.status_code == 403, "status is refused to a non-local operator")
    preview = client.post(
        "/schedules/preview",
        json={"tool": "anything", "args": {}, "cadence": "every:60"},
    )
    check(preview.status_code == 403, "schedule writes remain refused even when worker LAN access is enabled")
    check("loopback-only" in preview.json()["detail"], "schedule refusal explains the stronger local-only boundary")
    check(not calls, "schedule admission happens before any registry or SQLite resource is opened")

    github_calls = []

    def github_bomb():
        github_calls.append("store")
        raise AssertionError("refused GitHub admin request opened its grant store")

    def account_bomb():
        github_calls.append("account")
        raise AssertionError("refused GitHub admin request inspected credential config")

    github_guard_app = FastAPI()
    github_guard_app.include_router(
        build_github_connector_admin_router(
            grant_factory=github_bomb,
            account_provider=account_bomb,
            operator_allowed=lambda _request: False,
        )
    )
    github_guard_client = TestClient(github_guard_app)
    denied_preview = github_guard_client.post(
        "/github-connector/grants/preview",
        json={"repositories": ["Ternedal/ModelRig"], "operations": ["issue"]},
    )
    check(denied_preview.status_code == 403,
          "GitHub grant administration stays loopback-only when worker LAN access is enabled")
    check("loopback-only" in denied_preview.json()["detail"],
          "GitHub refusal explains the stronger local-only boundary")
    check(not github_calls,
          "GitHub admission happens before credential config or SQLite is opened")
finally:
    if old_allow_lan is None:
        os.environ.pop("KALIV_WORKER_ALLOW_LAN", None)
    else:
        os.environ["KALIV_WORKER_ALLOW_LAN"] = old_allow_lan


# T-036 operator flow: configured account is authority; caller chooses only
# exact repositories + documented read operations and confirms the preview hash.
with tempfile.TemporaryDirectory(prefix="kaliv-github-admin-") as temp:
    db_path = os.path.join(temp, "grants.db")

    def grant_factory():
        return GitHubConnectorGrantStore(db_path)

    github_app = FastAPI()
    github_app.include_router(
        build_github_connector_admin_router(
            grant_factory=grant_factory,
            account_provider=lambda: "Ternedal",
        )
    )
    github = TestClient(github_app)

    scope_req = {
        "repositories": ["Ternedal/ModelRig"],
        "operations": ["issue", "pull_request"],
    }
    preview = github.post("/github-connector/grants/preview", json=scope_req)
    check(preview.status_code == 200, "GitHub grant preview succeeds on exact documented scope")
    preview_body = preview.json()
    digest = preview_body.get("scope_sha256")
    check(preview_body.get("grant_persisted") is False and preview_body.get("production_activation") is False,
          "preview is non-mutating and cannot activate production")
    check(preview_body.get("scope", {}).get("account") == "ternedal" and
          preview_body.get("scope", {}).get("repositories") == ["ternedal/modelrig"],
          "configured credential account + repository are canonicalized by the authority")
    check(isinstance(digest, str) and len(digest) == 64,
          "preview exposes the canonical scope digest the create action must bind")

    store = grant_factory()
    try:
        check(store.list_grants() == (), "preview persisted no grant row")
    finally:
        store.close()

    wrong_digest = github.post(
        "/github-connector/grants",
        json={**scope_req, "expected_scope_sha256": "0" * 64},
    )
    check(wrong_digest.status_code == 409,
          "create rejects a stale/wrong preview digest before persistence")
    store = grant_factory()
    try:
        check(store.list_grants() == (), "wrong preview digest leaves zero grants")
    finally:
        store.close()

    spoofed = github.post(
        "/github-connector/grants",
        json={
            **scope_req,
            "expected_scope_sha256": digest,
            "account": "attacker",
            "actor": "model",
        },
    )
    check(spoofed.status_code == 422,
          "caller cannot spoof credential account or audit actor through extra fields")

    created = github.post(
        "/github-connector/grants",
        json={**scope_req, "expected_scope_sha256": digest},
    )
    check(created.status_code == 200, "preview-bound GitHub grant is persisted")
    grant = created.json().get("grant", {})
    grant_id = grant.get("grant_id")
    check(grant.get("created_by") == "loopback-operator" and grant.get("status") == "active",
          "grant provenance is fixed to the admitted operator path, not caller text")
    check(grant.get("scope_sha256") == digest and grant.get("production_activation") is False,
          "persisted grant exactly matches preview scope and remains non-production")

    # A second scope that intersects repo+operation would make github_read
    # ambiguous. Operator creation blocks that normal path instead of relying on
    # runtime ambiguity handling as the first line of defence.
    overlap_req = {
        "repositories": ["ternedal/modelrig"],
        "operations": ["issue"],
    }
    overlap_preview = github.post("/github-connector/grants/preview", json=overlap_req).json()
    overlap = github.post(
        "/github-connector/grants",
        json={**overlap_req, "expected_scope_sha256": overlap_preview["scope_sha256"]},
    )
    check(overlap.status_code == 409 and "overlaps" in overlap.json().get("detail", ""),
          "overlapping active authority is refused before it can make reads ambiguous")

    wrong_revoke = github.post(
        f"/github-connector/grants/{grant_id}/revoke",
        json={"expected_scope_sha256": "f" * 64, "confirm_revoke": True},
    )
    check(wrong_revoke.status_code == 409,
          "revoke refuses a grant whose visible scope no longer matches confirmation")
    store = grant_factory()
    try:
        check(store.get(grant_id).active, "wrong revoke digest leaves grant active")
    finally:
        store.close()

    missing_confirm = github.post(
        f"/github-connector/grants/{grant_id}/revoke",
        json={"expected_scope_sha256": digest, "confirm_revoke": False},
    )
    check(missing_confirm.status_code == 422,
          "revocation requires an explicit literal confirmation, not generic truthy input")

    revoked = github.post(
        f"/github-connector/grants/{grant_id}/revoke",
        json={"expected_scope_sha256": digest, "confirm_revoke": True},
    )
    check(revoked.status_code == 200 and revoked.json().get("revoked_now") is True,
          "confirmed operator revocation transitions the durable grant")
    revoked_grant = revoked.json().get("grant", {})
    check(revoked_grant.get("status") == "revoked" and
          revoked_grant.get("revoked_by") == "loopback-operator",
          "revoked grant carries durable operator provenance")
    first_revoked_at = revoked_grant.get("revoked_at")

    revoked_again = github.post(
        f"/github-connector/grants/{grant_id}/revoke",
        json={"expected_scope_sha256": digest, "confirm_revoke": True},
    )
    check(revoked_again.status_code == 200 and revoked_again.json().get("revoked_now") is False,
          "repeat revoke is idempotent rather than manufacturing a second transition")
    check(revoked_again.json().get("grant", {}).get("revoked_at") == first_revoked_at,
          "idempotent revoke preserves the original revocation timestamp")

    # Once old authority is revoked, the same exact scope can be granted anew;
    # the new grant gets a fresh id and the runtime sees one active match.
    recreated = github.post(
        "/github-connector/grants",
        json={**scope_req, "expected_scope_sha256": digest},
    )
    check(recreated.status_code == 200 and recreated.json().get("grant", {}).get("grant_id") != grant_id,
          "revoked authority can be deliberately re-granted as a fresh durable grant")

    unknown = github.post(
        "/github-connector/grants/ghg_00000000000000000000000000000000/revoke",
        json={"expected_scope_sha256": digest, "confirm_revoke": True},
    )
    check(unknown.status_code == 404, "unknown grant revocation is explicit, never reported green")

print(f"\n===== STANDING-GRANT API GUARD: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

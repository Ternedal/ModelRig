"""The audit log must record every gate outcome -- especially the refusals.

An audit trail that logs what ran but not what was REFUSED is not an audit
trail; it is a success log. For ordinary writes that is already a gap worth
closing, and for the coming desktop actions it is the whole point: when a
click is blocked, expired, or denied, "what was refused, against what, and
why" is exactly what you need to see afterward.

These tests drive the gate through each outcome and assert a row lands with
the right outcome word, the tool's real risk, and the origin -- and that the
confirmation card shows the tool's own risk rather than a hardcoded one.

Run: PYTHONPATH=worker python3 tests/worker_audit.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

_tmp = tempfile.mkdtemp(prefix="kaliv-audit-")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
os.environ["KALIV_TOOLS_STATE"] = os.path.join(_tmp, "state.json")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "docs")
os.environ["KALIV_GITHUB_CONNECTOR_DB"] = os.path.join(_tmp, "github-grants.db")
os.environ["KALIV_GITHUB_CONNECTOR_AUDIT_DB"] = os.path.join(_tmp, "github-audit.db")

from app import tools as T  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def gate() -> T.ToolGate:
    return T.ToolGate(audit=T.AuditLog(os.environ["KALIV_AUDIT_DB"]))


def last(g: T.ToolGate) -> dict:
    rows = g.audit.recent(limit=1)
    return rows[0] if rows else {}


def denied(fn, *a, **k):
    try:
        fn(*a, **k)
        return None
    except T.ToolDenied as e:
        return str(e)


# --- refusals must leave a trace --------------------------------------------

g = gate()
denied(g.propose, "no_such_tool", {}, conversation_id="c1")
row = last(g)
check(row.get("outcome") == "blocked", "an unknown tool is recorded as blocked, not dropped")
check(row.get("tool") == "no_such_tool", "the refused tool is named in the row")

g.set_enabled(False)
denied(g.propose, "rig_status", {}, conversation_id="c2")
check(last(g).get("outcome") == "blocked", "a proposal to a DISABLED tool layer is recorded")
g.set_enabled(True)

g.set_enabled(False, tool="note_append")
denied(g.propose, "note_append", {"text": "x"}, conversation_id="c3")
row = last(g)
check(row.get("outcome") == "blocked", "a disabled single tool is recorded as blocked")
check(row.get("risk") == "write", "the row carries the tool's REAL risk, not a guess")
g.set_enabled(True, tool="note_append")

# --- the human's decision is the interesting part ---------------------------

g = gate()
p = g.propose("note_append", {"text": "audit probe"}, conversation_id="c4")
check(p.get("status") == "confirmation_required", "a write parks for confirmation")
check(p.get("risk") == "write", "the card shows the tool's own risk (not hardcoded)")

g.confirm(p["confirmation_id"], "deny")
row = last(g)
check(row.get("outcome") == "denied",
      "a REFUSED action is recorded -- the whole point of an audit trail")
check(row.get("conversation_id") == "c4", "the refusal is tied to the conversation it came from")

p = g.propose("note_append", {"text": "audit probe 2"}, conversation_id="c5")
g.confirm(p["confirmation_id"], "approve")
check(last(g).get("outcome") == "executed", "an approved action is recorded as executed")

# --- origin is part of the story --------------------------------------------

g = gate()
p = g.propose("note_append", {"text": "from cloud"}, conversation_id="c7", origin="cloud")
check(p.get("origin") == "cloud", "the card says who asked")
check("Cloud-modellen foreslår" in p.get("summary", ""),
      "a cloud suggestion is labelled as one on the card the human approves")
g.confirm(p["confirmation_id"], "deny")
check(last(g).get("origin") == "cloud", "the audit row keeps the origin of a refused action")

# --- the desktop class rides the same rails ---------------------------------

probe = T.Tool(name="_audit_probe_click", description="probe", risk="desktop",
               run=lambda a: "clicked")
T.REGISTRY[probe.name] = probe
try:
    g = gate()
    p = g.propose(probe.name, {"x": 10, "y": 20}, conversation_id="c8")
    check(p.get("status") == "confirmation_required",
          "a desktop action parks for confirmation like a write")
    check(p.get("risk") == "desktop",
          "the card shows risk=desktop -- a click is NOT a write and must not be labelled one")
    g.confirm(p["confirmation_id"], "deny")
    row = last(g)
    check(row.get("outcome") == "denied" and row.get("risk") == "desktop",
          "a refused desktop action lands in the audit with its own risk class")
finally:
    del T.REGISTRY[probe.name]

check(all(t.risk != "desktop" for t in T.REGISTRY.values()),
      "the probe is gone: no real tool declares desktop yet")

# --- egress classes (F-208): where a RESULT may travel ----------------------
# Risk gates the action; sensitivity gates the answer. list_documents is the
# case in one line: a harmless read that hands your document names to whoever
# asked -- including a cloud model, with no card and nothing said out loud.

check(T.may_egress("public"), "public results travel freely")
check(T.may_egress("operational"), "operational results travel (today's documented behaviour)")
check(not T.may_egress("private"), "private needs consent")
check(T.may_egress("private", consent=True), "consent unlocks private")
check(not T.may_egress("secret", consent=True),
      "consent CANNOT unlock a secret -- that is what makes it one")

check(T.REGISTRY["list_documents"].sensitivity == "private",
      "list_documents is private: it returns YOUR document names")
check(T.REGISTRY["current_datetime"].sensitivity == "public", "the clock is public")
check(T.REGISTRY["rig_status"].sensitivity == "operational", "rig state is operational")
check(all(t.sensitivity in ("public", "operational", "private", "secret")
          for t in T.REGISTRY.values()),
      "every registered tool is classified explicitly -- no tool inherits a default nobody chose")

# secret is enforced NOW, though nothing is secret yet: the rule exists before
# the tool that needs it, not after.
vault = T.Tool(name="_audit_probe_vault", description="probe", risk="read",
               sensitivity="secret", run=lambda a: "hunter2")
T.REGISTRY[vault.name] = vault
try:
    g = gate()
    msg = denied(g.propose, vault.name, {}, conversation_id="c9", origin="cloud")
    check(msg is not None and "aldrig" in msg,
          "a secret-returning tool refuses a CLOUD origin, gate flag or not")
    check(last(g).get("outcome") == "blocked", "the refused egress is in the audit")
    out = g.propose(vault.name, {}, conversation_id="c10", origin="local")
    check(out.get("status") == "executed", "the same tool runs fine for a LOCAL model")
finally:
    del T.REGISTRY[vault.name]

# private stays open until Anders decides #6 -- dormant, not silently changed
g = gate()
out = g.propose("list_documents", {}, conversation_id="c11", origin="cloud")
check(out.get("status") == "executed",
      "with the gate off, cloud reads behave exactly as documented today")

os.environ["KALIV_EGRESS_GATE"] = "1"
try:
    g = gate()
    msg = denied(g.propose, "list_documents", {}, conversation_id="c12", origin="cloud")
    check(msg is not None and "samtykke" in msg,
          "with the gate ON, a cloud model is refused your document names")
    check(g.propose("rig_status", {}, conversation_id="c13", origin="cloud").get("status") == "executed",
          "the gate refuses PRIVATE results, not everything -- rig state still answers")
finally:
    os.environ.pop("KALIV_EGRESS_GATE", None)

check(not T.egress_gate_enabled(), "the gate is OFF by default -- #6 is Anders' call, not a quiet default")

# --- pre-approved scheduled writes: the ONE way past a confirmation card ----
# The scheduler cannot park a write for a card at 03:00 -- nobody would answer
# and it would expire before morning. So Anders approves it when he creates the
# schedule, and that approval travels as a fingerprint. This is the narrowest
# door in the system and it gets pushed on from four sides.

from app.scheduler import fingerprint as _fp  # noqa: E402

_args = {"text": "morgenlog"}
_ok = _fp("note_append", _args)

g = gate()
out = g.propose("note_append", _args, conversation_id="sch1", origin="schedule", pre_approved=_ok)
check(out.get("result") is not None,
      "a scheduled write WITH its approval runs -- no card, because there is nobody to show it to")
row = last(g)
check(row.get("outcome") == "executed" and row.get("origin") == "schedule",
      "the run is audited as a scheduled execution")
check(row.get("confirmation_id") == f"schedule:{_ok[:12]}",
      "the audit names the APPROVAL it ran under -- 'who allowed this at 03:00' has an answer")

msg = denied(g.propose, "note_append", {"text": "noget helt andet"},
             conversation_id="sch2", origin="schedule", pre_approved=_ok)
check(msg is not None and "anden handling" in msg,
      "the same approval on different arguments is refused: he approved THAT action")
check(last(g).get("outcome") == "blocked", "and the refused attempt is in the trail")

msg = denied(g.propose, "note_append", _args, conversation_id="sch3",
             origin="cloud", pre_approved=_ok)
check(msg is not None and "planlagte" in msg,
      "a CLOUD model cannot carry a pre-approval -- that would launder a write past its own card")

probe = T.Tool(name="_audit_probe_click2", description="probe", risk="desktop",
               run=lambda a: "clicked")
T.REGISTRY[probe.name] = probe
try:
    msg = denied(g.propose, probe.name, {"x": 1}, conversation_id="sch4",
                 origin="schedule", pre_approved=_fp(probe.name, {"x": 1}))
    check(msg is not None and "forhåndsgodkendes" in msg,
          "a desktop action can never be pre-approved: the screen it would land on does not exist yet")
finally:
    del T.REGISTRY[probe.name]

g.set_enabled(False)
msg = denied(g.propose, "note_append", _args, conversation_id="sch5",
             origin="schedule", pre_approved=_ok)
check(msg is not None, "the kill-switch beats a pre-approval -- schedules are what must stop first")
g.set_enabled(True)

# --- T-036 GitHub pilot: external READ still requires a fresh card -----------
# The connector has its own durable scope/revocation authority. ToolGate owns
# the human confirmation because network=public. The two authorities must both
# remain true when the read actually executes.

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from app import github_connector_tool as GH  # noqa: E402
from app.github_connector_client import GitHubReadResult  # noqa: E402
from app.github_connector_contract import (  # noqa: E402
    GitHubConnectorGrantStore,
    GitHubConnectorScope,
    GitHubSourceReceipt,
)


class _FakeGitHubReader:
    account = "ternedal"

    def __init__(self, grants):
        self.grants = grants
        self.calls = []

    def read(self, grant_id, *, repository, operation, object_id=None, now):
        self.calls.append((grant_id, repository, operation, object_id, now))
        grant = self.grants.authorize(
            grant_id, repository=repository, operation=operation
        )
        stable_object = str(object_id) if object_id is not None else "1287914122"
        document = {
            "id": object_id or 1287914122,
            "number": object_id,
            "title": "T-036 fixture",
            "state": "open",
            "body": "THIS PRIVATE BODY MUST NOT ENTER THE PILOT PROJECTION",
            "user": {"login": "Ternedal"},
        }
        source = GitHubSourceReceipt(
            grant_id=grant.grant_id,
            scope_sha256=grant.scope.digest,
            repository=repository,
            repository_id=1287914122,
            object_type=operation,
            object_id=stable_object,
            revision="sha256:fixture-revision",
            retrieved_at=now,
        )
        return GitHubReadResult(
            repository=repository,
            operation=operation,
            object_id=stable_object,
            document=document,
            source=source,
            revalidated_cache=False,
        )


class _NoMountApp:
    def include_router(self, *_args, **_kwargs):
        raise AssertionError("default-off registration must not mount a router")


os.environ.pop("KALIV_GITHUB_CONNECTOR_PILOT", None)
check(not GH.register_github_connector_pilot(_NoMountApp()),
      "GitHub connector pilot is absent by default -- import alone grants no network capability")
check("github_read" not in T.REGISTRY,
      "default-off GitHub pilot does not advertise a model-visible tool")

grant_path = os.path.join(_tmp, "github-pilot-grants.db")
connector_audit_path = os.path.join(_tmp, "github-pilot-audit.db")
grants = GitHubConnectorGrantStore(grant_path)
scope = GitHubConnectorScope(
    account="Ternedal",
    repositories=("Ternedal/ModelRig",),
    operations=("issue",),
)
grant = grants.create(scope, actor="Anders", now=100)
connector_audit = GH.GitHubConnectorAuditLog(connector_audit_path)
reader = _FakeGitHubReader(grants)
runtime = GH.GitHubConnectorPilotRuntime(
    grants=grants,
    reader=reader,
    audit=connector_audit,
    now=lambda: 200,
)
github_tool = GH.build_github_read_tool(runtime)
check(github_tool.risk == "read" and github_tool.network == "public",
      "github_read is a read whose ACTION explicitly crosses the public network")
check(github_tool.sensitivity == "private" and github_tool.idempotent is False,
      "GitHub result is private and the metered/fresh external read is not declared replayable")
check(not github_tool.schedulable,
      "GitHub pilot cannot be pre-approved for unattended scheduled execution")
check(set(github_tool.params["properties"]["operation"]["enum"]) ==
      {"repository", "issue", "pull_request", "workflow_run"},
      "model schema contains only the four documented read operations -- no mutation verbs")

T.REGISTRY[github_tool.name] = github_tool
try:
    g = gate()
    g.set_enabled(True)
    gh_args = {
        "repository": "Ternedal/ModelRig",
        "operation": "issue",
        "object_id": 83,
    }
    proposal = g.propose("github_read", gh_args, conversation_id="gh1", origin="local")
    check(proposal.get("status") == "confirmation_required" and proposal.get("risk") == "read",
          "public-network GitHub READ parks for a human card even though risk=read")
    check(reader.calls == [],
          "proposal/confirmation card performs ZERO GitHub reader calls")

    executed = g.confirm(proposal["confirmation_id"], "approve")
    check(executed.get("status") == "executed" and len(reader.calls) == 1,
          "approved card executes exactly one scope-bound GitHub read")
    wrapped = executed.get("result", "")
    check('"connector":"github"' in wrapped and '"title":"T-036 fixture"' in wrapped,
          "approved result carries a bounded GitHub projection back as tool data")
    check("THIS PRIVATE BODY" not in wrapped,
          "pilot projection excludes issue/PR body content instead of mirroring arbitrary private text")
    connector_row = connector_audit.recent(limit=1)[0]
    check(connector_row.get("connector") == "github" and connector_row.get("repository") == "ternedal/modelrig",
          "connector audit records explicit connector identity + canonical repository -- never inferred from origin")
    check(connector_row.get("grant_id") == grant.grant_id and
          connector_row.get("scope_sha256") == scope.digest and
          connector_row.get("revision") == "sha256:fixture-revision",
          "connector audit binds the exact durable grant/scope and returned revision")
    check(connector_row.get("outcome") == "executed" and connector_row.get("detail") == "fresh_remote_read",
          "successful connector read has a categorical privacy-safe outcome/detail")
    check(last(g).get("tool") == "github_read" and last(g).get("outcome") == "executed",
          "generic ToolGate audit and connector-specific evidence both exist for the same execution")

    # Revoke AFTER the card was shown but BEFORE approval. The card is not an
    # authority snapshot: runtime re-reads current durable grants at execution.
    proposal = g.propose("github_read", gh_args, conversation_id="gh2", origin="local")
    before_calls = len(reader.calls)
    grants.revoke(grant.grant_id, actor="Anders", now=201)
    msg = denied(g.confirm, proposal["confirmation_id"], "approve")
    check(msg is not None and "ingen aktiv tilladelse" in msg,
          "revocation between proposal and approval stops the new GitHub call")
    check(len(reader.calls) == before_calls,
          "revoked scope makes ZERO reader/transport calls after confirmation")
    revoked_row = connector_audit.recent(limit=1)[0]
    check(revoked_row.get("outcome") == "blocked" and revoked_row.get("detail") == "no_active_exact_grant",
          "revoked attempt is explicit connector-audit evidence, not a missing/green read")
    check(revoked_row.get("grant_id") == grant.grant_id and revoked_row.get("scope_sha256") == scope.digest,
          "blocked revoked attempt still identifies the historical grant/scope that was withdrawn")

    # Multiple active grants for the same scope are refused rather than picking
    # one nondeterministically and making later revocation/audit ambiguous.
    grants.create(scope, actor="Anders", now=202)
    grants.create(scope, actor="Anders", now=203)
    proposal = g.propose("github_read", gh_args, conversation_id="gh3", origin="local")
    before_calls = len(reader.calls)
    msg = denied(g.confirm, proposal["confirmation_id"], "approve")
    check(msg is not None and "flere aktive tilladelser" in msg,
          "ambiguous duplicate active scopes fail closed")
    check(len(reader.calls) == before_calls,
          "ambiguous grants make ZERO reader/transport calls")
    check(connector_audit.recent(limit=1)[0].get("detail") == "ambiguous_active_exact_grants",
          "ambiguous authority has its own explicit connector-audit reason")

    # Operator view is read-only + loopback-only by construction. TestClient is
    # deliberately admitted as the same convention used by Control Center.
    operator_app = FastAPI()
    operator_app.include_router(
        GH.build_github_connector_router(
            grant_factory=lambda: GitHubConnectorGrantStore(grant_path),
            audit_factory=lambda: GH.GitHubConnectorAuditLog(connector_audit_path),
        )
    )
    client = TestClient(operator_app)
    response = client.get(
        "/github-connector/audit",
        params={"repository": "Ternedal/ModelRig", "operation": "issue", "limit": 10},
    )
    check(response.status_code == 200 and response.json().get("connector") == "github",
          "loopback operator audit route exposes the explicit connector ledger")
    check(all(entry.get("repository") == "ternedal/modelrig" for entry in response.json().get("entries", [])),
          "operator audit filtering is exact on repository scope")
    grants_response = client.get("/github-connector/grants", params={"include_revoked": True})
    check(grants_response.status_code == 200 and grants_response.json().get("production_activation") is False,
          "operator grant view remains observability-only with production activation false")
finally:
    del T.REGISTRY[github_tool.name]
    connector_audit.close()
    grants.close()

print(f"\n===== WORKER AUDIT: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

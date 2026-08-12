"""Read-tool contracts plus dormant T-036 GitHub read-client evidence.

Run: PYTHONPATH=worker python3 tests/worker_tools_readtools.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import uuid

_tmp = tempfile.mkdtemp(prefix="kaliv-readtools-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

from app import tools as T  # noqa: E402
from app.github_connector_client import (  # noqa: E402
    GITHUB_API_ORIGIN,
    GitHubReadClient,
    GitHubReadContractError,
    GitHubReadDenied,
    GitHubReadRateLimited,
    GitHubReadRemoteError,
    GitHubTransportRequest,
    GitHubTransportResponse,
)
from app.github_connector_contract import (  # noqa: E402
    GitHubConnectorDenied,
    GitHubConnectorGrantStore,
    GitHubConnectorScope,
)

passed = failed = 0


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def rejects(fn, expected, name):
    try:
        fn()
    except expected:
        check(True, name)
    else:
        check(False, name)


def fresh_gate():
    g = T.ToolGate(audit=T.AuditLog(os.environ["KALIV_AUDIT_DB"]))
    g.enabled = True
    return g


# Existing read tools: schema, immediate execution and no required args.
schema_names = {s["function"]["name"] for s in T.ollama_tool_schema(fresh_gate())}
check("list_models" in schema_names, "list_models exposed in the Ollama tool schema")
check("current_datetime" in schema_names, "current_datetime exposed in the Ollama tool schema")

g = fresh_gate()
res = g.propose("current_datetime", {})
check(res.get("status") != "confirmation_required", "current_datetime is NOT gated (runs immediately)")
out = res.get("result", "")
check(str(time.localtime().tm_year) in out, f"current_datetime includes the current year: {out!r}")
check(any(m in out for m in T._MONTHS_DA), f"current_datetime is phrased in Danish: {out!r}")

g = fresh_gate()
res = g.propose("list_models", {})
check(res.get("status") != "confirmation_required", "list_models is NOT gated (runs immediately)")
out = res.get("result", "")
check(isinstance(out, str) and len(out) > 0, f"list_models returns non-empty text: {out[:60]!r}")

for name in ("list_models", "current_datetime"):
    tool = T.REGISTRY[name]
    check(not (tool.params or {}).get("required"), f"{name} takes no required args")


# T-036 fixed-origin read client. The fake transport sees exactly what a future
# credential/socket adapter would receive; there is deliberately no token field.
class QueueTransport:
    def __init__(self, *items):
        self.items = list(items)
        self.requests = []

    def get(self, request):
        self.requests.append(request)
        if not self.items:
            raise AssertionError("unexpected GitHub transport call")
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def response(document=None, *, status=200, headers=None):
    body = b"" if document is None else json.dumps(document, separators=(",", ":")).encode()
    values = {"etag": 'W/"fixture-v1"', "x-ratelimit-remaining": "4999", "x-ratelimit-reset": "2000"}
    if headers:
        values.update(headers)
    return GitHubTransportResponse(status=status, headers=values, body=body)


def grant_store(*, operations=("repository", "issue", "pull_request", "workflow_run")):
    store = GitHubConnectorGrantStore(":memory:", uuid_factory=lambda: uuid.UUID(int=42))
    scope = GitHubConnectorScope(
        account="Ternedal",
        repositories=("Ternedal/ModelRig",),
        operations=operations,
    )
    grant = store.create(scope, actor="Anders", now=100)
    return store, grant


store, gh = grant_store()
repo_transport = QueueTransport(
    response({"id": 1287914122, "full_name": "Ternedal/ModelRig", "private": False})
)
repo_client = GitHubReadClient(grants=store, transport=repo_transport)
repo_result = repo_client.read(
    gh.grant_id,
    repository="TERNEDAL/ModelRig",
    operation="repository",
    now=1000,
)
repo_request = repo_transport.requests[0]
check(repo_request.origin == GITHUB_API_ORIGIN, "GitHub client origin is fixed to api.github.com")
check(repo_request.url == "https://api.github.com/repos/ternedal/modelrig", "repository path is canonical and fixed-origin")
header_names = {name for name, _ in repo_request.headers}
check("authorization" not in header_names and "cookie" not in header_names, "credential headers are absent from client request surface")
check(repo_result.source.repository_id == 1287914122, "repository result binds stable repository id")
check(repo_result.source.object_id == "1287914122", "repository result binds stable object id")
check(repo_result.source.revision.startswith("etag-sha256:"), "repository revision binds hashed ETag")
check(repo_result.revalidated_cache is False, "fresh GitHub response is not labeled cache revalidation")

issue_transport = QueueTransport(
    response(
        {
            "id": 3001,
            "repository_id": 1287914122,
            "number": 88,
            "repository_url": "https://api.github.com/repos/ternedal/modelrig",
            "title": "Control Center",
            "state": "open",
        }
    )
)
issue_client = GitHubReadClient(grants=store, transport=issue_transport)
issue_result = issue_client.read(
    gh.grant_id,
    repository="ternedal/modelrig",
    operation="issue",
    object_id=88,
    now=1001,
)
check(issue_transport.requests[0].path == "/repos/ternedal/modelrig/issues/88", "issue read builds documented single-object path")
check(issue_result.source.object_id == "88", "issue source binds requested number")

pr_sha = "a" * 40
pr_transport = QueueTransport(
    response(
        {
            "id": 4001,
            "number": 497,
            "title": "GitHub connector contract",
            "base": {"repo": {"id": 1287914122, "full_name": "Ternedal/ModelRig"}},
            "head": {"sha": pr_sha},
        }
    )
)
pr_client = GitHubReadClient(grants=store, transport=pr_transport)
pr_result = pr_client.read(
    gh.grant_id,
    repository="ternedal/modelrig",
    operation="pull_request",
    object_id=497,
    now=1002,
)
check(pr_transport.requests[0].path == "/repos/ternedal/modelrig/pulls/497", "PR read builds documented single-object path")
check(pr_result.source.revision.startswith(f"sha:{pr_sha}+etag-sha256:"), "PR source binds head SHA and representation ETag")

run_sha = "b" * 40
run_transport = QueueTransport(
    response(
        {
            "id": 31503718139,
            "name": "ci",
            "status": "completed",
            "conclusion": "success",
            "head_sha": run_sha,
            "repository": {"id": 1287914122, "full_name": "Ternedal/ModelRig"},
        }
    )
)
run_client = GitHubReadClient(grants=store, transport=run_transport)
run_result = run_client.read(
    gh.grant_id,
    repository="ternedal/modelrig",
    operation="workflow_run",
    object_id=31503718139,
    now=1003,
)
check(run_transport.requests[0].path == "/repos/ternedal/modelrig/actions/runs/31503718139", "workflow-run read builds documented path")
check(run_result.source.revision.startswith(f"sha:{run_sha}+etag-sha256:"), "workflow source binds head SHA and ETag")

# Revalidation is explicit. A 304 without exact prior cache evidence is an error;
# a 304 after a 200 may reuse only that exact cache key and emits a fresh source
# timestamp rather than silently presenting stale data after a network failure.
cache_transport = QueueTransport(
    response({"id": 1287914122, "full_name": "Ternedal/ModelRig"}),
    response(None, status=304),
)
cache_client = GitHubReadClient(grants=store, transport=cache_transport)
first_cached = cache_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1100)
second_cached = cache_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1101)
check(dict(cache_transport.requests[1].headers).get("if-none-match") == 'W/"fixture-v1"', "cache revalidation sends only trusted If-None-Match")
check(second_cached.revalidated_cache is True, "304 is explicitly labeled revalidated cache")
check(second_cached.document == first_cached.document, "304 reuses only exact cached representation")
check(second_cached.source.retrieved_at == 1101, "revalidation emits current retrieval evidence")

miss_transport = QueueTransport(response(None, status=304))
miss_client = GitHubReadClient(grants=store, transport=miss_transport)
rejects(
    lambda: miss_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1102),
    GitHubReadRemoteError,
    "304 without exact cache fails closed",
)

stale_transport = QueueTransport(
    response({"id": 1287914122, "full_name": "Ternedal/ModelRig"}),
    TimeoutError("fixture transport timeout"),
)
stale_client = GitHubReadClient(grants=store, transport=stale_transport)
stale_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1103)
rejects(
    lambda: stale_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1104),
    TimeoutError,
    "transport failure never silently falls back to stale cache",
)

# Rate-limit and pagination are deterministic rather than inferred from bodies.
rate_transport = QueueTransport(
    response(None, status=403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "2222"})
)
rate_client = GitHubReadClient(grants=store, transport=rate_transport)
try:
    rate_client.read(gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1200)
except GitHubReadRateLimited as exc:
    check(exc.reset_at == 2222, "rate limit carries strict reset timestamp")
else:
    check(False, "rate-limited GitHub response is rejected")

bad_rate_transport = QueueTransport(
    response({"id": 1287914122, "full_name": "Ternedal/ModelRig"}, headers={"x-ratelimit-remaining": "1.0"})
)
rejects(
    lambda: GitHubReadClient(grants=store, transport=bad_rate_transport).read(
        gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1201
    ),
    GitHubReadRemoteError,
    "fractional/string-like rate-limit counter is rejected",
)

page_transport = QueueTransport(
    response(
        {"id": 1287914122, "full_name": "Ternedal/ModelRig"},
        headers={"link": '<https://api.github.com/repos/ternedal/modelrig?page=2>; rel="next"'},
    )
)
rejects(
    lambda: GitHubReadClient(grants=store, transport=page_transport).read(
        gh.grant_id, repository="ternedal/modelrig", operation="repository", now=1202
    ),
    GitHubReadRemoteError,
    "single-object pilot rejects hidden pagination",
)

# Response identity cannot widen the grant. GitHub's issue endpoint can return
# PR objects; the explicit issue operation rejects that ambiguity.
wrong_repo_transport = QueueTransport(
    response(
        {
            "id": 4002,
            "number": 497,
            "base": {"repo": {"id": 999, "full_name": "Other/Repo"}},
            "head": {"sha": "c" * 40},
        }
    )
)
rejects(
    lambda: GitHubReadClient(grants=store, transport=wrong_repo_transport).read(
        gh.grant_id,
        repository="ternedal/modelrig",
        operation="pull_request",
        object_id=497,
        now=1300,
    ),
    GitHubReadRemoteError,
    "cross-repository PR response is rejected",
)

issue_as_pr_transport = QueueTransport(
    response(
        {
            "id": 3002,
            "repository_id": 1287914122,
            "number": 88,
            "repository_url": "https://api.github.com/repos/ternedal/modelrig",
            "pull_request": {"url": "fixture"},
        }
    )
)
rejects(
    lambda: GitHubReadClient(grants=store, transport=issue_as_pr_transport).read(
        gh.grant_id,
        repository="ternedal/modelrig",
        operation="issue",
        object_id=88,
        now=1301,
    ),
    GitHubReadRemoteError,
    "issue operation refuses GitHub PR-shaped issue response",
)

# Invalid selectors and closed header surface fail before any credential/network
# adapter can be invoked.
no_call_transport = QueueTransport()
no_call_client = GitHubReadClient(grants=store, transport=no_call_transport)
rejects(
    lambda: no_call_client.read(
        gh.grant_id,
        repository="ternedal/modelrig",
        operation="issue",
        object_id=0,
        now=1400,
    ),
    GitHubReadContractError,
    "non-positive GitHub object id fails before transport",
)
check(len(no_call_transport.requests) == 0, "invalid object id makes zero transport calls")
rejects(
    lambda: GitHubTransportRequest(
        path="/repos/ternedal/modelrig",
        headers=(
            ("accept", "application/vnd.github+json"),
            ("x-github-api-version", "2022-11-28"),
            ("authorization", "Bearer should-never-be-model-data"),
        ),
    ),
    GitHubReadContractError,
    "Authorization cannot enter generic GitHub client request headers",
)

# Durable revocation is checked before cache or transport on every new read.
rev_store, rev_grant = grant_store(operations=("repository",))
rev_transport = QueueTransport(response({"id": 1287914122, "full_name": "Ternedal/ModelRig"}))
rev_client = GitHubReadClient(grants=rev_store, transport=rev_transport)
rev_store.revoke(rev_grant.grant_id, actor="Anders", now=1500)
rejects(
    lambda: rev_client.read(
        rev_grant.grant_id,
        repository="ternedal/modelrig",
        operation="repository",
        now=1501,
    ),
    GitHubConnectorDenied,
    "revoked connector grant blocks read before transport",
)
check(len(rev_transport.requests) == 0, "revoked grant makes zero GitHub transport calls")

# Missing/private/forbidden responses collapse to one denial class; the client
# does not turn 404 into an existence oracle for repositories outside access.
for status in (401, 403, 404):
    denied_transport = QueueTransport(
        response(None, status=status, headers={"x-ratelimit-remaining": "1"})
    )
    rejects(
        lambda denied_transport=denied_transport: GitHubReadClient(
            grants=store, transport=denied_transport
        ).read(
            gh.grant_id,
            repository="ternedal/modelrig",
            operation="repository",
            now=1600,
        ),
        GitHubReadDenied,
        f"GitHub HTTP {status} collapses to access-unavailable denial",
    )

store.close()
rev_store.close()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
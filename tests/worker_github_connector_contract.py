from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_tmp = tempfile.mkdtemp(prefix="kaliv-github-connector-")
os.environ.setdefault("KALIV_DATA_DIR", _tmp)
sys.path.insert(0, str(ROOT / "worker"))

from app.github_connector_contract import (  # noqa: E402
    GitHubConnectorContractError,
    GitHubConnectorDenied,
    GitHubConnectorGrantStore,
    GitHubConnectorScope,
    GitHubSourceReceipt,
)


def _scope(**overrides) -> GitHubConnectorScope:
    values = {
        "account": "Ternedal",
        "repositories": ("Ternedal/ModelRig", "OpenAI/OpenAI"),
        "operations": ("workflow_run", "issue", "repository", "pull_request"),
    }
    values.update(overrides)
    return GitHubConnectorScope(**values)


def test_scope_is_exact_canonical_and_digest_order_independent() -> None:
    first = _scope()
    second = GitHubConnectorScope(
        account="ternedal",
        repositories=("openai/openai", "ternedal/modelrig"),
        operations=("repository", "issue", "pull_request", "workflow_run"),
    )
    assert first == second
    assert first.repositories == ("openai/openai", "ternedal/modelrig")
    assert first.operations == ("repository", "issue", "pull_request", "workflow_run")
    assert first.digest == second.digest
    assert first.allows("TERNEDAL/ModelRig", "issue") is True
    assert first.allows("ternedal/other", "issue") is False
    assert first.to_dict()["production_activation"] is False


def test_scope_rejects_wildcards_git_suffix_duplicates_and_unknown_operations() -> None:
    invalid = (
        {"repositories": ("Ternedal/*",)},
        {"repositories": ("Ternedal/ModelRig.git",)},
        {"repositories": ("Ternedal/ModelRig", "ternedal/modelrig")},
        {"operations": ("issue", "issue")},
        {"operations": ("issue", "delete_repository")},
        {"repositories": ()},
    )
    for overrides in invalid:
        try:
            _scope(**overrides)
        except GitHubConnectorContractError:
            pass
        else:
            raise AssertionError(f"invalid scope accepted: {overrides!r}")


def test_grant_persists_and_authorization_rechecks_durable_revocation() -> None:
    path = os.path.join(_tmp, "persist.db")
    fixed = uuid.UUID("11111111-2222-3333-4444-555555555555")
    store = GitHubConnectorGrantStore(path, uuid_factory=lambda: fixed)
    grant = store.create(_scope(), actor="Anders", now=100)
    assert grant.grant_id == "ghg_11111111222233334444555555555555"
    assert grant.active is True
    assert store.authorize(
        grant.grant_id, repository="ternedal/modelrig", operation="pull_request"
    ).active is True
    store.close()

    reopened = GitHubConnectorGrantStore(path)
    persisted = reopened.get(grant.grant_id)
    assert persisted is not None
    assert persisted.scope.digest == grant.scope.digest
    revoked = reopened.revoke(grant.grant_id, actor="Anders", now=120)
    assert revoked.active is False
    assert revoked.revoked_at == 120
    assert revoked.revoked_by == "Anders"

    try:
        reopened.authorize(
            grant.grant_id, repository="ternedal/modelrig", operation="pull_request"
        )
    except GitHubConnectorDenied as exc:
        assert "revoked" in str(exc)
    else:
        raise AssertionError("revoked durable grant authorized a new call")

    # Revocation is safe to repeat and does not rewrite the original evidence.
    again = reopened.revoke(grant.grant_id, actor="Other operator", now=130)
    assert again.revoked_at == 120
    assert again.revoked_by == "Anders"
    reopened.close()


def test_authorization_fails_closed_outside_repository_or_operation_scope() -> None:
    store = GitHubConnectorGrantStore(":memory:")
    grant = store.create(
        _scope(
            repositories=("Ternedal/ModelRig",),
            operations=("issue",),
        ),
        actor="Anders",
        now=1,
    )
    for repository, operation in (
        ("Ternedal/Other", "issue"),
        ("Ternedal/ModelRig", "repository"),
    ):
        try:
            store.authorize(
                grant.grant_id,
                repository=repository,
                operation=operation,
            )
        except GitHubConnectorDenied:
            pass
        else:
            raise AssertionError("out-of-scope GitHub read was authorized")
    store.close()


def test_stored_scope_digest_corruption_fails_closed() -> None:
    store = GitHubConnectorGrantStore(":memory:")
    grant = store.create(_scope(), actor="Anders", now=1)
    store._db.execute(  # contract-adversarial: emulate on-disk corruption
        "UPDATE github_connector_grants SET scope_sha256=? WHERE grant_id=?",
        ("0" * 64, grant.grant_id),
    )
    try:
        store.get(grant.grant_id)
    except GitHubConnectorDenied as exc:
        assert "corrupt" in str(exc)
    else:
        raise AssertionError("corrupt durable scope was accepted")
    store.close()


def test_source_receipt_binds_stable_provenance_without_raw_content_or_tokens() -> None:
    store = GitHubConnectorGrantStore(":memory:")
    grant = store.create(_scope(), actor="Anders", now=10)
    receipt = GitHubSourceReceipt(
        grant_id=grant.grant_id,
        scope_sha256=grant.scope.digest,
        repository="Ternedal/ModelRig",
        repository_id=1287914122,
        object_type="pull_request",
        object_id="496",
        revision="3b45eb4080accd94c1139a0154811e7995acdb02",
        retrieved_at=20,
    )
    payload = receipt.to_dict()
    assert payload["connector"] == "github"
    assert payload["repository"] == "ternedal/modelrig"
    assert payload["repository_id"] == 1287914122
    assert payload["object_id"] == "496"
    assert payload["revision"] == "3b45eb4080accd94c1139a0154811e7995acdb02"
    assert payload["production_activation"] is False
    encoded = json.dumps(payload)
    for forbidden in ("token", "authorization", "body", "content", "secret"):
        assert forbidden not in encoded.lower()
    store.close()


def test_contract_rejects_optimistic_activation_and_weak_source_types() -> None:
    try:
        _scope(production_activation=True)
    except GitHubConnectorContractError:
        pass
    else:
        raise AssertionError("production_activation=true was accepted")

    store = GitHubConnectorGrantStore(":memory:")
    grant = store.create(_scope(), actor="Anders", now=10)
    invalid_receipts = (
        {"repository_id": True},
        {"repository_id": 0},
        {"object_id": ""},
        {"revision": "rev with spaces"},
        {"retrieved_at": True},
        {"production_activation": True},
    )
    base = {
        "grant_id": grant.grant_id,
        "scope_sha256": grant.scope.digest,
        "repository": "Ternedal/ModelRig",
        "repository_id": 1287914122,
        "object_type": "issue",
        "object_id": "88",
        "revision": "etag:abc123",
        "retrieved_at": 20,
    }
    for override in invalid_receipts:
        values = dict(base)
        values.update(override)
        try:
            GitHubSourceReceipt(**values)
        except GitHubConnectorContractError:
            pass
        else:
            raise AssertionError(f"invalid source receipt accepted: {override!r}")
    store.close()


TESTS = [
    value
    for name, value in sorted(globals().items())
    if name.startswith("test_")
]

if __name__ == "__main__":
    for test_case in TESTS:
        test_case()
    print(f"github connector contract: {len(TESTS)} passed")

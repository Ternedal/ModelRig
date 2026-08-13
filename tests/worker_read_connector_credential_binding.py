from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import replace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.read_connector_credential_binding import (  # noqa: E402
    CredentialBoundProviderRequest,
    ReadConnectorCredentialBinder,
    ReadConnectorCredentialError,
    ReadConnectorCredentialEvidence,
)
from app.read_connector_package_contract import (  # noqa: E402
    ReadConnectorDenied,
    ReadConnectorGrantStore,
    ReadConnectorScope,
)
from app.read_connector_provider_request import (  # noqa: E402
    ProviderRequestPlan,
    build_drive_document_read,
    build_gmail_message_get,
    build_notion_page_get,
)

passed = failed = 0


def check(cond: bool, label: str) -> None:
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {label}")
    else:
        failed += 1
        print(f"  FAIL: {label}")


def raises(exc_type, fn, contains: str) -> bool:
    try:
        fn()
    except exc_type as exc:
        return contains in str(exc)
    return False


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class FakeCredentials:
    def __init__(
        self,
        *,
        connector: str,
        account_ref: str,
        workspace_ref: str | None = None,
        state: str = "ready",
        expires_at: int | None = 10_000,
        token: str = "t" * 40,
    ) -> None:
        self.connector = connector
        self.account_ref = account_ref
        self.workspace_ref = workspace_ref
        self.state = state
        self.expires_at = expires_at
        self.token = token
        self.token_reads = 0

    def evidence(self, *, now: int) -> ReadConnectorCredentialEvidence:
        kind = "notion_integration_bearer" if self.connector == "notion" else "google_oauth_bearer"
        return ReadConnectorCredentialEvidence(
            connector=self.connector,
            account_ref=self.account_ref,
            workspace_ref=self.workspace_ref,
            credential_kind=kind,
            state=self.state,
            checked_at=now,
            expires_at=self.expires_at,
        )

    def bearer_token(self) -> str:
        self.token_reads += 1
        return self.token


def scope(
    connector: str,
    *,
    account_ref: str,
    object_scope: str,
    operation: str,
    workspace_ref: str | None = None,
) -> ReadConnectorScope:
    return ReadConnectorScope(
        connector=connector,
        account_ref=account_ref,
        workspace_ref=workspace_ref,
        object_scopes=(object_scope,),
        operations=(operation,),
    )


def main() -> int:
    grants = ReadConnectorGrantStore(uuid_factory=UUIDs())
    drive_scope = scope(
        "google_drive",
        account_ref="google-account-1",
        object_scope="doc-7",
        operation="document_read",
    )
    drive_grant = grants.create_grant(drive_scope, actor="Anders", now=1)
    drive_plan = build_drive_document_read(drive_scope, file_id="doc-7")
    drive_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-1",
        token="drive-secret-token-1234567890abcd",
    )
    drive_binder = ReadConnectorCredentialBinder(
        grants=grants,
        credentials=drive_credentials,
    )

    binding = drive_binder.prepare(drive_grant.grant_id, drive_plan, now=100)
    check(isinstance(binding, CredentialBoundProviderRequest), "exact grant + credential prepares one typed binding")
    check(binding.scope_sha256 == drive_scope.digest, "binding pins exact scope digest")
    check(binding.account_ref == "google-account-1", "binding pins exact credential account")
    check(binding.workspace_ref is None, "Google binding carries no workspace authority")
    check(binding.credential_kind == "google_oauth_bearer", "Google binding pins OAuth bearer kind")
    check(binding.production_activation is False, "credential binding remains dormant")
    check(drive_credentials.token_reads == 0, "prepare never loads bearer material")

    audit = binding.to_audit_dict()
    serialized = json.dumps(audit, sort_keys=True)
    check("drive-secret-token" not in serialized, "binding audit contains no bearer material")
    check("body_json" not in audit and "url" not in audit, "binding audit inherits privacy-minimized request identity")
    check(audit["grant_id"] == drive_grant.grant_id, "binding audit records grant authority")
    check(audit["scope_sha256"] == drive_scope.digest, "binding audit records exact scope digest")

    token = drive_binder.trusted_bearer_for_execution(binding, now=101)
    check(token == drive_credentials.token, "execution seam releases the configured bearer only after recheck")
    check(drive_credentials.token_reads == 1, "bearer is loaded only at execution boundary")

    mismatch_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="different-google-account",
    )
    mismatch_binder = ReadConnectorCredentialBinder(grants=grants, credentials=mismatch_credentials)
    check(
        raises(
            ReadConnectorDenied,
            lambda: mismatch_binder.prepare(drive_grant.grant_id, drive_plan, now=110),
            "outside exact active scope",
        ),
        "credential account cannot widen or substitute grant account",
    )
    check(mismatch_credentials.token_reads == 0, "account mismatch never reads token")

    gmail_credentials = FakeCredentials(
        connector="gmail",
        account_ref="google-account-1",
    )
    gmail_binder = ReadConnectorCredentialBinder(grants=grants, credentials=gmail_credentials)
    check(
        raises(
            ReadConnectorDenied,
            lambda: gmail_binder.prepare(drive_grant.grant_id, drive_plan, now=120),
            "credential connector does not match",
        ),
        "credential capability cannot cross connector identity",
    )
    check(gmail_credentials.token_reads == 0, "connector mismatch never reads token")

    expired_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-1",
        state="expired_credentials",
        expires_at=130,
    )
    expired_binder = ReadConnectorCredentialBinder(grants=grants, credentials=expired_credentials)
    check(
        raises(
            ReadConnectorDenied,
            lambda: expired_binder.prepare(drive_grant.grant_id, drive_plan, now=130),
            "expired_credentials",
        ),
        "expired credential state fails closed before preparation",
    )
    check(expired_credentials.token_reads == 0, "expired state never reads token")

    invalid_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-1",
        state="invalid_credentials",
        expires_at=None,
    )
    invalid_binder = ReadConnectorCredentialBinder(grants=grants, credentials=invalid_credentials)
    check(
        raises(
            ReadConnectorDenied,
            lambda: invalid_binder.prepare(drive_grant.grant_id, drive_plan, now=140),
            "invalid_credentials",
        ),
        "invalid credential state is distinct and fail-closed",
    )

    revoke_credentials = FakeCredentials(
        connector="google_drive",
        account_ref="google-account-1",
        token="revoke-secret-token-1234567890abcd",
    )
    revoke_binder = ReadConnectorCredentialBinder(grants=grants, credentials=revoke_credentials)
    revoke_binding = revoke_binder.prepare(drive_grant.grant_id, drive_plan, now=150)
    grants.revoke(
        drive_grant.grant_id,
        expected_scope_sha256=drive_scope.digest,
        actor="Anders",
        now=151,
    )
    check(
        raises(
            ReadConnectorDenied,
            lambda: revoke_binder.trusted_bearer_for_execution(revoke_binding, now=152),
            "missing or revoked",
        ),
        "grant revoke between prepare and execute blocks bearer release",
    )
    check(revoke_credentials.token_reads == 0, "revoked grant is rechecked before token read")
    grants.close()

    grants2 = ReadConnectorGrantStore(uuid_factory=UUIDs())
    notion_scope = scope(
        "notion",
        account_ref="notion-account-1",
        workspace_ref="workspace-main",
        object_scope="page-1",
        operation="page_get",
    )
    notion_grant = grants2.create_grant(notion_scope, actor="Anders", now=200)
    notion_plan = build_notion_page_get(notion_scope, page_id="page-1")
    notion_credentials = FakeCredentials(
        connector="notion",
        account_ref="notion-account-1",
        workspace_ref="workspace-main",
        expires_at=None,
        token="notion-secret-token-1234567890abcd",
    )
    notion_binder = ReadConnectorCredentialBinder(grants=grants2, credentials=notion_credentials)
    notion_binding = notion_binder.prepare(notion_grant.grant_id, notion_plan, now=210)
    check(notion_binding.workspace_ref == "workspace-main", "Notion binding pins exact workspace authority")
    check(notion_binding.credential_kind == "notion_integration_bearer", "Notion binding pins integration bearer kind")

    wrong_workspace = FakeCredentials(
        connector="notion",
        account_ref="notion-account-1",
        workspace_ref="workspace-other",
        expires_at=None,
    )
    wrong_workspace_binder = ReadConnectorCredentialBinder(grants=grants2, credentials=wrong_workspace)
    check(
        raises(
            ReadConnectorDenied,
            lambda: wrong_workspace_binder.prepare(notion_grant.grant_id, notion_plan, now=211),
            "outside exact active scope",
        ),
        "Notion credential workspace cannot substitute scoped workspace",
    )
    check(wrong_workspace.token_reads == 0, "workspace mismatch never reads token")

    gmail_scope = scope(
        "gmail",
        account_ref="google-account-2",
        object_scope="msg-1",
        operation="message_get",
    )
    gmail_grant = grants2.create_grant(gmail_scope, actor="Anders", now=220)
    valid_gmail_plan = build_gmail_message_get(gmail_scope, message_id="msg-1")
    forged_host_plan = ProviderRequestPlan(
        connector="gmail",
        authority_operation=valid_gmail_plan.authority_operation,
        provider_operation=valid_gmail_plan.provider_operation,
        object_scope=valid_gmail_plan.object_scope,
        method="GET",
        host="www.googleapis.com",
        path=valid_gmail_plan.path,
        query=valid_gmail_plan.query,
        headers=valid_gmail_plan.headers,
        body_json=None,
        response_kind="json",
        expected_content_types=("application/json",),
        max_response_bytes=valid_gmail_plan.max_response_bytes,
    )
    gmail_exact_credentials = FakeCredentials(
        connector="gmail",
        account_ref="google-account-2",
    )
    gmail_exact_binder = ReadConnectorCredentialBinder(grants=grants2, credentials=gmail_exact_credentials)
    check(
        raises(
            ReadConnectorCredentialError,
            lambda: gmail_exact_binder.prepare(gmail_grant.grant_id, forged_host_plan, now=221),
            "host does not match connector",
        ),
        "credential boundary rechecks connector-specific provider host",
    )

    changing_credentials = FakeCredentials(
        connector="gmail",
        account_ref="google-account-2",
        token="changing-secret-token-1234567890ab",
    )
    changing_binder = ReadConnectorCredentialBinder(grants=grants2, credentials=changing_credentials)
    changing_binding = changing_binder.prepare(gmail_grant.grant_id, valid_gmail_plan, now=230)
    changing_credentials.account_ref = "google-account-3"
    check(
        raises(
            ReadConnectorDenied,
            lambda: changing_binder.trusted_bearer_for_execution(changing_binding, now=231),
            "identity changed",
        ),
        "credential identity change between prepare and execute fails closed",
    )
    check(changing_credentials.token_reads == 0, "changed credential identity is rejected before token read")

    bad_token = "TOP-SECRET VALUE THAT MUST NEVER APPEAR"
    bad_token_credentials = FakeCredentials(
        connector="gmail",
        account_ref="google-account-2",
        token=bad_token,
    )
    bad_token_binder = ReadConnectorCredentialBinder(grants=grants2, credentials=bad_token_credentials)
    bad_token_binding = bad_token_binder.prepare(gmail_grant.grant_id, valid_gmail_plan, now=240)
    try:
        bad_token_binder.trusted_bearer_for_execution(bad_token_binding, now=241)
    except ReadConnectorCredentialError as exc:
        check(bad_token not in str(exc), "malformed bearer errors never echo secret material")
    else:
        check(False, "malformed bearer is rejected")

    check(
        raises(
            ReadConnectorCredentialError,
            lambda: ReadConnectorCredentialEvidence(
                connector="notion",
                account_ref="notion-account-1",
                workspace_ref="workspace-main",
                credential_kind="google_oauth_bearer",
                state="ready",
                checked_at=250,
            ),
            "kind does not match connector",
        ),
        "credential kind cannot be relabeled across providers",
    )
    check(
        raises(
            ReadConnectorCredentialError,
            lambda: ReadConnectorCredentialEvidence(
                connector="google_drive",
                account_ref="google-account-1",
                workspace_ref="workspace-illegal",
                credential_kind="google_oauth_bearer",
                state="ready",
                checked_at=250,
            ),
            "cannot carry workspace_ref",
        ),
        "Google credential evidence cannot smuggle workspace authority",
    )
    check(
        raises(
            ReadConnectorCredentialError,
            lambda: replace(
                notion_binding,
                scope_sha256="0" * 64,
            ),
            "scope digest",
        ) is False,
        "alternate well-shaped digest remains representable but must be rejected at execution authority check",
    )
    tampered = replace(notion_binding, scope_sha256="0" * 64)
    check(
        raises(
            ReadConnectorDenied,
            lambda: notion_binder.trusted_bearer_for_execution(tampered, now=251),
            "scope changed",
        ),
        "well-shaped tampered scope digest cannot release bearer material",
    )
    check(notion_credentials.token_reads == 0, "tampered scope digest is rejected before token read")

    grants2.close()
    print(f"\n===== T-037 CREDENTIAL BINDING: {passed} passed, {failed} failed =====")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

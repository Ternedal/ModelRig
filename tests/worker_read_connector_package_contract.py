from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path

from app.data_sharing import DEFAULT_POLICY
from app.read_connector_package_contract import (
    ReadConnectorAuditLog,
    ReadConnectorContractError,
    ReadConnectorDenied,
    ReadConnectorGrantStore,
    ReadConnectorScope,
    ReadConnectorSourceReceipt,
    allowed_operations,
    build_cross_connector_sharing_request,
    capability_id,
    connectors,
    readiness_for,
)


class FixedUUIDs:
    def __init__(self) -> None:
        self._values = iter(
            (
                uuid.UUID("01234567-89ab-cdef-0123-456789abcdef"),
                uuid.UUID("fedcba98-7654-3210-fedc-ba9876543210"),
            )
        )

    def __call__(self) -> uuid.UUID:
        return next(self._values)


class ReadConnectorPackageContractTests(unittest.TestCase):
    def test_four_connectors_are_separate_read_capabilities(self) -> None:
        self.assertEqual(
            connectors(),
            ("google_calendar", "google_drive", "gmail", "notion"),
        )
        self.assertEqual(
            {capability_id(item) for item in connectors()},
            {
                "tool:google_calendar_read",
                "tool:google_drive_read",
                "tool:gmail_read",
                "tool:notion_read",
            },
        )
        self.assertEqual(len({capability_id(item) for item in connectors()}), 4)
        for connector in connectors():
            operations = allowed_operations(connector)
            self.assertTrue(operations)
            self.assertTrue(all("create" not in op for op in operations))
            self.assertTrue(all("update" not in op for op in operations))
            self.assertTrue(all("delete" not in op for op in operations))
            self.assertTrue(all("send" not in op for op in operations))

    def test_scope_is_exact_canonical_and_notion_requires_workspace(self) -> None:
        scope = ReadConnectorScope(
            connector="google_drive",
            account_ref="acct-123",
            workspace_ref="drive-42",
            object_scopes=("folder-b", "folder-a"),
            operations=("document_read", "file_search"),
        )
        self.assertEqual(scope.object_scopes, ("folder-a", "folder-b"))
        self.assertEqual(scope.operations, ("file_search", "document_read"))
        self.assertEqual(scope.to_dict()["capability_id"], "tool:google_drive_read")
        self.assertFalse(scope.to_dict()["production_activation"])
        self.assertEqual(len(scope.digest), 64)

        with self.assertRaisesRegex(ReadConnectorContractError, "notion scope requires"):
            ReadConnectorScope(
                connector="notion",
                account_ref="notion-user-1",
                object_scopes=("page-1",),
                operations=("page_get",),
            )

        with self.assertRaisesRegex(ReadConnectorContractError, "duplicates"):
            ReadConnectorScope(
                connector="gmail",
                account_ref="google-sub-1",
                object_scopes=("label-inbox", "label-inbox"),
                operations=("message_search",),
            )

        with self.assertRaisesRegex(ReadConnectorContractError, "unsupported gmail"):
            ReadConnectorScope(
                connector="gmail",
                account_ref="google-sub-1",
                object_scopes=("label-inbox",),
                operations=("message_send",),
            )

        with self.assertRaisesRegex(ReadConnectorContractError, "stable provider identifier"):
            ReadConnectorScope(
                connector="google_calendar",
                account_ref="person@example.com",
                object_scopes=("calendar-1",),
                operations=("event_get",),
            )

    def test_durable_revoke_stops_later_authorization_and_scope_digest_is_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "connector-grants.db")
            scope = ReadConnectorScope(
                connector="google_calendar",
                account_ref="google-sub-123",
                object_scopes=("calendar-primary",),
                operations=("event_get", "event_search"),
            )
            store = ReadConnectorGrantStore(path, uuid_factory=FixedUUIDs())
            try:
                grant = store.create_grant(scope, actor="loopback-operator", now=100)
                self.assertEqual(
                    store.authorize(
                        grant.grant_id,
                        connector="google_calendar",
                        account_ref="google-sub-123",
                        workspace_ref=None,
                        object_scope="calendar-primary",
                        operation="event_get",
                    ).grant_id,
                    grant.grant_id,
                )
                with self.assertRaisesRegex(ReadConnectorDenied, "outside exact"):
                    store.authorize(
                        grant.grant_id,
                        connector="google_calendar",
                        account_ref="google-sub-123",
                        workspace_ref=None,
                        object_scope="calendar-other",
                        operation="event_get",
                    )
                with self.assertRaisesRegex(ReadConnectorDenied, "scope changed"):
                    store.revoke(
                        grant.grant_id,
                        expected_scope_sha256="b" * 64,
                        actor="loopback-operator",
                        now=120,
                    )
                revoked = store.revoke(
                    grant.grant_id,
                    expected_scope_sha256=scope.digest,
                    actor="loopback-operator",
                    now=120,
                )
                self.assertFalse(revoked.active)
                with self.assertRaisesRegex(ReadConnectorDenied, "missing or revoked"):
                    store.authorize(
                        grant.grant_id,
                        connector="google_calendar",
                        account_ref="google-sub-123",
                        workspace_ref=None,
                        object_scope="calendar-primary",
                        operation="event_get",
                    )
            finally:
                store.close()

            reopened = ReadConnectorGrantStore(path)
            try:
                persisted = reopened.list_grants(include_revoked=True)
                self.assertEqual(len(persisted), 1)
                self.assertFalse(persisted[0].active)
                self.assertEqual(persisted[0].scope.digest, scope.digest)
            finally:
                reopened.close()

    def test_readiness_is_never_green_without_scope_and_credential_evidence(self) -> None:
        store = ReadConnectorGrantStore(uuid_factory=FixedUUIDs())
        try:
            missing = readiness_for(
                store,
                connector="gmail",
                grant_id="rcg_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                credential_state="ready",
                checked_at=200,
            )
            self.assertEqual(missing.state, "missing_scope")
            self.assertIsNone(missing.scope_sha256)

            scope = ReadConnectorScope(
                connector="gmail",
                account_ref="google-sub-7",
                object_scopes=("label-important",),
                operations=("message_search", "message_get"),
            )
            grant = store.create_grant(scope, actor="operator", now=201)
            expired = readiness_for(
                store,
                connector="gmail",
                grant_id=grant.grant_id,
                credential_state="expired_credentials",
                checked_at=202,
            )
            self.assertEqual(expired.state, "expired_credentials")
            self.assertEqual(expired.scope_sha256, scope.digest)

            ready = readiness_for(
                store,
                connector="gmail",
                grant_id=grant.grant_id,
                credential_state="ready",
                checked_at=203,
            )
            self.assertEqual(ready.state, "ready")
            payload = ready.to_dict()
            self.assertNotIn("token", payload)
            self.assertNotIn("credential", payload)
            self.assertFalse(payload["production_activation"])

            store.revoke(
                grant.grant_id,
                expected_scope_sha256=scope.digest,
                actor="operator",
                now=204,
            )
            revoked = readiness_for(
                store,
                connector="gmail",
                grant_id=grant.grant_id,
                credential_state="ready",
                checked_at=205,
            )
            self.assertEqual(revoked.state, "revoked")
        finally:
            store.close()

    def test_source_receipt_binds_stable_identity_revision_and_scope(self) -> None:
        receipt = ReadConnectorSourceReceipt(
            connector="notion",
            grant_id="rcg_0123456789abcdef0123456789abcdef",
            scope_sha256="a" * 64,
            account_ref="notion-user-1",
            workspace_ref="workspace-1",
            object_scope="page-root-1",
            operation="page_get",
            source_id="notion-page-42",
            object_id="page-42",
            revision="rev-2026-08-12T100000Z",
            retrieved_at=300,
        )
        payload = receipt.to_dict()
        self.assertEqual(payload["connector"], "notion")
        self.assertEqual(payload["capability_id"], "tool:notion_read")
        self.assertEqual(payload["source_id"], "notion-page-42")
        self.assertEqual(payload["object_id"], "page-42")
        self.assertEqual(payload["revision"], "rev-2026-08-12T100000Z")
        self.assertTrue(payload["retrieved_at"].endswith("Z"))
        self.assertFalse(payload["production_activation"])
        self.assertNotIn("content", payload)
        self.assertNotIn("body", payload)

    def test_audit_distinguishes_connector_account_operation_and_scope(self) -> None:
        audit = ReadConnectorAuditLog()
        try:
            audit.record(
                connector="google_drive",
                account_ref="google-sub-1",
                workspace_ref="drive-1",
                object_scope="folder-1",
                operation="file_search",
                outcome="executed",
                duration_ms=7,
                detail="fresh_remote_read",
                grant_id="rcg_0123456789abcdef0123456789abcdef",
                scope_sha256="a" * 64,
                source_id="drive-file-99",
                object_id="file-99",
                revision="rev-99",
            )
            audit.record(
                connector="notion",
                account_ref="notion-user-1",
                workspace_ref="workspace-1",
                object_scope="page-root-1",
                operation="search",
                outcome="blocked",
                duration_ms=1,
                detail="no_active_exact_grant",
            )
            rows = audit.recent(limit=10)
            self.assertEqual(len(rows), 2)
            drive = audit.recent(
                connector="google_drive",
                account_ref="google-sub-1",
                object_scope="folder-1",
                operation="file_search",
                outcome="executed",
            )
            self.assertEqual(len(drive), 1)
            self.assertEqual(drive[0]["connector"], "google_drive")
            self.assertEqual(drive[0]["account_ref"], "google-sub-1")
            self.assertEqual(drive[0]["object_scope"], "folder-1")
            self.assertEqual(drive[0]["operation"], "file_search")
            self.assertNotIn("body", drive[0])
            self.assertNotIn("content", drive[0])
            with self.assertRaisesRegex(ReadConnectorContractError, "requires connector"):
                audit.recent(operation="file_search")
        finally:
            audit.close()

    def test_cross_connector_processing_uses_t032_exact_request_policy(self) -> None:
        destination = ReadConnectorScope(
            connector="notion",
            account_ref="notion-user-1",
            workspace_ref="workspace-1",
            object_scopes=("page-root-1",),
            operations=("search", "page_get"),
        )
        private_request = build_cross_connector_sharing_request(
            source_connector="gmail",
            destination_scope=destination,
            data_category="private",
            purpose_code="notion_summary",
            purpose="Ground a user-requested Notion summary with selected Gmail context.",
            summary="Selected Gmail context for Notion read query",
            content_sha256="c" * 64,
            max_bytes=4096,
        )
        self.assertEqual(private_request.surface, "connector")
        self.assertEqual(private_request.destination_type, "connector")
        self.assertEqual(private_request.provider, "notion")
        self.assertEqual(DEFAULT_POLICY.decision(private_request), "confirmation_required")

        public_request = build_cross_connector_sharing_request(
            source_connector="google_calendar",
            destination_scope=destination,
            data_category="public",
            purpose_code="public_context",
            purpose="Use selected public context for a Notion lookup.",
            summary="Public context for Notion lookup",
            content_sha256="d" * 64,
            max_bytes=1024,
        )
        self.assertEqual(DEFAULT_POLICY.decision(public_request), "automatic")

        secret_request = build_cross_connector_sharing_request(
            source_connector="google_drive",
            destination_scope=destination,
            data_category="secret",
            purpose_code="forbidden_secret",
            purpose="This request must be rejected by T-032 policy.",
            summary="Secret connector context",
            content_sha256="e" * 64,
            max_bytes=128,
        )
        self.assertEqual(DEFAULT_POLICY.decision(secret_request), "forbidden")

        with self.assertRaisesRegex(ReadConnectorContractError, "two connectors"):
            build_cross_connector_sharing_request(
                source_connector="notion",
                destination_scope=destination,
                data_category="public",
                purpose_code="same_connector",
                purpose="Same-connector processing is not this cross-connector adapter.",
                summary="Same connector",
                content_sha256="f" * 64,
                max_bytes=128,
            )


if __name__ == "__main__":
    unittest.main()

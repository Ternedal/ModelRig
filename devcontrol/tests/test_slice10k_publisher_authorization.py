from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.publisher_authorization as authorization_module
from kaliv_dev_control.publisher_authorization import (
    HmacPublisherAuthorizationIssuer,
    PublisherAuthorizationError,
    PublisherAuthorizationLease,
    PublisherAuthorizationVerifier,
    PublisherPostconditionGate,
    PublisherPostconditionReceipt,
    PublisherPreflightGate,
    PublisherPreflightReceipt,
    PublisherReplayLedger,
    PublisherReplayLedgerEntry,
    RemoteRepositoryIdentity,
    TrustedAuthorizationIssuerKey,
    load_publisher_authorization_lease,
    load_publisher_postcondition_receipt,
    load_publisher_preflight_receipt,
    load_publisher_replay_ledger_entry,
    publisher_authorization_policy_sha256,
    publisher_credential_policy_rules_sha256,
    write_publisher_authorization_lease,
    write_publisher_postcondition_receipt,
    write_publisher_preflight_receipt,
    write_publisher_replay_ledger_entry,
)
from test_slice10g_command_receipt import make_task
from test_slice10h_semantic_review import ROOT
from test_slice10j_publisher_dry_run import make_artifacts

ISSUER = "publisher.authorization.issuer"
ISSUER_SYSTEM = "offline-authorization-service-v1"
ISSUER_KEY_ID = "publisher-authorization-key-2026"
ISSUER_SECRET = b"a" * 32
REPOSITORY_ID = "900000001"
LEDGER_ID = "publisher-replay-ledger-primary"
ISSUED = "2026-08-04T06:45:00Z"
CONSUMED = "2026-08-04T06:46:00Z"
CHECKED = "2026-08-04T06:47:00Z"
OBSERVED = "2026-08-04T06:48:00Z"
EXPIRES = "2026-08-04T06:55:00Z"


def make_authorization(directory: Path):
    (
        task,
        semantic_verifier,
        _,
        request,
        signed_request,
        publisher_verifier,
        _,
    ) = make_artifacts()
    remote = RemoteRepositoryIdentity.github(
        repository=request.repository,
        repository_id=REPOSITORY_ID,
    )
    issuer = HmacPublisherAuthorizationIssuer(
        key_id=ISSUER_KEY_ID,
        issuer_actor_id=ISSUER,
        issuer_system_id=ISSUER_SYSTEM,
        secret=ISSUER_SECRET,
    )
    lease = issuer.issue(
        signed_request=signed_request,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        remote_repository=remote,
        issued_at_utc=ISSUED,
        expires_at_utc=EXPIRES,
    )
    authorization_verifier = PublisherAuthorizationVerifier(
        {
            ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                issuer_actor_id=ISSUER,
                secret=ISSUER_SECRET,
            )
        }
    )
    ledger = PublisherReplayLedger(root=directory, ledger_id=LEDGER_ID)
    replay_entry = ledger.consume_once(
        lease=lease,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        consumed_at_utc=CONSUMED,
    )
    preflight = PublisherPreflightReceipt.from_consumed_lease(
        lease=lease,
        replay_entry=replay_entry,
        task=task,
        authorization_verifier=authorization_verifier,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        checked_at_utc=CHECKED,
    )
    postcondition = PublisherPostconditionReceipt.from_preflight_without_execution(
        preflight=preflight,
        observed_at_utc=OBSERVED,
    )
    return (
        task,
        semantic_verifier,
        request,
        signed_request,
        publisher_verifier,
        remote,
        lease,
        authorization_verifier,
        ledger,
        replay_entry,
        preflight,
        postcondition,
    )


class PublisherAuthorizationTests(unittest.TestCase):
    def test_one_time_lease_binds_exact_request_remote_policy_and_time(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                request,
                signed_request,
                publisher_verifier,
                remote,
                lease,
                authorization_verifier,
                _,
                replay_entry,
                preflight,
                postcondition,
            ) = make_authorization(Path(directory).resolve())

            self.assertEqual(lease.signed_request.canonical_json(), signed_request.canonical_json())
            self.assertEqual(lease.signed_request_sha256, signed_request.sha256)
            self.assertEqual(lease.request_sha256, request.sha256)
            self.assertEqual(lease.invocation_nonce, request.invocation_nonce)
            self.assertEqual(lease.remote_repository.canonical_json(), remote.canonical_json())
            self.assertEqual(lease.remote_repository_sha256, remote.sha256)
            self.assertEqual(lease.credential_policy.repository, request.repository)
            self.assertEqual(lease.credential_policy.head_branch, request.head_branch)
            self.assertEqual(lease.credential_policy.maximum_uses, 1)
            self.assertFalse(lease.credential_policy.token_material_present)
            self.assertFalse(lease.credential_policy.reusable_credential_allowed)
            self.assertIn("merge", lease.credential_policy.denied_capabilities)
            self.assertIn("ready-for-review", lease.credential_policy.denied_capabilities)
            self.assertEqual(
                lease.authorization_policy_sha256,
                publisher_authorization_policy_sha256(),
            )
            self.assertEqual(
                lease.credential_policy.rules_sha256,
                publisher_credential_policy_rules_sha256(),
            )
            self.assertTrue(lease.one_time)
            self.assertEqual(lease.maximum_uses, 1)
            self.assertTrue(lease.draft_only)
            self.assertEqual(lease.merge_authority, "human")

            verified = authorization_verifier.verify(
                lease=lease,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                at_utc=CONSUMED,
            )
            self.assertEqual(verified.sha256, lease.sha256)
            replay_entry.verify_against(lease)
            self.assertTrue(
                PublisherPreflightGate.valid(
                    receipt=preflight,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )
            )
            self.assertTrue(
                PublisherPostconditionGate.valid(
                    receipt=postcondition,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )
            )

    def test_issuer_is_separate_and_lease_lifetime_is_bounded(self):
        task, semantic_verifier, _, _, signed_request, publisher_verifier, _ = make_artifacts()
        request = signed_request.request
        remote = RemoteRepositoryIdentity.github(
            repository=request.repository,
            repository_id=REPOSITORY_ID,
        )
        developer = request.readiness.semantic_review_request.developer_actor_id
        reviewer = request.readiness.reviewer_actor_id
        publisher = request.publisher_actor_id
        for actor in (developer, reviewer, publisher):
            with self.subTest(actor=actor):
                issuer = HmacPublisherAuthorizationIssuer(
                    key_id=ISSUER_KEY_ID,
                    issuer_actor_id=actor,
                    issuer_system_id=ISSUER_SYSTEM,
                    secret=ISSUER_SECRET,
                )
                with self.assertRaisesRegex(PublisherAuthorizationError, "separate"):
                    issuer.issue(
                        signed_request=signed_request,
                        task=task,
                        publisher_verifier=publisher_verifier,
                        semantic_verifier=semantic_verifier,
                        control_plane_root=ROOT,
                        remote_repository=remote,
                        issued_at_utc=ISSUED,
                        expires_at_utc=EXPIRES,
                    )

        issuer = HmacPublisherAuthorizationIssuer(
            key_id=ISSUER_KEY_ID,
            issuer_actor_id=ISSUER,
            issuer_system_id=ISSUER_SYSTEM,
            secret=ISSUER_SECRET,
        )
        with self.assertRaisesRegex(PublisherAuthorizationError, "lifetime"):
            issuer.issue(
                signed_request=signed_request,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
                remote_repository=remote,
                issued_at_utc=ISSUED,
                expires_at_utc="2026-08-04T07:00:01Z",
            )

    def test_expiry_boundaries_wrong_keys_and_signature_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                authorization_verifier,
                _,
                _,
                _,
                _,
            ) = make_authorization(Path(directory).resolve())

            for at_utc in ("2026-08-04T06:44:59Z", EXPIRES):
                with self.subTest(at_utc=at_utc):
                    with self.assertRaisesRegex(PublisherAuthorizationError, "not currently valid"):
                        authorization_verifier.verify(
                            lease=lease,
                            task=task,
                            publisher_verifier=publisher_verifier,
                            semantic_verifier=semantic_verifier,
                            control_plane_root=ROOT,
                            at_utc=at_utc,
                        )

            wrong = PublisherAuthorizationVerifier(
                {
                    ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                        issuer_actor_id=ISSUER,
                        secret=b"x" * 32,
                    )
                }
            )
            with self.assertRaisesRegex(PublisherAuthorizationError, "signature"):
                wrong.verify(
                    lease=lease,
                    task=task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    at_utc=CONSUMED,
                )

            payload = lease.to_dict()
            payload["signature_sha256"] = "0" * 64
            tampered = PublisherAuthorizationLease.from_mapping(payload)
            with self.assertRaisesRegex(PublisherAuthorizationError, "signature"):
                authorization_verifier.verify(
                    lease=tampered,
                    task=task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    at_utc=CONSUMED,
                )

    def test_remote_identity_and_credential_policy_tampering_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            *_, lease, _, _, _, _, _ = make_authorization(Path(directory).resolve())

            payload = lease.to_dict()
            payload["remote_repository"]["repository"] = "attacker/repository"
            with self.assertRaisesRegex(PublisherAuthorizationError, "inconsistent"):
                PublisherAuthorizationLease.from_mapping(payload)

            payload = lease.to_dict()
            payload["credential_policy"]["allowed_permissions"].append(
                "administration:write"
            )
            with self.assertRaisesRegex(PublisherAuthorizationError, "least privilege"):
                PublisherAuthorizationLease.from_mapping(payload)

            payload = lease.to_dict()
            payload["credential_policy"]["denied_capabilities"].remove("merge")
            with self.assertRaisesRegex(PublisherAuthorizationError, "incomplete"):
                PublisherAuthorizationLease.from_mapping(payload)

            payload = lease.to_dict()
            payload["credential_policy"]["token_material_present"] = True
            with self.assertRaisesRegex(PublisherAuthorizationError, "authority boundary"):
                PublisherAuthorizationLease.from_mapping(payload)

    def test_replay_ledger_rejects_sequential_and_parallel_reuse(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                authorization_verifier,
                ledger,
                entry,
                _,
                _,
            ) = make_authorization(root)
            self.assertEqual(ledger.load(lease.invocation_nonce).sha256, entry.sha256)
            with self.assertRaisesRegex(PublisherAuthorizationError, "already been consumed"):
                ledger.consume_once(
                    lease=lease,
                    task=task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    consumed_at_utc=CONSUMED,
                )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                authorization_verifier,
                _,
                _,
                _,
                _,
            ) = self._lease_without_consumption(root)
            ledger = PublisherReplayLedger(root=root, ledger_id=LEDGER_ID)

            def consume():
                try:
                    return ledger.consume_once(
                        lease=lease,
                        task=task,
                        authorization_verifier=authorization_verifier,
                        publisher_verifier=publisher_verifier,
                        semantic_verifier=semantic_verifier,
                        control_plane_root=ROOT,
                        consumed_at_utc=CONSUMED,
                    )
                except PublisherAuthorizationError as exc:
                    return exc

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: consume(), range(2)))
            self.assertEqual(
                sum(isinstance(item, PublisherReplayLedgerEntry) for item in results),
                1,
            )
            self.assertEqual(
                sum(isinstance(item, PublisherAuthorizationError) for item in results),
                1,
            )

    @staticmethod
    def _lease_without_consumption(root: Path):
        (
            task,
            semantic_verifier,
            _,
            request,
            signed_request,
            publisher_verifier,
            _,
        ) = make_artifacts()
        remote = RemoteRepositoryIdentity.github(
            repository=request.repository,
            repository_id=REPOSITORY_ID,
        )
        lease = HmacPublisherAuthorizationIssuer(
            key_id=ISSUER_KEY_ID,
            issuer_actor_id=ISSUER,
            issuer_system_id=ISSUER_SYSTEM,
            secret=ISSUER_SECRET,
        ).issue(
            signed_request=signed_request,
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=ROOT,
            remote_repository=remote,
            issued_at_utc=ISSUED,
            expires_at_utc=EXPIRES,
        )
        verifier = PublisherAuthorizationVerifier(
            {
                ISSUER_KEY_ID: TrustedAuthorizationIssuerKey(
                    issuer_actor_id=ISSUER,
                    secret=ISSUER_SECRET,
                )
            }
        )
        return (
            task,
            semantic_verifier,
            request,
            signed_request,
            publisher_verifier,
            remote,
            lease,
            verifier,
            None,
            None,
            None,
            None,
        )

    def test_preflight_is_exact_and_claims_no_credential_or_write_adapter(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                request,
                _,
                publisher_verifier,
                _,
                lease,
                authorization_verifier,
                _,
                replay_entry,
                preflight,
                _,
            ) = make_authorization(Path(directory).resolve())
            self.assertEqual(preflight.lease_sha256, lease.sha256)
            self.assertEqual(preflight.replay_entry_sha256, replay_entry.sha256)
            self.assertEqual(preflight.invocation_nonce, request.invocation_nonce)
            self.assertEqual(preflight.authorized_operations, request.requested_operations)
            self.assertTrue(preflight.lease_valid)
            self.assertTrue(preflight.nonce_consumed)
            self.assertTrue(preflight.remote_identity_matches)
            self.assertTrue(preflight.credential_policy_matches)
            self.assertTrue(preflight.exact_draft_only_scope)
            self.assertFalse(preflight.credential_material_present)
            self.assertFalse(preflight.write_adapter_present)
            self.assertFalse(preflight.repository_write_performed)
            self.assertFalse(preflight.network_write_performed)
            preflight.verify(
                task=task,
                authorization_verifier=authorization_verifier,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )

            payload = preflight.to_dict()
            payload["authorized_operations"] = payload["authorized_operations"][:-1]
            with self.assertRaisesRegex(PublisherAuthorizationError, "inconsistent"):
                PublisherPreflightReceipt.from_mapping(payload)

    def test_postcondition_can_only_represent_no_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            *_, postcondition = make_authorization(Path(directory).resolve())
            self.assertEqual(postcondition.execution_state, "not_executed")
            for value in (
                postcondition.postconditions_verified,
                postcondition.repository_state_observed,
                postcondition.network_state_observed,
                postcondition.repository_write_performed,
                postcondition.network_write_performed,
                postcondition.commit_created,
                postcondition.branch_created,
                postcondition.branch_pushed,
                postcondition.pull_request_created,
                postcondition.ready_for_review,
                postcondition.reviewers_requested,
                postcondition.merged,
                postcondition.released,
                postcondition.deployed,
            ):
                self.assertFalse(value)

            for field in (
                "postconditions_verified",
                "repository_state_observed",
                "network_state_observed",
                "repository_write_performed",
                "network_write_performed",
                "commit_created",
                "branch_created",
                "branch_pushed",
                "pull_request_created",
                "ready_for_review",
                "reviewers_requested",
                "merged",
                "released",
                "deployed",
            ):
                payload = postcondition.to_dict()
                payload[field] = True
                with self.subTest(field=field):
                    with self.assertRaisesRegex(
                        PublisherAuthorizationError, "unavailable execution"
                    ):
                        PublisherPostconditionReceipt.from_mapping(payload)

            payload = postcondition.to_dict()
            payload["execution_state"] = "succeeded"
            with self.assertRaisesRegex(PublisherAuthorizationError, "unavailable execution"):
                PublisherPostconditionReceipt.from_mapping(payload)

    def test_other_task_and_execution_authority_drift_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            (
                task,
                semantic_verifier,
                _,
                _,
                publisher_verifier,
                _,
                lease,
                authorization_verifier,
                _,
                _,
                preflight,
                _,
            ) = make_authorization(Path(directory).resolve())
            other_task = make_task("2" * 40)
            with self.assertRaises(PublisherAuthorizationError):
                authorization_verifier.verify(
                    lease=lease,
                    task=other_task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                    at_utc=CONSUMED,
                )
            self.assertFalse(
                PublisherPreflightGate.valid(
                    receipt=preflight,
                    task=other_task,
                    authorization_verifier=authorization_verifier,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )
            )

            with patch(
                "kaliv_dev_control.semantic_review.tier_a_toolhost_sha256",
                return_value="0" * 64,
            ):
                with self.assertRaises(PublisherAuthorizationError):
                    authorization_verifier.verify(
                        lease=lease,
                        task=task,
                        publisher_verifier=publisher_verifier,
                        semantic_verifier=semantic_verifier,
                        control_plane_root=ROOT,
                        at_utc=CONSUMED,
                    )

    def test_canonical_file_roundtrip_and_create_once_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            *_, lease, _, _, replay_entry, preflight, postcondition = self._full_with_subdirectory(root)
            lease_path = root / "lease.json"
            replay_path = root / "replay-copy.json"
            preflight_path = root / "preflight.json"
            postcondition_path = root / "postcondition.json"

            self.assertEqual(write_publisher_authorization_lease(lease_path, lease), lease.sha256)
            self.assertEqual(
                write_publisher_replay_ledger_entry(replay_path, replay_entry),
                replay_entry.sha256,
            )
            self.assertEqual(
                write_publisher_preflight_receipt(preflight_path, preflight),
                preflight.sha256,
            )
            self.assertEqual(
                write_publisher_postcondition_receipt(postcondition_path, postcondition),
                postcondition.sha256,
            )
            self.assertEqual(load_publisher_authorization_lease(lease_path).sha256, lease.sha256)
            self.assertEqual(
                load_publisher_replay_ledger_entry(replay_path).sha256,
                replay_entry.sha256,
            )
            self.assertEqual(
                load_publisher_preflight_receipt(preflight_path).sha256,
                preflight.sha256,
            )
            self.assertEqual(
                load_publisher_postcondition_receipt(postcondition_path).sha256,
                postcondition.sha256,
            )
            with self.assertRaisesRegex(PublisherAuthorizationError, "already exists"):
                write_publisher_authorization_lease(lease_path, lease)

            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(lease.canonical_json().encode("utf-8") + b"\n")
            with self.assertRaisesRegex(PublisherAuthorizationError, "canonical"):
                load_publisher_authorization_lease(noncanonical)

    @staticmethod
    def _full_with_subdirectory(root: Path):
        ledger = root / "ledger"
        ledger.mkdir()
        return make_authorization(ledger)

    def test_schemas_api_surface_and_module_have_no_live_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            *_, lease, _, _, replay_entry, preflight, postcondition = self._full_with_subdirectory(
                Path(directory).resolve()
            )
            artifacts = (
                (
                    "development-publisher-authorization-lease-v1.schema.json",
                    lease.to_dict(),
                ),
                (
                    "development-publisher-replay-ledger-entry-v1.schema.json",
                    replay_entry.to_dict(),
                ),
                (
                    "development-publisher-preflight-receipt-v1.schema.json",
                    preflight.to_dict(),
                ),
                (
                    "development-publisher-postcondition-receipt-v1.schema.json",
                    postcondition.to_dict(),
                ),
            )
            for filename, payload in artifacts:
                with self.subTest(filename=filename):
                    schema = json.loads(
                        (ROOT / "devcontrol/schemas" / filename).read_text(
                            encoding="utf-8"
                        )
                    )
                    self.assertEqual(set(schema["required"]), set(payload))
                    self.assertEqual(set(schema["properties"]), set(payload))

        issue_parameters = set(
            inspect.signature(HmacPublisherAuthorizationIssuer.issue).parameters
        )
        for forbidden in (
            "token",
            "credential",
            "permissions",
            "github",
            "client",
            "transport",
            "operations",
            "merge",
            "release",
            "deploy",
        ):
            self.assertNotIn(forbidden, issue_parameters)

        consume_parameters = set(
            inspect.signature(PublisherReplayLedger.consume_once).parameters
        )
        for forbidden in (
            "token",
            "credential",
            "github",
            "client",
            "transport",
            "execute",
            "push",
            "pull_request",
        ):
            self.assertNotIn(forbidden, consume_parameters)

        names = set(dir(authorization_module))
        for forbidden in (
            "create_branch",
            "commit_changes",
            "push_branch",
            "create_pull_request",
            "update_pull_request",
            "request_reviewers",
            "mark_ready_for_review",
            "merge_pull_request",
            "release",
            "deploy",
        ):
            self.assertNotIn(forbidden, names)
        source = inspect.getsource(authorization_module)
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("import requests", source)
        self.assertNotIn("import urllib", source)
        self.assertNotIn("import socket", source)
        self.assertNotIn("Authorization:", source)
        self.assertNotIn("api.github.com", source)
        self.assertNotIn("github_token", source)


if __name__ == "__main__":
    unittest.main()

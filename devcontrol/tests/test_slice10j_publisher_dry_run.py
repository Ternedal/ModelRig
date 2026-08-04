from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.publisher_dry_run as publisher_module
from kaliv_dev_control.publisher_dry_run import (
    HmacPublisherRequestSigner,
    PublisherDryRunError,
    PublisherDryRunGate,
    PublisherDryRunReceipt,
    PublisherOperationKind,
    PublisherRequest,
    PublisherRequestVerifier,
    SignedPublisherRequest,
    TrustedPublisherKey,
    load_publisher_dry_run_receipt,
    load_publisher_request,
    load_signed_publisher_request,
    publisher_dry_run_policy_sha256,
    write_publisher_dry_run_receipt,
    write_publisher_request,
    write_signed_publisher_request,
)
from kaliv_dev_control.semantic_review import SemanticReviewVerifier
from test_slice10g_command_receipt import make_task
from test_slice10h_semantic_review import KEY_ID, REVIEWER, ROOT, SECRET
from test_slice10i_draft_pr_readiness import make_proposal

PUBLISHER = "human.publisher"
PUBLISHER_SYSTEM = "offline-publisher-console-v1"
PUBLISHER_KEY_ID = "publisher-key-2026"
PUBLISHER_SECRET = b"p" * 32
NONCE = "a" * 64


def make_artifacts():
    task, _, _, semantic_verifier, readiness = make_proposal()
    request = PublisherRequest.from_readiness(
        readiness=readiness,
        task=task,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
        publisher_actor_id=PUBLISHER,
        publisher_system_id=PUBLISHER_SYSTEM,
        invocation_nonce=NONCE,
    )
    signed = HmacPublisherRequestSigner(
        key_id=PUBLISHER_KEY_ID,
        publisher_actor_id=PUBLISHER,
        secret=PUBLISHER_SECRET,
    ).sign(request)
    publisher_verifier = PublisherRequestVerifier(
        {
            PUBLISHER_KEY_ID: TrustedPublisherKey(
                publisher_actor_id=PUBLISHER,
                secret=PUBLISHER_SECRET,
            )
        }
    )
    receipt = PublisherDryRunReceipt.from_signed_request(
        signed_request=signed,
        task=task,
        publisher_verifier=publisher_verifier,
        semantic_verifier=semantic_verifier,
        control_plane_root=ROOT,
    )
    return task, semantic_verifier, readiness, request, signed, publisher_verifier, receipt


class PublisherDryRunTests(unittest.TestCase):
    def test_signed_human_invocation_binds_exact_readiness_and_fixed_operations(self):
        (
            task,
            semantic_verifier,
            readiness,
            request,
            signed,
            publisher_verifier,
            receipt,
        ) = make_artifacts()

        self.assertEqual(request.readiness.canonical_json(), readiness.canonical_json())
        self.assertEqual(request.readiness_sha256, readiness.sha256)
        self.assertEqual(request.task_sha256, readiness.task_sha256)
        self.assertEqual(request.staged_patch_sha256, readiness.staged_patch_sha256)
        self.assertEqual(request.publisher_actor_id, PUBLISHER)
        self.assertEqual(request.publisher_system_id, PUBLISHER_SYSTEM)
        self.assertEqual(request.invocation_nonce, NONCE)
        self.assertTrue(request.human_invoked)
        self.assertTrue(request.dry_run_only)
        self.assertTrue(request.draft_only)
        self.assertEqual(request.merge_authority, "human")
        self.assertEqual(request.publisher_policy_sha256, publisher_dry_run_policy_sha256())
        self.assertEqual(
            request.requested_operations,
            tuple(item.value for item in PublisherOperationKind),
        )

        verified = publisher_verifier.verify(
            signed_request=signed,
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=ROOT,
        )
        self.assertEqual(verified.sha256, request.sha256)

        self.assertEqual(receipt.signed_request_sha256, signed.sha256)
        self.assertEqual(receipt.request_sha256, request.sha256)
        self.assertEqual(receipt.readiness_sha256, readiness.sha256)
        self.assertEqual(receipt.publisher_actor_id, PUBLISHER)
        self.assertEqual(receipt.publisher_key_id, PUBLISHER_KEY_ID)
        self.assertEqual(
            tuple(item.operation for item in receipt.operations),
            tuple(PublisherOperationKind),
        )
        self.assertEqual(
            tuple(item.sequence for item in receipt.operations),
            (1, 2, 3, 4, 5),
        )
        self.assertTrue(receipt.dry_run)
        for value in (
            receipt.executed,
            receipt.repository_write_performed,
            receipt.network_write_performed,
            receipt.commit_created,
            receipt.branch_created,
            receipt.branch_pushed,
            receipt.pull_request_created,
            receipt.ready_for_review,
            receipt.reviewers_requested,
            receipt.merged,
            receipt.released,
            receipt.deployed,
        ):
            self.assertFalse(value)

        receipt.verify(
            task=task,
            publisher_verifier=publisher_verifier,
            semantic_verifier=semantic_verifier,
            control_plane_root=ROOT,
        )
        self.assertTrue(
            PublisherDryRunGate.valid(
                receipt=receipt,
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )
        )

    def test_plan_is_deterministic_complete_and_never_claims_execution(self):
        *_, first = make_artifacts()
        *_, second = make_artifacts()
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.sha256, second.sha256)

        verify, commit, branch, push, draft_pr = first.operations
        self.assertFalse(verify.repository_write_required)
        self.assertFalse(verify.network_write_required)
        self.assertTrue(commit.repository_write_required)
        self.assertFalse(commit.network_write_required)
        self.assertTrue(branch.repository_write_required)
        self.assertFalse(branch.network_write_required)
        self.assertTrue(push.repository_write_required)
        self.assertTrue(push.network_write_required)
        self.assertTrue(draft_pr.repository_write_required)
        self.assertTrue(draft_pr.network_write_required)
        self.assertTrue(all(item.status == "planned_not_executed" for item in first.operations))

        commit_parameters = {item.name: item.value for item in commit.parameters}
        self.assertEqual(commit_parameters["parent_sha"], first.base_sha)
        self.assertEqual(commit_parameters["staged_patch_sha256"], first.staged_patch_sha256)
        self.assertEqual(commit_parameters["author_actor_id"], PUBLISHER)
        pr_parameters = {item.name: item.value for item in draft_pr.parameters}
        self.assertEqual(pr_parameters["draft"], "true")
        self.assertEqual(pr_parameters["merge_authority"], "human")
        self.assertEqual(pr_parameters["head_branch"], first.head_branch)

    def test_request_builder_exposes_no_repository_or_publication_selection(self):
        parameters = set(inspect.signature(PublisherRequest.from_readiness).parameters)
        for forbidden in (
            "repository",
            "base_sha",
            "base_branch",
            "head_branch",
            "title",
            "body",
            "staged_patch_sha256",
            "operations",
            "draft",
            "merge_authority",
            "github",
            "token",
            "credential",
            "workspace",
            "command_id",
            "argv",
        ):
            self.assertNotIn(forbidden, parameters)

        receipt_parameters = set(
            inspect.signature(PublisherDryRunReceipt.from_signed_request).parameters
        )
        for forbidden in (
            "github",
            "token",
            "credential",
            "repository",
            "branch",
            "title",
            "body",
            "execute",
            "push",
            "pull_request",
        ):
            self.assertNotIn(forbidden, receipt_parameters)

    def test_publisher_actor_must_be_separate_and_signer_must_match_actor(self):
        task, _, _, semantic_verifier, readiness = make_proposal()
        developer = readiness.semantic_review_request.developer_actor_id
        for actor in (developer, REVIEWER):
            with self.subTest(actor=actor):
                with self.assertRaisesRegex(PublisherDryRunError, "separate"):
                    PublisherRequest.from_readiness(
                        readiness=readiness,
                        task=task,
                        semantic_verifier=semantic_verifier,
                        control_plane_root=ROOT,
                        publisher_actor_id=actor,
                        publisher_system_id=PUBLISHER_SYSTEM,
                        invocation_nonce=NONCE,
                    )

        request = PublisherRequest.from_readiness(
            readiness=readiness,
            task=task,
            semantic_verifier=semantic_verifier,
            control_plane_root=ROOT,
            publisher_actor_id=PUBLISHER,
            publisher_system_id=PUBLISHER_SYSTEM,
            invocation_nonce=NONCE,
        )
        with self.assertRaisesRegex(PublisherDryRunError, "another actor"):
            HmacPublisherRequestSigner(
                key_id=PUBLISHER_KEY_ID,
                publisher_actor_id="other.publisher",
                secret=PUBLISHER_SECRET,
            ).sign(request)

    def test_request_and_signature_tampering_fail_closed(self):
        task, semantic_verifier, _, request, signed, publisher_verifier, receipt = make_artifacts()

        cases = []
        payload = request.to_dict()
        payload["readiness_sha256"] = "f" * 64
        cases.append(("readiness hash", payload))

        payload = request.to_dict()
        payload["staged_patch_sha256"] = "f" * 64
        cases.append(("identities", payload))

        payload = request.to_dict()
        payload["requested_operations"] = payload["requested_operations"][:-1]
        cases.append(("operations", payload))

        payload = request.to_dict()
        payload["human_invoked"] = False
        cases.append(("authority", payload))

        payload = request.to_dict()
        payload["merge_authority"] = "model"
        cases.append(("authority", payload))

        for expected, altered in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(PublisherDryRunError, expected):
                    PublisherRequest.from_mapping(altered)

        signature_payload = signed.to_dict()
        signature_payload["signature_sha256"] = "0" * 64
        tampered_signed = SignedPublisherRequest.from_mapping(signature_payload)
        self.assertFalse(
            PublisherDryRunGate.valid(
                receipt=PublisherDryRunReceipt.from_mapping(
                    {
                        **receipt.to_dict(),
                        "signed_request": tampered_signed.to_dict(),
                        "signed_request_sha256": tampered_signed.sha256,
                    }
                ),
                task=task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )
        )

        wrong_verifier = PublisherRequestVerifier(
            {
                PUBLISHER_KEY_ID: TrustedPublisherKey(
                    publisher_actor_id=PUBLISHER,
                    secret=b"x" * 32,
                )
            }
        )
        with self.assertRaisesRegex(PublisherDryRunError, "signature"):
            wrong_verifier.verify(
                signed_request=signed,
                task=task,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )

        untrusted = PublisherRequestVerifier(
            {
                "other-key": TrustedPublisherKey(
                    publisher_actor_id=PUBLISHER,
                    secret=PUBLISHER_SECRET,
                )
            }
        )
        with self.assertRaisesRegex(PublisherDryRunError, "not trusted"):
            untrusted.verify(
                signed_request=signed,
                task=task,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )

    def test_receipt_plan_and_every_forbidden_result_flag_fail_closed(self):
        _, _, _, _, _, _, receipt = make_artifacts()

        operation_payload = receipt.to_dict()
        operation_payload["operations"][1]["parameters"][0]["value"] = "attacker/repo"
        with self.assertRaisesRegex(PublisherDryRunError, "deterministic"):
            PublisherDryRunReceipt.from_mapping(operation_payload)

        for field in (
            "executed",
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
            payload = receipt.to_dict()
            payload[field] = True
            with self.subTest(field=field):
                with self.assertRaisesRegex(PublisherDryRunError, "forbidden execution"):
                    PublisherDryRunReceipt.from_mapping(payload)

        payload = receipt.to_dict()
        payload["merge_authority"] = "publisher"
        with self.assertRaisesRegex(PublisherDryRunError, "forbidden execution"):
            PublisherDryRunReceipt.from_mapping(payload)

    def test_other_task_and_execution_authority_drift_fail_closed(self):
        task, semantic_verifier, _, request, signed, publisher_verifier, receipt = make_artifacts()
        other_task = make_task("2" * 40)
        self.assertFalse(
            PublisherDryRunGate.valid(
                receipt=receipt,
                task=other_task,
                publisher_verifier=publisher_verifier,
                semantic_verifier=semantic_verifier,
                control_plane_root=ROOT,
            )
        )

        with patch(
            "kaliv_dev_control.semantic_review.tier_a_toolhost_sha256",
            return_value="0" * 64,
        ):
            with self.assertRaisesRegex(PublisherDryRunError, "authority"):
                PublisherDryRunReceipt.from_signed_request(
                    signed_request=signed,
                    task=task,
                    publisher_verifier=publisher_verifier,
                    semantic_verifier=semantic_verifier,
                    control_plane_root=ROOT,
                )

        readiness_payload = request.to_dict()
        readiness_payload["readiness"]["title"] += " altered"
        with self.assertRaises(ValueError):
            PublisherRequest.from_mapping(readiness_payload)

    def test_canonical_file_roundtrip_and_no_overwrite(self):
        _, _, _, request, signed, _, receipt = make_artifacts()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request_path = root / "publisher-request.json"
            signed_path = root / "signed-publisher-request.json"
            receipt_path = root / "publisher-dry-run-receipt.json"

            self.assertEqual(write_publisher_request(request_path, request), request.sha256)
            self.assertEqual(
                write_signed_publisher_request(signed_path, signed), signed.sha256
            )
            self.assertEqual(
                write_publisher_dry_run_receipt(receipt_path, receipt), receipt.sha256
            )
            self.assertEqual(load_publisher_request(request_path).sha256, request.sha256)
            self.assertEqual(
                load_signed_publisher_request(signed_path).sha256,
                signed.sha256,
            )
            self.assertEqual(
                load_publisher_dry_run_receipt(receipt_path).sha256,
                receipt.sha256,
            )
            with self.assertRaisesRegex(PublisherDryRunError, "already exists"):
                write_publisher_dry_run_receipt(receipt_path, receipt)

            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(request.canonical_json().encode("utf-8") + b"\n")
            with self.assertRaisesRegex(PublisherDryRunError, "canonical"):
                load_publisher_request(noncanonical)

    def test_schemas_match_artifacts_and_module_has_no_live_adapter(self):
        _, _, _, request, signed, _, receipt = make_artifacts()
        artifacts = (
            (
                "development-publisher-request-v1.schema.json",
                request.to_dict(),
            ),
            (
                "development-signed-publisher-request-v1.schema.json",
                signed.to_dict(),
            ),
            (
                "development-publisher-dry-run-receipt-v1.schema.json",
                receipt.to_dict(),
            ),
        )
        for filename, payload in artifacts:
            with self.subTest(filename=filename):
                schema = json.loads(
                    (ROOT / "devcontrol/schemas" / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(set(schema["required"]), set(payload))
                self.assertEqual(set(schema["properties"]), set(payload))

        names = set(dir(publisher_module))
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
        source = inspect.getsource(publisher_module)
        self.assertNotIn("Authorization:", source)
        self.assertNotIn("api.github.com", source)
        self.assertNotIn("github_token", source)


if __name__ == "__main__":
    unittest.main()

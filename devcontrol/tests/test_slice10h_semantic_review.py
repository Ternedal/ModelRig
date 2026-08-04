from __future__ import annotations

import base64
import hashlib
import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kaliv_dev_control.semantic_review import (
    CriterionAssessment,
    CriterionOutcome,
    FindingSeverity,
    HmacSemanticReviewVerdictSigner,
    SemanticFinding,
    SemanticReviewApprovalGate,
    SemanticReviewDecision,
    SemanticReviewError,
    SemanticReviewRequest,
    SemanticReviewVerdict,
    SemanticReviewVerifier,
    SignedSemanticReviewVerdict,
    TrustedSemanticReviewerKey,
    criterion_sha256,
    load_semantic_review_request,
    load_signed_semantic_review_verdict,
    semantic_review_policy_sha256,
    write_semantic_review_request,
    write_signed_semantic_review_verdict,
)
from kaliv_dev_control.tier_a_command_receipt import (
    GitWorkspaceSnapshot,
    TierACommandReceipt,
)
from test_slice10g_command_receipt import make_task, result

ROOT = Path(__file__).resolve().parents[2]
PATCH_BYTES = (
    b"diff --git a/tracked.txt b/tracked.txt\n"
    b"index df967b9..19d9cc8 100644\n"
    b"--- a/tracked.txt\n"
    b"+++ b/tracked.txt\n"
    b"@@ -1 +1 @@\n"
    b"-base\n"
    b"+staged\n"
)
KEY_ID = "slice-10h-review-key"
REVIEWER = "semantic-reviewer-b"
DEVELOPER = "developer-a"
SECRET = b"slice-10h-independent-review-secret-0001"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()


def make_receipt(task, patch_bytes: bytes = PATCH_BYTES) -> TierACommandReceipt:
    patch_sha = hashlib.sha256(patch_bytes).hexdigest()
    snapshot = GitWorkspaceSnapshot(
        head_sha=task.base_sha,
        staged_patch_sha256=patch_sha,
        staged_patch_bytes=len(patch_bytes),
        unstaged_patch_sha256=EMPTY_SHA,
        unstaged_patch_bytes=0,
        untracked_paths_sha256=EMPTY_SHA,
        untracked_path_count=0,
    )
    return TierACommandReceipt.create(
        task=task,
        result=result(task),
        before=snapshot,
        after=snapshot,
        reset=None,
    )


def make_request():
    task = make_task("1" * 40)
    receipt = make_receipt(task)
    request = SemanticReviewRequest.from_evidence(
        task=task,
        developer_actor_id=DEVELOPER,
        staged_patch=PATCH_BYTES,
        receipt=receipt,
        control_plane_root=ROOT,
    )
    return task, receipt, request


def assessments(request, outcome=CriterionOutcome.SATISFIED):
    return tuple(
        CriterionAssessment(
            criterion_sha256=criterion_sha256(criterion),
            outcome=outcome,
            rationale=(
                "The exact patch and passing Tier-A receipt satisfy this criterion."
                if outcome is CriterionOutcome.SATISFIED
                else "The supplied evidence does not prove this criterion."
            ),
        )
        for criterion in request.acceptance_criteria
    )


def approve(request):
    verdict = SemanticReviewVerdict.create(
        request=request,
        reviewer_actor_id=REVIEWER,
        reviewer_system_id="offline-semantic-reviewer-v1",
        decision=SemanticReviewDecision.APPROVE,
        criterion_assessments=assessments(request),
        findings=(),
    )
    signed = HmacSemanticReviewVerdictSigner(
        key_id=KEY_ID,
        reviewer_actor_id=REVIEWER,
        secret=SECRET,
    ).sign(verdict)
    verifier = SemanticReviewVerifier(
        {KEY_ID: TrustedSemanticReviewerKey(REVIEWER, SECRET)}
    )
    return verdict, signed, verifier


class SemanticReviewTests(unittest.TestCase):
    def test_request_binds_exact_patch_receipt_task_policy_and_authority(self):
        task, receipt, request = make_request()

        self.assertEqual(request.staged_patch, PATCH_BYTES)
        self.assertEqual(request.staged_patch_sha256, hashlib.sha256(PATCH_BYTES).hexdigest())
        self.assertEqual(request.receipt_sha256, receipt.sha256)
        self.assertEqual(request.review_policy_sha256, semantic_review_policy_sha256())
        self.assertEqual(request.acceptance_criteria, task.acceptance_criteria)
        request.verify_task(task)
        request.verify_execution_authority(ROOT)

        restored = SemanticReviewRequest.from_mapping(request.to_dict())
        self.assertEqual(restored.canonical_json(), request.canonical_json())
        self.assertEqual(restored.sha256, request.sha256)

    def test_authenticated_approval_requires_actor_and_key_separation(self):
        task, _, request = make_request()
        verdict, signed, verifier = approve(request)

        verified = verifier.verify(
            task=task,
            request=request,
            signed_verdict=signed,
            control_plane_root=ROOT,
        )
        self.assertEqual(verified.canonical_json(), verdict.canonical_json())
        self.assertTrue(
            SemanticReviewApprovalGate.ready(
                task=task,
                request=request,
                signed_verdict=signed,
                verifier=verifier,
                control_plane_root=ROOT,
            )
        )

        wrong_actor = SemanticReviewVerifier(
            {KEY_ID: TrustedSemanticReviewerKey("reviewer-c", SECRET)}
        )
        with self.assertRaisesRegex(SemanticReviewError, "actor"):
            wrong_actor.verify(
                task=task,
                request=request,
                signed_verdict=signed,
                control_plane_root=ROOT,
            )

        with self.assertRaisesRegex(SemanticReviewError, "another actor"):
            HmacSemanticReviewVerdictSigner(
                key_id=KEY_ID,
                reviewer_actor_id="reviewer-c",
                secret=SECRET,
            ).sign(verdict)

    def test_request_rejects_patch_receipt_and_task_tampering(self):
        task, _, request = make_request()

        patch_payload = request.to_dict()
        patch_payload["staged_patch_base64"] = base64.b64encode(
            PATCH_BYTES + b"tamper"
        ).decode("ascii")
        with self.assertRaisesRegex(SemanticReviewError, "patch"):
            SemanticReviewRequest.from_mapping(patch_payload)

        receipt_payload = request.to_dict()
        receipt_payload["receipt_sha256"] = "f" * 64
        with self.assertRaisesRegex(SemanticReviewError, "receipt hash"):
            SemanticReviewRequest.from_mapping(receipt_payload)

        criteria_payload = request.to_dict()
        criteria_payload["acceptance_criteria"] = ["Different criterion"]
        altered = SemanticReviewRequest.from_mapping(criteria_payload)
        with self.assertRaisesRegex(SemanticReviewError, "task"):
            altered.verify_task(task)

    def test_authority_mismatch_fails_even_with_a_fresh_valid_signature(self):
        task, _, request = make_request()
        payload = request.to_dict()
        payload["execution_authority_sha256"] = "0" * 64
        changed = SemanticReviewRequest.from_mapping(payload)
        verdict = SemanticReviewVerdict.create(
            request=changed,
            reviewer_actor_id=REVIEWER,
            reviewer_system_id="offline-semantic-reviewer-v1",
            decision=SemanticReviewDecision.APPROVE,
            criterion_assessments=assessments(changed),
            findings=(),
        )
        signed = HmacSemanticReviewVerdictSigner(
            key_id=KEY_ID,
            reviewer_actor_id=REVIEWER,
            secret=SECRET,
        ).sign(verdict)
        verifier = SemanticReviewVerifier(
            {KEY_ID: TrustedSemanticReviewerKey(REVIEWER, SECRET)}
        )

        with self.assertRaisesRegex(SemanticReviewError, "authority"):
            verifier.verify(
                task=task,
                request=changed,
                signed_verdict=signed,
                control_plane_root=ROOT,
            )
        self.assertFalse(
            SemanticReviewApprovalGate.ready(
                task=task,
                request=changed,
                signed_verdict=signed,
                verifier=verifier,
                control_plane_root=ROOT,
            )
        )

    def test_signature_and_request_binding_tampering_fail_closed(self):
        task, _, request = make_request()
        _, signed, verifier = approve(request)

        signature_payload = signed.to_dict()
        signature_payload["signature_sha256"] = "0" * 64
        tampered_signature = SignedSemanticReviewVerdict.from_mapping(
            signature_payload
        )
        with self.assertRaisesRegex(SemanticReviewError, "signature"):
            verifier.verify(
                task=task,
                request=request,
                signed_verdict=tampered_signature,
                control_plane_root=ROOT,
            )

        other_task = make_task("2" * 40)
        with self.assertRaisesRegex(SemanticReviewError, "task"):
            verifier.verify(
                task=other_task,
                request=request,
                signed_verdict=signed,
                control_plane_root=ROOT,
            )

    def test_uncertain_or_findings_cannot_pass_the_approval_gate(self):
        task, _, request = make_request()
        verdict = SemanticReviewVerdict.create(
            request=request,
            reviewer_actor_id=REVIEWER,
            reviewer_system_id="offline-semantic-reviewer-v1",
            decision=SemanticReviewDecision.REQUEST_CHANGES,
            criterion_assessments=assessments(
                request, CriterionOutcome.UNCERTAIN
            ),
            findings=(
                SemanticFinding(
                    severity=FindingSeverity.HIGH,
                    title="Evidence gap",
                    detail="The exact request does not prove the required behavior.",
                ),
            ),
        )
        signed = HmacSemanticReviewVerdictSigner(
            key_id=KEY_ID,
            reviewer_actor_id=REVIEWER,
            secret=SECRET,
        ).sign(verdict)
        verifier = SemanticReviewVerifier(
            {KEY_ID: TrustedSemanticReviewerKey(REVIEWER, SECRET)}
        )
        self.assertEqual(
            verifier.verify(
                task=task,
                request=request,
                signed_verdict=signed,
                control_plane_root=ROOT,
            ).decision,
            SemanticReviewDecision.REQUEST_CHANGES,
        )
        self.assertFalse(
            SemanticReviewApprovalGate.ready(
                task=task,
                request=request,
                signed_verdict=signed,
                verifier=verifier,
                control_plane_root=ROOT,
            )
        )

        with self.assertRaisesRegex(SemanticReviewError, "approval"):
            SemanticReviewVerdict.create(
                request=request,
                reviewer_actor_id=REVIEWER,
                reviewer_system_id="offline-semantic-reviewer-v1",
                decision=SemanticReviewDecision.APPROVE,
                criterion_assessments=assessments(
                    request, CriterionOutcome.UNCERTAIN
                ),
                findings=(),
            )

    def test_canonical_offline_exchange_roundtrips_and_refuses_overwrite(self):
        _, _, request = make_request()
        _, signed, _ = approve(request)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            request_path = root / "request.json"
            verdict_path = root / "verdict.json"

            self.assertEqual(
                write_semantic_review_request(request_path, request),
                request.sha256,
            )
            self.assertEqual(
                write_signed_semantic_review_verdict(verdict_path, signed),
                signed.sha256,
            )
            self.assertEqual(
                load_semantic_review_request(request_path).canonical_json(),
                request.canonical_json(),
            )
            self.assertEqual(
                load_signed_semantic_review_verdict(verdict_path).canonical_json(),
                signed.canonical_json(),
            )
            with self.assertRaisesRegex(SemanticReviewError, "already exists"):
                write_semantic_review_request(request_path, request)

            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(request.canonical_json().encode("utf-8") + b"\n")
            with self.assertRaisesRegex(SemanticReviewError, "canonical"):
                load_semantic_review_request(noncanonical)

    def test_schema_fields_match_canonical_artifacts(self):
        _, _, request = make_request()
        verdict, signed, _ = approve(request)
        schemas = ROOT / "devcontrol" / "schemas"
        for filename, artifact in (
            ("development-semantic-review-request-v1.schema.json", request),
            ("development-semantic-review-verdict-v1.schema.json", verdict),
            ("development-signed-semantic-review-verdict-v1.schema.json", signed),
        ):
            with self.subTest(filename=filename):
                schema = json.loads((schemas / filename).read_text(encoding="utf-8"))
                fields = set(artifact.to_dict())
                self.assertEqual(set(schema["required"]), fields)
                self.assertEqual(set(schema["properties"]), fields)

    def test_review_api_has_no_workspace_command_or_runtime_selection(self):
        parameters = set(
            inspect.signature(SemanticReviewRequest.from_evidence).parameters
        )
        self.assertNotIn("workspace_root", parameters)
        self.assertNotIn("command_id", parameters)
        self.assertNotIn("argv", parameters)
        self.assertNotIn("catalog", parameters)
        self.assertNotIn("toolchain", parameters)

        with patch(
            "kaliv_dev_control.semantic_review.tier_a_toolhost_sha256",
            return_value="a" * 64,
        ) as authority:
            task = make_task("1" * 40)
            SemanticReviewRequest.from_evidence(
                task=task,
                developer_actor_id=DEVELOPER,
                staged_patch=PATCH_BYTES,
                receipt=make_receipt(task),
                control_plane_root=ROOT,
            )
        authority.assert_called_once()


if __name__ == "__main__":
    unittest.main()

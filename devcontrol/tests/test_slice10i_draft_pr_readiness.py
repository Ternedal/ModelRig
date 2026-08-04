from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.draft_pr_readiness as readiness_module
from kaliv_dev_control.draft_pr_readiness import (
    AuthenticatedDraftPrReadinessProposal,
    DraftPrReadinessError,
    DraftPrReadinessGate,
    draft_pr_readiness_policy_sha256,
    load_authenticated_draft_pr_readiness_proposal,
    write_authenticated_draft_pr_readiness_proposal,
)
from kaliv_dev_control.semantic_review import (
    CriterionOutcome,
    FindingSeverity,
    HmacSemanticReviewVerdictSigner,
    SemanticFinding,
    SemanticReviewDecision,
    SemanticReviewVerdict,
    SemanticReviewVerifier,
    TrustedSemanticReviewerKey,
)
from test_slice10g_command_receipt import make_task
from test_slice10h_semantic_review import (
    KEY_ID,
    REVIEWER,
    ROOT,
    SECRET,
    approve,
    assessments,
    make_request,
)


def make_proposal(*, base_branch: str = "main"):
    task, _, request = make_request()
    _, signed, verifier = approve(request)
    proposal = AuthenticatedDraftPrReadinessProposal.from_evidence(
        task=task,
        request=request,
        signed_verdict=signed,
        verifier=verifier,
        control_plane_root=ROOT,
        base_branch=base_branch,
    )
    return task, request, signed, verifier, proposal


class DraftPrReadinessTests(unittest.TestCase):
    def test_proposal_embeds_exact_task_patch_receipt_and_signed_approval(self):
        task, request, signed, verifier, proposal = make_proposal()

        self.assertEqual(proposal.task.canonical_json(), task.canonical_json())
        self.assertEqual(proposal.repository, task.repository)
        self.assertEqual(proposal.base_sha, task.base_sha)
        self.assertEqual(proposal.staged_patch_sha256, request.staged_patch_sha256)
        self.assertEqual(proposal.staged_patch_bytes, request.staged_patch_bytes)
        self.assertEqual(proposal.receipt_sha256, request.receipt_sha256)
        self.assertEqual(proposal.semantic_review_request_sha256, request.sha256)
        self.assertEqual(
            proposal.signed_semantic_review_verdict_sha256,
            signed.sha256,
        )
        self.assertEqual(proposal.reviewer_actor_id, REVIEWER)
        self.assertEqual(proposal.reviewer_key_id, KEY_ID)
        self.assertEqual(
            proposal.proposal_policy_sha256,
            draft_pr_readiness_policy_sha256(),
        )
        self.assertTrue(proposal.draft)
        self.assertEqual(proposal.merge_authority, "human")
        self.assertTrue(proposal.head_branch.startswith("kaliv-draft/"))
        self.assertIn("draft pull-request proposal only", proposal.body)

        proposal.verify(
            task=task,
            verifier=verifier,
            control_plane_root=ROOT,
        )
        self.assertTrue(
            DraftPrReadinessGate.ready(
                proposal=proposal,
                task=task,
                verifier=verifier,
                control_plane_root=ROOT,
            )
        )

        restored = AuthenticatedDraftPrReadinessProposal.from_mapping(
            proposal.to_dict()
        )
        self.assertEqual(restored.canonical_json(), proposal.canonical_json())
        self.assertEqual(restored.sha256, proposal.sha256)

    def test_generation_is_deterministic_and_callers_cannot_supply_presentation(self):
        _, _, _, _, first = make_proposal(base_branch="main")
        _, _, _, _, second = make_proposal(base_branch="main")
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(first.sha256, second.sha256)

        parameters = set(
            inspect.signature(
                AuthenticatedDraftPrReadinessProposal.from_evidence
            ).parameters
        )
        for forbidden in (
            "repository",
            "head_branch",
            "title",
            "body",
            "draft",
            "merge_authority",
            "github",
            "pull_request",
            "command_id",
            "argv",
            "workspace_root",
        ):
            self.assertNotIn(forbidden, parameters)

        _, _, _, _, other_base = make_proposal(base_branch="release/candidate")
        self.assertEqual(other_base.base_branch, "release/candidate")
        self.assertNotEqual(other_base.body, first.body)
        self.assertEqual(other_base.head_branch, first.head_branch)

    def test_task_evidence_and_presentation_tampering_fail_closed(self):
        task, request, _, verifier, proposal = make_proposal()

        cases = []
        payload = proposal.to_dict()
        payload["task_sha256"] = "f" * 64
        cases.append(("task hash", payload))

        payload = proposal.to_dict()
        payload["staged_patch_sha256"] = "f" * 64
        cases.append(("identities", payload))

        payload = proposal.to_dict()
        payload["receipt_sha256"] = "f" * 64
        cases.append(("identities", payload))

        payload = proposal.to_dict()
        payload["semantic_review_request_sha256"] = "f" * 64
        cases.append(("request hash", payload))

        payload = proposal.to_dict()
        payload["signed_semantic_review_verdict_sha256"] = "f" * 64
        cases.append(("verdict hash", payload))

        payload = proposal.to_dict()
        payload["title"] = proposal.title + " altered"
        cases.append(("presentation", payload))

        payload = proposal.to_dict()
        payload["body"] = proposal.body + "\nInjected text."
        cases.append(("presentation", payload))

        payload = proposal.to_dict()
        payload["head_branch"] = "attacker/selected"
        cases.append(("head branch", payload))

        payload = proposal.to_dict()
        payload["draft"] = False
        cases.append(("authority", payload))

        payload = proposal.to_dict()
        payload["merge_authority"] = "model"
        cases.append(("authority", payload))

        for expected, altered in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(DraftPrReadinessError, expected):
                    AuthenticatedDraftPrReadinessProposal.from_mapping(altered)

        other_task = make_task("2" * 40)
        self.assertFalse(
            DraftPrReadinessGate.ready(
                proposal=proposal,
                task=other_task,
                verifier=verifier,
                control_plane_root=ROOT,
            )
        )

        request_payload = proposal.to_dict()
        request_payload["semantic_review_request"]["receipt_sha256"] = "e" * 64
        with self.assertRaisesRegex(ValueError, "receipt"):
            AuthenticatedDraftPrReadinessProposal.from_mapping(request_payload)

        wrong_secret_verifier = SemanticReviewVerifier(
            {KEY_ID: TrustedSemanticReviewerKey(REVIEWER, b"x" * 32)}
        )
        self.assertFalse(
            DraftPrReadinessGate.ready(
                proposal=proposal,
                task=task,
                verifier=wrong_secret_verifier,
                control_plane_root=ROOT,
            )
        )

    def test_nonapproval_untrusted_key_and_authority_drift_cannot_build(self):
        task, _, request = make_request()
        rejected = SemanticReviewVerdict.create(
            request=request,
            reviewer_actor_id=REVIEWER,
            reviewer_system_id="offline-semantic-reviewer-v1",
            decision=SemanticReviewDecision.REQUEST_CHANGES,
            criterion_assessments=assessments(
                request,
                CriterionOutcome.UNCERTAIN,
            ),
            findings=(
                SemanticFinding(
                    severity=FindingSeverity.HIGH,
                    title="Evidence gap",
                    detail="The exact evidence does not prove the criterion.",
                ),
            ),
        )
        rejected_signed = HmacSemanticReviewVerdictSigner(
            key_id=KEY_ID,
            reviewer_actor_id=REVIEWER,
            secret=SECRET,
        ).sign(rejected)
        verifier = SemanticReviewVerifier(
            {KEY_ID: TrustedSemanticReviewerKey(REVIEWER, SECRET)}
        )
        with self.assertRaisesRegex(DraftPrReadinessError, "did not approve"):
            AuthenticatedDraftPrReadinessProposal.from_evidence(
                task=task,
                request=request,
                signed_verdict=rejected_signed,
                verifier=verifier,
                control_plane_root=ROOT,
            )

        _, signed, _ = approve(request)
        wrong_verifier = SemanticReviewVerifier(
            {"different-key": TrustedSemanticReviewerKey(REVIEWER, SECRET)}
        )
        with self.assertRaisesRegex(DraftPrReadinessError, "not trusted"):
            AuthenticatedDraftPrReadinessProposal.from_evidence(
                task=task,
                request=request,
                signed_verdict=signed,
                verifier=wrong_verifier,
                control_plane_root=ROOT,
            )

        with patch(
            "kaliv_dev_control.semantic_review.tier_a_toolhost_sha256",
            return_value="0" * 64,
        ):
            with self.assertRaisesRegex(DraftPrReadinessError, "authority"):
                AuthenticatedDraftPrReadinessProposal.from_evidence(
                    task=task,
                    request=request,
                    signed_verdict=signed,
                    verifier=verifier,
                    control_plane_root=ROOT,
                )

    def test_canonical_file_roundtrip_refuses_overwrite_and_noncanonical_input(self):
        _, _, _, _, proposal = make_proposal()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "draft-pr-readiness.json"
            self.assertEqual(
                write_authenticated_draft_pr_readiness_proposal(
                    output,
                    proposal,
                ),
                proposal.sha256,
            )
            loaded = load_authenticated_draft_pr_readiness_proposal(output)
            self.assertEqual(loaded.canonical_json(), proposal.canonical_json())
            with self.assertRaisesRegex(DraftPrReadinessError, "already exists"):
                write_authenticated_draft_pr_readiness_proposal(output, proposal)

            noncanonical = root / "noncanonical.json"
            noncanonical.write_bytes(
                proposal.canonical_json().encode("utf-8") + b"\n"
            )
            with self.assertRaisesRegex(DraftPrReadinessError, "canonical"):
                load_authenticated_draft_pr_readiness_proposal(noncanonical)

    def test_schema_matches_artifact_and_module_has_no_write_adapter(self):
        _, _, _, _, proposal = make_proposal()
        schema = json.loads(
            (
                ROOT
                / "devcontrol/schemas/"
                "development-authenticated-draft-pr-readiness-proposal-v1.schema.json"
            ).read_text(encoding="utf-8")
        )
        fields = set(proposal.to_dict())
        self.assertEqual(set(schema["required"]), fields)
        self.assertEqual(set(schema["properties"]), fields)

        names = set(dir(readiness_module))
        for forbidden in (
            "create_pull_request",
            "update_pull_request",
            "push_branch",
            "merge_pull_request",
            "request_reviewers",
            "deploy",
            "release",
        ):
            self.assertNotIn(forbidden, names)

    def test_invalid_base_branch_fails_before_artifact_creation(self):
        task, _, request = make_request()
        _, signed, verifier = approve(request)
        for invalid in ("../main", "main..other", "/main", "main.lock"):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(
                    DraftPrReadinessError,
                    "canonical branch",
                ):
                    AuthenticatedDraftPrReadinessProposal.from_evidence(
                        task=task,
                        request=request,
                        signed_verdict=signed,
                        verifier=verifier,
                        control_plane_root=ROOT,
                        base_branch=invalid,
                    )


if __name__ == "__main__":
    unittest.main()

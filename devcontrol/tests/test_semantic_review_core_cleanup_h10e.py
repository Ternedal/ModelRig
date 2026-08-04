from __future__ import annotations

import inspect
import unittest

import kaliv_dev_control._semantic_review_core as core
import kaliv_dev_control.semantic_review as public


class SemanticReviewCoreCleanupH10ETests(unittest.TestCase):
    def test_public_and_core_models_keep_exact_identity(self) -> None:
        for name in (
            "SemanticReviewRequest",
            "CriterionAssessment",
            "SemanticFinding",
            "SemanticReviewVerdict",
            "SignedSemanticReviewVerdict",
            "HmacSemanticReviewVerdictSigner",
            "TrustedSemanticReviewerKey",
            "SemanticReviewVerifier",
            "SemanticReviewApprovalGate",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(public, name), getattr(core, name))

        self.assertIs(
            public.load_semantic_review_request,
            core.load_semantic_review_request,
        )
        self.assertIs(
            public.load_signed_semantic_review_verdict,
            core.load_signed_semantic_review_verdict,
        )

    def test_no_importable_semantic_review_module_contains_legacy_writer(self) -> None:
        forbidden = (
            "tempfile.mkstemp",
            "os.replace",
            "os.fsync",
        )
        for module in (core, public):
            source = inspect.getsource(module)
            for token in forbidden:
                with self.subTest(module=module.__name__, token=token):
                    self.assertNotIn(token, source)

        core_source = inspect.getsource(core)
        self.assertNotIn("def _write_canonical_file(", core_source)
        self.assertNotIn("def write_semantic_review_request(", core_source)
        self.assertNotIn("def write_signed_semantic_review_verdict(", core_source)

        public_source = inspect.getsource(public)
        self.assertEqual(public_source.count("def write_semantic_review_request("), 1)
        self.assertEqual(
            public_source.count("def write_signed_semantic_review_verdict("),
            1,
        )
        self.assertNotIn("vars(_core).pop", public_source)

    def test_core_is_model_loader_only_and_facade_owns_publication(self) -> None:
        self.assertFalse(hasattr(core, "_write_canonical_file"))
        self.assertFalse(hasattr(core, "write_semantic_review_request"))
        self.assertFalse(hasattr(core, "write_signed_semantic_review_verdict"))
        self.assertTrue(callable(core.load_semantic_review_request))
        self.assertTrue(callable(core.load_signed_semantic_review_verdict))
        self.assertTrue(callable(public.write_semantic_review_request))
        self.assertTrue(callable(public.write_signed_semantic_review_verdict))


if __name__ == "__main__":
    unittest.main()

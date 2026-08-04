from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control._semantic_review_core as semantic_core
import kaliv_dev_control.semantic_review as semantic_module
from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.semantic_review import (
    SemanticReviewError,
    load_semantic_review_request,
    load_signed_semantic_review_verdict,
    write_semantic_review_request,
    write_signed_semantic_review_verdict,
)
from test_slice10h_semantic_review import approve, make_request


class SemanticReviewDurablePublicationH10DTests(unittest.TestCase):
    @staticmethod
    def _cases():
        _, _, request = make_request()
        _, signed, _ = approve(request)
        return (
            (
                "semantic-review-request.json",
                request,
                write_semantic_review_request,
                load_semantic_review_request,
            ),
            (
                "signed-semantic-review-verdict.json",
                signed,
                write_signed_semantic_review_verdict,
                load_signed_semantic_review_verdict,
            ),
        )

    def test_both_artifacts_publish_byte_identically_and_reload_canonically(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for filename, value, writer, loader in self._cases():
                with self.subTest(filename=filename):
                    path = root / filename
                    payload = value.canonical_json().encode("utf-8")
                    self.assertEqual(writer(path, value), value.sha256)
                    self.assertEqual(path.read_bytes(), payload)
                    self.assertEqual(loader(path).sha256, value.sha256)

    def test_exactly_one_concurrent_writer_wins_for_every_artifact(self):
        for filename, value, writer, _ in self._cases():
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                path = root / filename
                barrier = threading.Barrier(24)

                def attempt() -> bool:
                    barrier.wait()
                    try:
                        writer(path, value)
                    except SemanticReviewError:
                        return False
                    return True

                with ThreadPoolExecutor(max_workers=24) as pool:
                    results = list(pool.map(lambda _: attempt(), range(24)))

                self.assertEqual(sum(results), 1)
                self.assertEqual(
                    path.read_bytes(),
                    value.canonical_json().encode("utf-8"),
                )
                self.assertEqual([item for item in root.iterdir() if item != path], [])

    def test_durability_failure_leaves_no_artifact_for_every_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for filename, value, writer, _ in self._cases():
                with self.subTest(filename=filename):
                    path = root / filename
                    with patch.object(
                        semantic_module,
                        "create_once_file",
                        side_effect=DurablePublicationError("injected failure"),
                    ):
                        with self.assertRaisesRegex(
                            SemanticReviewError,
                            "durably published",
                        ):
                            writer(path, value)
                    self.assertFalse(path.exists())
                    self.assertEqual(list(root.iterdir()), [])

    def test_link_output_is_rejected(self):
        _, value, writer, _ = self._cases()[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "semantic-review-request.json"
            try:
                path.symlink_to(root / "missing-target.json")
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(SemanticReviewError, "unsafe"):
                writer(path, value)
            self.assertTrue(path.is_symlink())

    def test_public_boundary_has_one_durable_writer_path(self):
        source = inspect.getsource(semantic_module)
        self.assertIn("create_once_file", source)
        self.assertIn("DurablePublicationError", source)
        self.assertNotIn("tempfile.mkstemp", source)
        self.assertNotIn("os.replace", source)
        self.assertNotIn("os.fsync", source)
        self.assertNotIn("prefix=\".semantic-", source)
        self.assertFalse(hasattr(semantic_core, "_write_canonical_file"))
        self.assertFalse(hasattr(semantic_core, "write_semantic_review_request"))
        self.assertFalse(
            hasattr(semantic_core, "write_signed_semantic_review_verdict")
        )

    def test_public_model_identity_and_patch_point_are_preserved(self):
        self.assertIs(
            semantic_module.SemanticReviewRequest,
            semantic_core.SemanticReviewRequest,
        )
        with patch.object(
            semantic_module,
            "tier_a_toolhost_sha256",
            return_value="a" * 64,
        ) as authority:
            make_request()
        authority.assert_called_once()


if __name__ == "__main__":
    unittest.main()

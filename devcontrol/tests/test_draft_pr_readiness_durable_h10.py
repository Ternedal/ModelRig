from __future__ import annotations

import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.draft_pr_readiness as readiness_module
from kaliv_dev_control.draft_pr_readiness import (
    DraftPrReadinessError,
    load_authenticated_draft_pr_readiness_proposal,
    write_authenticated_draft_pr_readiness_proposal,
)
from kaliv_dev_control.durable_publication import DurablePublicationError
from test_slice10i_draft_pr_readiness import make_proposal


class DraftPrReadinessDurableH10Tests(unittest.TestCase):
    def test_canonical_bytes_and_hash_are_unchanged(self):
        _, _, _, _, proposal = make_proposal()
        payload = proposal.canonical_json().encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "readiness.json"
            self.assertEqual(
                write_authenticated_draft_pr_readiness_proposal(
                    output,
                    proposal,
                ),
                proposal.sha256,
            )
            self.assertEqual(output.read_bytes(), payload)
            loaded = load_authenticated_draft_pr_readiness_proposal(output)
            self.assertEqual(loaded.canonical_json(), proposal.canonical_json())
            self.assertEqual(loaded.sha256, proposal.sha256)

        source = inspect.getsource(readiness_module)
        self.assertIn("create_once_file(output, payload)", source)
        self.assertNotIn("tempfile.mkstemp", source)
        self.assertNotIn("os.replace", source)

    def test_parallel_publication_has_exactly_one_winner(self):
        _, _, _, _, proposal = make_proposal()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "readiness.json"

            def publish() -> tuple[str, str]:
                try:
                    result = write_authenticated_draft_pr_readiness_proposal(
                        output,
                        proposal,
                    )
                    return ("success", result)
                except DraftPrReadinessError as exc:
                    return ("rejected", str(exc))

            with ThreadPoolExecutor(max_workers=12) as executor:
                results = list(executor.map(lambda _: publish(), range(24)))

            successes = [value for status, value in results if status == "success"]
            rejections = [value for status, value in results if status == "rejected"]
            self.assertEqual(successes, [proposal.sha256])
            self.assertEqual(len(rejections), 23)
            self.assertEqual(
                output.read_bytes(),
                proposal.canonical_json().encode("utf-8"),
            )
            self.assertEqual({path.name for path in root.iterdir()}, {output.name})

    def test_publication_failure_is_fail_closed_without_output(self):
        _, _, _, _, proposal = make_proposal()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "readiness.json"
            with patch.object(
                readiness_module,
                "create_once_file",
                side_effect=DurablePublicationError("simulated directory sync failure"),
            ):
                with self.assertRaisesRegex(
                    DraftPrReadinessError,
                    "could not be durably published",
                ):
                    write_authenticated_draft_pr_readiness_proposal(
                        output,
                        proposal,
                    )
            self.assertFalse(output.exists())
            self.assertFalse(output.is_symlink())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import inspect
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.physical_isolation as physical_module
from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.physical_isolation import (
    PhysicalIsolationError,
    SignedWindowsIsolationReport,
    write_signed_report,
)
from test_slice6 import signed_report


class PhysicalIsolationDurablePublicationH10BTests(unittest.TestCase):
    def test_publication_preserves_exact_canonical_bytes_and_hash(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "signed-isolation.json"
            self.assertEqual(write_signed_report(output, evidence), evidence.sha256)
            self.assertEqual(
                output.read_bytes(),
                evidence.canonical_json().encode("utf-8"),
            )
            loaded = SignedWindowsIsolationReport.from_mapping(
                __import__("json").loads(output.read_text(encoding="utf-8"))
            )
            self.assertEqual(loaded.canonical_json(), evidence.canonical_json())
            self.assertEqual(loaded.sha256, evidence.sha256)

    def test_parallel_publication_has_exactly_one_winner(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            output = root / "signed-isolation.json"

            def publish(_: int) -> tuple[str, str]:
                try:
                    return ("ok", write_signed_report(output, evidence))
                except PhysicalIsolationError as exc:
                    return ("error", str(exc))

            with ThreadPoolExecutor(max_workers=24) as executor:
                results = tuple(executor.map(publish, range(24)))

            winners = tuple(value for status, value in results if status == "ok")
            losers = tuple(value for status, value in results if status == "error")
            self.assertEqual(winners, (evidence.sha256,))
            self.assertEqual(len(losers), 23)
            self.assertTrue(
                all(
                    "already exists" in message
                    or "durably published" in message
                    for message in losers
                )
            )
            self.assertEqual(
                output.read_bytes(),
                evidence.canonical_json().encode("utf-8"),
            )
            self.assertEqual(tuple(root.iterdir()), (output,))

    def test_durability_failure_leaves_no_artifact(self):
        evidence = signed_report()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory).resolve() / "signed-isolation.json"
            with patch.object(
                physical_module,
                "create_once_file",
                side_effect=DurablePublicationError("simulated durability failure"),
            ):
                with self.assertRaisesRegex(
                    PhysicalIsolationError,
                    "durably published",
                ):
                    write_signed_report(output, evidence)
            self.assertFalse(output.exists())
            self.assertFalse(output.is_symlink())

    def test_writer_uses_shared_durable_primitive_not_replace(self):
        source = inspect.getsource(physical_module)
        writer_source = inspect.getsource(write_signed_report)
        self.assertIn("create_once_file(output, payload)", writer_source)
        self.assertNotIn("os.replace(", source)
        self.assertNotIn("tempfile.mkstemp(", source)


if __name__ == "__main__":
    unittest.main()

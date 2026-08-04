from __future__ import annotations

import inspect
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import kaliv_dev_control.publisher_dry_run as publisher_module
from kaliv_dev_control.durable_publication import DurablePublicationError
from kaliv_dev_control.publisher_dry_run import (
    PublisherDryRunError,
    load_publisher_dry_run_receipt,
    load_publisher_request,
    load_signed_publisher_request,
    write_publisher_dry_run_receipt,
    write_publisher_request,
    write_signed_publisher_request,
)
from test_slice10j_publisher_dry_run import make_artifacts


class PublisherDryRunDurablePublicationH10CTests(unittest.TestCase):
    @staticmethod
    def _cases():
        _, _, _, request, signed, _, receipt = make_artifacts()
        return (
            (
                "publisher-request.json",
                request,
                write_publisher_request,
                load_publisher_request,
            ),
            (
                "signed-publisher-request.json",
                signed,
                write_signed_publisher_request,
                load_signed_publisher_request,
            ),
            (
                "publisher-dry-run-receipt.json",
                receipt,
                write_publisher_dry_run_receipt,
                load_publisher_dry_run_receipt,
            ),
        )

    def test_all_artifacts_publish_byte_identically_and_reload_canonically(self):
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
                    except PublisherDryRunError:
                        return False
                    return True

                with ThreadPoolExecutor(max_workers=24) as pool:
                    results = list(pool.map(lambda _: attempt(), range(24)))

                self.assertEqual(sum(results), 1)
                self.assertEqual(path.read_bytes(), value.canonical_json().encode("utf-8"))
                self.assertEqual([item for item in root.iterdir() if item != path], [])

    def test_durability_failure_leaves_no_artifact_for_every_type(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for filename, value, writer, _ in self._cases():
                with self.subTest(filename=filename):
                    path = root / filename
                    with patch.object(
                        publisher_module,
                        "create_once_file",
                        side_effect=DurablePublicationError("injected failure"),
                    ):
                        with self.assertRaisesRegex(PublisherDryRunError, "durably published"):
                            writer(path, value)
                    self.assertFalse(path.exists())
                    self.assertEqual(list(root.iterdir()), [])

    def test_link_output_is_rejected(self):
        _, value, writer, _ = self._cases()[0]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            path = root / "publisher-request.json"
            try:
                path.symlink_to(root / "missing-target.json")
            except OSError as exc:
                self.skipTest(f"symlink creation is unavailable: {exc}")
            with self.assertRaisesRegex(PublisherDryRunError, "unsafe"):
                writer(path, value)
            self.assertTrue(path.is_symlink())

    def test_legacy_replace_writer_is_physically_absent(self):
        source = inspect.getsource(publisher_module)
        self.assertIn("create_once_file", source)
        self.assertIn("DurablePublicationError", source)
        self.assertNotIn("tempfile.mkstemp", source)
        self.assertNotIn("os.replace", source)
        self.assertNotIn("os.fsync", source)
        self.assertNotIn("prefix=\".publisher-", source)


if __name__ == "__main__":
    unittest.main()

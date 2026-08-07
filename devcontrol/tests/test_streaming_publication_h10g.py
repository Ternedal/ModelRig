from __future__ import annotations

import hashlib
import inspect
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from kaliv_dev_control.streaming_publication import (
    StreamingPublicationError,
    publish_stream_once,
)


class StreamingPublicationH10GTests(unittest.TestCase):
    @staticmethod
    def _validator(expected: bytes):
        digest = hashlib.sha256(expected).hexdigest()

        def validate(path: Path) -> None:
            if not path.is_file() or path.read_bytes() != expected:
                raise ValueError("concurrent destination differs")
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError("concurrent destination hash differs")

        return validate

    def test_streams_exact_bytes_and_reports_the_single_publisher(self) -> None:
        payload = b"streamed immutable runtime\n" * 1024
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)

            published = publish_stream_once(
                source,
                destination,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
                expected_size=len(payload),
                maximum=len(payload),
                validate_existing=self._validator(payload),
            )

            self.assertTrue(published)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(
                sorted(item.name for item in root.iterdir()),
                ["final.bin", "source.bin"],
            )

    def test_parallel_same_content_has_exactly_one_winner(self) -> None:
        payload = b"one exact concurrent runtime\n" * 128
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)
            barrier = threading.Barrier(24)

            def attempt() -> bool:
                barrier.wait()
                return publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                    expected_size=len(payload),
                    maximum=len(payload),
                    validate_existing=self._validator(payload),
                    sync_parent_on_race=True,
                )

            with ThreadPoolExecutor(max_workers=24) as pool:
                results = list(pool.map(lambda _: attempt(), range(24)))

            self.assertEqual(sum(results), 1)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertEqual(
                sorted(item.name for item in root.iterdir()),
                ["final.bin", "source.bin"],
            )

    def test_concurrent_different_content_fails_without_replacement(self) -> None:
        payload = b"expected"
        existing = b"different"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)
            destination.write_bytes(existing)

            with self.assertRaisesRegex(ValueError, "differs"):
                publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                    expected_size=len(payload),
                    maximum=len(payload),
                    validate_existing=self._validator(payload),
                )
            self.assertEqual(destination.read_bytes(), existing)

    def test_source_change_and_invalid_budget_fail_without_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(b"12345")

            with self.assertRaisesRegex(StreamingPublicationError, "invalid_inputs"):
                publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(b"12345").hexdigest(),
                    expected_size=5,
                    maximum=4,
                    validate_existing=self._validator(b"12345"),
                )
            self.assertFalse(destination.exists())

            with self.assertRaisesRegex(StreamingPublicationError, "source_changed"):
                publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(b"other").hexdigest(),
                    expected_size=5,
                    maximum=5,
                    validate_existing=self._validator(b"other"),
                )
            self.assertFalse(destination.exists())

    def test_temporary_preparer_metadata_is_synced_before_publication(self) -> None:
        payload = b"permission callback"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)
            observed: list[Path] = []
            events: list[str] = []
            original_link = os.link

            def prepare(path: Path) -> None:
                self.assertTrue(path.is_file())
                self.assertFalse(destination.exists())
                observed.append(path)
                events.append("prepare")

            def sync(path: Path) -> None:
                self.assertEqual(path, observed[0])
                self.assertFalse(destination.exists())
                events.append("sync")

            def link(source_path: Path, destination_path: Path) -> None:
                self.assertEqual(Path(source_path), observed[0])
                events.append("link")
                original_link(source_path, destination_path)

            with mock.patch(
                "kaliv_dev_control.streaming_publication.sync_file",
                side_effect=sync,
            ), mock.patch(
                "kaliv_dev_control.streaming_publication.os.link",
                side_effect=link,
            ):
                self.assertTrue(
                    publish_stream_once(
                        source,
                        destination,
                        expected_sha256=hashlib.sha256(payload).hexdigest(),
                        expected_size=len(payload),
                        maximum=len(payload),
                        validate_existing=self._validator(payload),
                        prepare_temporary=prepare,
                    )
                )
            self.assertEqual(events, ["prepare", "sync", "link"])
            self.assertEqual(len(observed), 1)
            self.assertFalse(observed[0].exists())

    def test_permission_metadata_sync_failure_is_fail_closed(self) -> None:
        payload = b"permission durability"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)

            with mock.patch(
                "kaliv_dev_control.streaming_publication.sync_file",
                side_effect=StreamingPublicationError("injected"),
            ):
                with self.assertRaisesRegex(
                    StreamingPublicationError,
                    "permission_metadata_sync_failed",
                ):
                    publish_stream_once(
                        source,
                        destination,
                        expected_sha256=hashlib.sha256(payload).hexdigest(),
                        expected_size=len(payload),
                        maximum=len(payload),
                        validate_existing=self._validator(payload),
                        prepare_temporary=lambda path: path.chmod(0o500),
                    )
            self.assertFalse(destination.exists())
            self.assertEqual(
                sorted(item.name for item in root.iterdir()),
                ["source.bin"],
            )

    def test_durability_failure_is_domain_error_without_temp_sibling(self) -> None:
        payload = b"durability"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)
            with mock.patch(
                "kaliv_dev_control.streaming_publication.sync_directory",
                side_effect=StreamingPublicationError("injected"),
            ):
                with self.assertRaisesRegex(
                    StreamingPublicationError,
                    "directory_sync_failed",
                ):
                    publish_stream_once(
                        source,
                        destination,
                        expected_sha256=hashlib.sha256(payload).hexdigest(),
                        expected_size=len(payload),
                        maximum=len(payload),
                        validate_existing=self._validator(payload),
                    )
            self.assertTrue(destination.is_file())
            self.assertEqual(
                sorted(item.name for item in root.iterdir()),
                ["final.bin", "source.bin"],
            )

    def test_implementation_is_streaming_and_never_replaces(self) -> None:
        source = inspect.getsource(publish_stream_once)
        self.assertIn('input_file.read(1024 * 1024)', source)
        self.assertIn("sync_file(temporary)", source)
        self.assertIn("os.link", source)
        self.assertNotIn("read_bytes", source)
        self.assertNotIn("os.replace", source)


if __name__ == "__main__":
    unittest.main()

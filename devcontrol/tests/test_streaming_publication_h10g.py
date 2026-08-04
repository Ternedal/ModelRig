from __future__ import annotations

import hashlib
import inspect
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

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
                [item.name for item in root.iterdir()],
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
                [item.name for item in root.iterdir()],
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

    def test_budget_and_source_change_fail_without_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(b"12345")

            with self.assertRaisesRegex(
                StreamingPublicationError,
                "invalid_inputs",
            ):
                publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(b"12345").hexdigest(),
                    expected_size=5,
                    maximum=4,
                    validate_existing=self._validator(b"12345"),
                )
            self.assertFalse(destination.exists())

            with self.assertRaisesRegex(
                StreamingPublicationError,
                "source_changed",
            ):
                publish_stream_once(
                    source,
                    destination,
                    expected_sha256=hashlib.sha256(b"other").hexdigest(),
                    expected_size=5,
                    maximum=5,
                    validate_existing=self._validator(b"other"),
                )
            self.assertFalse(destination.exists())

    def test_temporary_preparer_runs_before_publication(self) -> None:
        payload = b"permission callback"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source.bin"
            destination = root / "final.bin"
            source.write_bytes(payload)
            observed: list[Path] = []

            def prepare(path: Path) -> None:
                self.assertTrue(path.is_file())
                self.assertFalse(destination.exists())
                observed.append(path)

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
            self.assertEqual(len(observed), 1)
            self.assertFalse(observed[0].exists())

    def test_implementation_is_streaming_and_never_replaces(self) -> None:
        source = inspect.getsource(publish_stream_once)
        self.assertIn("input_file.read(1024 * 1024)", source)
        self.assertIn("os.link", source)
        self.assertNotIn("read_bytes", source)
        self.assertNotIn("os.replace", source)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""The staged-sink conformance suite, run against a reference sink and against broken ones.

The reference sink here is test scaffolding, not the storage implementation
(ChatGPT owns that, #2296 6494148463). It shows the rules are satisfiable and
that the suite catches sinks that break them.

Run: PYTHONPATH=worker python3 tests/worker_staged_sink_conformance.py
"""
from __future__ import annotations

import contextlib
import io
import os
import secrets
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests" / "support"))

from app.media_generation_contract import ArtifactSinkUnavailable, StagedFileArtifactSink  # noqa: E402
from staged_sink_conformance import MP4, StagedSinkConformance  # noqa: E402


class _Writer:
    """Write-only handle: no name, no fileno, so the generator never learns the path."""

    def __init__(self, fh, sink, ticket):
        self._fh, self._sink, self._ticket = fh, sink, ticket

    def write(self, data: bytes) -> int:
        return self._fh.write(data)

    def flush(self) -> None:
        self._fh.flush()


class ReferenceSink:
    def __init__(self, root: str, max_bytes: int):
        self.staging = Path(root, "staging")
        self.store = Path(root, "store")
        self.staging.mkdir()
        self.store.mkdir()
        self.max_bytes = max_bytes
        self.registry: set[str] = set()
        self._live: dict[str, Path] = {}
        self.volume_present = True
        self.fail_registration = False

    def _require_volume(self):
        if not self.volume_present:
            raise ArtifactSinkUnavailable("external media volume is not mounted")

    @contextlib.contextmanager
    def staged(self, extension: str):
        if extension != ".mp4":
            raise ValueError("only .mp4 is staged")
        self._require_volume()
        ticket = secrets.token_hex(8)
        path = self.staging / f"{ticket}.mp4.part"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        fh = os.fdopen(fd, "wb")
        self._live[ticket] = path
        writer = _Writer(fh, self, ticket)
        try:
            yield writer
        finally:
            self._live.pop(ticket, None)
            fh.close()
            path.unlink(missing_ok=True)

    def adopt(self, handle, mime_type: str) -> str:
        if not isinstance(handle, _Writer) or handle._sink is not self or handle._ticket not in self._live:
            raise ValueError("not a live handle from this sink")
        if mime_type != "video/mp4":
            raise ValueError("only video/mp4")
        self._require_volume()
        path = self._live.pop(handle._ticket)  # one adoption per handle
        handle._fh.flush()
        os.fsync(handle._fh.fileno())
        size = path.stat().st_size
        if not 12 <= size <= self.max_bytes:
            raise ValueError("size out of bounds")
        with open(path, "rb") as fh:
            if fh.read(12)[4:8] != b"ftyp":
                raise ValueError("not an MP4")
        asset_id = secrets.token_hex(16)
        target = self.store / f"{asset_id}.mp4"
        os.replace(path, target)  # atomic, same filesystem
        if self.fail_registration:  # registration failed: clean up, never report success
            self.fail_registration = False
            target.unlink(missing_ok=True)
            raise OSError("catalog registration failed")
        self.registry.add(asset_id)  # "durable registration" for the reference
        return asset_id


class ReferenceConformance(StagedSinkConformance, unittest.TestCase):
    max_bytes = 4096

    def setUp(self):
        self.roots = []

    def tearDown(self):
        for root in self.roots:
            shutil.rmtree(root, ignore_errors=True)

    def make_sink(self):
        root = tempfile.mkdtemp()
        self.roots.append(root)
        return ReferenceSink(root, self.max_bytes)

    def published(self, sink):
        on_disk = {p.stem for p in sink.store.iterdir()}
        return sink.registry & on_disk

    def staging_leftovers(self, sink):
        return sorted(p.name for p in sink.staging.iterdir())

    def make_volume_unavailable(self, sink):
        sink.volume_present = False

    def fail_next_registration(self, sink):
        sink.fail_registration = True

    def test_reference_satisfies_the_protocol(self):
        self.assertIsInstance(self.make_sink(), StagedFileArtifactSink)


# --- broken sinks: each must fail the suite ------------------------------------------------
class DeletesOnExit(ReferenceSink):
    """Leaving the context deletes the promoted asset too."""

    @contextlib.contextmanager
    def staged(self, extension):
        with super().staged(extension) as writer:
            yield writer
        for asset in list(self.registry):
            (self.store / f"{asset}.mp4").unlink(missing_ok=True)
            self.registry.discard(asset)


class AdoptsTwice(ReferenceSink):
    """Forgets that a handle was adopted: a second adopt() publishes a second asset."""

    def adopt(self, handle, mime_type):
        asset = super().adopt(handle, mime_type)
        again = self.staging / f"{handle._ticket}.again"
        shutil.copyfile(self.store / f"{asset}.mp4", again)
        self._live[handle._ticket] = again
        return asset


class AcceptsForeign(ReferenceSink):
    def adopt(self, handle, mime_type):
        if isinstance(handle, _Writer) and handle._sink is not self:
            handle._sink, self._live[handle._ticket] = self, handle._sink._live[handle._ticket]
        return super().adopt(handle, mime_type)


class AnyMime(ReferenceSink):
    def adopt(self, handle, mime_type):
        return super().adopt(handle, "video/mp4")


class NoSizeBound(ReferenceSink):
    def __init__(self, root, max_bytes):
        super().__init__(root, 10 ** 12)


class LeavesStagingBehind(ReferenceSink):
    @contextlib.contextmanager
    def staged(self, extension):
        if extension != ".mp4":
            raise ValueError("only .mp4")
        path = self.staging / f"{secrets.token_hex(8)}.mp4.part"
        fh = open(path, "wb")
        ticket = path.stem
        self._live[ticket] = path
        yield _Writer(fh, self, ticket)
        fh.close()


class FallsBackWhenTheVolumeIsGone(ReferenceSink):
    def _require_volume(self):
        pass  # keeps writing to wherever it is: the forbidden fallback


class ExposesUnindexedAssets(ReferenceSink):
    def adopt(self, handle, mime_type):
        if self.fail_registration:
            self.fail_registration = False
            path = self._live.pop(handle._ticket)
            asset = secrets.token_hex(16)
            os.replace(path, self.store / f"{asset}.mp4")
            self.registry.add(asset)  # reported nowhere, but visible as published
            raise OSError("catalog registration failed")
        return super().adopt(handle, mime_type)


class ExposesPath(ReferenceSink):
    @contextlib.contextmanager
    def staged(self, extension):
        with super().staged(extension) as writer:
            writer.name = str(self._live[writer._ticket])
            yield writer


class BrokenSinksFailTheSuite(unittest.TestCase):
    def run_suite_against(self, sink_class) -> int:
        class Case(ReferenceConformance):
            def make_sink(self):
                root = tempfile.mkdtemp()
                self.roots.append(root)
                return sink_class(root, self.max_bytes)

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Case)
        result = unittest.TestResult()
        suite.run(result)
        return len(result.failures) + len(result.errors)

    def test_each_broken_sink_is_caught(self):
        for broken in (DeletesOnExit, AdoptsTwice, AcceptsForeign, AnyMime, NoSizeBound,
                       LeavesStagingBehind, ExposesPath, FallsBackWhenTheVolumeIsGone, ExposesUnindexedAssets):
            with self.subTest(sink=broken.__name__):
                self.assertGreater(self.run_suite_against(broken), 0, f"{broken.__name__} passed the suite")

    def test_the_reference_passes(self):
        self.assertEqual(self.run_suite_against(ReferenceSink), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

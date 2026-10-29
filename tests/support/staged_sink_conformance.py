"""Conformance tests for a StagedFileArtifactSink (ModelRig #2296 slice 2, seam 6494148463).

ChatGPT implements the storage side; this suite encodes the seam's rules so an
implementation can be checked against them. Mix it into a unittest.TestCase:

    class MySinkConformance(StagedSinkConformance, unittest.TestCase):
        max_bytes = 1024 * 1024
        def make_sink(self): ...            # a fresh sink on a fresh verified volume
        def published(self, sink): ...      # asset ids durably registered (a set)
        def staging_leftovers(self, sink):  # files still in the staging area (a list)

tests/worker_staged_sink_conformance.py runs it against a reference sink and
shows that broken sinks fail it.
"""
from __future__ import annotations

import io
import os

MP4 = b"\x00\x00\x00\x18ftypisom\x00\x00\x02\x00isomiso2" + b"\x00" * 64


class Boom(Exception):
    pass


class StagedSinkConformance:
    max_bytes: int

    # -- to implement -----------------------------------------------------------
    def make_sink(self):  # pragma: no cover - abstract
        raise NotImplementedError

    def published(self, sink) -> set:  # pragma: no cover - abstract
        raise NotImplementedError

    def staging_leftovers(self, sink) -> list:  # pragma: no cover - abstract
        raise NotImplementedError

    # -- the rules ----------------------------------------------------------------
    def test_adopt_inside_the_context_publishes_and_survives_leaving_it(self):
        sink = self.make_sink()
        with sink.staged(".mp4") as output:
            output.write(MP4)
            asset_id = sink.adopt(output, "video/mp4")
        self.assertIsInstance(asset_id, str)
        self.assertTrue(asset_id)
        self.assertEqual(self.published(sink), {asset_id}, "leaving the context must not delete the promoted asset")
        self.assertEqual(self.staging_leftovers(sink), [])

    def test_leaving_without_adopt_publishes_nothing_and_cleans_up(self):
        sink = self.make_sink()
        with sink.staged(".mp4") as output:
            output.write(MP4)
        self.assertEqual(self.published(sink), set())
        self.assertEqual(self.staging_leftovers(sink), [])

    def test_an_error_before_adopt_publishes_nothing_and_cleans_up(self):
        sink = self.make_sink()
        with self.assertRaises(Boom):
            with sink.staged(".mp4") as output:
                output.write(MP4[:20])  # a partially written MP4
                raise Boom()
        self.assertEqual(self.published(sink), set())
        self.assertEqual(self.staging_leftovers(sink), [])

    def test_an_error_after_adopt_keeps_the_durably_registered_asset(self):
        sink = self.make_sink()
        with self.assertRaises(Boom):
            with sink.staged(".mp4") as output:
                output.write(MP4)
                asset_id = sink.adopt(output, "video/mp4")
                raise Boom()  # e.g. the job transition failed afterwards
        self.assertEqual(self.published(sink), {asset_id})
        self.assertEqual(self.staging_leftovers(sink), [])

    def test_a_second_adopt_is_refused(self):
        sink = self.make_sink()
        with sink.staged(".mp4") as output:
            output.write(MP4)
            first = sink.adopt(output, "video/mp4")
            with self.assertRaises(Exception):
                sink.adopt(output, "video/mp4")
        self.assertEqual(self.published(sink), {first})

    def test_a_foreign_handle_is_refused(self):
        sink, other = self.make_sink(), self.make_sink()
        with other.staged(".mp4") as foreign:
            foreign.write(MP4)
            with self.assertRaises(Exception):
                sink.adopt(foreign, "video/mp4")
        with self.assertRaises(Exception):
            sink.adopt(io.BytesIO(MP4), "video/mp4")
        self.assertEqual(self.published(sink), set())
        self.assertEqual(self.published(other), set())

    def test_adopt_after_leaving_the_context_is_refused(self):
        sink = self.make_sink()
        with sink.staged(".mp4") as output:
            output.write(MP4)
        with self.assertRaises(Exception):
            sink.adopt(output, "video/mp4")
        self.assertEqual(self.published(sink), set())

    def test_only_video_mp4(self):
        for mime in ("image/png", "video/webm", "video/mp4; codecs=avc1", "VIDEO/MP4", "", None):
            with self.subTest(mime=mime):
                sink = self.make_sink()
                with sink.staged(".mp4") as output:
                    output.write(MP4)
                    with self.assertRaises(Exception):
                        sink.adopt(output, mime)
                self.assertEqual(self.published(sink), set())
                self.assertEqual(self.staging_leftovers(sink), [])

    def test_only_mp4_staging(self):
        for extension in (".png", ".MP4", "mp4", ".mp4/../x", ""):
            with self.subTest(extension=extension):
                sink = self.make_sink()
                with self.assertRaises(Exception):
                    with sink.staged(extension):
                        pass
                self.assertEqual(self.staging_leftovers(sink), [])

    def test_size_bounds(self):
        for data in (b"", MP4[:4], MP4 + b"\x00" * (self.max_bytes - len(MP4) + 1)):
            with self.subTest(size=len(data)):
                sink = self.make_sink()
                with sink.staged(".mp4") as output:
                    output.write(data)
                    with self.assertRaises(Exception):
                        sink.adopt(output, "video/mp4")
                self.assertEqual(self.published(sink), set())
                self.assertEqual(self.staging_leftovers(sink), [])

    def test_the_generator_never_sees_a_path(self):
        sink = self.make_sink()
        with sink.staged(".mp4") as output:
            name = getattr(output, "name", None)
            self.assertFalse(isinstance(name, (str, bytes)) and os.path.exists(name),
                             "the handle must not expose the staging path")
            self.assertFalse(hasattr(output, "fileno"), "no descriptor either (it resolves to the path)")
            output.write(MP4)
            sink.adopt(output, "video/mp4")

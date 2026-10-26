"""Regression specification for the ASR startup prewarm race.

This test is intentionally isolated from production startup wiring. It can be
used when a readiness-aware prewarm implementation is proposed. No GPU required.
"""
import os
import sys
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'worker'))
from app import voice_asr


class ASRStartupRaceTests(unittest.TestCase):
    def test_model_load_failure_does_not_publish_partial_model(self):
        original_model = voice_asr._model
        original_error = voice_asr._load_error
        voice_asr._model = None
        from types import SimpleNamespace

        class FailingWhisperModel:
            def __init__(self, *args, **kwargs):
                raise RuntimeError("simulated CUDA failure")

        try:
            with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=FailingWhisperModel)}), \
                 patch.object(voice_asr, "_device", return_value="cuda"), \
                 patch.object(voice_asr, "_model_name", return_value="large-v3"), \
                 patch.object(voice_asr, "_compute_type", return_value="int8"), \
                 patch.object(voice_asr, "_add_cuda_dll_dirs", return_value=[]):
                with self.assertRaisesRegex(RuntimeError, "simulated CUDA failure"):
                    voice_asr._get_model()
                self.assertIsNone(voice_asr._model)
                self.assertIn("simulated CUDA failure", voice_asr._load_error)
        finally:
            voice_asr._model = original_model
            voice_asr._load_error = original_error

    def test_concurrent_model_requests_construct_once(self):
        original = voice_asr._model
        original_error = voice_asr._load_error
        voice_asr._model = None
        calls = []
        constructed = object()

        class FakeWhisperModel:
            def __new__(cls, *args, **kwargs):
                calls.append((args, kwargs))
                time.sleep(0.02)
                return constructed

        import sys
        from types import SimpleNamespace
        try:
            with patch.dict(sys.modules, {"faster_whisper": SimpleNamespace(WhisperModel=FakeWhisperModel)}), \
                 patch.object(voice_asr, "_device", return_value="cpu"), \
                 patch.object(voice_asr, "_model_name", return_value="small"), \
                 patch.object(voice_asr, "_compute_type", return_value="int8"):
                results = []
                errors = []
                def request():
                    try:
                        results.append(voice_asr._get_model())
                    except Exception as exc:
                        errors.append(exc)
                threads = [threading.Thread(target=request) for _ in range(8)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=3)
                self.assertTrue(all(not thread.is_alive() for thread in threads))
                self.assertEqual(errors, [])
                self.assertEqual(len(calls), 1)
                self.assertEqual(len(results), 8)
                self.assertTrue(all(result is constructed for result in results))
        finally:
            voice_asr._model = original
            voice_asr._load_error = original_error


class ASRImportStatusTests(unittest.TestCase):
    def test_native_import_failure_is_visible_in_worker_log(self):
        # Simulate a broken native dependency, not a model download or GPU load.
        import builtins
        original_import = builtins.__import__

        def block_native_import(name, *args, **kwargs):
            if name == "faster_whisper":
                raise ImportError("missing native dependency for ASR")
            return original_import(name, *args, **kwargs)

        with (
            patch("builtins.__import__", side_effect=block_native_import),
            self.assertLogs("modelrig.worker", level="WARNING") as captured,
        ):
            result = voice_asr.status()

        self.assertFalse(result["ok"])
        self.assertIsNone(result["model"])
        self.assertIsNone(result["device"])
        self.assertIn("native dependency", result["detail"])
        self.assertNotIn("missing native dependency for ASR", result["detail"])
        self.assertTrue(any("ImportError" in line and "missing native dependency" in line
                            for line in captured.output))


if __name__ == "__main__":
    unittest.main()

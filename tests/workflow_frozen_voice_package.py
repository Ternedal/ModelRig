"""Importable ASR must not hide missing frozen CUDA/VAD payloads."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_frozen_voice_package import validate_entries  # noqa: E402

CUDA = [
    "nvidia/cublas/bin/cublas64_12.dll",
    "nvidia/cublas/bin/cublasLt64_12.dll",
    "nvidia/cudnn/bin/cudnn64_9.dll",
    "nvidia/cudnn/bin/cudnn_ops64_9.dll",
]
VAD = "faster_whisper/assets/silero_vad_v6.onnx"


class FrozenVoicePayloadTests(unittest.TestCase):
    def test_importable_engines_without_cuda_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "lacks CUDA runtime"):
            validate_entries(["faster_whisper/__init__.py", "piper/__init__.py", VAD], CUDA)

    def test_all_upstream_cuda_dlls_are_required(self):
        with self.assertRaisesRegex(RuntimeError, "cudnn_ops64_9.dll"):
            validate_entries(CUDA[:-1] + [VAD], CUDA)

    def test_missing_vad_model_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Silero VAD"):
            validate_entries(CUDA, CUDA)

    def test_missing_build_side_cuda_wheels_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "build environment"):
            validate_entries(CUDA + [VAD], [])

    def test_dlls_must_be_in_the_registered_namespace_directories(self):
        with self.assertRaisesRegex(RuntimeError, "lacks CUDA runtime"):
            validate_entries([path.rsplit("/", 1)[-1] for path in CUDA] + [VAD], CUDA)

    def test_complete_windows_archive_accepts_case_and_slash_variants(self):
        report = validate_entries([path.upper().replace("/", "\\") for path in CUDA + [VAD]], CUDA)
        self.assertEqual(report["cuda_dlls"], len(CUDA))
        self.assertEqual(len(report["vad_models"]), 1)


if __name__ == "__main__":
    unittest.main()

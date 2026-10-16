"""Frozen Kaliv worker: reuse paired CUDA 12 libraries without a global install.

Runs on Linux CI with a synthetic Windows-style venv tree and a mocked
add_dll_directory; the real CUDA inference is a separate physical gate.
"""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "worker"))
from app import voice_asr  # noqa: E402


def check(ok: bool, message: str) -> None:
    if not ok:
        raise AssertionError(message)
    print("  PASS:", message)


with tempfile.TemporaryDirectory(prefix="kaliv-cuda-discovery-") as tmp:
    root = Path(tmp)
    venvs = root / "venvs"
    good = venvs / "KalivVoice-v1" / "Lib" / "site-packages"
    cublas = good / "nvidia" / "cublas" / "bin"
    cudnn = good / "ctranslate2"
    cublas.mkdir(parents=True)
    cudnn.mkdir(parents=True)
    (cublas / "cublas64_12.dll").write_bytes(b"test-only")
    (cudnn / "cudnn64_9.dll").write_bytes(b"test-only")

    # A half-installed venv must not supply a cuBLAS/cuDNN cross-venv mix.
    incomplete = venvs / "A-incomplete" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin"
    incomplete.mkdir(parents=True)
    (incomplete / "cublas64_12.dll").write_bytes(b"test-only")

    exe = root / "test" / "kaliv" / "modelrig-worker-windows-x64.exe"
    exe.parent.mkdir(parents=True)
    explicit = root / "extra-cuda"
    explicit.mkdir()

    env_patch = {
        "MODELRIG_VENVS_DIR": str(venvs),
        "KALIV_CUDA_DLL_DIRS": str(explicit),
    }
    with mock.patch.dict(os.environ, env_patch), mock.patch.object(sys, "executable", str(exe)):
        dirs = voice_asr._candidate_cuda_dll_dirs()
        # Windows Path.resolve() may expand 8.3 temp paths and normalize case.
        # Compare canonical paths rather than their pre-resolve spelling.
        canonical = {os.path.normcase(str(Path(d).resolve())) for d in dirs}
        def found(path):
            return os.path.normcase(str(path.resolve())) in canonical

        print("CUDA discovery:", dirs)
        check(found(cublas) and found(cudnn),
              "frozen worker discovers CUDA 12 cuBLAS and cuDNN 9 in a rig venv")
        check(not found(incomplete),
              "incomplete venv cannot mix CUDA DLLs with another environment")
        check(found(explicit), "explicit Kaliv CUDA directory is supported")

        old_path = os.environ.get("PATH", "")
        old_added = voice_asr._dll_dirs_added
        old_dirs = list(voice_asr._registered_dll_dirs)
        old_handles = list(voice_asr._dll_directory_handles)
        handles = []
        try:
            voice_asr._dll_dirs_added = False
            voice_asr._registered_dll_dirs.clear()
            voice_asr._dll_directory_handles.clear()

            def add_dir(directory):
                handles.append(directory)
                return object()

            with mock.patch.object(os, "add_dll_directory", side_effect=add_dir, create=True):
                result = voice_asr._add_cuda_dll_dirs()
                check(os.path.normcase(str(cublas.resolve())) in
                      {os.path.normcase(str(Path(d).resolve())) for d in result} and
                      os.path.normcase(str(cudnn.resolve())) in
                      {os.path.normcase(str(Path(d).resolve())) for d in result},
                      "CUDA directories registered at first model load")
                check(os.environ["PATH"].split(os.pathsep)[:len(result)] == result,
                      "CUDA DLLs are prepended to process-local PATH")
                check(len(voice_asr._dll_directory_handles) == len(result),
                      "DLL directory registration handles remain alive")
                check(voice_asr._add_cuda_dll_dirs() == result,
                      "registration is idempotent")
                with mock.patch.object(voice_asr, "_candidate_cuda_dll_dirs",
                                       side_effect=AssertionError("eager CUDA scan")):
                    check(voice_asr.registered_dll_dirs() == result,
                          "status reads cached paths without rescanning disk")
        finally:
            os.environ["PATH"] = old_path
            voice_asr._dll_dirs_added = old_added
            voice_asr._registered_dll_dirs[:] = old_dirs
            voice_asr._dll_directory_handles[:] = old_handles

print("frozen CUDA 12 DLL discovery contract PASS")

"""Reject a Windows voice EXE missing the GPU DLLs or bundled VAD model.

ASR imports do not load a CUDA model. Inspect the executable's actual archive
against every DLL in the installed NVIDIA wheels before accepting the package.
The GPU itself is validated on the rig, not inferred from this archive check.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path


def _canonical(path: str) -> str:
    return path.replace("\\", "/").lower()


def validate_entries(entries: list[str], cuda_files: list[str]) -> dict:
    packed = {_canonical(path) for path in entries}
    expected = {_canonical(path) for path in cuda_files}
    essentials = {
        "nvidia/cublas/bin/cublas64_12.dll",
        "nvidia/cublas/bin/cublaslt64_12.dll",
        "nvidia/cudnn/bin/cudnn64_9.dll",
    }
    if not essentials.issubset(expected):
        raise RuntimeError("CUDA build environment lacks the required Windows runtime DLLs")
    missing = sorted(expected - packed)
    if missing:
        raise RuntimeError("Frozen worker lacks CUDA runtime files: " + ", ".join(missing))
    vad = sorted(path for path in packed if
                 path.startswith("faster_whisper/assets/")
                 and "silero" in path and path.endswith(".onnx"))
    if not vad:
        raise RuntimeError("Frozen worker lacks the Silero VAD model used by ASR")
    return {"cuda_dlls": len(expected), "vad_models": vad}


def installed_cuda_files() -> list[str]:
    nvidia = importlib.import_module("nvidia")
    files = []
    for root in nvidia.__path__:
        namespace = Path(root)
        for provider in ("cublas", "cudnn"):
            for dll in (namespace / provider / "bin").glob("*.dll"):
                files.append(dll.relative_to(namespace.parent).as_posix())
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("exe", type=Path)
    args = parser.parse_args()
    from PyInstaller.archive.readers import CArchiveReader

    archive = CArchiveReader(str(args.exe))
    report = validate_entries(list(archive.toc), installed_cuda_files())
    print("Frozen Windows voice payload verified: " + json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()

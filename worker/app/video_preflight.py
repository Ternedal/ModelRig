"""Read-only preflight for experimental Wan media storage.

No directory creation, model downloads, ComfyUI launch or GPU allocation.
This is advisory: an operator must independently attest physical drive identity,
ComfyUI model search paths and actual CUDA/VRAM availability.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from .video_storage_config import configured_video_storage


def probe_nvidia_gpus():
    """Read-only GPU inventory; no CUDA context or model loading."""
    try:
        completed = subprocess.run(
            ["nvidia-smi", "--query-gpu=index,name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unavailable", "devices": []}
    if completed.returncode != 0:
        return {"status": "unavailable", "devices": []}
    devices = []
    for line in completed.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 3:
            return {"status": "invalid_output", "devices": []}
        try:
            index, memory_mib = int(parts[0]), int(parts[2])
        except ValueError:
            return {"status": "invalid_output", "devices": []}
        if index < 0 or memory_mib <= 0:
            return {"status": "invalid_output", "devices": []}
        devices.append({"index": index, "name": parts[1], "memory_mib": memory_mib})
    return {"status": "detected" if devices else "unavailable", "devices": devices}


def check(environ=None):
    env = os.environ if environ is None else environ
    result = {"ready": False, "checks": {}, "limitations": [
        "Physical external-drive identity not attested",
        "ComfyUI effective model paths and custom-node caches not verified",
        "GPU memory, Wan graph and MP4 playback not tested",
    ]}
    try:
        storage = configured_video_storage(env)
        root = storage.root
        for relative in ("Media", "Media/Images", "Media/Videos", "Media/VR",
                         "Jobs", "Temp", "Cache", "ComfyUI", "ComfyUI/input",
                         "ComfyUI/output", "ComfyUI/temp", "ComfyUI/models",
                         "ComfyUI/user", "ComfyUI/huggingface",
                         "ComfyUI/torch", "ComfyUI/xdg-cache"):
            path = root / relative
            if path.is_symlink():
                raise ValueError("Symlink forbidden: " + relative)
            if path.exists() and not path.resolve().is_relative_to(root):
                raise ValueError("Directory escapes media root: " + relative)
        usage = shutil.disk_usage(root)
        result["checks"]["media_root"] = str(root)
        result["checks"]["free_bytes"] = usage.free
        result["checks"]["reserve_bytes"] = storage.minimum_free_bytes
        result["checks"]["configured_paths"] = "pass"
        result["checks"]["storage"] = "pass"
    except (OSError, RuntimeError, ValueError) as exc:
        result["checks"]["storage"] = "fail"
        result["checks"]["error"] = type(exc).__name__ + ": " + str(exc)
    result["checks"]["gpus"] = probe_nvidia_gpus()
    # Inventory alone does not qualify model fit or actual CUDA execution.
    return result


def main():
    parser = argparse.ArgumentParser(description="Read-only Wan preflight")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = check()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report["checks"].get("storage") == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())

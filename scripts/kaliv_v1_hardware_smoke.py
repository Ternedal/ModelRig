#!/usr/bin/env python3
"""Read-only local hardware smoke inventory. No model inference or external network."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def gpu_inventory() -> dict:
    binary = shutil.which("nvidia-smi")
    if not binary:
        return {"status": "UNAVAILABLE", "gpus": [], "error": "nvidia-smi not found"}
    try:
        result = subprocess.run(
            [binary, "--query-gpu=index,name,memory.total,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15, check=True,
        )
        gpus = []
        for line in result.stdout.splitlines():
            fields = [field.strip() for field in line.split(",")]
            if len(fields) != 4 or not fields[0].isdigit() or not fields[2].isdigit():
                return {"status": "ERROR", "gpus": [], "error": "unexpected nvidia-smi output"}
            gpus.append({"index": int(fields[0]), "name": fields[1],
                         "memory_mib": int(fields[2]), "driver": fields[3]})
        return {"status": "OBSERVED" if gpus else "UNAVAILABLE", "gpus": gpus}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "ERROR", "gpus": [], "error": type(exc).__name__}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        print("Refusing to overwrite existing report", file=sys.stderr)
        return 2
    gpu = gpu_inventory()
    report = {
        "schema": "kaliv-v1-local-hardware-smoke/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "gpu": gpu,
        "release_ready": False,
        "production_activation": False,
        "physical_qualification": "PENDING",
        "note": "Inventory only; no inference, thermal stress, CUDA validation, or physical PASS.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({"gpu_status": gpu["status"], "gpu_count": len(gpu["gpus"]),
                      "report": str(args.output)}, indent=2))
    return 0 if gpu["status"] == "OBSERVED" else 2


if __name__ == "__main__":
    raise SystemExit(main())

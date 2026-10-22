#!/usr/bin/env python3
"""Non-invasive V1 physical campaign preflight. Never starts production or claims PASS."""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOS = ("ModelRig", "BodyRig", "VisionRig", "VoiceRig")
GATES = (
    "software_exact_green", "consciousness_live_lifecycle",
    "visionrig_physical_perception", "voicerig_physical_acceptance",
    "bodyrig_photoreal_likeness", "bodyrig_digital_twin_m6",
    "bodyrig_android_live_body", "end_to_end_latency",
    "recovery_soak", "repository_authority",
)


def inspect_repo(path: Path) -> dict:
    result = {"path": str(path), "present": path.is_dir(), "sha": None, "clean": False}
    if not path.is_dir() or not shutil.which("git"):
        return result
    try:
        sha = subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                             capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        dirty = subprocess.run(["git", "-C", str(path), "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10, check=True).stdout
        result.update(sha=sha if re.fullmatch(r"[0-9a-f]{40}", sha) else None, clean=not bool(dirty.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("C:/Rig/src"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        print("Refusing to overwrite existing campaign report", file=sys.stderr)
        return 2
    repos = {name: inspect_repo(args.workspace / name) for name in REPOS}
    tools = {name: shutil.which(name) is not None for name in ("git", "python", "nvidia-smi", "adb")}
    ready = bool(tools["git"] and tools["python"]) and all(
        x["present"] and x["sha"] and x["clean"] for x in repos.values()
    )
    report = {
        "schema": "kaliv-v1-physical-preflight/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_PHYSICAL_QUALIFICATION" if ready else "BLOCKED",
        "release_ready": False,
        "production_activation": False,
        "repositories": repos,
        "tools": tools,
        "gates": {gate: "PENDING" for gate in GATES},
        "note": "Preflight only. No GPU inference, sensor tests, human QA or release gate executed.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
        f.write("\n")
    print(json.dumps({"status": report["status"], "report": str(args.output)}, indent=2))
    return 0 if ready else 2


if __name__ == "__main__":
    raise SystemExit(main())

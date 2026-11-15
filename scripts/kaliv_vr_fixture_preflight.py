#!/usr/bin/env python3
"""Fail-closed preflight for a Kaliv VR downstream avatar fixture.

Usage: python scripts/kaliv_vr_fixture_preflight.py path/to/avatar.vrm
Does not claim Unity/Quest compatibility or BodyRig pipeline completion.
"""
import argparse
import json
from pathlib import Path
import struct
import sys

def inspect(path: Path) -> dict:
    data = path.read_bytes()
    if len(data) < 20 or data[:4] != b"glTF":
        raise ValueError("Not a binary GLB/VRM file")
    magic, version, total = struct.unpack_from("<4sII", data)
    if version != 2 or total != len(data):
        raise ValueError("Invalid GLB v2 header/length")
    chunk_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON" or 20 + chunk_length > len(data):
        raise ValueError("Missing/invalid GLB JSON chunk")
    doc = json.loads(data[20:20 + chunk_length].decode("utf-8"))
    if "VRMC_vrm" not in doc.get("extensionsUsed", []):
        raise ValueError("VRMC_vrm must be declared in extensionsUsed")
    vrm = doc.get("extensions", {}).get("VRMC_vrm")
    if not isinstance(vrm, dict):
        raise ValueError("Missing VRMC_vrm extension (VRM 1.0 required)")
    if vrm.get("specVersion") != "1.0":
        raise ValueError("VRM 1.0 specVersion required")
    human = vrm.get("humanoid", {}).get("humanBones", {})
    required = ("hips", "spine", "head", "leftUpperArm", "leftLowerArm",
                "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
                "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg",
                "rightLowerLeg", "rightFoot")
    nodes = doc.get("nodes", [])
    missing = [b for b in required if not isinstance(human.get(b), dict)
               or not isinstance(human[b].get("node"), int)
               or not 0 <= human[b]["node"] < len(nodes)]
    if missing:
        raise ValueError("Missing/invalid required humanoid bones: " + ", ".join(missing))
    if not doc.get("skins"):
        raise ValueError("No skin: cannot animate humanoid mesh")
    return {"file": str(path), "vrm_spec": vrm.get("specVersion"),
            "nodes": len(nodes), "skins": len(doc["skins"]),
            "animations": len(doc.get("animations", [])),
            "required_bones": len(required), "status": "structural preflight PASS"}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("avatar", type=Path)
    args = p.parse_args()
    try:
        print(json.dumps(inspect(args.avatar), indent=2))
    except (OSError, ValueError, KeyError, IndexError, UnicodeError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())

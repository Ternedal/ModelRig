#!/usr/bin/env python3
"""Contract tests for the portable VoiceRig -> ModelRig `.mrvoice` handoff."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path

from app import voice_profiles


def build_package(path: Path, *, evil: bool = False) -> None:
    payloads = {
        "reference.wav": b"reference",
        "conditioning.pt": b"conditioning",
        "preview.wav": b"preview",
    }
    checksums = {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}
    manifest = {
        "format": "modelrig-voice",
        "format_version": 1,
        "id": "anders-test",
        "name": "Anders",
        "language": "da",
        "engine": {"name": "chatterbox-multilingual", "model": "v3"},
        "files": {
            "reference": "reference.wav",
            "conditioning": "conditioning.pt",
            "preview": "preview.wav",
        },
        "defaults": {"exaggeration": 0.5, "cfg_weight": 0.5, "temperature": 0.8},
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("checksums.json", json.dumps(checksums))
        for name, raw in payloads.items():
            zf.writestr(name, raw)
        if evil:
            zf.writestr("../escape", b"no")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["KALIV_VOICES_DIR"] = str(root)
        package = root / "anders.mrvoice"
        build_package(package)

        manifest = voice_profiles.validate_package(package)
        assert manifest["id"] == "anders-test"
        assert voice_profiles.default_profile_path() == package

        profiles = voice_profiles.list_profiles()
        assert len(profiles) == 1
        assert profiles[0]["default"] is True
        assert profiles[0]["valid"] is True

        second = root / "second.mrvoice"
        build_package(second)
        assert voice_profiles.default_profile_path() is None
        (root / "default.txt").write_text("anders.mrvoice\n", encoding="utf-8")
        assert voice_profiles.default_profile_path() == package

        evil = root / "evil.mrvoice"
        build_package(evil, evil=True)
        try:
            voice_profiles.validate_package(evil)
        except ValueError as exc:
            assert "invalid path" in str(exc)
        else:
            raise AssertionError("path traversal package was accepted")

    print("worker voice profiles: OK")


if __name__ == "__main__":
    main()

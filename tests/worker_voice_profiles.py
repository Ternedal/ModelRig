#!/usr/bin/env python3
"""Contract tests for the portable VoiceRig -> ModelRig `.mrvoice` handoff."""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import types
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


def test_conditionals_load_contract(root: Path) -> None:
    calls: dict[str, object] = {}

    class FakeLoaded:
        def to(self, device):
            calls["to"] = device
            return self

    class FakeConditionals:
        @classmethod
        def load(cls, path, map_location="cpu"):
            calls["path"] = Path(path).name
            calls["map_location"] = map_location
            return FakeLoaded()

    class FakeModel:
        conds = None

        def prepare_conditionals(self, *_args, **_kwargs):
            raise AssertionError("saved conditioning unexpectedly fell back to reference audio")

    package = types.ModuleType("chatterbox")
    package.__path__ = []
    mtl = types.ModuleType("chatterbox.mtl_tts")
    mtl.Conditionals = FakeConditionals
    old_package = sys.modules.get("chatterbox")
    old_mtl = sys.modules.get("chatterbox.mtl_tts")
    sys.modules["chatterbox"] = package
    sys.modules["chatterbox.mtl_tts"] = mtl
    try:
        (root / "conditioning.pt").write_bytes(b"fake")
        model = FakeModel()
        voice_profiles._load_conditionals(model, root, "cuda")
        assert calls == {
            "path": "conditioning.pt",
            "map_location": "cuda",
            "to": "cuda",
        }
        assert model.conds is not None
    finally:
        if old_package is None:
            sys.modules.pop("chatterbox", None)
        else:
            sys.modules["chatterbox"] = old_package
        if old_mtl is None:
            sys.modules.pop("chatterbox.mtl_tts", None)
        else:
            sys.modules["chatterbox.mtl_tts"] = old_mtl


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        os.environ["MODELRIG_VOICES_DIR"] = str(root)
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

        conditionals_root = root / "conditionals-contract"
        conditionals_root.mkdir()
        test_conditionals_load_contract(conditionals_root)

    print("worker voice profiles: OK")


if __name__ == "__main__":
    main()

import struct
import zipfile
from pathlib import Path

import pytest

from bodyrig.package import MRBodyError, build_package, validate_package


def glb(payload: bytes = b"") -> bytes:
    length = 12 + len(payload)
    return b"glTF" + struct.pack("<II", 2, length) + payload


PNG = b"\x89PNG\r\n\x1a\n" + b"test"
BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "shape": {"height_scale": 1.0, "shoulder_to_height": 0.24},
    "motion": {"energy": 0.42, "gesture_frequency": 0.37},
    "runtime": {"idle_strength": 0.35, "gaze_smoothing": 0.7},
}
PROVENANCE = {
    "format": "modelrig-body-provenance",
    "version": 1,
    "created_at": "2026-08-23T10:00:00Z",
    "source": {"kind": "user-supplied-local-media", "count": 2},
    "synthetic_avatar": True,
    "pipeline": [],
}


def make_package(path: Path) -> Path:
    return build_package(
        path,
        body_id="test-body",
        name="Test Body",
        avatar_vrm=glb(),
        bodyprint=BODYPRINT,
        provenance=PROVENANCE,
        thumbnail_png=PNG,
        motions={"motions/idle.vrma": glb(b"idle")},
    )


def test_roundtrip(tmp_path: Path):
    package = make_package(tmp_path / "test.mrbody")
    result = validate_package(package)
    assert result.manifest["id"] == "test-body"
    assert "motions/idle.vrma" in result.payload_names


def test_checksum_tamper_fails(tmp_path: Path):
    package = make_package(tmp_path / "test.mrbody")
    tampered = tmp_path / "tampered.mrbody"
    with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(tampered, "w") as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "thumbnail.png":
                data += b"tamper"
            target.writestr(info, data)
    with pytest.raises(MRBodyError, match="checksum mismatch"):
        validate_package(tampered)


def test_unknown_payload_fails(tmp_path: Path):
    package = make_package(tmp_path / "test.mrbody")
    bad = tmp_path / "bad.mrbody"
    with zipfile.ZipFile(package, "r") as source, zipfile.ZipFile(bad, "w") as target:
        for info in source.infolist():
            target.writestr(info, source.read(info.filename))
        target.writestr("evil.exe", b"nope")
    with pytest.raises(MRBodyError, match="unknown payload"):
        validate_package(bad)


def test_path_traversal_fails_before_read(tmp_path: Path):
    bad = tmp_path / "traversal.mrbody"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("../avatar.vrm", glb())
    with pytest.raises(MRBodyError, match="unsafe archive path"):
        validate_package(bad)


def test_bodyprint_nan_fails_build(tmp_path: Path):
    bodyprint = dict(BODYPRINT)
    bodyprint["motion"] = {"energy": float("nan")}
    with pytest.raises(MRBodyError, match="outside"):
        build_package(
            tmp_path / "nan.mrbody",
            body_id="nan-body",
            name="NaN",
            avatar_vrm=glb(),
            bodyprint=bodyprint,
            provenance=PROVENANCE,
            thumbnail_png=PNG,
        )

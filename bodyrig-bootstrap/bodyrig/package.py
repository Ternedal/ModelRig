from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

FORMAT = "modelrig-body"
FORMAT_VERSION = 1
MAX_ENTRIES = 12
MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_JSON = 512 * 1024
MAX_THUMBNAIL = 8 * 1024 * 1024
MAX_AVATAR = 192 * 1024 * 1024
MAX_MOTION = 32 * 1024 * 1024

REQUIRED = {
    "manifest.json",
    "checksums.json",
    "avatar.vrm",
    "bodyprint.json",
    "provenance.json",
    "thumbnail.png",
}
OPTIONAL = {
    "motions/idle.vrma",
    "motions/walk.vrma",
    "motions/talk.vrma",
    "motions/gesture_01.vrma",
    "motions/gesture_02.vrma",
    "motions/gesture_03.vrma",
}
ALLOWED = REQUIRED | OPTIONAL
SLUG_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
BUILDER_VERSION_RE = re.compile(r"^[0-9A-Za-z.+_-]{1,64}$")
PIPELINE_STAGE_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
PIPELINE_ADAPTER_RE = re.compile(r"^[A-Za-z0-9._+-]{1,120}$")
PIPELINE_REVISION_RE = re.compile(r"^[A-Za-z0-9._/+:-]{1,128}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class MRBodyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedBody:
    manifest: dict[str, Any]
    bodyprint: dict[str, Any]
    provenance: dict[str, Any]
    payload_names: tuple[str, ...]


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MRBodyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _loads_json(data: bytes, name: str) -> Any:
    if len(data) > MAX_JSON:
        raise MRBodyError(f"{name}: JSON payload exceeds limit")
    try:
        text = data.decode("utf-8")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MRBodyError(f"{name}: non-finite JSON constant {token}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MRBodyError(f"{name}: invalid UTF-8 JSON") from exc


def _dumps_json(value: object, *, pretty: bool = False) -> bytes:
    try:
        if pretty:
            text = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ) + "\n"
        else:
            text = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            )
    except (TypeError, ValueError) as exc:
        raise MRBodyError("package JSON contains unsupported/non-finite value") from exc
    return text.encode("utf-8")


def _validate_number(value: Any, lo: float, hi: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MRBodyError(f"bodyprint.{field}: expected number")
    number = float(value)
    if not math.isfinite(number) or not lo <= number <= hi:
        raise MRBodyError(f"bodyprint.{field}: outside {lo}..{hi}")


def _validate_object_fields(
    obj: Any,
    allowed: Mapping[str, tuple[float, float]],
    section: str,
) -> None:
    if not isinstance(obj, dict):
        raise MRBodyError(f"bodyprint.{section}: expected object")
    if not obj:
        raise MRBodyError(f"bodyprint.{section}: section may not be empty")
    unknown = set(obj) - set(allowed)
    if unknown:
        raise MRBodyError(f"bodyprint.{section}: unknown fields: {sorted(unknown)}")
    for key, value in obj.items():
        lo, hi = allowed[key]
        _validate_number(value, lo, hi, f"{section}.{key}")


def validate_bodyprint(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MRBodyError("bodyprint.json: expected object")
    allowed_top = {"format", "version", "shape", "motion", "expression", "runtime"}
    unknown = set(value) - allowed_top
    if unknown:
        raise MRBodyError(f"bodyprint.json: unknown fields: {sorted(unknown)}")
    if value.get("format") != "modelrig-bodyprint" or value.get("version") != 1:
        raise MRBodyError("bodyprint.json: unsupported format/version")

    sections = {
        "shape": {
            "height_scale": (0.000001, 4.0),
            "shoulder_to_height": (0.0, 1.0),
            "hip_to_height": (0.0, 1.0),
            "arm_to_height": (0.0, 1.0),
            "leg_to_height": (0.0, 1.0),
        },
        "motion": {
            "energy": (0.0, 1.0),
            "gesture_frequency": (0.0, 1.0),
            "gesture_amplitude": (0.0, 1.0),
            "head_motion": (0.0, 1.0),
            "turn_speed": (0.0, 1.0),
            "walk_cadence_spm": (0.0, 300.0),
        },
        "expression": {
            "blink_rate_per_min": (0.0, 120.0),
            "gaze_strength": (0.0, 1.0),
            "head_tilt": (0.0, 1.0),
            "speech_motion": (0.0, 1.0),
        },
        "runtime": {
            "idle_strength": (0.0, 1.0),
            "gaze_smoothing": (0.0, 1.0),
            "gesture_intensity": (0.0, 1.0),
            "breathing_strength": (0.0, 1.0),
        },
    }
    observed = 0
    for section, rules in sections.items():
        if section in value:
            observed += 1
            _validate_object_fields(value[section], rules, section)
    if observed == 0:
        raise MRBodyError("bodyprint.json: at least one observed section is required")
    return value


def validate_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MRBodyError("manifest.json: expected object")
    required = {
        "format",
        "format_version",
        "id",
        "name",
        "avatar",
        "bodyprint",
        "provenance",
        "thumbnail",
        "builder",
    }
    if set(value) != required:
        raise MRBodyError("manifest.json: fields must match v1 contract exactly")
    if value["format"] != FORMAT or value["format_version"] != FORMAT_VERSION:
        raise MRBodyError("manifest.json: unsupported format/version")
    if not isinstance(value["id"], str) or not SLUG_RE.fullmatch(value["id"]):
        raise MRBodyError("manifest.json: invalid id")
    if not isinstance(value["name"], str) or not 1 <= len(value["name"]) <= 160:
        raise MRBodyError("manifest.json: invalid name")
    if value["avatar"] != {"format": "vrm", "version": "1.0", "path": "avatar.vrm"}:
        raise MRBodyError("manifest.json: invalid avatar descriptor")
    if (
        value["bodyprint"] != "bodyprint.json"
        or value["provenance"] != "provenance.json"
        or value["thumbnail"] != "thumbnail.png"
    ):
        raise MRBodyError("manifest.json: invalid payload path")
    builder = value["builder"]
    if (
        not isinstance(builder, dict)
        or set(builder) - {"name", "version", "revision"}
        or not {"name", "version"} <= set(builder)
    ):
        raise MRBodyError("manifest.json: invalid builder")
    if builder["name"] != "bodyrig":
        raise MRBodyError("manifest.json: invalid builder identity")
    if not isinstance(builder["version"], str) or not BUILDER_VERSION_RE.fullmatch(builder["version"]):
        raise MRBodyError("manifest.json: invalid builder version")
    revision = builder.get("revision")
    if revision is not None and (
        not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision)
    ):
        raise MRBodyError("manifest.json: invalid builder revision")
    return value


def validate_provenance(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MRBodyError("provenance.json: expected object")
    required = {
        "format",
        "version",
        "created_at",
        "source",
        "synthetic_avatar",
        "pipeline",
    }
    if set(value) != required:
        raise MRBodyError("provenance.json: fields must match v1 contract exactly")
    if value["format"] != "modelrig-body-provenance" or value["version"] != 1:
        raise MRBodyError("provenance.json: unsupported format/version")
    if value["synthetic_avatar"] is not True:
        raise MRBodyError("provenance.json: synthetic_avatar must be true")

    created_at = value["created_at"]
    if not isinstance(created_at, str) or not 20 <= len(created_at) <= 40:
        raise MRBodyError("provenance.json: invalid created_at")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MRBodyError("provenance.json: invalid created_at") from exc
    if parsed.tzinfo is None:
        raise MRBodyError("provenance.json: created_at requires timezone")

    source = value["source"]
    if not isinstance(source, dict) or set(source) != {"kind", "count"}:
        raise MRBodyError("provenance.json: source fields must match v1 exactly")
    if source["kind"] != "user-supplied-local-media":
        raise MRBodyError("provenance.json: invalid source kind")
    count = source["count"]
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 10:
        raise MRBodyError("provenance.json: source count must be 1..10")

    pipeline = value["pipeline"]
    if not isinstance(pipeline, list) or not 1 <= len(pipeline) <= 32:
        raise MRBodyError("provenance.json: pipeline must contain 1..32 stages")
    for index, stage in enumerate(pipeline):
        if not isinstance(stage, dict) or set(stage) != {"stage", "adapter", "revision"}:
            raise MRBodyError(f"provenance.json: pipeline[{index}] fields are invalid")
        if not isinstance(stage["stage"], str) or not PIPELINE_STAGE_RE.fullmatch(stage["stage"]):
            raise MRBodyError(f"provenance.json: pipeline[{index}].stage is invalid")
        if not isinstance(stage["adapter"], str) or not PIPELINE_ADAPTER_RE.fullmatch(stage["adapter"]):
            raise MRBodyError(f"provenance.json: pipeline[{index}].adapter is invalid")
        if not isinstance(stage["revision"], str) or not PIPELINE_REVISION_RE.fullmatch(stage["revision"]):
            raise MRBodyError(f"provenance.json: pipeline[{index}].revision is invalid")
    return value


def _validate_glb(data: bytes, name: str) -> None:
    if len(data) < 12 or data[:4] != b"glTF" or int.from_bytes(data[4:8], "little") != 2:
        raise MRBodyError(f"{name}: expected glTF/GLB v2 container")
    if int.from_bytes(data[8:12], "little") != len(data):
        raise MRBodyError(f"{name}: GLB length mismatch")


def _entry_limit(name: str) -> int:
    if name in {"manifest.json", "checksums.json", "bodyprint.json", "provenance.json"}:
        return MAX_JSON
    if name == "thumbnail.png":
        return MAX_THUMBNAIL
    if name == "avatar.vrm":
        return MAX_AVATAR
    if name.endswith(".vrma"):
        return MAX_MOTION
    return 0


def _safe_name(name: str) -> None:
    if "\\" in name or name.startswith("/"):
        raise MRBodyError(f"unsafe archive path: {name!r}")
    path = PurePosixPath(name)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise MRBodyError(f"unsafe archive path: {name!r}")
    if name not in ALLOWED:
        raise MRBodyError(f"unknown payload path: {name}")


def validate_package(path: str | os.PathLike[str]) -> ValidatedBody:
    try:
        archive = zipfile.ZipFile(Path(path), "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise MRBodyError("invalid .mrbody ZIP") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise MRBodyError("too many archive entries")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise MRBodyError("duplicate archive entries")
        total = 0
        for info in infos:
            _safe_name(info.filename)
            if info.flag_bits & 0x1:
                raise MRBodyError("encrypted archive entries are not allowed")
            if info.file_size > _entry_limit(info.filename):
                raise MRBodyError(f"{info.filename}: exceeds size limit")
            total += info.file_size
            if total > MAX_TOTAL_UNCOMPRESSED:
                raise MRBodyError("package exceeds total size limit")

        name_set = set(names)
        if not REQUIRED <= name_set:
            raise MRBodyError(f"missing required files: {sorted(REQUIRED - name_set)}")

        manifest_raw = archive.read("manifest.json")
        manifest = validate_manifest(_loads_json(manifest_raw, "manifest.json"))
        bodyprint = validate_bodyprint(_loads_json(archive.read("bodyprint.json"), "bodyprint.json"))
        provenance = validate_provenance(_loads_json(archive.read("provenance.json"), "provenance.json"))
        checksums = _loads_json(archive.read("checksums.json"), "checksums.json")
        if not isinstance(checksums, dict):
            raise MRBodyError("checksums.json: expected object")

        checksummed_files = name_set - {"checksums.json"}
        if set(checksums) != checksummed_files:
            raise MRBodyError("checksums.json: entries must exactly match all files except checksums.json")
        for checksum_name, expected in checksums.items():
            if not isinstance(expected, str) or not SHA_RE.fullmatch(expected):
                raise MRBodyError(f"checksums.json: invalid hash for {checksum_name}")
            if hashlib.sha256(archive.read(checksum_name)).hexdigest() != expected:
                raise MRBodyError(f"checksum mismatch: {checksum_name}")

        _validate_glb(archive.read("avatar.vrm"), "avatar.vrm")
        if not archive.read("thumbnail.png").startswith(PNG_SIGNATURE):
            raise MRBodyError("thumbnail.png: invalid PNG signature")
        payloads = name_set - {"manifest.json", "checksums.json"}
        for motion_name in payloads & OPTIONAL:
            _validate_glb(archive.read(motion_name), motion_name)

        return ValidatedBody(
            manifest=manifest,
            bodyprint=bodyprint,
            provenance=provenance,
            payload_names=tuple(sorted(payloads)),
        )


def build_package(
    destination: str | os.PathLike[str],
    *,
    body_id: str,
    name: str,
    avatar_vrm: bytes,
    bodyprint: Mapping[str, Any],
    provenance: Mapping[str, Any],
    thumbnail_png: bytes,
    motions: Mapping[str, bytes] | None = None,
    builder_version: str = "0.1.0",
    builder_revision: str | None = None,
) -> Path:
    if not SLUG_RE.fullmatch(body_id):
        raise MRBodyError("invalid body id")
    motions = dict(motions or {})
    if set(motions) - OPTIONAL:
        raise MRBodyError("unknown motion payload")

    manifest: dict[str, Any] = {
        "format": FORMAT,
        "format_version": FORMAT_VERSION,
        "id": body_id,
        "name": name,
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": {"name": "bodyrig", "version": builder_version},
    }
    if builder_revision is not None:
        manifest["builder"]["revision"] = builder_revision

    bodyprint_dict = validate_bodyprint(dict(bodyprint))
    provenance_dict = validate_provenance(dict(provenance))
    validate_manifest(manifest)
    _validate_glb(avatar_vrm, "avatar.vrm")
    if not thumbnail_png.startswith(PNG_SIGNATURE):
        raise MRBodyError("thumbnail_png: invalid PNG signature")
    for motion_name, motion_data in motions.items():
        _validate_glb(motion_data, motion_name)

    manifest_bytes = _dumps_json(manifest, pretty=True)
    file_bytes: dict[str, bytes] = {
        "manifest.json": manifest_bytes,
        "avatar.vrm": avatar_vrm,
        "bodyprint.json": _dumps_json(bodyprint_dict),
        "provenance.json": _dumps_json(provenance_dict),
        "thumbnail.png": thumbnail_png,
        **motions,
    }
    checksums = {
        filename: hashlib.sha256(data).hexdigest()
        for filename, data in file_bytes.items()
    }
    checksums_bytes = _dumps_json(checksums, pretty=True)

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=destination.name + ".",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", manifest_bytes)
            archive.writestr("checksums.json", checksums_bytes)
            for filename, data in file_bytes.items():
                if filename != "manifest.json":
                    archive.writestr(filename, data)
        validate_package(temp_path)
        os.replace(temp_path, destination)
    finally:
        temp_path.unlink(missing_ok=True)
    return destination


def install_package(
    package_path: str | os.PathLike[str],
    library_dir: str | os.PathLike[str],
) -> Path:
    validated = validate_package(package_path)
    library = Path(library_dir)
    library.mkdir(parents=True, exist_ok=True)
    target = library / f"{validated.manifest['id']}.mrbody"
    data = Path(package_path).read_bytes()
    fd, temp_name = tempfile.mkstemp(
        prefix=target.name + ".",
        suffix=".tmp",
        dir=library,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        validate_package(temp_name)
        os.replace(temp_name, target)
    finally:
        Path(temp_name).unlink(missing_ok=True)
    return target

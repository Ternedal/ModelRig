"""Deterministic `.mrbody` V1 builder and pre-extraction validator.

This module implements the existing repository package specification without
claiming visual avatar quality. `avatar.vrm` receives structural GLB/VRM-1.0
checks only; physical rig fidelity and Unity/Quest loading remain separate
acceptance gates.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import binascii
import hashlib
from io import BytesIO
import json
import math
from pathlib import PurePosixPath
import re
import stat
import struct
from typing import Any, Mapping
import zipfile

from .identity import validate_identity_bundle


MRBODY_FORMAT = "modelrig-body"
MRBODY_VERSION = 1
MRBODY_BUILDER_VERSION = "0.1.0"

REQUIRED_PATHS = (
    "manifest.json",
    "checksums.json",
    "avatar.vrm",
    "bodyprint.json",
    "provenance.json",
    "thumbnail.png",
)
OPTIONAL_MOTION_PATHS = (
    "motions/idle.vrma",
    "motions/walk.vrma",
    "motions/talk.vrma",
    "motions/gesture_01.vrma",
    "motions/gesture_02.vrma",
    "motions/gesture_03.vrma",
)
ALLOWED_PATHS = frozenset((*REQUIRED_PATHS, *OPTIONAL_MOTION_PATHS))
PAYLOAD_REQUIRED = frozenset(
    {"avatar.vrm", "bodyprint.json", "provenance.json", "thumbnail.png"}
)
IDENTITY_CONTENT_AUTHORITIES = frozenset(
    {"modelrig.bodyrig.identity_bundle", "bodyrig.portable_identity"}
)

MAX_ENTRIES = 12
MAX_TOTAL_UNCOMPRESSED = 256 * 1024 * 1024
MAX_ARCHIVE_BYTES = 260 * 1024 * 1024
ENTRY_LIMITS = {
    "manifest.json": 512 * 1024,
    "checksums.json": 512 * 1024,
    "bodyprint.json": 512 * 1024,
    "provenance.json": 512 * 1024,
    "thumbnail.png": 8 * 1024 * 1024,
    "avatar.vrm": 192 * 1024 * 1024,
    **{path: 32 * 1024 * 1024 for path in OPTIONAL_MOTION_PATHS},
}

_ID_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
_BODYID_RE = re.compile(r"^bodyid-([0-9a-f]{24})$")
_VERSION_RE = re.compile(r"^[0-9A-Za-z.+_-]{1,64}$")
_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
_STAGE_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
_ADAPTER_RE = re.compile(r"^[A-Za-z0-9._+-]{1,120}$")
_PIPELINE_REVISION_RE = re.compile(r"^[A-Za-z0-9._/+:-]{1,128}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class MRBodyError(ValueError):
    """An `.mrbody` build or pre-extraction validation rule failed."""


@dataclass(frozen=True)
class MRBodyInspection:
    """Validated package metadata; payloads remain inside the untrusted archive."""

    body_id: str
    name: str
    identity_content_id: str | None
    manifest: Mapping[str, Any]
    bodyprint: Mapping[str, Any]
    provenance: Mapping[str, Any]
    checksums: Mapping[str, str]
    payload_sizes: tuple[tuple[str, int], ...]


def _canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise MRBodyError("package JSON is not canonicalizable") from exc


def _json_object(data: bytes, label: str) -> dict[str, Any]:
    if not data:
        raise MRBodyError(f"{label} is empty")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MRBodyError(f"{label} must be UTF-8 JSON") from exc

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise MRBodyError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                MRBodyError(f"{label} contains non-finite JSON constant {token}")
            ),
        )
    except MRBodyError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise MRBodyError(f"{label} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise MRBodyError(f"{label} must contain a JSON object")
    return value


def _finite_number(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MRBodyError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise MRBodyError(f"{label} must be within [{minimum},{maximum}]")
    return number


def _validate_manifest(value: Mapping[str, Any]) -> None:
    expected = {
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
    if set(value) != expected:
        raise MRBodyError("manifest.json contains missing or unsupported fields")
    if value.get("format") != MRBODY_FORMAT or type(value.get("format_version")) is not int or value["format_version"] != 1:
        raise MRBodyError("manifest format/version is unsupported")
    identifier = value.get("id")
    if not isinstance(identifier, str) or _ID_RE.fullmatch(identifier) is None:
        raise MRBodyError("manifest.id is invalid or path-unsafe")
    name = value.get("name")
    if not isinstance(name, str) or not 1 <= len(name) <= 160:
        raise MRBodyError("manifest.name must contain 1..160 characters")
    avatar = value.get("avatar")
    if avatar != {"format": "vrm", "version": "1.0", "path": "avatar.vrm"}:
        raise MRBodyError("manifest avatar declaration must be VRM 1.0 at avatar.vrm")
    if value.get("bodyprint") != "bodyprint.json" or value.get("provenance") != "provenance.json" or value.get("thumbnail") != "thumbnail.png":
        raise MRBodyError("manifest payload references are invalid")
    builder = value.get("builder")
    if not isinstance(builder, Mapping) or not {"name", "version"} <= set(builder) <= {"name", "version", "revision"}:
        raise MRBodyError("manifest.builder fields are invalid")
    if builder.get("name") != "bodyrig" or not isinstance(builder.get("version"), str) or _VERSION_RE.fullmatch(builder["version"]) is None:
        raise MRBodyError("manifest.builder is invalid")
    revision = builder.get("revision")
    if revision is not None and (not isinstance(revision, str) or _REVISION_RE.fullmatch(revision) is None):
        raise MRBodyError("manifest.builder.revision must be a 40-character lowercase git SHA")


def _validate_bodyprint(value: Mapping[str, Any]) -> None:
    if set(value) - {"format", "version", "shape", "motion", "expression", "runtime"}:
        raise MRBodyError("bodyprint.json contains unsupported fields")
    if value.get("format") != "modelrig-bodyprint" or type(value.get("version")) is not int or value["version"] != 1:
        raise MRBodyError("bodyprint format/version is unsupported")
    sections = [name for name in ("shape", "motion", "expression", "runtime") if name in value]
    if not sections:
        raise MRBodyError("bodyprint must contain at least one observed section")

    definitions: dict[str, dict[str, tuple[float, float]]] = {
        "shape": {
            "height_scale": (0.0, 4.0),
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
    for section_name in sections:
        section = value[section_name]
        allowed = definitions[section_name]
        if not isinstance(section, Mapping) or not section or set(section) - set(allowed):
            raise MRBodyError(f"bodyprint.{section_name} fields are invalid")
        for key, item in section.items():
            minimum, maximum = allowed[key]
            number = _finite_number(item, f"bodyprint.{section_name}.{key}", minimum, maximum)
            if section_name == "shape" and key == "height_scale" and number <= 0.0:
                raise MRBodyError("bodyprint.shape.height_scale must be positive")


def _validate_provenance(value: Mapping[str, Any]) -> None:
    if set(value) != {"format", "version", "created_at", "source", "synthetic_avatar", "pipeline"}:
        raise MRBodyError("provenance.json contains missing or unsupported fields")
    if value.get("format") != "modelrig-body-provenance" or type(value.get("version")) is not int or value["version"] != 1:
        raise MRBodyError("provenance format/version is unsupported")
    created_at = value.get("created_at")
    if not isinstance(created_at, str) or not 20 <= len(created_at) <= 40:
        raise MRBodyError("provenance.created_at is invalid")
    try:
        parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MRBodyError("provenance.created_at is not ISO date-time") from exc
    if parsed.tzinfo is None:
        raise MRBodyError("provenance.created_at requires timezone")
    source = value.get("source")
    if not isinstance(source, Mapping) or set(source) != {"kind", "count"}:
        raise MRBodyError("provenance.source fields are invalid")
    if source.get("kind") != "user-supplied-local-media" or type(source.get("count")) is not int or not 1 <= source["count"] <= 10:
        raise MRBodyError("provenance.source is invalid")
    if value.get("synthetic_avatar") is not True:
        raise MRBodyError("provenance.synthetic_avatar must be true")
    pipeline = value.get("pipeline")
    if not isinstance(pipeline, list) or not 1 <= len(pipeline) <= 32:
        raise MRBodyError("provenance.pipeline must contain 1..32 stages")
    for index, item in enumerate(pipeline):
        if not isinstance(item, Mapping) or set(item) != {"stage", "adapter", "revision"}:
            raise MRBodyError(f"provenance.pipeline[{index}] fields are invalid")
        stage, adapter, revision = item["stage"], item["adapter"], item["revision"]
        if not isinstance(stage, str) or _STAGE_RE.fullmatch(stage) is None:
            raise MRBodyError(f"provenance.pipeline[{index}].stage is invalid")
        if not isinstance(adapter, str) or _ADAPTER_RE.fullmatch(adapter) is None:
            raise MRBodyError(f"provenance.pipeline[{index}].adapter is invalid")
        if not isinstance(revision, str) or _PIPELINE_REVISION_RE.fullmatch(revision) is None:
            raise MRBodyError(f"provenance.pipeline[{index}].revision is invalid")


def _validate_checksums(value: Mapping[str, Any], present_paths: set[str]) -> dict[str, str]:
    if not 4 <= len(value) <= 10:
        raise MRBodyError("checksums.json must contain 4..10 payload hashes")
    if set(value) - (ALLOWED_PATHS - {"manifest.json", "checksums.json"}):
        raise MRBodyError("checksums.json contains an unsupported payload path")
    if not PAYLOAD_REQUIRED <= set(value):
        raise MRBodyError("checksums.json is missing a required payload hash")
    expected = present_paths - {"manifest.json", "checksums.json"}
    if set(value) != expected:
        raise MRBodyError("checksums.json does not exactly cover package payloads")
    result: dict[str, str] = {}
    for path, digest in value.items():
        if not isinstance(path, str) or not isinstance(digest, str) or _SHA256_RE.fullmatch(digest) is None:
            raise MRBodyError("checksums.json contains a non-canonical SHA-256")
        result[path] = digest
    return result


def _parse_glb_json(data: bytes, label: str) -> dict[str, Any]:
    if len(data) < 20 or data[:4] != b"glTF":
        raise MRBodyError(f"{label} is not a GLB file")
    magic, version, declared_length = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or version != 2 or declared_length != len(data):
        raise MRBodyError(f"{label} must be an exact glTF 2.0 GLB")
    offset = 12
    first_json: bytes | None = None
    chunk_index = 0
    while offset < len(data):
        if offset + 8 > len(data):
            raise MRBodyError(f"{label} has a truncated GLB chunk header")
        length, chunk_type = struct.unpack_from("<II", data, offset)
        offset += 8
        if length < 0 or offset + length > len(data):
            raise MRBodyError(f"{label} has an invalid GLB chunk length")
        payload = data[offset : offset + length]
        offset += length
        if chunk_index == 0:
            if chunk_type != 0x4E4F534A:
                raise MRBodyError(f"{label} first GLB chunk must be JSON")
            first_json = payload
        elif chunk_type not in {0x004E4942}:
            raise MRBodyError(f"{label} contains unsupported GLB chunk type")
        chunk_index += 1
    if offset != len(data) or first_json is None:
        raise MRBodyError(f"{label} has invalid GLB framing")
    document = _json_object(
        first_json.rstrip(b" \t\r\n\x00"),
        f"{label} GLB JSON",
    )
    asset = document.get("asset")
    if not isinstance(asset, Mapping) or asset.get("version") != "2.0":
        raise MRBodyError(f"{label} GLB asset.version must be 2.0")
    return document


def validate_vrm1_bytes(data: bytes) -> None:
    if not isinstance(data, bytes) or not data or len(data) > ENTRY_LIMITS["avatar.vrm"]:
        raise MRBodyError("avatar.vrm is empty or exceeds the V1 size limit")
    document = _parse_glb_json(data, "avatar.vrm")
    used = document.get("extensionsUsed")
    extensions = document.get("extensions")
    if not isinstance(used, list) or "VRMC_vrm" not in used:
        raise MRBodyError("avatar.vrm does not declare the VRMC_vrm extension")
    if not isinstance(extensions, Mapping) or not isinstance(extensions.get("VRMC_vrm"), Mapping):
        raise MRBodyError("avatar.vrm lacks VRMC_vrm extension data")
    if extensions["VRMC_vrm"].get("specVersion") != "1.0":
        raise MRBodyError("avatar.vrm must declare VRMC_vrm specVersion 1.0")


def validate_png_bytes(data: bytes) -> None:
    if not isinstance(data, bytes) or not data or len(data) > ENTRY_LIMITS["thumbnail.png"]:
        raise MRBodyError("thumbnail.png is empty or exceeds the V1 size limit")
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise MRBodyError("thumbnail.png has an invalid PNG signature")
    offset = 8
    seen_ihdr = False
    seen_iend = False
    while offset < len(data):
        if offset + 12 > len(data):
            raise MRBodyError("thumbnail.png has a truncated PNG chunk")
        length = struct.unpack_from(">I", data, offset)[0]
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            raise MRBodyError("thumbnail.png has an invalid PNG chunk length")
        payload = data[offset + 8 : offset + 8 + length]
        stored_crc = struct.unpack_from(">I", data, offset + 8 + length)[0]
        actual_crc = binascii.crc32(chunk_type)
        actual_crc = binascii.crc32(payload, actual_crc) & 0xFFFFFFFF
        if stored_crc != actual_crc:
            raise MRBodyError("thumbnail.png has a PNG CRC mismatch")
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                raise MRBodyError("thumbnail.png must begin with a 13-byte IHDR")
            width, height = struct.unpack_from(">II", payload, 0)
            if not 1 <= width <= 8192 or not 1 <= height <= 8192:
                raise MRBodyError("thumbnail.png dimensions are outside 1..8192")
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            raise MRBodyError("thumbnail.png contains duplicate IHDR")
        if chunk_type == b"IEND":
            if length != 0 or end != len(data):
                raise MRBodyError("thumbnail.png IEND must be empty and final")
            seen_iend = True
            offset = end
            break
        offset = end
    if not seen_ihdr or not seen_iend or offset != len(data):
        raise MRBodyError("thumbnail.png is structurally incomplete")


def _unit_saturation(value: Any, scale: float, label: str) -> float:
    number = _finite_number(value, label, 0.0, 1_000_000.0)
    if scale <= 0.0:
        raise MRBodyError("internal portable-bodyprint scale must be positive")
    return round(number / (scale + number), 6) if number > 0.0 else 0.0


def portable_bodyprint_from_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    """Project only truthfully representable M2.4 evidence into BodyPrint v1.

    M1.3 currently measures torso-normalized 2D proportions, while BodyPrint v1
    shape keys are explicitly `*_to_height`. Those are not equivalent, so M2.5
    intentionally does not invent a shape section. A future 3D/metric adapter may
    populate it without changing the archive boundary.
    """

    try:
        validate_identity_bundle(identity)
    except Exception as exc:
        raise MRBodyError(str(exc)) from exc
    components = identity["components"]
    motion_component = components["motion"]
    face_component = components["face"]
    result: dict[str, Any] = {"format": "modelrig-bodyprint", "version": 1}

    motion_confidence = motion_component["manifest"]["confidence"]["motion"]
    if isinstance(motion_confidence, (int, float)) and not isinstance(motion_confidence, bool) and float(motion_confidence) >= 0.20:
        metrics = motion_component["motion_profile"]["metrics"]
        hand = _finite_number(metrics["hand_activity_per_second"], "motion hand activity", 0.0, 1_000_000.0)
        head = _finite_number(metrics["head_activity_per_second"], "motion head activity", 0.0, 1_000_000.0)
        result["motion"] = {
            "energy": _unit_saturation((hand + head) / 2.0, 1.0, "motion combined activity"),
            "gesture_frequency": _unit_saturation(
                metrics["gesture_frequency_per_minute"], 20.0, "gesture frequency"
            ),
            "gesture_amplitude": _unit_saturation(metrics["gesture_range"], 1.0, "gesture range"),
            "head_motion": _unit_saturation(head, 1.0, "head activity"),
        }

    blink = face_component["blink"].get("mean_per_minute")
    if isinstance(blink, (int, float)) and not isinstance(blink, bool) and math.isfinite(float(blink)) and 0.0 <= float(blink) <= 120.0:
        result["expression"] = {"blink_rate_per_min": round(float(blink), 6)}

    if len(result) == 2:
        raise MRBodyError(
            "identity has insufficient truthfully representable evidence for modelrig-bodyprint v1"
        )
    _validate_bodyprint(result)
    return result


def _pipeline_item(stage: str, adapter: str, revision: str) -> dict[str, str]:
    item = {"stage": stage, "adapter": adapter, "revision": revision}
    probe = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": "2026-01-01T00:00:00Z",
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [item],
    }
    _validate_provenance(probe)
    return item


def provenance_from_identity(identity: Mapping[str, Any]) -> dict[str, Any]:
    try:
        validate_identity_bundle(identity)
    except Exception as exc:
        raise MRBodyError(str(exc)) from exc
    identifier = identity["id"]
    match = _BODYID_RE.fullmatch(identifier) if isinstance(identifier, str) else None
    if match is None:
        raise MRBodyError("identity id is not a canonical bodyid")
    motion = identity["components"]["motion"]
    created_at = motion["manifest"].get("created_at")
    backend = identity["binding"]["backend"]
    value = {
        "format": "modelrig-body-provenance",
        "version": 1,
        "created_at": created_at,
        "source": {"kind": "user-supplied-local-media", "count": 1},
        "synthetic_avatar": True,
        "pipeline": [
            _pipeline_item("tracking", backend["id"], backend["model_revision"]),
            _pipeline_item(
                "identity_content",
                "modelrig.bodyrig.identity_bundle",
                match.group(1),
            ),
            _pipeline_item("mrbody_builder", "bodyrig", MRBODY_BUILDER_VERSION),
        ],
    }
    _validate_provenance(value)
    return value


def _identity_from_provenance(provenance: Mapping[str, Any]) -> str | None:
    identity_stages = [
        item
        for item in provenance.get("pipeline", [])
        if isinstance(item, Mapping) and item.get("stage") == "identity_content"
    ]
    if not identity_stages:
        return None
    if len(identity_stages) != 1:
        raise MRBodyError("provenance contains ambiguous identity_content stages")
    stage = identity_stages[0]
    if stage.get("adapter") not in IDENTITY_CONTENT_AUTHORITIES:
        return None
    revision = stage.get("revision")
    if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{24}", revision) is None:
        raise MRBodyError("provenance identity_content revision is invalid")
    return f"bodyid-{revision}"


def _payload_digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _zip_info(path: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_STORED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.flag_bits = 0
    return info


def build_mrbody(
    identity: Mapping[str, Any],
    *,
    display_name: str,
    avatar_vrm: bytes,
    thumbnail_png: bytes,
    motions: Mapping[str, bytes] | None = None,
    builder_revision: str | None = None,
) -> bytes:
    """Build deterministic `.mrbody` V1 bytes from validated derived identity/assets."""

    try:
        validate_identity_bundle(identity)
    except Exception as exc:
        raise MRBodyError(str(exc)) from exc
    identifier = identity.get("id")
    if not isinstance(identifier, str) or _BODYID_RE.fullmatch(identifier) is None:
        raise MRBodyError("M2.5 requires a canonical M2.4 bodyid")
    if not isinstance(display_name, str) or not 1 <= len(display_name) <= 160:
        raise MRBodyError("display_name must contain 1..160 characters")
    validate_vrm1_bytes(avatar_vrm)
    validate_png_bytes(thumbnail_png)

    motion_payloads: dict[str, bytes] = {}
    for path, data in (motions or {}).items():
        if path not in OPTIONAL_MOTION_PATHS:
            raise MRBodyError(f"unsupported optional motion path: {path!r}")
        if not isinstance(data, bytes) or not data or len(data) > ENTRY_LIMITS[path]:
            raise MRBodyError(f"{path} is empty or exceeds the V1 size limit")
        motion_payloads[path] = data

    bodyprint = portable_bodyprint_from_identity(identity)
    provenance = provenance_from_identity(identity)
    bodyprint_bytes = _canonical_json_bytes(bodyprint)
    provenance_bytes = _canonical_json_bytes(provenance)
    payloads: dict[str, bytes] = {
        "avatar.vrm": avatar_vrm,
        "bodyprint.json": bodyprint_bytes,
        "provenance.json": provenance_bytes,
        "thumbnail.png": thumbnail_png,
        **motion_payloads,
    }
    checksums = {path: _payload_digest(data) for path, data in sorted(payloads.items())}
    checksums_bytes = _canonical_json_bytes(checksums)
    builder: dict[str, str] = {"name": "bodyrig", "version": MRBODY_BUILDER_VERSION}
    if builder_revision is not None:
        if not isinstance(builder_revision, str) or _REVISION_RE.fullmatch(builder_revision) is None:
            raise MRBodyError("builder_revision must be a 40-character lowercase git SHA")
        builder["revision"] = builder_revision
    manifest = {
        "format": MRBODY_FORMAT,
        "format_version": MRBODY_VERSION,
        "id": identifier,
        "name": display_name,
        "avatar": {"format": "vrm", "version": "1.0", "path": "avatar.vrm"},
        "bodyprint": "bodyprint.json",
        "provenance": "provenance.json",
        "thumbnail": "thumbnail.png",
        "builder": builder,
    }
    _validate_manifest(manifest)
    manifest_bytes = _canonical_json_bytes(manifest)

    entries: dict[str, bytes] = {
        "manifest.json": manifest_bytes,
        "checksums.json": checksums_bytes,
        **payloads,
    }
    if len(entries) > MAX_ENTRIES:
        raise MRBodyError("package exceeds V1 entry-count limit")
    if sum(len(data) for data in entries.values()) > MAX_TOTAL_UNCOMPRESSED:
        raise MRBodyError("package exceeds V1 total uncompressed limit")
    for path, data in entries.items():
        if len(data) > ENTRY_LIMITS[path]:
            raise MRBodyError(f"{path} exceeds its V1 size limit")

    order = [*REQUIRED_PATHS, *sorted(motion_payloads)]
    output = BytesIO()
    with zipfile.ZipFile(output, "w", allowZip64=False) as archive:
        for path in order:
            archive.writestr(_zip_info(path), entries[path])
    result = output.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise MRBodyError("package archive bytes exceed implementation safety cap")
    inspection = validate_mrbody(result, expected_identity_id=identifier)
    if inspection.body_id != identifier:
        raise MRBodyError("builder self-validation lost identity binding")
    return result


def _validate_archive_path(path: str) -> None:
    if not path or "\x00" in path or "\\" in path:
        raise MRBodyError("archive path is empty, NUL-containing or uses backslashes")
    pure = PurePosixPath(path)
    if path.startswith("/") or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise MRBodyError(f"archive path is absolute or traversing: {path!r}")
    if path not in ALLOWED_PATHS:
        raise MRBodyError(f"archive contains unsupported path: {path!r}")


def _validate_zip_info(info: zipfile.ZipInfo) -> None:
    _validate_archive_path(info.filename)
    if info.is_dir():
        raise MRBodyError("directory entries are not valid in `.mrbody` V1")
    if info.flag_bits & 0x1:
        raise MRBodyError("encrypted ZIP entries are forbidden")
    if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
        raise MRBodyError("unsupported ZIP compression method")
    mode = (info.external_attr >> 16) & 0xFFFF
    kind = stat.S_IFMT(mode)
    if kind not in {0, stat.S_IFREG}:
        raise MRBodyError("symlink/special-file ZIP entries are forbidden")
    cap = ENTRY_LIMITS[info.filename]
    if info.file_size < 0 or info.file_size > cap:
        raise MRBodyError(f"{info.filename} exceeds its declared V1 size limit")
    if info.compress_size < 0:
        raise MRBodyError("ZIP entry has invalid compressed size")


def _read_entry_bounded(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
    cap = ENTRY_LIMITS[info.filename]
    output = bytearray()
    try:
        with archive.open(info, "r") as stream:
            while True:
                chunk = stream.read(min(64 * 1024, cap + 1 - len(output)))
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > cap:
                    raise MRBodyError(f"{info.filename} expands beyond its V1 size limit")
    except MRBodyError:
        raise
    except (RuntimeError, OSError, EOFError, zipfile.BadZipFile) as exc:
        raise MRBodyError(f"failed to read ZIP entry {info.filename}") from exc
    if len(output) != info.file_size:
        raise MRBodyError(f"{info.filename} decompressed size disagrees with ZIP metadata")
    return bytes(output)


def validate_mrbody(
    archive_bytes: bytes,
    *,
    expected_identity_id: str | None = None,
) -> MRBodyInspection:
    """Validate an untrusted `.mrbody` entirely before any extraction occurs."""

    if not isinstance(archive_bytes, bytes) or not archive_bytes:
        raise MRBodyError("`.mrbody` archive must be non-empty bytes")
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise MRBodyError("`.mrbody` archive exceeds implementation safety cap")
    try:
        archive = zipfile.ZipFile(BytesIO(archive_bytes), "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise MRBodyError("invalid `.mrbody` ZIP container") from exc

    with archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= MAX_ENTRIES:
            raise MRBodyError("archive entry count is outside V1 limits")
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise MRBodyError("archive contains duplicate entries")
        for info in infos:
            _validate_zip_info(info)
        present = set(names)
        if not set(REQUIRED_PATHS) <= present:
            raise MRBodyError("archive is missing one or more required V1 files")
        total_declared = sum(info.file_size for info in infos)
        if total_declared > MAX_TOTAL_UNCOMPRESSED:
            raise MRBodyError("archive exceeds V1 total uncompressed limit")

        entries: dict[str, bytes] = {}
        streamed_total = 0
        for info in infos:
            data = _read_entry_bounded(archive, info)
            streamed_total += len(data)
            if streamed_total > MAX_TOTAL_UNCOMPRESSED:
                raise MRBodyError("archive expands beyond V1 total uncompressed limit")
            entries[info.filename] = data

    manifest = _json_object(entries["manifest.json"], "manifest.json")
    bodyprint = _json_object(entries["bodyprint.json"], "bodyprint.json")
    provenance = _json_object(entries["provenance.json"], "provenance.json")
    raw_checksums = _json_object(entries["checksums.json"], "checksums.json")
    _validate_manifest(manifest)
    _validate_bodyprint(bodyprint)
    _validate_provenance(provenance)
    checksums = _validate_checksums(raw_checksums, set(entries))

    for path, expected in checksums.items():
        actual = _payload_digest(entries[path])
        if actual != expected:
            raise MRBodyError(f"checksum mismatch for {path}")

    validate_vrm1_bytes(entries["avatar.vrm"])
    validate_png_bytes(entries["thumbnail.png"])

    embedded_identity = _identity_from_provenance(provenance)
    if embedded_identity is not None and manifest["id"] != embedded_identity:
        raise MRBodyError("manifest.id disagrees with provenance identity_content binding")
    if expected_identity_id is not None:
        if not isinstance(expected_identity_id, str) or _BODYID_RE.fullmatch(expected_identity_id) is None:
            raise MRBodyError("expected_identity_id must be a canonical bodyid")
        if manifest["id"] != expected_identity_id:
            raise MRBodyError("package manifest id does not match expected identity")
        if embedded_identity != expected_identity_id:
            raise MRBodyError("package provenance does not bind the expected identity")

    return MRBodyInspection(
        body_id=manifest["id"],
        name=manifest["name"],
        identity_content_id=embedded_identity,
        manifest=manifest,
        bodyprint=bodyprint,
        provenance=provenance,
        checksums=checksums,
        payload_sizes=tuple(sorted((path, len(data)) for path, data in entries.items())),
    )

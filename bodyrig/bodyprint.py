from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping


class BodyprintValidationError(ValueError):
    """Raised when a bodyprint manifest violates the v0.1 contract."""


_CAPABILITIES = {
    "appearance",
    "body_shape",
    "motion_style",
    "face_behavior",
    "gaze",
    "gestures",
}
_CONFIDENCE_FIELDS = {
    "appearance",
    "body_shape",
    "motion",
    "face_behavior",
    "hands",
    "gaze",
}


def _require_string(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value:
        raise BodyprintValidationError(f"{key} must be a non-empty string")
    return value


def _validate_confidence(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BodyprintValidationError(f"confidence.{field} must be numeric")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise BodyprintValidationError(f"confidence.{field} must be within 0..1")


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    """Validate the stable, runtime-relevant subset of bodyprint v0.1.

    The repository also contains the normative JSON Schema.  This stdlib
    validator intentionally covers the same high-value invariants without
    adding a package dependency to ModelRig CI.
    """

    if not isinstance(manifest, Mapping):
        raise BodyprintValidationError("manifest must be an object")
    if manifest.get("format") != "bodyrig.bodyprint":
        raise BodyprintValidationError("unsupported bodyprint format")

    version = _require_string(manifest, "version")
    parts = version.split(".")
    if len(parts) != 3 or parts[:2] != ["0", "1"] or not parts[2].isdigit():
        raise BodyprintValidationError("only bodyprint version 0.1.x is supported")

    _require_string(manifest, "id")
    created_at = _require_string(manifest, "created_at")
    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BodyprintValidationError("created_at must be an ISO-8601 timestamp") from exc

    capabilities = manifest.get("capabilities")
    if not isinstance(capabilities, list):
        raise BodyprintValidationError("capabilities must be an array")
    if any(not isinstance(item, str) or item not in _CAPABILITIES for item in capabilities):
        raise BodyprintValidationError("capabilities contains an unsupported value")
    if len(set(capabilities)) != len(capabilities):
        raise BodyprintValidationError("capabilities must be unique")

    confidence = manifest.get("confidence")
    if not isinstance(confidence, Mapping):
        raise BodyprintValidationError("confidence must be an object")
    if set(confidence) != _CONFIDENCE_FIELDS:
        raise BodyprintValidationError(
            "confidence must contain exactly: " + ", ".join(sorted(_CONFIDENCE_FIELDS))
        )
    for field in _CONFIDENCE_FIELDS:
        _validate_confidence(confidence[field], field)

    avatar = manifest.get("avatar")
    if avatar is not None:
        if not isinstance(avatar, Mapping):
            raise BodyprintValidationError("avatar must be an object or null")
        _require_string(avatar, "path")
        _require_string(avatar, "format")
        if not isinstance(avatar.get("optional"), bool):
            raise BodyprintValidationError("avatar.optional must be boolean")

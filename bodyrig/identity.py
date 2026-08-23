"""BodyRig M2.4 unified content-addressed identity bundle.

The bundle binds the already-independent M1.2 motion bodyprint, M1.3 shape
profile and M2.1 facial-behavior profile to one canonical tracking receipt.
It is data-only and renderer-neutral: no source media, ML runtime dependency,
bones, VRM mappings or executable payloads are introduced here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .face_behavior import (
    build_face_behavior,
    canonical_face_behavior_json,
    validate_face_behavior,
)
from .fingerprint import (
    FingerprintConfig,
    build_bodyprint,
    canonical_bodyprint_json,
    validate_bodyprint_package,
)
from .shape import (
    ShapeConfig,
    build_shape_profile,
    canonical_shape_json,
    validate_shape_profile,
)
from .tracking import SCHEMA as TRACKING_SCHEMA

SCHEMA = "bodyrig.identity_bundle/v0.1"
BUILDER_ID = "modelrig.bodyrig.identity_bundle"
BUILDER_VERSION = "0.1.0"


class IdentityBundleError(ValueError):
    """One or more BodyRig identity components cannot be bound safely."""


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise IdentityBundleError(f"{label} must be a SHA-256 digest")
    try:
        int(value, 16)
    except ValueError as exc:
        raise IdentityBundleError(f"{label} must be a SHA-256 digest") from exc
    return value.lower()


def _backend(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise IdentityBundleError(f"{label} must be an object")
    expected = {"id", "version", "model_revision"}
    if set(value) != expected:
        raise IdentityBundleError(f"{label} fields are invalid")
    result: dict[str, str] = {}
    for key in ("id", "version", "model_revision"):
        item = value.get(key)
        if not isinstance(item, str) or not item:
            raise IdentityBundleError(f"{label}.{key} is required")
        result[key] = item
    return result


def _motion_binding(motion: Mapping[str, Any]) -> dict[str, Any]:
    provenance = motion["provenance"]
    return {
        "tracking_schema": provenance["tracking_schema"],
        "tracking_sha256": _sha256(provenance["tracking_sha256"], "motion.provenance.tracking_sha256"),
        "source_sha256": _sha256(provenance["source_sha256"], "motion.provenance.source_sha256"),
        "backend": _backend(provenance["backend"], "motion.provenance.backend"),
    }


def _shape_binding(shape: Mapping[str, Any]) -> dict[str, Any]:
    evidence = shape["evidence"]
    return {
        "tracking_schema": TRACKING_SCHEMA,
        "tracking_sha256": _sha256(evidence["tracking_sha256"], "shape.evidence.tracking_sha256"),
        "source_sha256": _sha256(evidence["source_sha256"], "shape.evidence.source_sha256"),
        "backend": _backend(evidence["backend"], "shape.evidence.backend"),
    }


def _face_binding(face: Mapping[str, Any]) -> dict[str, Any]:
    provenance = face["provenance"]
    return {
        "tracking_schema": provenance["tracking_schema"],
        "tracking_sha256": _sha256(provenance["tracking_sha256"], "face.provenance.tracking_sha256"),
        "source_sha256": _sha256(provenance["source_sha256"], "face.provenance.source_sha256"),
        "backend": _backend(provenance["backend"], "face.provenance.backend"),
    }


def _identity_payload(bundle: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in bundle.items() if key != "id"}


def _content_id(bundle: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _identity_payload(bundle),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"bodyid-{hashlib.sha256(canonical).hexdigest()[:24]}"


def _validate_components(
    motion: Mapping[str, Any],
    shape: Mapping[str, Any],
    face: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    try:
        validate_bodyprint_package(motion)
        validate_shape_profile(shape)
        validate_face_behavior(face)
    except Exception as exc:
        raise IdentityBundleError(str(exc)) from exc

    motion_binding = _motion_binding(motion)
    shape_binding = _shape_binding(shape)
    face_binding = _face_binding(face)
    if motion_binding["tracking_schema"] != TRACKING_SCHEMA:
        raise IdentityBundleError("motion tracking schema is invalid")
    if shape_binding != motion_binding:
        raise IdentityBundleError("shape profile does not bind the same tracking/source/backend receipt")
    if face_binding != motion_binding:
        raise IdentityBundleError("face behavior does not bind the same tracking/source/backend receipt")

    if motion["provenance"].get("source_video_required_at_runtime") is not False:
        raise IdentityBundleError("motion runtime must not require source video")
    if shape["evidence"].get("source_video_required_at_runtime") is not False:
        raise IdentityBundleError("shape runtime must not require source video")
    if face["provenance"].get("source_video_required_at_runtime") is not False:
        raise IdentityBundleError("face runtime must not require source video")
    return motion_binding, shape_binding, face_binding


def compose_identity_bundle(
    *,
    motion: Mapping[str, Any],
    shape: Mapping[str, Any],
    face: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind separately-built components that prove one identical tracking receipt."""

    binding, _shape_binding_value, _face_binding_value = _validate_components(
        motion, shape, face
    )
    bundle: dict[str, Any] = {
        "schema": SCHEMA,
        "id": "pending",
        "binding": binding,
        "component_ids": {
            "motion": motion["manifest"]["id"],
            "shape": shape["id"],
            "face": face["id"],
        },
        "components": {
            "motion": dict(motion),
            "shape": dict(shape),
            "face": dict(face),
        },
        "builder": {"id": BUILDER_ID, "version": BUILDER_VERSION},
        "runtime": {"source_video_required_at_runtime": False},
        "production_activation": False,
    }
    bundle["id"] = _content_id(bundle)
    validate_identity_bundle(bundle)
    return bundle


def build_identity_bundle(
    tracking: Mapping[str, Any],
    *,
    fingerprint_config: FingerprintConfig | None = None,
    shape_config: ShapeConfig | None = None,
) -> dict[str, Any]:
    """Build all landed BodyRig identity components from one tracking receipt."""

    try:
        motion = build_bodyprint(tracking, config=fingerprint_config)
        shape = build_shape_profile(tracking, config=shape_config)
        face = build_face_behavior(tracking)
    except Exception as exc:
        raise IdentityBundleError(str(exc)) from exc
    return compose_identity_bundle(motion=motion, shape=shape, face=face)


def validate_identity_bundle(bundle: Mapping[str, Any]) -> None:
    if not isinstance(bundle, Mapping):
        raise IdentityBundleError("identity bundle must be an object")
    expected = {
        "schema",
        "id",
        "binding",
        "component_ids",
        "components",
        "builder",
        "runtime",
        "production_activation",
    }
    if set(bundle) != expected:
        raise IdentityBundleError("identity bundle contains missing or unsupported top-level fields")
    if bundle.get("schema") != SCHEMA:
        raise IdentityBundleError(f"schema must be {SCHEMA}")
    if bundle.get("production_activation") is not False:
        raise IdentityBundleError("production_activation must remain false")

    components = bundle.get("components")
    if not isinstance(components, Mapping) or set(components) != {"motion", "shape", "face"}:
        raise IdentityBundleError("components fields are invalid")
    motion = components["motion"]
    shape = components["shape"]
    face = components["face"]
    if not all(isinstance(item, Mapping) for item in (motion, shape, face)):
        raise IdentityBundleError("all identity components must be objects")
    motion_binding, _shape_value, _face_value = _validate_components(motion, shape, face)

    binding = bundle.get("binding")
    if not isinstance(binding, Mapping) or set(binding) != {
        "tracking_schema",
        "tracking_sha256",
        "source_sha256",
        "backend",
    }:
        raise IdentityBundleError("binding fields are invalid")
    normalized_binding = {
        "tracking_schema": binding.get("tracking_schema"),
        "tracking_sha256": _sha256(binding.get("tracking_sha256"), "binding.tracking_sha256"),
        "source_sha256": _sha256(binding.get("source_sha256"), "binding.source_sha256"),
        "backend": _backend(binding.get("backend"), "binding.backend"),
    }
    if normalized_binding != motion_binding:
        raise IdentityBundleError("bundle binding does not match component tracking receipt")

    component_ids = bundle.get("component_ids")
    if not isinstance(component_ids, Mapping) or set(component_ids) != {"motion", "shape", "face"}:
        raise IdentityBundleError("component_ids fields are invalid")
    expected_ids = {
        "motion": motion["manifest"]["id"],
        "shape": shape["id"],
        "face": face["id"],
    }
    if dict(component_ids) != expected_ids:
        raise IdentityBundleError("component_ids do not match embedded component identities")

    builder = bundle.get("builder")
    if not isinstance(builder, Mapping) or set(builder) != {"id", "version"}:
        raise IdentityBundleError("builder fields are invalid")
    if builder.get("id") != BUILDER_ID or builder.get("version") != BUILDER_VERSION:
        raise IdentityBundleError("identity bundle builder provenance is invalid")

    runtime = bundle.get("runtime")
    if not isinstance(runtime, Mapping) or set(runtime) != {"source_video_required_at_runtime"}:
        raise IdentityBundleError("runtime fields are invalid")
    if runtime.get("source_video_required_at_runtime") is not False:
        raise IdentityBundleError("identity runtime must not require source video")

    identifier = bundle.get("id")
    if not isinstance(identifier, str) or not identifier.startswith("bodyid-"):
        raise IdentityBundleError("identity bundle id is invalid")
    if identifier != _content_id(bundle):
        raise IdentityBundleError("identity bundle id does not match complete bundle content")


def canonical_identity_json(bundle: Mapping[str, Any]) -> str:
    validate_identity_bundle(bundle)
    return json.dumps(
        bundle,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_component_jsons(bundle: Mapping[str, Any]) -> dict[str, str]:
    """Return individually validated canonical component JSON for package builders."""

    validate_identity_bundle(bundle)
    components = bundle["components"]
    return {
        "motion": canonical_bodyprint_json(components["motion"]),
        "shape": canonical_shape_json(components["shape"]),
        "face": canonical_face_behavior_json(components["face"]),
    }

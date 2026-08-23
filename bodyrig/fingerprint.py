"""Public BodyRig M1.2 fingerprint API with whole-package content identity.

The reviewed motion/gesture implementation lives byte-for-byte in
``_fingerprint_impl``. This facade strengthens only the public identity
boundary: ``manifest.id`` names the complete validated package, excluding the
id field itself so the digest is not self-referential.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from . import _fingerprint_impl as _impl
from ._fingerprint_impl import *  # noqa: F401,F403 - preserve established API


def _identity_payload(package: Mapping[str, Any]) -> dict[str, Any]:
    manifest = package.get("manifest")
    if not isinstance(manifest, Mapping):
        raise FingerprintError("bodyprint manifest must be an object")
    manifest_without_id = dict(manifest)
    manifest_without_id.pop("id", None)
    return {
        "schema": package.get("schema"),
        "manifest": manifest_without_id,
        "motion_profile": package.get("motion_profile"),
        "gestures": package.get("gestures"),
        "provenance": package.get("provenance"),
        "production_activation": package.get("production_activation"),
    }


def _content_id(package: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _identity_payload(package),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return f"bodyprint-{hashlib.sha256(canonical).hexdigest()[:24]}"


def validate_bodyprint_package(package: Mapping[str, Any]) -> None:
    """Validate structure, gesture identities and whole-package identity."""
    _impl.validate_bodyprint_package(package)
    actual_id = package["manifest"].get("id")
    expected_id = _content_id(package)
    if actual_id != expected_id:
        raise FingerprintError("manifest.id does not match complete bodyprint package content")


def build_bodyprint(
    tracking: Mapping[str, Any], *, config: FingerprintConfig | None = None
) -> dict[str, Any]:
    """Build a deterministic bodyprint whose id names the complete package."""
    package = _impl.build_bodyprint(tracking, config=config)
    package["manifest"] = dict(package["manifest"])
    package["manifest"]["id"] = _content_id(package)
    validate_bodyprint_package(package)
    return package


def canonical_bodyprint_json(package: Mapping[str, Any]) -> str:
    """Serialize only a structurally and content-identity valid package."""
    validate_bodyprint_package(package)
    return json.dumps(
        package,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )

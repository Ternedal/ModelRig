"""Dependency-free media request validation for staged image/video integration.

No GPU, network or filesystem operations are performed here.
"""
from __future__ import annotations

import re

_ASSET_ID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")
_KINDS = frozenset({"text_to_image", "image_to_image", "text_to_video", "image_to_video"})


def validate_request(request: object) -> dict:
    """Return a validated normalized request or raise ValueError.

    This is a staging contract, not an enabled production endpoint.
    """
    if not isinstance(request, dict):
        raise ValueError("request_must_be_object")
    if set(request) - {"kind", "prompt", "input_image_id"}:
        raise ValueError("unexpected_fields")
    kind = request.get("kind")
    if not isinstance(kind, str) or kind not in _KINDS:
        raise ValueError("unsupported_kind")
    prompt = request.get("prompt")
    if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 2000:
        raise ValueError("invalid_prompt")
    image_id = request.get("input_image_id")
    if kind in {"image_to_image", "image_to_video"}:
        if not isinstance(image_id, str) or _ASSET_ID.fullmatch(image_id) is None:
            raise ValueError("invalid_input_image_id")
    elif image_id is not None:
        raise ValueError("unexpected_input_image_id")
    return {"kind": kind, "prompt": prompt.strip(), "input_image_id": image_id}

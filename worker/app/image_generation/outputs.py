"""Strict ComfyUI output selection.

Descriptors are never accepted from a client. Callers must obtain them from
history of a prompt ID created by the server and owned by the requesting job.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SAFE_FILENAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True)
class ImageDescriptor:
    filename: str
    subfolder: str
    kind: str


def select_output_image(outputs: Any) -> ImageDescriptor:
    """Select a validated output image without accepting path components."""
    if not isinstance(outputs, dict):
        raise ValueError("Missing ComfyUI outputs")
    for output in outputs.values():
        if not isinstance(output, dict):
            continue
        images = output.get("images")
        if not isinstance(images, list):
            continue
        for item in images:
            if not isinstance(item, dict):
                continue
            filename = item.get("filename")
            subfolder = item.get("subfolder", "")
            kind = item.get("type")
            if (
                isinstance(filename, str)
                and _SAFE_FILENAME.fullmatch(filename)
                and not filename.startswith(".")
                and filename.lower().endswith((".png", ".webp", ".jpg", ".jpeg"))
                and subfolder == ""
                and kind == "output"
            ):
                return ImageDescriptor(filename=filename, subfolder="", kind="output")
    raise ValueError("No safe output image descriptor")

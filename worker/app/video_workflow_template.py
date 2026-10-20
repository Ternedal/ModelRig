"""Operator-owned ComfyUI workflow template binding (offline, no execution).

The graph is loaded from a locally provisioned JSON file, never from a request.
Only the literal prompt placeholder is substituted; no user text becomes a
node ID, class type, model path, or graph structure.
"""
from __future__ import annotations

import json
from pathlib import Path

from .video_contract import VideoRequest

PROMPT_SLOT = "__KALIV_VIDEO_PROMPT__"
MAX_TEMPLATE_BYTES = 1_000_000


def trusted_text_to_video_factory(template_path: Path):
    """Load an operator-installed, immutable-for-this-process API-format graph."""
    path = Path(template_path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise ValueError("Absolute regular workflow template file required")
    if not path.name.endswith(".json") or path.stat().st_size > MAX_TEMPLATE_BYTES:
        raise ValueError("Invalid workflow template file")
    with path.open("rb") as handle:
        raw = handle.read(MAX_TEMPLATE_BYTES + 1)
    if len(raw) > MAX_TEMPLATE_BYTES:
        raise ValueError("Workflow template too large")
    graph = json.loads(raw)
    if not isinstance(graph, dict) or not graph:
        raise ValueError("Expected ComfyUI API-format workflow object")
    slots = 0
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not node_id.isdecimal() or not isinstance(node, dict):
            raise ValueError("Invalid ComfyUI workflow node")
        if not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ValueError("Invalid ComfyUI workflow node definition")
        for key, value in node["inputs"].items():
            if value == PROMPT_SLOT:
                if key != "text":
                    raise ValueError("Prompt placeholder must be a text input")
                slots += 1
    if slots != 1:
        raise ValueError("Exactly one text prompt placeholder is required")

    def build(request: VideoRequest) -> dict:
        if request.kind != "text_to_video" or request.output_profile != "flat_2d":
            raise ValueError("Template only supports flat text-to-video")
        # JSON roundtrip copies graph and ensures only JSON-compatible values.
        result = json.loads(json.dumps(graph))
        for node in result.values():
            if node["inputs"].get("text") == PROMPT_SLOT:
                node["inputs"]["text"] = request.prompt
        return result

    return build

"""Operator-owned ComfyUI workflow template binding (offline, no execution).

The graph is loaded from a locally provisioned JSON file, never from a request.
Only allowlisted literal placeholders are substituted; user input never
becomes a node ID, class type, model path, or graph structure.
"""
from __future__ import annotations

import json
from pathlib import Path

from .video_contract import VideoRequest

SLOTS = {
    "__KALIV_VIDEO_PROMPT__": ("text", "prompt"),
    "__KALIV_VIDEO_WIDTH__": ("width", "width"),
    "__KALIV_VIDEO_HEIGHT__": ("height", "height"),
    "__KALIV_VIDEO_FPS__": ("fps", "fps"),
    "__KALIV_VIDEO_FRAMES__": ("length", "frames"),
}
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
    found = {}
    for node_id, node in graph.items():
        if not isinstance(node_id, str) or not node_id.isdecimal() or not isinstance(node, dict):
            raise ValueError("Invalid ComfyUI workflow node")
        if not isinstance(node.get("class_type"), str) or not isinstance(node.get("inputs"), dict):
            raise ValueError("Invalid ComfyUI workflow node definition")
        for key, value in node["inputs"].items():
            serialized = json.dumps(value, ensure_ascii=True)
            for marker, (expected_key, _) in SLOTS.items():
                if marker not in serialized:
                    continue
                if key != expected_key or value != marker or marker in found:
                    raise ValueError("Invalid or duplicate workflow parameter slot")
                found[marker] = (node_id, key)
    if set(found) != set(SLOTS):
        raise ValueError("Workflow must bind prompt, width, height, fps and frames exactly once")

    def build(request: VideoRequest) -> dict:
        if request.kind != "text_to_video" or request.output_profile != "flat_2d":
            raise ValueError("Template only supports flat text-to-video")
        result = json.loads(json.dumps(graph))
        values = {
            "prompt": request.prompt,
            "width": request.width,
            "height": request.height,
            "fps": request.fps,
            "frames": request.fps * request.duration_seconds + 1,
        }
        for marker, (node_id, key) in found.items():
            result[node_id]["inputs"][key] = values[SLOTS[marker][1]]
        return result

    return build

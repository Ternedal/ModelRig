"""Pinned, operator-owned ComfyUI workflow templates (ModelRig #2296 slice 2).

A template is an API-format ComfyUI graph that an operator installs. The
profile pins its SHA-256; the bytes are hashed and parsed exactly once, so
the graph that is checked is the graph that runs. Requests only fill marked
value slots: a prompt never becomes a node id, class type, model file name or
graph structure, and the graph itself never comes from a request.

Slot markers are whole input values. Each must appear exactly once, under an
input name from its allowlist, and no other string in the graph may contain
the marker prefix.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from typing import Mapping

from .media_generation_contract import GenerationError, GenerationRequest

MAX_TEMPLATE_BYTES = 1024 * 1024
MAX_NODES = 512
MARKER_PREFIX = "__KALIV_VIDEO_"

# marker -> (request field, input names it may fill)
SLOTS: Mapping[str, tuple[str, frozenset[str]]] = {
    "__KALIV_VIDEO_PROMPT__": ("prompt", frozenset({"text", "prompt"})),
    "__KALIV_VIDEO_WIDTH__": ("width", frozenset({"width"})),
    "__KALIV_VIDEO_HEIGHT__": ("height", frozenset({"height"})),
    "__KALIV_VIDEO_FPS__": ("fps", frozenset({"fps", "frame_rate"})),
    "__KALIV_VIDEO_FRAMES__": ("frames", frozenset({"length", "num_frames", "frames"})),
    "__KALIV_VIDEO_STEPS__": ("steps", frozenset({"steps"})),
    "__KALIV_VIDEO_SEED__": ("seed", frozenset({"seed", "noise_seed"})),
}

_SHA256 = re.compile(r"[0-9a-f]{64}")


def _fail(reason: str) -> GenerationError:
    return GenerationError(f"workflow template refused: {reason}")


def _strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)


@dataclass(frozen=True)
class WorkflowTemplate:
    graph: Mapping[str, object]
    slots: Mapping[str, tuple[str, str]]  # marker -> (node id, input name)
    sha256: str

    def bind(self, request: GenerationRequest, *, fps: int) -> dict:
        """A fresh graph with request values in the slots. The request must already be validated."""
        if request.task != "text_to_video":
            raise GenerationError("this template binds text_to_video only")
        seed = request.seed if request.seed is not None else secrets.randbelow(2**32)
        values = {"prompt": request.prompt, "width": request.width, "height": request.height,
                  "fps": fps, "frames": request.frames, "steps": request.steps, "seed": seed}
        for field in ("width", "height", "frames", "steps"):
            if type(values[field]) is not int:
                raise GenerationError(f"{field} must be filled in by validate_request first")
        graph = copy.deepcopy(dict(self.graph))
        for marker, (node_id, input_name) in self.slots.items():
            graph[node_id]["inputs"][input_name] = values[SLOTS[marker][0]]
        return graph


def load_template(raw: bytes, expected_sha256: str) -> WorkflowTemplate:
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise _fail("pinned SHA-256 is malformed")
    if type(raw) is not bytes or not raw or len(raw) > MAX_TEMPLATE_BYTES:
        raise _fail("template must be 1 byte..1 MiB")
    actual = hashlib.sha256(raw).hexdigest()
    if not hmac.compare_digest(actual, expected_sha256):
        raise _fail("SHA-256 does not match the profile pin")
    try:
        graph = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise _fail("not valid JSON") from None
    if not isinstance(graph, dict) or not 1 <= len(graph) <= MAX_NODES:
        raise _fail("expected an API-format graph object")
    found: dict[str, tuple[str, str]] = {}
    for node_id, node in graph.items():
        if not node_id.isdecimal() or not isinstance(node, dict):
            raise _fail("node ids must be decimal and nodes objects")
        if set(node) - {"class_type", "inputs", "_meta"}:
            raise _fail(f"node {node_id} has unexpected keys")
        if not isinstance(node.get("class_type"), str) or not node["class_type"]:
            raise _fail(f"node {node_id} has no class_type")
        if MARKER_PREFIX in node["class_type"]:
            raise _fail("a slot marker cannot name a class")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            raise _fail(f"node {node_id} has no inputs object")
        for input_name, value in inputs.items():
            if isinstance(value, str) and value in SLOTS:
                field, allowed = SLOTS[value]
                if input_name not in allowed:
                    raise _fail(f"{value} may not fill input {input_name!r}")
                if value in found:
                    raise _fail(f"{value} appears more than once")
                found[value] = (node_id, input_name)
            elif any(MARKER_PREFIX in text for text in _strings(value)):
                raise _fail("a slot marker must be a whole input value")
            if MARKER_PREFIX in input_name:
                raise _fail("a slot marker cannot be an input name")
        if "_meta" in node and any(MARKER_PREFIX in text for text in _strings(node["_meta"])):
            raise _fail("a slot marker cannot sit in _meta")
    missing = sorted(set(SLOTS) - set(found))
    if missing:
        raise _fail(f"missing slots {missing}")
    return WorkflowTemplate(graph=graph, slots=found, sha256=actual)

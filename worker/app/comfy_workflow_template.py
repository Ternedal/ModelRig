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
# Every extension ComfyUI lists in a model folder (folder_paths.supported_pt_extensions), plus
# .gguf. A string input ending in one of these is a model file, whatever the input is called.
MODEL_FILE_SUFFIXES = (".safetensors", ".ckpt", ".pt", ".pt2", ".pth", ".bin", ".pkl", ".gguf", ".sft")


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


# ComfyUI's tokenizer loads models/embeddings/<name> for "embedding:<name>" in any text it
# encodes, with or without an extension (comfy/sd1_clip.py). Under pins no such load is allowed.
EMBEDDING_REFERENCE = "embedding:"


@dataclass(frozen=True)
class WorkflowTemplate:
    graph: Mapping[str, object]
    slots: Mapping[str, tuple[str, str]]  # marker -> (node id, input name)
    sha256: str
    pinned: bool = False

    def bind(self, request: GenerationRequest, *, fps: int) -> dict:
        """A fresh graph with request values in the slots. The request must already be validated."""
        if self.pinned and EMBEDDING_REFERENCE in request.prompt.casefold():
            # The prompt enters the graph here, after load_template's checks (#2328 review 4472675615).
            raise GenerationError("a prompt may not reference an embedding under a pinned profile")
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


def _model_files(graph: Mapping[str, object]):
    """(node id, input name, value) for every input value that names a model file.

    Keyed on the VALUE, not the input name: loaders name their inputs freely
    (ckpt_name, unet_name, but also clip_name1/clip_name2 on DualCLIPLoader), so a
    name heuristic lets an unpinned file through (#2328 review 4472123690).

    Detection is generous (case and surrounding whitespace ignored); the value is then
    compared with the pins EXACTLY as ComfyUI will receive it. " wan.safetensors" is a different
    file from "wan.safetensors" and must not satisfy its pin (#2328 review 4472405235).
    """
    for node_id, node in graph.items():
        for input_name, value in node["inputs"].items():
            for text in _strings(value):
                if text.strip().lower().endswith(MODEL_FILE_SUFFIXES):
                    yield node_id, input_name, text


def load_template(raw: bytes, expected_sha256: str, *, pinned_files=None) -> WorkflowTemplate:
    """pinned_files: the profile's weights paths. When given, every model file the graph loads
    must be one of them (G3, #2296 6634996133): a pinned graph can only load pinned bytes.

    A loader names its file relative to its model folder, so a value must equal a pin's path
    without the folder: pin "loras/sub/x.safetensors" is loaded as "sub/x.safetensors". Exactly,
    and with "/" only -- a backslash is a separator on Windows but a file-name character on
    POSIX, so "evil\\x.safetensors" is ambiguous and refused (#2328 review 4472675602)."""
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
    if pinned_files is not None:
        loadable = {str(path).split("/", 1)[1] for path in pinned_files if "/" in str(path)}
        for node_id, input_name, value in _model_files(graph):
            if value not in loadable:  # pins cannot contain "\\", so a backslash never matches
                raise _fail(f"node {node_id} loads a model file that is not pinned ({input_name})")
        for node_id, node in graph.items():
            if any(EMBEDDING_REFERENCE in text.casefold() for text in _strings(node["inputs"])):
                raise _fail(f"node {node_id} references an embedding, which is not pinned")
    return WorkflowTemplate(graph=graph, slots=found, sha256=actual, pinned=pinned_files is not None)

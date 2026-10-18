"""Safe workflow parameterization for a *server-owned* ComfyUI API graph.

No model-specific node schema is assumed here: an operator must pin and review
the exact Qwen-Image graph and identify its parameter slots before activation.
"""
from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import Any

_NODE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class WorkflowSlots:
    prompt_node: str
    prompt_field: str = "text"
    seed_node: str | None = None
    seed_field: str = "seed"

    def __post_init__(self) -> None:
        for name in (self.prompt_node, self.seed_node):
            if name is not None and not _NODE_ID.fullmatch(name):
                raise ValueError("Invalid node identifier")
        for field in (self.prompt_field, self.seed_field):
            if not _NODE_ID.fullmatch(field):
                raise ValueError("Invalid workflow field")


def render_workflow(
    template: dict[str, Any], slots: WorkflowSlots, *,
    prompt: str, seed: int | None = None,
) -> dict[str, Any]:
    """Return an isolated copy, changing only explicitly approved scalar slots."""
    if not isinstance(template, dict) or not template:
        raise ValueError("Workflow template is required")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 2000:
        raise ValueError("Prompt must contain 1-2000 characters")
    if seed is not None and (type(seed) is not int or not 0 <= seed < 2**64):
        raise ValueError("Seed must be a 64-bit unsigned integer")
    if seed is not None and slots.seed_node is None:
        raise ValueError("Workflow has no approved seed slot")

    graph = copy.deepcopy(template)

    def set_slot(node_id: str, field: str, value: Any) -> None:
        node = graph.get(node_id)
        if not isinstance(node, dict) or not isinstance(node.get("class_type"), str):
            raise ValueError("Missing approved workflow node")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict) or field not in inputs:
            raise ValueError("Missing approved workflow input")
        if isinstance(inputs[field], (dict, list)):
            raise ValueError("Approved input must be a scalar")
        inputs[field] = value

    set_slot(slots.prompt_node, slots.prompt_field, prompt)
    if seed is not None:
        set_slot(slots.seed_node, slots.seed_field, seed)
    return graph

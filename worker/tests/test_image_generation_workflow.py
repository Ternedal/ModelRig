"""Unit tests for immutable, allowlisted image workflow parameterization."""
import copy

import pytest

from app.image_generation.workflow import WorkflowSlots, render_workflow


def _template():
    return {
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "old"}},
        "9": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20}},
    }


def test_only_approved_slots_change():
    template = _template()
    original = copy.deepcopy(template)
    rendered = render_workflow(
        template, WorkflowSlots(prompt_node="6", seed_node="9"),
        prompt="En blå elefant", seed=123,
    )
    assert rendered["6"]["inputs"]["text"] == "En blå elefant"
    assert rendered["9"]["inputs"]["seed"] == 123
    assert rendered["9"]["inputs"]["steps"] == 20
    assert template == original


@pytest.mark.parametrize("prompt", ["", " ", "x" * 2001])
def test_rejects_invalid_prompts(prompt):
    with pytest.raises(ValueError):
        render_workflow(_template(), WorkflowSlots(prompt_node="6"), prompt=prompt)


@pytest.mark.parametrize("seed", [-1, 2**64, True, "12"])
def test_rejects_invalid_seeds(seed):
    with pytest.raises(ValueError):
        render_workflow(
            _template(), WorkflowSlots(prompt_node="6", seed_node="9"),
            prompt="test", seed=seed,
        )


def test_rejects_missing_slot_and_unapproved_seed():
    with pytest.raises(ValueError):
        render_workflow(_template(), WorkflowSlots(prompt_node="missing"), prompt="test")
    with pytest.raises(ValueError):
        render_workflow(_template(), WorkflowSlots(prompt_node="6"), prompt="test", seed=1)


def test_rejects_path_like_node_ids():
    with pytest.raises(ValueError):
        WorkflowSlots(prompt_node="../../etc")


def test_comfyui_output_requires_image_descriptor():
    from app.image_generation.service import _has_image_output

    assert not _has_image_output(None)
    assert not _has_image_output({"10": {"images": []}})
    assert not _has_image_output({"10": {"text": ["done"]}})
    assert not _has_image_output({"10": {"images": [{"filename": ""}]}})
    assert _has_image_output({
        "10": {"images": [{"filename": "result.png", "type": "output"}]}
    })

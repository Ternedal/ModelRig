"""Regression tests for safe ComfyUI output selection."""
import pytest

from app.image_generation.outputs import ImageDescriptor, select_output_image


def test_accepts_plain_output_image():
    item = select_output_image({
        "42": {"images": [{"filename": "render_001.png", "subfolder": "", "type": "output"}]}
    })
    assert item == ImageDescriptor("render_001.png", "", "output")


@pytest.mark.parametrize("filename", [
    "../secret.png", "/tmp/secret.png", "folder\\secret.png",
    ".hidden.png", "evil.txt", "bad name.png",
])
def test_rejects_unsafe_filenames(filename):
    with pytest.raises(ValueError):
        select_output_image({
            "42": {"images": [{"filename": filename, "subfolder": "", "type": "output"}]}
        })


def test_rejects_preview_and_nested_output():
    with pytest.raises(ValueError):
        select_output_image({
            "42": {"images": [{"filename": "render.png", "subfolder": "private", "type": "output"}]}
        })
    with pytest.raises(ValueError):
        select_output_image({
            "42": {"images": [{"filename": "render.png", "subfolder": "", "type": "temp"}]}
        })

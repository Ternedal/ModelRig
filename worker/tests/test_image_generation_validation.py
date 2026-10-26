"""Tests for bounded image header checks."""
import struct
import pytest
from app.image_generation.image_validation import InvalidImage, validate_image_header


def _png(width, height):
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00" + b"\x00" * 4


def test_valid_png_header():
    assert validate_image_header(_png(1024, 768)) == "image/png"


@pytest.mark.parametrize("size", [(0, 100), (8193, 100), (100, 0)])
def test_rejects_invalid_dimensions(size):
    with pytest.raises(InvalidImage):
        validate_image_header(_png(*size))


def test_rejects_non_image():
    with pytest.raises(InvalidImage):
        validate_image_header(b"not an image" * 4)

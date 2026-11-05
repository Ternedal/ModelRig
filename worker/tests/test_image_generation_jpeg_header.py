"""JPEG frame header boundary checks."""
import pytest

from app.image_generation.image_validation import InvalidImage, validate_image_header


def _jpeg(width, height):
    sof = (
        b"\xff\xc0\x00\x11\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
    )
    return b"\xff\xd8" + sof + b"\xff\xd9"


def test_jpeg_dimensions_accepted():
    assert validate_image_header(_jpeg(100, 200)) == "image/jpeg"


def test_jpeg_oversized_dimensions_rejected():
    with pytest.raises(InvalidImage):
        validate_image_header(_jpeg(9000, 100))


def test_truncated_jpeg_rejected():
    with pytest.raises(InvalidImage):
        validate_image_header(b"\xff\xd8\xff\xc0" + b"\x00" * 25)

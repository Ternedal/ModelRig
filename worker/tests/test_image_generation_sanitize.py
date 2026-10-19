"""Image sanitization tests; Pillow remains optional for the base worker."""
import io

import pytest

from app.image_generation.image_validation import InvalidImage
from app.image_generation.sanitize import sanitize_to_png


def test_rejects_empty_input_without_optional_decoder():
    with pytest.raises(InvalidImage):
        sanitize_to_png(b"")


def test_reencode_strips_metadata():
    Image = pytest.importorskip("PIL.Image")
    original = Image.new("RGB", (16, 16), (20, 30, 40))
    stream = io.BytesIO()
    original.save(stream, format="PNG")
    sanitized = sanitize_to_png(stream.getvalue())
    with Image.open(io.BytesIO(sanitized)) as result:
        assert result.format == "PNG"
        assert result.size == (16, 16)
        assert not result.info


def test_rejects_oversized_dimensions():
    Image = pytest.importorskip("PIL.Image")
    original = Image.new("RGB", (40, 40))
    stream = io.BytesIO()
    original.save(stream, format="PNG")
    with pytest.raises(InvalidImage):
        sanitize_to_png(stream.getvalue(), max_dimension=32)

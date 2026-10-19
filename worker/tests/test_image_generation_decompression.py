"""Decoder decompression warning regression."""
import io

import pytest

from app.image_generation.image_validation import InvalidImage
from app.image_generation.sanitize import sanitize_to_png


def test_decompression_bomb_warning_is_rejected(monkeypatch):
    Image = pytest.importorskip("PIL.Image")
    image = Image.new("RGB", (20, 20))
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(InvalidImage):
        sanitize_to_png(stream.getvalue(), max_dimension=100, max_pixels=10000)

"""Real image decoding and storage integration (no sanitizer mocking).

Requires Pillow in the isolated image test environment; the regular worker
intentionally does not install a decoder by default.
"""
import io

import pytest

from app.image_generation.artifacts import ImageArtifactStore
from app.image_generation.ingest import ingest_completed_job
from app.image_generation.jobs import ImageJob, ImageJobManager, JobStatus
from app.image_generation.outputs import ImageDescriptor


def test_real_decoder_ingestion_round_trip(tmp_path):
    Image = pytest.importorskip("PIL.Image")
    import asyncio

    original = Image.new("RGB", (12, 8), (20, 80, 160))
    original.info["comment"] = "discard this metadata"
    raw = io.BytesIO()
    original.save(raw, format="JPEG")
    source = raw.getvalue()
    prompt_id = "00000000-0000-4000-8000-000000000001"

    class FakeAdapter:
        async def history(self, requested):
            assert requested == prompt_id
            return {prompt_id: {"outputs": {"save": {"images": [
                {"filename": "render.jpg", "subfolder": "", "type": "output"}
            ]}}}}

        async def fetch_output(self, descriptor):
            assert descriptor == ImageDescriptor(
                filename="render.jpg", subfolder="", kind="output"
            )
            return source

    async def scenario():
        manager = ImageJobManager()
        manager._jobs["job"] = ImageJob(
            id="job", owner_id="alice", status=JobStatus.SUCCEEDED,
            result=prompt_id
        )
        store = ImageArtifactStore(tmp_path)
        artifact_id = await ingest_completed_job(
            "alice", "job", manager=manager, adapter=FakeAdapter(), store=store
        )
        assert store.get_png("bob", artifact_id) is None
        clean = store.get_png("alice", artifact_id)
        assert clean is not None and clean.startswith(b"\x89PNG\r\n\x1a\n")
        with Image.open(io.BytesIO(clean)) as result:
            assert result.format == "PNG"
            assert result.size == (12, 8)
            assert not result.info
            assert result.getpixel((0, 0))[2] > 100

    asyncio.run(scenario())

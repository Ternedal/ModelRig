"""Type boundary checks for owner-scoped image jobs."""
import asyncio

from app.image_generation.jobs import ImageJobManager


def test_non_string_identifiers_do_not_leak_jobs():
    async def run():
        manager = ImageJobManager()
        job = await manager.submit("alice", lambda: asyncio.sleep(0, result="ok"))
        assert manager.get(None, job.id) is None
        assert manager.get("alice", None) is None
        assert manager.get("bob", job.id) is None
        await manager.shutdown()
    asyncio.run(run())

"""Completed job eviction must not permanently exhaust image job capacity."""
import asyncio

from app.image_generation.jobs import ImageJobManager, JobStatus


def test_reclaims_completed_job_at_capacity():
    async def run():
        manager = ImageJobManager(max_jobs=1)
        first = await manager.submit("alice", lambda: asyncio.sleep(0, result="first"))
        await manager._tasks[first.id]
        assert first.status == JobStatus.SUCCEEDED
        second = await manager.submit("alice", lambda: asyncio.sleep(0, result="second"))
        await manager._tasks[second.id]
        assert second.status == JobStatus.SUCCEEDED
        assert manager.get("alice", first.id) is None
        assert manager.get("alice", second.id) is second
        await manager.shutdown()
    asyncio.run(run())

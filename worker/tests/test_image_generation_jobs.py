"""Tests for the default-off image job manager."""
import asyncio

import pytest

from app.image_generation.jobs import ImageJobManager, JobStatus


def test_job_success_and_owner_isolation():
    async def run():
        manager = ImageJobManager()
        job = await manager.submit("alice", lambda: asyncio.sleep(0, result="artifact-1"))
        assert manager.get("bob", job.id) is None
        await manager._tasks[job.id]
        assert manager.get("alice", job.id).status == JobStatus.SUCCEEDED
        assert manager.get("alice", job.id).result == "artifact-1"
        await manager.shutdown()

    asyncio.run(run())


def test_failure_is_sanitized():
    async def run():
        manager = ImageJobManager()
        async def fail():
            raise RuntimeError("secret engine internals")
        job = await manager.submit("alice", fail)
        await manager._tasks[job.id]
        assert job.status == JobStatus.FAILED
        assert job.error == "Image generation failed"
        await manager.shutdown()

    asyncio.run(run())


def test_cancel_running_job():
    async def run():
        manager = ImageJobManager()
        started = asyncio.Event()
        async def slow():
            started.set()
            await asyncio.sleep(60)
            return "never"
        job = await manager.submit("alice", slow)
        await started.wait()
        assert not await manager.cancel("bob", job.id)
        assert await manager.cancel("alice", job.id)
        await manager.shutdown()
        assert job.status == JobStatus.CANCELLED

    asyncio.run(run())


def test_capacity_limit():
    async def run():
        manager = ImageJobManager(max_jobs=1)
        job = await manager.submit("alice", lambda: asyncio.sleep(60, result="ok"))
        with pytest.raises(RuntimeError, match="capacity"):
            await manager.submit("alice", lambda: asyncio.sleep(0, result="no"))
        await manager.shutdown()
        assert job.status == JobStatus.CANCELLED

    asyncio.run(run())

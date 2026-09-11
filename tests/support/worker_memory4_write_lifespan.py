from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

from app.memory.write_mount import compose_memory4_write_lifespan


passed = failed = 0


def check(condition, name):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class Closable:
    def __init__(self, events):
        self.events = events

    def close(self):
        self.events.append("write:close")


events: list[str] = []


@asynccontextmanager
async def scheduler_owner(_app):
    events.append("scheduler:enter")
    try:
        yield
    finally:
        events.append("scheduler:exit")


@asynccontextmanager
async def existing_context_wrapper(app):
    events.append("context:enter")
    try:
        async with scheduler_owner(app):
            yield
    finally:
        events.append("context:close")


# Match R04's documented authority marker: runtime enters this wrapper, while
# repository introspection must still see the scheduler as the root owner.
existing_context_wrapper.__wrapped__ = scheduler_owner
composed = compose_memory4_write_lifespan(existing_context_wrapper)
check(
    getattr(composed, "__wrapped__", None) is scheduler_owner,
    "W04-A lifespan preserves scheduler as root production authority",
)

app = SimpleNamespace(
    state=SimpleNamespace(
        memory4_write_substrate=Closable(events),
        memory4_write_service=object(),
        memory4_write_mounted=True,
    )
)


async def exercise():
    async with composed(app):
        events.append("body")


asyncio.run(exercise())
check(
    events == [
        "context:enter",
        "scheduler:enter",
        "body",
        "scheduler:exit",
        "context:close",
        "write:close",
    ],
    "W04-A runtime still enters existing wrapper and closes write state last",
)
check(
    app.state.memory4_write_substrate is None
    and app.state.memory4_write_service is None
    and app.state.memory4_write_mounted is False,
    "W04-A lifespan clears process-owned write state",
)

print(f"\n===== MEMORY 4 W04-A LIFESPAN: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

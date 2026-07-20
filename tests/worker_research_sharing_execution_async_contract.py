from __future__ import annotations

import asyncio
import hashlib
import uuid

from app.data_sharing import DataSharingLedger
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_sharing_boundary import ResearchSharingBoundary
from app.research_sharing_execution import (
    ResearchSharingExecutionError,
    execute_research_sharing,
)

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class SyncRun:
    def __init__(self) -> None:
        self.calls = []

    def run(self, meter):
        self.calls.append("run")
        return "not-awaitable"

    async def close(self) -> None:
        self.calls.append("close")


class SyncClose:
    def __init__(self) -> None:
        self.calls = []

    async def run(self, meter):
        self.calls.append("run")
        meter.record_sent(4)
        return "discarded"

    def close(self):
        self.calls.append("close")
        return None


PLAN = EgressPlan(
    destination="browser-use",
    purpose="Exercise the injected async operation contract",
    payload_sha256=hashlib.sha256(b"async contract fixture").hexdigest(),
    sensitivity="public",
    allowed_domains=("example.com",),
    max_bytes=100,
)
INTENT = ResearchSharingIntent(
    plan=PLAN,
    summary="A controlled public fixture without local document content.",
)


def context(now: int):
    ledger = DataSharingLedger(uuid_factory=UUIDs())
    boundary = ResearchSharingBoundary(ledger, mode="enforce")
    lease = boundary.prepare(INTENT, now=now, receipt_ttl_seconds=60)
    return ledger, boundary, lease


def finished(ledger: DataSharingLedger) -> dict:
    return next(event for event in ledger.recent_events(20) if event["event_type"] == "finished")


async def run_case(operation, expected_code: str, expected_bytes: int, now: int):
    ledger, boundary, lease = context(now)
    try:
        await execute_research_sharing(
            boundary,
            lease,
            INTENT,
            operation,
            now_claim=now + 1,
            now_complete=now + 2,
        )
    except ResearchSharingExecutionError as exc:
        check(exc.outcome == "blocked", f"{expected_code} is blocked")
        check(exc.error_code == expected_code, f"{expected_code} has stable code")
        check(exc.bytes_sent == expected_bytes, f"{expected_code} returns exact measured bytes")
    else:
        check(False, f"{expected_code} is rejected")
    event = finished(ledger)
    check(event["outcome"] == "blocked", f"{expected_code} is terminally audited")
    check(event["error_code"] == expected_code, f"{expected_code} audit is normalized")
    check(event["bytes_sent"] == expected_bytes, f"{expected_code} audit keeps exact measured bytes")
    ledger.close()


async def main() -> None:
    sync_run = SyncRun()
    await run_case(sync_run, "operation_contract_violation", 0, 100)
    check(sync_run.calls == ["run", "close"], "sync run still receives one cleanup attempt")

    sync_close = SyncClose()
    await run_case(sync_close, "cleanup_contract_violation", 4, 200)
    check(sync_close.calls == ["run", "close"], "sync close is invoked exactly once")

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


asyncio.run(main())

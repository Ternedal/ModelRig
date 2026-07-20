from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from dataclasses import replace

from app.data_sharing import DataSharingLedger
from app.research_data_sharing import ResearchSharingIntent
from app.research_egress import EgressPlan
from app.research_sharing_boundary import (
    ResearchSharingBoundary,
    ResearchSharingBoundaryDenied,
)
from app.research_sharing_execution import (
    OutboundByteMeter,
    ResearchExternalBlocked,
    ResearchExternalFailed,
    ResearchSharingExecutionContractError,
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


def rejects(fn, expected, name: str) -> None:
    try:
        fn()
    except expected:
        check(True, name)
    else:
        check(False, name)


async def rejects_async(awaitable, expected, name: str):
    try:
        await awaitable
    except expected as exc:
        check(True, name)
        return exc
    check(False, name)
    return None


class UUIDs:
    def __init__(self) -> None:
        self.value = 0

    def __call__(self) -> uuid.UUID:
        self.value += 1
        return uuid.UUID(int=self.value)


class Operation:
    def __init__(
        self,
        *,
        result="ok",
        chunks=(),
        run_mode="success",
        close_mode="success",
    ) -> None:
        self.result = result
        self.chunks = tuple(chunks)
        self.run_mode = run_mode
        self.close_mode = close_mode
        self.calls = []
        self.started = asyncio.Event()

    async def run(self, meter: OutboundByteMeter):
        self.calls.append("run")
        self.started.set()
        for chunk in self.chunks:
            meter.record_sent(chunk)
        if self.run_mode == "blocked":
            raise ResearchExternalBlocked("peer_mismatch")
        if self.run_mode == "failed":
            raise ResearchExternalFailed("connect_timeout")
        if self.run_mode == "unexpected":
            raise RuntimeError("private operation exception sentinel")
        if self.run_mode == "contract":
            meter.record_sent(True)
        if self.run_mode == "wait":
            await asyncio.Event().wait()
        return self.result

    async def close(self) -> None:
        self.calls.append("close")
        if self.close_mode == "failed":
            raise RuntimeError("private cleanup exception sentinel")
        if self.close_mode == "wait":
            await asyncio.Event().wait()


RAW_PURPOSE = "Perform one bounded public research operation"
RAW_SUMMARY = "A public query without local document content."
RAW_PAYLOAD = b"public research request sentinel"
BASE_PLAN = EgressPlan(
    destination="browser-use",
    purpose=RAW_PURPOSE,
    payload_sha256=hashlib.sha256(RAW_PAYLOAD).hexdigest(),
    sensitivity="public",
    allowed_domains=("example.com",),
    max_bytes=100,
)
BASE_INTENT = ResearchSharingIntent(plan=BASE_PLAN, summary=RAW_SUMMARY)


def public_context(*, mode="enforce", intent=BASE_INTENT, now=100):
    ledger = DataSharingLedger(uuid_factory=UUIDs())
    boundary = ResearchSharingBoundary(ledger, mode=mode)
    lease = boundary.prepare(intent, now=now, receipt_ttl_seconds=60)
    return ledger, boundary, lease


def private_context(*, now=100):
    intent = replace(
        BASE_INTENT,
        plan=replace(
            BASE_PLAN,
            sensitivity="private",
            purpose="Use one user-selected private excerpt for research",
            payload_sha256=hashlib.sha256(b"private excerpt").hexdigest(),
        ),
        summary="A bounded excerpt selected by the user.",
    )
    ledger = DataSharingLedger(uuid_factory=UUIDs())
    boundary = ResearchSharingBoundary(ledger, mode="enforce")
    request = intent.to_request()
    permission = ledger.propose(request, now=now, ttl_seconds=60)
    ledger.approve(permission.permission_id, actor="Anders", now=now + 1)
    lease = boundary.prepare(
        intent,
        permission_id=permission.permission_id,
        now=now + 2,
        receipt_ttl_seconds=60,
    )
    return intent, ledger, boundary, lease, permission.permission_id


def terminal_event(ledger: DataSharingLedger) -> dict:
    return next(event for event in ledger.recent_events(100) if event["event_type"] == "finished")


async def main() -> None:
    # Success is claim-before-call, exact measured bytes, one cleanup, one terminal event.
    ledger, boundary, lease = public_context()
    operation = Operation(result={"answer": "fixture"}, chunks=(10, 15))
    result = await execute_research_sharing(
        boundary,
        lease,
        BASE_INTENT,
        operation,
        now_claim=101,
        now_complete=102,
    )
    check(operation.calls == ["run", "close"], "successful operation runs then closes exactly once")
    check(result.value == {"answer": "fixture"}, "successful result is returned")
    check(result.bytes_sent == 25, "success returns measured outbound bytes")
    event = terminal_event(ledger)
    check(event["outcome"] == "completed" and event["bytes_sent"] == 25, "success is terminally audited")
    check(
        [item["event_type"] for item in reversed(ledger.recent_events(100))][-3:]
        == ["authorized", "claimed", "finished"],
        "receipt lifecycle orders authorize claim finish",
    )
    ledger.close()

    # A legitimate nullable operation result remains a success.
    ledger, boundary, lease = public_context(now=200)
    operation = Operation(result=None, chunks=(0,))
    result = await execute_research_sharing(
        boundary,
        lease,
        BASE_INTENT,
        operation,
        now_claim=201,
        now_complete=202,
    )
    check(result.value is None and result.bytes_sent == 0, "nullable success is preserved")
    check(terminal_event(ledger)["outcome"] == "completed", "nullable result is not treated as failure")
    ledger.close()

    # Observe, revoked and mismatched leases cannot enter or clean up an operation.
    ledger, observe, observe_lease = public_context(mode="observe", now=300)
    operation = Operation()
    await rejects_async(
        execute_research_sharing(observe, observe_lease, BASE_INTENT, operation),
        ResearchSharingBoundaryDenied,
        "observe lease is denied before operation",
    )
    check(operation.calls == [], "observe denial calls neither run nor close")
    check(ledger.recent_events(20) == [], "observe denial leaves common ledger untouched")
    ledger.close()

    private_intent, ledger, boundary, lease, permission_id = private_context(now=400)
    ledger.revoke(permission_id, actor="Anders", now=403)
    operation = Operation()
    await rejects_async(
        execute_research_sharing(boundary, lease, private_intent, operation, now_claim=404),
        PermissionError,
        "revoked lease is denied before operation",
    )
    check(operation.calls == [], "revoked lease calls neither run nor close")
    ledger.close()

    ledger, boundary, lease = public_context(now=500)
    operation = Operation()
    changed = replace(BASE_INTENT, summary=RAW_SUMMARY + " changed")
    await rejects_async(
        execute_research_sharing(boundary, lease, changed, operation, now_claim=501),
        ResearchSharingBoundaryDenied,
        "changed intent is denied before operation",
    )
    check(operation.calls == [], "mismatched intent calls neither run nor close")
    ledger.close()

    # Expected operation signals retain normalized outcome and actual bytes.
    for run_mode, expected_outcome, expected_code, name in (
        ("failed", "failed", "connect_timeout", "normalized transport failure"),
        ("blocked", "blocked", "peer_mismatch", "normalized policy block"),
    ):
        ledger, boundary, lease = public_context(now=600)
        operation = Operation(chunks=(7,), run_mode=run_mode)
        exc = await rejects_async(
            execute_research_sharing(
                boundary,
                lease,
                BASE_INTENT,
                operation,
                now_claim=601,
                now_complete=602,
            ),
            ResearchSharingExecutionError,
            name,
        )
        check(exc.outcome == expected_outcome and exc.error_code == expected_code, f"{name} preserves normalized signal")
        check(exc.bytes_sent == 7, f"{name} preserves actual bytes")
        event = terminal_event(ledger)
        check(event["outcome"] == expected_outcome and event["error_code"] == expected_code, f"{name} is audited")
        check(operation.calls == ["run", "close"], f"{name} still cleans up exactly once")
        ledger.close()

    # Unexpected exceptions and contract violations never expose private details.
    for run_mode, expected_outcome, expected_code, name in (
        ("unexpected", "failed", "operation_failed", "unexpected operation error"),
        ("contract", "blocked", "operation_contract_violation", "operation contract violation"),
    ):
        ledger, boundary, lease = public_context(now=700)
        operation = Operation(chunks=(3,), run_mode=run_mode)
        exc = await rejects_async(
            execute_research_sharing(
                boundary,
                lease,
                BASE_INTENT,
                operation,
                now_claim=701,
                now_complete=702,
            ),
            ResearchSharingExecutionError,
            name,
        )
        check(exc.outcome == expected_outcome and exc.error_code == expected_code, f"{name} is normalized")
        serialized = json.dumps(ledger.recent_events(100)) + str(exc)
        check("private operation exception sentinel" not in serialized, f"{name} hides raw exception")
        ledger.close()

    # Byte budget is enforced by the reporting meter and terminally blocked.
    ledger, boundary, lease = public_context(now=800)
    operation = Operation(chunks=(60, 41))
    exc = await rejects_async(
        execute_research_sharing(
            boundary,
            lease,
            BASE_INTENT,
            operation,
            now_claim=801,
            now_complete=802,
        ),
        ResearchSharingExecutionError,
        "byte budget overflow is blocked",
    )
    check(exc.outcome == "blocked" and exc.error_code == "byte_budget_exceeded", "byte overflow has stable code")
    check(exc.bytes_sent == 60, "overflow audit includes only bytes already confirmed sent")
    check(terminal_event(ledger)["bytes_sent"] == 60, "overflow terminal event uses measured count")
    ledger.close()

    # Operation timeout cancels run, still closes, and terminalizes measured progress.
    ledger, boundary, lease = public_context(now=900)
    operation = Operation(chunks=(9,), run_mode="wait")
    exc = await rejects_async(
        execute_research_sharing(
            boundary,
            lease,
            BASE_INTENT,
            operation,
            now_claim=901,
            now_complete=902,
            timeout_seconds=1,
        ),
        ResearchSharingExecutionError,
        "operation timeout is normalized",
    )
    check(exc.error_code == "operation_timeout" and exc.bytes_sent == 9, "timeout preserves measured progress")
    check(operation.calls == ["run", "close"], "timeout still closes exactly once")
    ledger.close()

    # Cleanup failures override success because the isolated operation is not safely closed.
    for close_mode, expected_code, name in (
        ("failed", "cleanup_failed", "cleanup exception"),
        ("wait", "cleanup_timeout", "cleanup timeout"),
    ):
        ledger, boundary, lease = public_context(now=1000)
        operation = Operation(result="discarded", chunks=(11,), close_mode=close_mode)
        exc = await rejects_async(
            execute_research_sharing(
                boundary,
                lease,
                BASE_INTENT,
                operation,
                now_claim=1001,
                now_complete=1002,
                cleanup_timeout_seconds=1,
            ),
            ResearchSharingExecutionError,
            name,
        )
        check(exc.outcome == "blocked" and exc.error_code == expected_code, f"{name} blocks result")
        check(exc.bytes_sent == 11, f"{name} preserves measured bytes")
        serialized = json.dumps(ledger.recent_events(100)) + str(exc)
        check("private cleanup exception sentinel" not in serialized, f"{name} hides raw cleanup detail")
        ledger.close()

    # Caller cancellation propagates only after cleanup and terminal audit.
    ledger, boundary, lease = public_context(now=1100)
    operation = Operation(chunks=(13,), run_mode="wait")
    task = asyncio.create_task(
        execute_research_sharing(
            boundary,
            lease,
            BASE_INTENT,
            operation,
            now_claim=1101,
            now_complete=1102,
        )
    )
    await operation.started.wait()
    task.cancel()
    await rejects_async(task, asyncio.CancelledError, "caller cancellation propagates")
    check(operation.calls == ["run", "close"], "cancellation cleans up exactly once")
    event = terminal_event(ledger)
    check(event["outcome"] == "failed" and event["error_code"] == "operation_cancelled", "cancellation is terminally audited")
    check(event["bytes_sent"] == 13, "cancellation preserves measured bytes")
    ledger.close()

    # Invalid wrapper inputs fail before claim or operation.
    ledger, boundary, lease = public_context(now=1200)
    operation = Operation()
    await rejects_async(
        execute_research_sharing(
            boundary,
            lease,
            BASE_INTENT,
            operation,
            timeout_seconds=True,
        ),
        ResearchSharingExecutionContractError,
        "boolean timeout is rejected",
    )
    check(operation.calls == [], "invalid timeout cannot enter operation")
    await rejects_async(
        execute_research_sharing(boundary, lease, BASE_INTENT, object()),
        ResearchSharingExecutionContractError,
        "operation interface is required",
    )
    check(ledger.recent_events(20)[0]["event_type"] == "authorized", "invalid inputs do not claim receipt")
    ledger.close()

    # Meter validation is independently fail closed.
    rejects(lambda: OutboundByteMeter(True), ResearchSharingExecutionContractError, "boolean meter limit is rejected")
    meter = OutboundByteMeter(5)
    rejects(lambda: meter.record_sent(True), ResearchSharingExecutionContractError, "boolean byte increment is rejected")
    check(meter.record_sent(5) == 5, "meter accepts exact ceiling")
    rejects(lambda: meter.record_sent(1), ResearchExternalBlocked, "meter blocks beyond ceiling")

    print(f"\n{passed} passed, {failed} failed")
    raise SystemExit(1 if failed else 0)


asyncio.run(main())

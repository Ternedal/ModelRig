#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "worker"
sys.path.insert(0, str(WORKER))

from app import browser_research_process as process  # noqa: E402
from app.browser_host import BrowserHostResponse  # noqa: E402

passed = failed = 0


def check(condition: bool, name: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


REQUEST = {
    "query": "Læs den offentlige side",
    "allowed_domains": ["example.com"],
    "max_sources": 1,
    "timeout_seconds": 30,
}
BINDING = "a" * 64


class Scenario:
    def __init__(
        self,
        *,
        bytes_sent: int = 0,
        host_response: BrowserHostResponse | None = None,
        host_error: Exception | None = None,
        build_error: Exception | None = None,
        claim_error: Exception | None = None,
        complete_error: Exception | None = None,
    ) -> None:
        self.bytes_sent = bytes_sent
        self.host_response = host_response
        self.host_error = host_error
        self.build_error = build_error
        self.claim_error = claim_error
        self.complete_error = complete_error
        self.proposed = 0
        self.approved = 0
        self.claimed = 0
        self.completions: list[dict[str, Any]] = []
        self.common_closed = 0
        self.peer_closed = 0
        self.runtime_closed = 0
        self.host_calls = 0


def run_case(scenario: Scenario) -> tuple[dict[str, Any] | None, str | None]:
    original = {
        "VerifiableDataSharingLedger": process.VerifiableDataSharingLedger,
        "VerifiableResearchSharingBoundary": process.VerifiableResearchSharingBoundary,
        "ResearchPeerAuthorizationBridge": process.ResearchPeerAuthorizationBridge,
        "ResearchPeerTransferLedger": process.ResearchPeerTransferLedger,
        "BrowserPeerFulfillmentController": process.BrowserPeerFulfillmentController,
        "build_claim_bound_browser_use_runtime": process.build_claim_bound_browser_use_runtime,
        "BrowserHost": process.BrowserHost,
    }

    class FakeCommon:
        def __init__(self, _path: str) -> None:
            pass

        def propose(self, _request, *, now: int, ttl_seconds: int):
            del now, ttl_seconds
            scenario.proposed += 1
            return SimpleNamespace(permission_id="dsp_test")

        def approve(self, permission_id: str, *, actor: str, now: int) -> None:
            del permission_id, actor, now
            scenario.approved += 1

        def close(self) -> None:
            scenario.common_closed += 1

    class FakeBoundary:
        def __init__(self, _common, *, mode: str, policy) -> None:
            del mode, policy

        def prepare(
            self,
            _intent,
            *,
            permission_id: str,
            now: int,
            receipt_ttl_seconds: int,
        ):
            del permission_id, now, receipt_ttl_seconds
            return SimpleNamespace(receipt_id="lease_test")

        def claim(self, _lease, _intent, *, now: int):
            del now
            if scenario.claim_error is not None:
                raise scenario.claim_error
            scenario.claimed += 1
            return SimpleNamespace(receipt_id="claim_test")

        def complete(
            self,
            _lease,
            _intent,
            *,
            outcome: str,
            bytes_sent: int,
            error_code: str | None = None,
            now: int,
        ) -> None:
            del now
            scenario.completions.append(
                {
                    "outcome": outcome,
                    "bytes_sent": bytes_sent,
                    "error_code": error_code,
                }
            )
            if scenario.complete_error is not None:
                raise scenario.complete_error

    class FakePeer:
        def __init__(self, *_args) -> None:
            pass

        def close(self) -> None:
            scenario.peer_closed += 1

    class FakeController:
        @classmethod
        def create(cls, *_args, **_kwargs):
            return SimpleNamespace(bytes_sent=scenario.bytes_sent)

    class FakeRuntime:
        def __init__(self) -> None:
            self.backend = object()

        def close(self) -> None:
            scenario.runtime_closed += 1

    def fake_build(*_args, **_kwargs):
        if scenario.build_error is not None:
            raise scenario.build_error
        return FakeRuntime()

    class FakeHost:
        def __init__(self, _backend) -> None:
            pass

        async def execute(self, _request):
            scenario.host_calls += 1
            if scenario.host_error is not None:
                raise scenario.host_error
            if scenario.host_response is None:
                raise AssertionError("test scenario omitted host response")
            return scenario.host_response

    process.VerifiableDataSharingLedger = FakeCommon
    process.VerifiableResearchSharingBoundary = FakeBoundary
    process.ResearchPeerAuthorizationBridge = lambda _boundary: object()
    process.ResearchPeerTransferLedger = FakePeer
    process.BrowserPeerFulfillmentController = FakeController
    process.build_claim_bound_browser_use_runtime = fake_build
    process.BrowserHost = FakeHost

    try:
        with tempfile.TemporaryDirectory(prefix="kaliv-browser-process-test-") as tmp:
            os.environ[process.DATA_ENV] = tmp
            try:
                result = asyncio.run(process._execute(BINDING, dict(REQUEST)))
                return result, None
            except process.BrowserResearchProcessError as exc:
                return None, exc.code
    finally:
        for name, value in original.items():
            setattr(process, name, value)


success = Scenario(
    bytes_sent=37,
    host_response=BrowserHostResponse.success(
        "br_test",
        {"research": {"answer": "ok"}, "trace": {}},
    ),
)
result, code = run_case(success)
check(code is None and result is not None, "successful host result returns")
check(
    success.completions
    == [{"outcome": "completed", "bytes_sent": 37, "error_code": None}],
    "success terminalizes exactly once with measured bytes",
)
check(success.runtime_closed == 1, "success closes runtime evidence")
check(success.peer_closed == 1, "success closes peer ledger")
check(success.common_closed == 1, "success closes common ledger")

blocked = Scenario(
    bytes_sent=41,
    host_response=BrowserHostResponse.failure(
        "br_test",
        "contract_violation",
        "normalized",
    ),
)
_result, code = run_case(blocked)
check(code == "contract_violation", "host contract failure stays normalized")
check(
    blocked.completions
    == [
        {
            "outcome": "blocked",
            "bytes_sent": 41,
            "error_code": "contract_violation",
        }
    ],
    "contract failure records blocked and actual bytes exactly once",
)

normalized = Scenario(
    bytes_sent=19,
    build_error=process.BrowserResearchProcessError("browser_model_missing"),
)
_result, code = run_case(normalized)
check(code == "browser_model_missing", "known process error remains specific")
check(
    normalized.completions
    == [
        {
            "outcome": "failed",
            "bytes_sent": 19,
            "error_code": "browser_model_missing",
        }
    ],
    "known post-claim failure terminalizes with measured bytes",
)
check(normalized.peer_closed == 1, "known post-claim failure closes peer ledger")
check(normalized.common_closed == 1, "known post-claim failure closes common ledger")

unexpected = Scenario(
    bytes_sent=23,
    build_error=RuntimeError("raw secret must never escape"),
)
_result, code = run_case(unexpected)
check(code == "browser_runtime_failed", "unexpected exception is normalized")
check(
    unexpected.completions
    == [
        {
            "outcome": "failed",
            "bytes_sent": 23,
            "error_code": "browser_runtime_failed",
        }
    ],
    "unexpected post-claim failure does not guess zero bytes",
)
check("secret" not in (code or ""), "raw exception text is not exposed")

preclaim = Scenario(
    bytes_sent=99,
    claim_error=RuntimeError("claim refused"),
)
_result, code = run_case(preclaim)
check(code == "browser_runtime_failed", "pre-claim exception is normalized")
check(preclaim.completions == [], "no terminal transition is forged before claim")
check(preclaim.peer_closed == 0, "pre-claim failure created no peer ledger")
check(preclaim.common_closed == 1, "pre-claim failure still closes common ledger")

terminal_failure = Scenario(
    bytes_sent=29,
    host_response=BrowserHostResponse.success(
        "br_test",
        {"research": {"answer": "ok"}, "trace": {}},
    ),
    complete_error=RuntimeError("disk failure"),
)
_result, code = run_case(terminal_failure)
check(
    code == "browser_terminalization_failed",
    "ledger completion failure is explicit and normalized",
)
check(
    len(terminal_failure.completions) == 1,
    "terminal ledger failure is never retried as a duplicate transition",
)
check(terminal_failure.runtime_closed == 1, "terminal failure still closes runtime")
check(terminal_failure.peer_closed == 1, "terminal failure still closes peer ledger")
check(terminal_failure.common_closed == 1, "terminal failure still closes common ledger")

check(process._measured_bytes(None) == 0, "no controller means zero measured bytes")
try:
    process._measured_bytes(SimpleNamespace(bytes_sent=True))
except process.BrowserResearchProcessError as exc:
    check(exc.code == "browser_byte_meter_invalid", "boolean byte meter fails closed")
else:
    check(False, "boolean byte meter fails closed")

print(f"\nBrowser research process contracts: {passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

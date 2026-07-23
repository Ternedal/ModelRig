from __future__ import annotations

from app.data_sharing import DataSharingReceipt
from app.research_sharing_boundary import (
    ResearchSharingBoundaryContractError,
    ResearchSharingLease,
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


def rejects(fn, name: str) -> None:
    try:
        fn()
    except ResearchSharingBoundaryContractError:
        check(True, name)
    else:
        check(False, name)


REQUEST = "b" * 64
POLICY = "c" * 64
PLAN = "a" * 64
AUTOMATIC = DataSharingReceipt(
    receipt_id="dsr_auto",
    request_digest=REQUEST,
    authorization="automatic",
    permission_id=None,
    authorized_at=10,
    expires_at=20,
    max_bytes=100,
)
PERMISSION = DataSharingReceipt(
    receipt_id="dsr_permission",
    request_digest=REQUEST,
    authorization="permission",
    permission_id="dsp_exact",
    authorized_at=10,
    expires_at=20,
    max_bytes=100,
)

check(
    ResearchSharingLease(
        mode="enforce",
        plan_digest=PLAN,
        request_digest=REQUEST,
        policy_sha256=POLICY,
        decision="automatic",
        receipt=AUTOMATIC,
    ).may_send,
    "automatic decision accepts automatic receipt",
)
check(
    ResearchSharingLease(
        mode="enforce",
        plan_digest=PLAN,
        request_digest=REQUEST,
        policy_sha256=POLICY,
        decision="confirmation_required",
        receipt=PERMISSION,
    ).may_send,
    "confirmation decision accepts permission receipt",
)
rejects(
    lambda: ResearchSharingLease(
        mode="enforce",
        plan_digest=PLAN,
        request_digest=REQUEST,
        policy_sha256=POLICY,
        decision="automatic",
        receipt=PERMISSION,
    ),
    "automatic decision rejects permission receipt",
)
rejects(
    lambda: ResearchSharingLease(
        mode="enforce",
        plan_digest=PLAN,
        request_digest=REQUEST,
        policy_sha256=POLICY,
        decision="confirmation_required",
        receipt=AUTOMATIC,
    ),
    "confirmation decision rejects automatic receipt",
)

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)

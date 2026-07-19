from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BRANCH = "agent/t032-data-sharing-policy-v1"


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    if os.environ.get("GITHUB_HEAD_REF") not in (None, "", BRANCH):
        raise SystemExit("refusing T-032 revocation patch outside exact branch")

    replace_once(
        ROOT / "worker/app/data_sharing.py",
        '''        allowed = {
            "approved": {"pending"}, "denied": {"pending"},
            "revoked": {"pending", "approved"},
        }
''',
        '''        allowed = {
            "approved": {"pending"}, "denied": {"pending"},
            "revoked": {"pending", "approved", "consumed"},
        }
''',
        "revocation state set",
    )
    replace_once(
        ROOT / "worker/app/data_sharing.py",
        '''                if target == "approved":
                    self._db.execute(
                        "UPDATE sharing_permissions SET status='approved', approved_by=?, approved_at=? "
                        "WHERE permission_id=? AND status='pending'", (actor, now, permission_id),
                    )
                else:
                    self._db.execute(
                        f"UPDATE sharing_permissions SET status=?, revoked_by=?, revoked_at=? "
                        f"WHERE permission_id=? AND status IN "
                        f"({'?,?' if target == 'revoked' else '?'})",
                        ((target, actor, now, permission_id, "pending", "approved")
                         if target == "revoked"
                         else (target, actor, now, permission_id, "pending")),
                    )
''',
        '''                if target == "approved":
                    changed = self._db.execute(
                        "UPDATE sharing_permissions SET status='approved', approved_by=?, approved_at=? "
                        "WHERE permission_id=? AND status='pending'", (actor, now, permission_id),
                    ).rowcount
                elif target == "revoked":
                    changed = self._db.execute(
                        "UPDATE sharing_permissions SET status='revoked', revoked_by=?, revoked_at=? "
                        "WHERE permission_id=? AND status IN ('pending','approved','consumed')",
                        (actor, now, permission_id),
                    ).rowcount
                    self._db.execute(
                        "UPDATE sharing_receipts SET status='revoked' "
                        "WHERE permission_id=? AND status='authorized'",
                        (permission_id,),
                    )
                else:
                    changed = self._db.execute(
                        "UPDATE sharing_permissions SET status='denied', revoked_by=?, revoked_at=? "
                        "WHERE permission_id=? AND status='pending'",
                        (actor, now, permission_id),
                    ).rowcount
                if changed != 1:
                    raise DataSharingDenied(f"permission cannot transition to {target}")
''',
        "atomic permission and receipt revocation",
    )
    replace_once(
        ROOT / "tests/worker_data_sharing_policy.py",
        '''rejects(
    lambda: ledger.authorize(request, permission_id=revoked.permission_id, now=203),
    DataSharingDenied,
    "revoked permission cannot authorize",
)

denied = ledger.propose(request, now=300, ttl_seconds=30)
''',
        '''rejects(
    lambda: ledger.authorize(request, permission_id=revoked.permission_id, now=203),
    DataSharingDenied,
    "revoked permission cannot authorize",
)

issued_then_revoked = ledger.propose(request, now=210, ttl_seconds=30)
ledger.approve(issued_then_revoked.permission_id, actor="Anders", now=211)
revoked_receipt = ledger.authorize(
    request,
    permission_id=issued_then_revoked.permission_id,
    now=212,
)
ledger.revoke(issued_then_revoked.permission_id, actor="Anders", now=213)
rejects(
    lambda: ledger.claim(revoked_receipt, request, now=214),
    DataSharingDenied,
    "revocation invalidates an issued but unclaimed receipt",
)

denied = ledger.propose(request, now=300, ttl_seconds=30)
''',
        "issued receipt revocation test",
    )
    replace_once(
        ROOT / "DATA_SHARING_POLICY.md",
        '''- consumed atomically when a receipt is issued.

External processing requires a claimable `kaliv-data-sharing-receipt/v1`. Receipts are short-lived, exact-request-bound, one-use at the boundary and terminal after completion.
''',
        '''- consumed atomically when a receipt is issued;
- still revocable until the issued receipt is claimed; revocation atomically invalidates every unclaimed receipt linked to it.

External processing requires a claimable `kaliv-data-sharing-receipt/v1`. Receipts are short-lived, exact-request-bound, one-use at the boundary and terminal after completion. Once claimed, revocation cannot pretend that already-started external processing never happened.
''',
        "revocation documentation",
    )

    print("T-032 revocation hardening applied")


if __name__ == "__main__":
    main()

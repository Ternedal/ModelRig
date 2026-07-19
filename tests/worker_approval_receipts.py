"""Approval receipts: the consumed token's attribution is persisted (T-014).

The backend approval token proves WHICH paired device approved and WHEN it was
issued. Before this, the worker verified all of it and kept only the
fingerprint -- a schedule firing three weeks later could not answer "when did I
approve this, and from where?". Now every consumed approval writes a receipt
row -- create or renew -- in the SAME transaction as the grant it authorises,
stamped with the grant revision it produced.

Renewal also bumps the revision now: for the same tool+args the renewed
fingerprint is IDENTICAL to the old one, so without the bump neither of the
revocation guard's other belts would catch an in-flight claim taken under the
old grant -- it would fire against the fresh budget. The revoke suite proves
the cancellation end to end; here the bookkeeping is proven.

Run: PYTHONPATH=worker python3 tests/worker_approval_receipts.py
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.schedule_admin import ScheduleAdminStore  # noqa: E402
from app.scheduler import ScheduleError, ScheduleStore  # noqa: E402

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


def _db():
    return os.path.join(tempfile.mkdtemp(prefix="receipts-"), "sched.db")


NOW = 1_000_000.0
RECEIPT = {
    "device_id": "pixel-6a-anders",
    "nonce": "nonce-abc123",
    "issued_at": 999_990,
    "consumed_at": NOW,
}

# --- create persists the receipt, atomically with the grant -----------------
st = ScheduleStore(path=_db())
s = st.create("note_append", {"text": "x"}, "every:60",
              approve_write=True, now=NOW, receipt=dict(RECEIPT))
rows = st.approval_receipts(s.schedule_id)
check(len(rows) == 1, "one consumed approval yields exactly one receipt")
r = rows[0]
check(r["kind"] == "create" and r["device_id"] == "pixel-6a-anders"
      and r["nonce"] == "nonce-abc123" and r["issued_at"] == 999_990
      and r["consumed_at"] == NOW,
      "the receipt carries WHO (device), WHEN issued, and WHEN consumed -- the "
      "attribution the token proved is no longer thrown away")
check(r["revision"] == 0 and r["fingerprint"] == s.approved_fingerprint,
      "the receipt is stamped with the grant revision it produced and the "
      "exact fingerprint it authorises")

# --- a receipt without an approved write is refused loudly ------------------
st2 = ScheduleStore(path=_db())
try:
    st2.create("rig_status", {}, "every:60", now=NOW, receipt=dict(RECEIPT))
    check(False, "a receipt without an approved write is refused")
except ScheduleError:
    check(True, "a receipt without an approved write is refused")

# --- atomicity: a broken receipt takes the schedule down with it ------------
st3 = ScheduleStore(path=_db())
bad = dict(RECEIPT)
del bad["device_id"]  # KeyError inside the transaction
try:
    st3.create("note_append", {"text": "x"}, "every:60",
               approve_write=True, now=NOW, receipt=bad)
    check(False, "a failing receipt insert rolls the whole create back")
except Exception:
    check(st3.list_all() == [] if hasattr(st3, "list_all")
          else st3._conn.execute("SELECT COUNT(*) c FROM schedules")
          .fetchone()["c"] == 0,
          "a failing receipt insert rolls the whole create back -- a grant "
          "claiming human approval cannot exist without its receipt")
check(st3._conn.execute("SELECT COUNT(*) c FROM approval_receipts")
      .fetchone()["c"] == 0,
      "and no orphan receipt survives either")

# --- reads have no receipts, by design --------------------------------------
st4 = ScheduleStore(path=_db())
rd = st4.create("rig_status", {}, "every:60", now=NOW)
check(st4.approval_receipts(rd.schedule_id) == [],
      "a read schedule has zero receipts -- reads deliberately need no approval")

# --- renew appends a receipt with the bumped revision ------------------------
db = _db()
ad = ScheduleAdminStore(db)
s5 = ad.create("note_append", {"text": "x"}, "every:60",
               approve_write=True, now=NOW, receipt=dict(RECEIPT))
before = ad.get(s5.schedule_id)
renew_receipt = {
    "device_id": "pixel-6a-anders",
    "nonce": "nonce-renew-777",
    "issued_at": 1_000_100,
    "consumed_at": NOW + 200,
}
after = ad.renew(
    s5.schedule_id,
    approved_fingerprint=s5.approved_fingerprint,
    ttl_days=7, max_runs=4, now=NOW + 200,
    receipt=renew_receipt,
)
rows = ad.approval_receipts(s5.schedule_id)
check(len(rows) == 2 and rows[0]["kind"] == "create"
      and rows[1]["kind"] == "renew",
      "renewal APPENDS a receipt -- the history of consumed approvals is "
      "complete, oldest first")
guard = ad.current_guard(s5.schedule_id)
check(guard["revision"] == before.revision + 1
      if hasattr(before, "revision") else guard["revision"] >= 1,
      "renewal bumps the grant revision -- same-fingerprint renewals can no "
      "longer be fired by a claim taken under the old grant")
check(rows[1]["revision"] == guard["revision"]
      and rows[1]["nonce"] == "nonce-renew-777",
      "the renew receipt is stamped with the post-bump revision, so it says "
      "WHICH incarnation of the grant it authorised")
check(after is not None and after.runs_used == 0,
      "the renewed grant starts with a fresh budget, exactly as before")

# --- renew without a receipt still works (older callers) ---------------------
after2 = ad.renew(
    s5.schedule_id,
    approved_fingerprint=s5.approved_fingerprint,
    ttl_days=7, max_runs=4, now=NOW + 400,
)
check(after2 is not None
      and len(ad.approval_receipts(s5.schedule_id)) == 2,
      "a receipt-less renew (older callers) neither fails nor fabricates a "
      "receipt")
check(ad.current_guard(s5.schedule_id)["revision"] == guard["revision"] + 1,
      "but it still bumps the revision -- the T-013 rule holds for every renew")

print(f"\n===== APPROVAL RECEIPTS: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

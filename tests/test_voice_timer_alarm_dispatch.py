"""Opt-in alarm dispatch tests; no live transport or background threads."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_alarm_dispatch import dispatch_once
from app.voice_timer_alarm_outbox import TimerAlarmOutbox
from app.voice_timer_state_ledger import TimerStateLedger
from app.voice_timer_due_sweeper import TimerDueSweeper


class FakeTransport:
    def __init__(self, answer=True, error=False):
        self.answer = answer
        self.error = error
        self.calls = []

    def send(self, claim):
        self.calls.append(claim.timer_id)
        if self.error:
            raise RuntimeError("offline")
        return self.answer


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "alarms.db")
        self.outbox = TimerAlarmOutbox(self.path)

    def queue_due(self, timer_id):
        with TimerStateLedger(self.path) as ledger:
            ledger.register_pending(timer_id)
            ledger.db.execute(
                "UPDATE voice_timer_state_ledger SET state='due' WHERE timer_id=?",
                (timer_id,),
            )
            ledger.db.commit()
        self.assertTrue(self.outbox.enqueue_due(timer_id))

    def test_restart_due_promotion_dispatch_retry_and_internal_ack(self):
        # ACTIVE is a fixture: production activation is not implemented.
        sweeper = TimerDueSweeper(self.path)
        with TimerStateLedger(self.path) as ledger:
            ledger.register_pending("integrated")
            ledger.db.execute(
                "UPDATE voice_timer_state_ledger SET state='active' "
                "WHERE timer_id='integrated'"
            )
            ledger.db.commit()
        self.assertTrue(sweeper.register_active_deadline("integrated", due_at=130))
        self.assertEqual(TimerDueSweeper(self.path).sweep_due(now=129), 0)
        self.assertEqual(TimerDueSweeper(self.path).sweep_due(now=130), 1)
        self.assertEqual(TimerDueSweeper(self.path).sweep_due(now=131), 0)
        restarted_outbox = TimerAlarmOutbox(self.path)
        failed = dispatch_once(restarted_outbox, FakeTransport(error=True), now=130)
        self.assertEqual(failed.outcome, "transport_error")
        self.assertEqual(dispatch_once(restarted_outbox, FakeTransport(), now=159).outcome, "idle")
        delivered_to_transport = dispatch_once(
            TimerAlarmOutbox(self.path), FakeTransport(), now=160,
        )
        self.assertEqual(delivered_to_transport.outcome, "transport_accepted_pending_receipt")
        self.assertEqual(TimerAlarmOutbox(self.path).status("integrated"), "leased")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual((ledger.get("integrated").state, ledger.get("integrated").revision),
                             ("due", 1))
        # No device attestation exists: even successful transport acceptance
        # must not mark the timer as delivered.
        self.assertEqual(dispatch_once(TimerAlarmOutbox(self.path), FakeTransport(), now=189).outcome, "idle")
        self.assertEqual(dispatch_once(TimerAlarmOutbox(self.path), FakeTransport(), now=190).outcome,
                         "transport_accepted_pending_receipt")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("integrated").state, "due")

    def test_restart_cancelled_alarm_never_dispatches(self):
        sweeper = TimerDueSweeper(self.path)
        with TimerStateLedger(self.path) as ledger:
            ledger.register_pending("cancel-after-due")
            ledger.db.execute(
                "UPDATE voice_timer_state_ledger SET state='active' "
                "WHERE timer_id='cancel-after-due'"
            )
            ledger.db.commit()
        self.assertTrue(sweeper.register_active_deadline("cancel-after-due", due_at=100))
        self.assertEqual(sweeper.sweep_due(now=100), 1)
        self.assertTrue(TimerAlarmOutbox(self.path).cancel_due("cancel-after-due"))
        after_restart = TimerAlarmOutbox(self.path)
        transport = FakeTransport()
        self.assertEqual(dispatch_once(after_restart, transport, now=200).outcome, "idle")
        self.assertEqual(transport.calls, [])
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("cancel-after-due").state, "cancelled")

    def test_idle_does_not_call_transport(self):
        transport = FakeTransport()
        result = dispatch_once(self.outbox, transport, now=100)
        self.assertEqual(result.outcome, "idle")
        self.assertEqual(transport.calls, [])

    def test_explicit_acceptance_marks_one_alarm(self):
        self.queue_due("a")
        self.queue_due("b")
        transport = FakeTransport()
        result = dispatch_once(self.outbox, transport, now=100)
        self.assertEqual(result.outcome, "transport_accepted_pending_receipt")
        self.assertEqual(transport.calls, ["a"])
        self.assertEqual(self.outbox.status("a"), "leased")
        self.assertEqual(self.outbox.status("b"), "queued")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "due")

    def test_acceptance_requires_separate_receipt(self):
        self.queue_due("a")
        result = dispatch_once(self.outbox, FakeTransport(), now=100)
        self.assertEqual(result.outcome, "transport_accepted_pending_receipt")
        self.assertEqual(self.outbox.status("a"), "leased")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "due")
        # Missing device acknowledgement causes an eventual retry.
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=129).outcome, "idle")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=130).outcome,
                         "transport_accepted_pending_receipt")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "due")

    def test_failed_send_retries_after_lease(self):
        self.queue_due("a")
        failure = FakeTransport(error=True)
        self.assertEqual(dispatch_once(self.outbox, failure, now=100).outcome, "transport_error")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=101).outcome, "idle")
        decline = FakeTransport(answer=False)
        self.assertEqual(dispatch_once(self.outbox, decline, now=130).outcome, "not_accepted")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "due")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=160).outcome, "transport_accepted_pending_receipt")

    def test_cancellation_suppresses_retry(self):
        self.queue_due("a")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(error=True), now=100).outcome, "transport_error")
        self.assertTrue(self.outbox.cancel_due("a"))
        transport = FakeTransport()
        self.assertEqual(dispatch_once(self.outbox, transport, now=131).outcome, "idle")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()

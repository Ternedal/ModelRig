"""Opt-in alarm dispatch tests; no live transport or background threads."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))
from app.voice_timer_alarm_dispatch import dispatch_once
from app.voice_timer_alarm_outbox import TimerAlarmOutbox
from app.voice_timer_state_ledger import TimerStateLedger


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
        self.assertEqual(result.outcome, "transport_accepted")
        self.assertEqual(transport.calls, ["a"])
        self.assertEqual(self.outbox.status("a"), "delivered")
        self.assertEqual(self.outbox.status("b"), "queued")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "delivered")

    def test_failed_send_retries_after_lease(self):
        self.queue_due("a")
        failure = FakeTransport(error=True)
        self.assertEqual(dispatch_once(self.outbox, failure, now=100).outcome, "transport_error")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=101).outcome, "idle")
        decline = FakeTransport(answer=False)
        self.assertEqual(dispatch_once(self.outbox, decline, now=130).outcome, "not_accepted")
        with TimerStateLedger(self.path) as ledger:
            self.assertEqual(ledger.get("a").state, "due")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(), now=160).outcome, "transport_accepted")

    def test_cancellation_suppresses_retry(self):
        self.queue_due("a")
        self.assertEqual(dispatch_once(self.outbox, FakeTransport(error=True), now=100).outcome, "transport_error")
        self.assertTrue(self.outbox.cancel_due("a"))
        transport = FakeTransport()
        self.assertEqual(dispatch_once(self.outbox, transport, now=131).outcome, "idle")
        self.assertEqual(transport.calls, [])


if __name__ == "__main__":
    unittest.main()

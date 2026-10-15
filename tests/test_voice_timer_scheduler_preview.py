"""Canonical timer UI previews are registry-gated and never write grants."""
import os
import sys
import unittest
from types import SimpleNamespace
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.voice_timer_handoff import prepare_timer_handoff
from app.voice_timer_scheduler_preview import (
    TimerPreviewUnavailable, preview_timer_with_scheduler
)


class FakeAdmin:
    def __init__(self, *, risk="write", approval=True):
        self.risk, self.approval = risk, approval
        self.calls = []

    def preview(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(risk=self.risk, requires_approval=self.approval)


class TimerSchedulerPreviewTests(unittest.TestCase):
    def setUp(self):
        self.handoff = prepare_timer_handoff("Sæt en timer på 5 minutter.")

    def test_canonical_preview_requires_approval_without_creation(self):
        admin = FakeAdmin()
        preview = preview_timer_with_scheduler(
            self.handoff, tool="registered_alarm", args={"duration": 300},
            cadence="once", admin=admin
        )
        self.assertTrue(preview.requires_approval)
        self.assertEqual(admin.calls[0]["max_runs"], 1)
        self.assertEqual(admin.calls[0]["ttl_days"], 1)
        self.assertFalse(self.handoff.timer_started)

    def test_read_only_and_unapproved_preview_fail_closed(self):
        for risk, approval in (("read", False), ("write", False)):
            with self.subTest(risk=risk, approval=approval):
                with self.assertRaises(TimerPreviewUnavailable):
                    preview_timer_with_scheduler(
                        self.handoff, tool="candidate", args={},
                        cadence="once", admin=FakeAdmin(risk=risk, approval=approval)
                    )

    def test_bad_handoff_or_missing_tool_does_not_call_scheduler(self):
        admin = FakeAdmin()
        with self.assertRaises(TimerPreviewUnavailable):
            preview_timer_with_scheduler(
                None, tool="alarm", args={}, cadence="once", admin=admin
            )
        with self.assertRaises(TimerPreviewUnavailable):
            preview_timer_with_scheduler(
                self.handoff, tool="", args={}, cadence="once", admin=admin
            )
        self.assertEqual(admin.calls, [])

    def test_real_admin_registry_rejects_unconfigured_timer_tool(self):
        from app.schedule_admin import ScheduleAdmin, ScheduleAdminNotFound
        admin = ScheduleAdmin(registry_factory=lambda: {}, clock=lambda: 100.0)
        with self.assertRaises(ScheduleAdminNotFound):
            preview_timer_with_scheduler(
                self.handoff, tool="unconfigured_alarm", args={},
                cadence="once", admin=admin
            )


if __name__ == "__main__":
    unittest.main()

"""Fail-closed regression for the Job Object close path.

This is run explicitly by the Windows isolation gate. The injected API makes a
rare CloseHandle failure deterministic: the wrapper must retain the handle so a
later cleanup attempt still owns the process tree.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "..", "worker"),
)

from app.windows_job import JobLimits, WindowsIsolationError, WindowsJob  # noqa: E402


class CloseApi:
    def __init__(self) -> None:
        self.fail_close = True
        self.close_calls = 0

    def create_job(self) -> int:
        return 101

    def configure_job(self, handle: int, limits: JobLimits) -> None:
        assert handle == 101
        assert isinstance(limits, JobLimits)

    def close_handle(self, handle: int) -> None:
        assert handle == 101
        self.close_calls += 1
        if self.fail_close:
            raise WindowsIsolationError("forced CloseHandle failure")


api = CloseApi()
job = WindowsJob(JobLimits(), api=api)

try:
    job.close()
except WindowsIsolationError:
    pass
else:
    raise AssertionError("CloseHandle failure was swallowed")

assert not job.closed, "failed CloseHandle discarded the only native handle"
assert api.close_calls == 1

api.fail_close = False
job.close()
assert job.closed, "successful retry did not release the retained handle"
assert api.close_calls == 2

# Idempotence must not attempt to close an already released native handle.
job.close()
assert api.close_calls == 2

print("WINDOWS JOB CLOSE CONTRACT: 5 passed, 0 failed")

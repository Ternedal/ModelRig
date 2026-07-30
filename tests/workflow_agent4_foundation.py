#!/usr/bin/env python3
"""Auto-discovered Agent 4 workflow gate for foundation and replay cases."""

from __future__ import annotations

import unittest

from support.agent4_foundation_core import (
    Agent4FoundationWorkflowTests,
    Agent4RetryPolicyTests,
    Agent4WatchdogCoordinatorTests,
    Agent4WatchdogPolicyTests,
)
from support.agent4_timeline_replay_cases import Agent4TimelineReplayTests


if __name__ == "__main__":
    unittest.main()

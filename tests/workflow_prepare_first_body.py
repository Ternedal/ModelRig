#!/usr/bin/env python3
"""prepare-first-body.ps1: the contract of the one-command first body.

The script cannot be executed here (Windows, a rig, a running appliance), so
this pins what must be true of it: it goes through the tool that already
builds/installs/selects, it only ever ADDS the env key, it verifies against
the rig rather than trusting its own steps, it treats a 503 as the specific
"env never reached the worker" case, and it refuses when the rig serves a
different body than the one just selected.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "prepare-first-body.ps1"
CMD = ROOT / "PREPARE_FIRST_BODY.cmd"


class PrepareFirstBodyContract(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT.read_text(encoding="utf-8")

    def test_delegates_the_build_instead_of_reimplementing_it(self) -> None:
        self.assertIn("bodyrig_demo_body.py", self.text)
        for reimplementation in ("build_mrbody", "MRBodyProfileStore", "install_mrbody"):
            self.assertNotIn(reimplementation, self.text)

    def test_env_key_is_added_never_overwritten(self) -> None:
        self.assertIn("KALIV_BODY_STORE=$Store", self.text)
        # An existing, different value is reported and left alone.
        self.assertIn("Roerer den ikke", self.text)
        add = self.text.index("Set-Content -LiteralPath $envFile")
        guard = self.text.index("[string]::IsNullOrWhiteSpace($current)")
        self.assertLess(guard, add, "the write must sit inside the empty-value branch")

    def test_verifies_against_the_rig_not_against_its_own_steps(self) -> None:
        for probe in ("/api/v1/pair/claim", "/api/v1/body/active", "/api/v1/body/frames?limit=3"):
            self.assertIn(probe, self.text)
        self.assertIn("$manifest.body_id -ne $bodyId", self.text)

    def test_names_the_503_cause_rather_than_the_status(self) -> None:
        self.assertIn("503", self.text)
        self.assertIn("naaede ikke den koerende worker", self.text)

    def test_warns_that_an_env_change_needs_a_restart(self) -> None:
        self.assertIn("$envChanged", self.text)
        self.assertIn("STOP_DEV_APPLIANCE", self.text)

    def test_cmd_entry_point_requires_a_vrm_and_defaults_the_name(self) -> None:
        cmd = CMD.read_text(encoding="ascii")
        self.assertIn("prepare-first-body.ps1", cmd)
        self.assertIn("BODYNAME=Kaliv", cmd)
        self.assertIn("exit /b 1", cmd)

    def test_runbook_points_at_the_script(self) -> None:
        runbook = (ROOT / "docs" / "bodyrig" / "FIRST_LIVE_BODY.md").read_text(encoding="utf-8")
        self.assertIn("PREPARE_FIRST_BODY.cmd", runbook)


if __name__ == "__main__":
    unittest.main(verbosity=2)

#!/usr/bin/env python3
"""A4-18 physical campaign/summary mutation contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import unittest
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scripts" / "agent4-physical-fixture.py"
MUTATE = ROOT / "scripts" / "agent4-physical-mutate-fixture.py"
RUNTIME = ROOT / "validation" / "agent4-physical-runtime"


class Agent4PhysicalReadMutationTests(unittest.TestCase):
    def test_campaign_and_summary_mutations_are_exact_and_receipted(self) -> None:
        run_root = RUNTIME / f"mutation-ci-{uuid.uuid4().hex}"
        data_root = run_root / "data"
        fixture_manifest = run_root / "fixture.json"
        campaign_receipt = run_root / "campaign-mutation.json"
        summary_receipt = run_root / "summary-mutation.json"
        try:
            fixture = subprocess.run(
                [
                    sys.executable,
                    str(FIXTURE),
                    "--data-root",
                    str(data_root),
                    "--manifest",
                    str(fixture_manifest),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                fixture.returncode,
                0,
                msg=f"stdout:\n{fixture.stdout}\nstderr:\n{fixture.stderr}",
            )

            campaign = subprocess.run(
                [
                    sys.executable,
                    str(MUTATE),
                    "--data-root",
                    str(data_root),
                    "--mode",
                    "campaign-record",
                    "--receipt",
                    str(campaign_receipt),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                campaign.returncode,
                0,
                msg=f"stdout:\n{campaign.stdout}\nstderr:\n{campaign.stderr}",
            )
            campaign_data = json.loads(campaign_receipt.read_text(encoding="utf-8"))
            self.assertEqual(campaign_data["mode"], "campaign-record")
            self.assertEqual(
                campaign_data["campaign_count_after"],
                campaign_data["campaign_count_before"] + 1,
            )
            self.assertEqual(
                campaign_data["evidence_count_after"],
                campaign_data["evidence_count_before"],
            )

            summary = subprocess.run(
                [
                    sys.executable,
                    str(MUTATE),
                    "--data-root",
                    str(data_root),
                    "--mode",
                    "summary",
                    "--receipt",
                    str(summary_receipt),
                ],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                summary.returncode,
                0,
                msg=f"stdout:\n{summary.stdout}\nstderr:\n{summary.stderr}",
            )
            summary_data = json.loads(summary_receipt.read_text(encoding="utf-8"))
            self.assertEqual(summary_data["mode"], "summary")
            self.assertEqual(
                summary_data["campaign_count_after"],
                summary_data["campaign_count_before"],
            )
            self.assertEqual(
                summary_data["evidence_count_after"],
                summary_data["evidence_count_before"] + 1,
            )
            self.assertNotEqual(
                summary_data["timeline_head_before"],
                summary_data["timeline_head_after"],
            )
            self.assertNotEqual(
                summary_data["evidence_head_before"],
                summary_data["evidence_head_after"],
            )

            for receipt in (campaign_data, summary_data):
                self.assertTrue(receipt["receipt_sha256"].startswith("sha256:"))
                self.assertFalse(receipt["external_dispatch"])
                self.assertFalse(receipt["background_runtime"])
                self.assertFalse(receipt["production_activation"])
        finally:
            shutil.rmtree(run_root, ignore_errors=True)

    def test_mutator_refuses_repeat_receipt_and_outside_paths(self) -> None:
        source = MUTATE.read_text(encoding="utf-8")
        for forbidden in (
            "mount_agent4_operator",
            "KALIV_AGENT3_ENABLED",
            "uvicorn",
            "threading.Thread",
            "asyncio.create_task",
        ):
            self.assertNotIn(forbidden, source)
        self.assertIn("physical mutation forbids dispatch", source)
        self.assertIn('"production_activation": False', source)

        outside = subprocess.run(
            [
                sys.executable,
                str(MUTATE),
                "--data-root",
                str(ROOT / "outside-agent4-mutation"),
                "--mode",
                "summary",
                "--receipt",
                str(ROOT / "outside-agent4-mutation.json"),
            ],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(outside.returncode, 0)
        self.assertIn("validation/agent4-physical-runtime", outside.stderr)
        self.assertFalse((ROOT / "outside-agent4-mutation").exists())
        self.assertFalse((ROOT / "outside-agent4-mutation.json").exists())


if __name__ == "__main__":
    unittest.main()

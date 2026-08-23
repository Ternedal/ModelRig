#!/usr/bin/env python3
"""Offline contracts for the A4-18R canonical physical fixture and mutations."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import agent4_a4_18r_physical_fixture as fixture  # noqa: E402
import agent4_a4_18r_physical_mutate as mutate  # noqa: E402

EXPECTED_SHA = "a" * 40


class A418rFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="modelrig-a4-18r-")
        self.output = Path(self.temp.name).resolve()
        self.data = self.output / "fixture-data"
        self.manifest = self.output / "fixture-manifest.json"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _build(self) -> dict[str, object]:
        return fixture.build_fixture(
            self.output,
            self.data,
            self.manifest,
            expected_sha=EXPECTED_SHA,
            replace=True,
        )

    def test_fixture_crosses_all_android_page_boundaries_without_external_authority(self) -> None:
        value = self._build()
        self.assertEqual(value["schema"], fixture.SCHEMA)
        self.assertEqual(value["repository_sha"], EXPECTED_SHA)
        self.assertEqual(value["selected_campaign_id"], fixture.SELECTED_CAMPAIGN_ID)
        self.assertGreater(value["campaign_count"], 25)
        self.assertGreater(value["timeline_count"], 25)
        self.assertGreater(value["evidence_count"], 25)
        self.assertEqual(value["evidence_count"], value["evidence_verification_count"])
        self.assertFalse(value["external_dispatch"])
        self.assertFalse(value["background_runtime"])
        self.assertFalse(value["public_network"])
        self.assertFalse(value["production_activation"])
        self.assertTrue(self.manifest.is_file())
        self.assertTrue(self.data.is_dir())

    def test_output_root_inside_repository_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            fixture.safe_output_root(ROOT / "validation" / "forbidden-a4-18r")
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            mutate.safe_output_root(ROOT / "validation" / "forbidden-a4-18r")

    def test_campaign_and_summary_mutations_are_narrow_and_self_digested(self) -> None:
        self._build()
        campaign_path = self.output / "campaign-mutation.json"
        campaign = mutate.mutate(
            self.output,
            self.data,
            self.manifest,
            "campaign-record",
            campaign_path,
            expected_sha=EXPECTED_SHA,
        )
        self.assertEqual(campaign["campaign_count_after"], campaign["campaign_count_before"] + 1)
        self.assertEqual(campaign["evidence_count_after"], campaign["evidence_count_before"])
        self.assertEqual(campaign["timeline_head_after"], campaign["timeline_head_before"])
        self.assertEqual(campaign["evidence_head_after"], campaign["evidence_head_before"])

        summary_path = self.output / "summary-mutation.json"
        summary = mutate.mutate(
            self.output,
            self.data,
            self.manifest,
            "summary",
            summary_path,
            expected_sha=EXPECTED_SHA,
        )
        self.assertEqual(summary["campaign_count_after"], summary["campaign_count_before"])
        self.assertEqual(summary["evidence_count_after"], summary["evidence_count_before"] + 1)
        self.assertNotEqual(summary["timeline_head_after"], summary["timeline_head_before"])
        self.assertNotEqual(summary["evidence_head_after"], summary["evidence_head_before"])
        for value in (campaign, summary):
            claimed = value["receipt_sha256"]
            body = dict(value)
            del body["receipt_sha256"]
            actual = "sha256:" + hashlib.sha256(mutate.canonical_json(body)).hexdigest()
            self.assertEqual(claimed, actual)
            self.assertFalse(value["external_dispatch"])
            self.assertFalse(value["background_runtime"])
            self.assertFalse(value["public_network"])
            self.assertFalse(value["production_activation"])

    def test_mutation_rejects_fixture_from_another_exact_sha(self) -> None:
        self._build()
        value = json.loads(self.manifest.read_text(encoding="utf-8"))
        value["repository_sha"] = "b" * 40
        self.manifest.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "exact SHA"):
            mutate.mutate(
                self.output,
                self.data,
                self.manifest,
                "campaign-record",
                self.output / "should-not-exist.json",
                expected_sha=EXPECTED_SHA,
            )


if __name__ == "__main__":
    unittest.main()

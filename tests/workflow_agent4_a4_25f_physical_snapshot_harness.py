#!/usr/bin/env python3
"""Offline contracts for the A4-25f physical snapshot-authority harness."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "scripts" / "agent4_a4_25f_physical_fixture.py"
MUTATE = ROOT / "scripts" / "agent4_a4_25f_physical_mutate.py"
ROOT_ID = re.compile(r"^[0-9a-f]{64}$")
HASH = re.compile(r"^sha256:[0-9a-f]{64}$")


def _head() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _run(*args: object, expect: int = 0) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, *map(str, args)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode != expect:
        raise AssertionError(
            f"command returned {result.returncode}, expected {expect}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


class A425fPhysicalSnapshotHarnessTests(unittest.TestCase):
    def test_fixture_publishes_one_verified_immutable_root_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="modelrig-a4-25f-") as directory:
            output = Path(directory)
            _run(
                FIXTURE,
                "--output-root",
                output,
                "--expected-sha",
                _head(),
            )

            manifest = json.loads((output / "fixture-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["schema"], "modelrig-agent4/a4-25f-physical-fixture/v1")
            self.assertEqual(manifest["repository_sha"], _head())
            self.assertRegex(manifest["root_snapshot_id"], ROOT_ID)
            self.assertEqual(manifest["root_sequence"], 1)
            self.assertIsNone(manifest["root_parent_snapshot_id"])
            self.assertRegex(manifest["selected_campaign_snapshot_id"], ROOT_ID)
            self.assertEqual(manifest["campaign_count"], 31)
            self.assertGreater(manifest["timeline_count"], 25)
            self.assertEqual(manifest["evidence_count"], 31)
            self.assertRegex(manifest["timeline_head"], HASH)
            self.assertRegex(manifest["evidence_head"], HASH)
            self.assertRegex(manifest["latest_evidence_timeline_head"], HASH)
            self.assertRegex(manifest["persisted_files_sha256"], HASH)
            self.assertRegex(manifest["manifest_sha256"], HASH)
            self.assertFalse(manifest["external_dispatch"])
            self.assertFalse(manifest["background_runtime"])
            self.assertFalse(manifest["api_mounted"])
            self.assertFalse(manifest["public_network"])
            self.assertFalse(manifest["production_activation"])
            self.assertTrue((output / "fixture-data" / "operator-snapshots" / "current.json").is_file())

    def test_mutations_publish_linear_parented_roots_with_expected_deltas(self) -> None:
        with tempfile.TemporaryDirectory(prefix="modelrig-a4-25f-") as directory:
            output = Path(directory)
            sha = _head()
            _run(FIXTURE, "--output-root", output, "--expected-sha", sha)
            baseline = json.loads((output / "fixture-manifest.json").read_text(encoding="utf-8"))
            previous_root = baseline["root_snapshot_id"]
            previous_sequence = baseline["root_sequence"]
            expected_campaign_count = baseline["campaign_count"]
            previous_selected = None

            for mode in (
                "campaign-transition",
                "evidence-append",
                "campaign-add",
                "campaign-delete",
            ):
                result = _run(
                    MUTATE,
                    "--output-root",
                    output,
                    "--expected-sha",
                    sha,
                    "--mode",
                    mode,
                )
                receipt = json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(
                    receipt["schema"],
                    "modelrig-agent4/a4-25f-physical-mutation/v1",
                )
                self.assertEqual(receipt["repository_sha"], sha)
                self.assertEqual(receipt["mode"], mode)
                self.assertEqual(receipt["root_before"], previous_root)
                self.assertEqual(receipt["root_after_parent"], previous_root)
                self.assertNotEqual(receipt["root_after"], previous_root)
                self.assertRegex(receipt["root_after"], ROOT_ID)
                self.assertEqual(receipt["root_sequence_before"], previous_sequence)
                self.assertEqual(receipt["root_sequence_after"], previous_sequence + 1)
                self.assertEqual(receipt["pending_projections_after"], 0)
                self.assertRegex(receipt["receipt_sha256"], HASH)
                self.assertFalse(receipt["external_dispatch"])
                self.assertFalse(receipt["background_runtime"])
                self.assertFalse(receipt["api_mounted"])
                self.assertFalse(receipt["public_network"])
                self.assertFalse(receipt["production_activation"])

                if mode == "campaign-transition":
                    self.assertEqual(
                        receipt["selected_after"]["state_revision"],
                        receipt["selected_before"]["state_revision"] + 1,
                    )
                    previous_selected = receipt["selected_after"]
                elif mode == "evidence-append":
                    self.assertEqual(
                        receipt["selected_after"]["evidence_sequence"],
                        receipt["selected_before"]["evidence_sequence"] + 1,
                    )
                    self.assertEqual(
                        receipt["selected_after"]["timeline_sequence"],
                        receipt["selected_before"]["timeline_sequence"] + 1,
                    )
                    if previous_selected is not None:
                        self.assertEqual(
                            receipt["selected_before"]["state_revision"],
                            previous_selected["state_revision"],
                        )
                elif mode == "campaign-add":
                    expected_campaign_count += 1
                    self.assertEqual(receipt["campaign_count_after"], expected_campaign_count)
                else:
                    expected_campaign_count -= 1
                    self.assertEqual(receipt["campaign_count_after"], expected_campaign_count)

                previous_root = receipt["root_after"]
                previous_sequence = receipt["root_sequence_after"]

            receipt_files = sorted((output / "mutations").glob("*.json"))
            self.assertEqual(len(receipt_files), 4)
            self.assertEqual(
                [path.name[:4] for path in receipt_files],
                ["0002", "0003", "0004", "0005"],
            )

    def test_fixture_refuses_repository_output_and_wrong_exact_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix="modelrig-a4-25f-") as directory:
            output = Path(directory)
            wrong = "0" * 40
            if wrong == _head():
                wrong = "1" * 40
            failed = subprocess.run(
                [
                    sys.executable,
                    str(FIXTURE),
                    "--output-root",
                    str(output),
                    "--expected-sha",
                    wrong,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse((output / "fixture-data").exists())

        inside = ROOT / "validation" / "a4-25f-must-not-write"
        failed_inside = subprocess.run(
            [
                sys.executable,
                str(FIXTURE),
                "--output-root",
                str(inside),
                "--expected-sha",
                _head(),
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(failed_inside.returncode, 0)
        self.assertFalse(inside.exists())

    def test_nonempty_unmarked_output_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="modelrig-a4-25f-") as directory:
            output = Path(directory)
            (output / "foreign.txt").write_text("do not delete\n", encoding="utf-8")
            failed = subprocess.run(
                [
                    sys.executable,
                    str(FIXTURE),
                    "--output-root",
                    str(output),
                    "--expected-sha",
                    _head(),
                    "--replace",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertEqual((output / "foreign.txt").read_text(encoding="utf-8"), "do not delete\n")


if __name__ == "__main__":
    unittest.main()

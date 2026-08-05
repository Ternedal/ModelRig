from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATOR_PATH = ROOT / "scripts/tier_a_bundle_inventory.py"
SPEC = importlib.util.spec_from_file_location(
    "tier_a_bundle_inventory", GENERATOR_PATH
)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("could not load Tier-A bundle inventory generator")
GENERATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(GENERATOR)


class TierAAuthorityBundleInventoryTests(unittest.TestCase):
    def test_inventory_snapshots_are_exact_and_reproducible(self):
        first = GENERATOR.build_inventory(ROOT)
        second = GENERATOR.build_inventory(ROOT)
        self.assertEqual(first, second)

        actual_json = GENERATOR.render_json(first)
        actual_markdown = GENERATOR.render_markdown(first)
        snapshot_path = ROOT / GENERATOR.SNAPSHOT_PATH
        markdown_path = ROOT / GENERATOR.MARKDOWN_PATH
        expected_json = snapshot_path.read_text(encoding="utf-8")
        expected_markdown = markdown_path.read_text(encoding="utf-8")
        if expected_json != actual_json or expected_markdown != actual_markdown:
            print("BEGIN H10I GENERATED JSON")
            print(actual_json, end="")
            print("END H10I GENERATED JSON")
            print("BEGIN H10I GENERATED MARKDOWN")
            print(actual_markdown, end="")
            print("END H10I GENERATED MARKDOWN")
            self.fail("Tier-A authority-bundle inventory snapshot is stale")

        parsed = json.loads(expected_json)
        self.assertEqual(parsed["schema"], GENERATOR.SCHEMA)
        self.assertEqual(parsed["file_count"], len(parsed["files"]))
        self.assertEqual(
            [item["path"] for item in parsed["files"]],
            list(GENERATOR._bundle_paths(ROOT)),
        )
        for responsibility in GENERATOR.RESPONSIBILITIES:
            self.assertEqual(
                parsed["responsibility_summary"][responsibility],
                [
                    item["path"]
                    for item in parsed["files"]
                    if responsibility in item["responsibilities"]
                ],
            )


if __name__ == "__main__":
    unittest.main()

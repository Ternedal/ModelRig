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
    def test_inventory_report_and_lock_are_exact_and_reproducible(self):
        first = GENERATOR.build_inventory(ROOT)
        second = GENERATOR.build_inventory(ROOT)
        self.assertEqual(first, second)

        expected_lock = GENERATOR.render_json(GENERATOR.build_lock(first))
        expected_markdown = GENERATOR.render_markdown(first)
        lock_path = ROOT / GENERATOR.LOCK_PATH
        markdown_path = ROOT / GENERATOR.MARKDOWN_PATH
        actual_lock = lock_path.read_text(encoding="utf-8")
        actual_markdown = markdown_path.read_text(encoding="utf-8")
        if actual_lock != expected_lock or actual_markdown != expected_markdown:
            print("BEGIN H10I GENERATED LOCK")
            print(expected_lock, end="")
            print("END H10I GENERATED LOCK")
            print("BEGIN H10I GENERATED MARKDOWN")
            print(expected_markdown, end="")
            print("END H10I GENERATED MARKDOWN")
            self.fail("Tier-A authority-bundle inventory is stale")

        lock = json.loads(actual_lock)
        self.assertEqual(lock["lock_schema"], GENERATOR.LOCK_SCHEMA)
        self.assertEqual(lock["inventory_schema"], GENERATOR.SCHEMA)
        self.assertEqual(lock["file_count"], len(first["files"]))
        self.assertEqual(lock["totals"], first["totals"])
        self.assertEqual(
            [item["path"] for item in first["files"]],
            list(GENERATOR._bundle_paths(ROOT)),
        )
        for responsibility in GENERATOR.RESPONSIBILITIES:
            self.assertEqual(
                first["responsibility_summary"][responsibility],
                [
                    item["path"]
                    for item in first["files"]
                    if responsibility in item["responsibilities"]
                ],
            )


if __name__ == "__main__":
    unittest.main()

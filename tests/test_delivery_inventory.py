import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "scripts" / "delivery_inventory.py"
spec = importlib.util.spec_from_file_location("delivery_inventory", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class DeliveryInventoryTests(unittest.TestCase):
    def test_counts(self):
        meta = {"full_name": "Ternedal/ModelRig", "default_branch": "main"}
        prs = [
            {"draft": True, "number": 1, "title": "draft", "html_url": "https://github.com/a"},
            {"draft": False, "number": 2, "title": "ready", "html_url": "https://github.com/b"},
        ]
        with patch.object(module, "fetch", return_value=(meta, {})):
            with patch.object(module, "paginate", side_effect=[prs, [{"name": "main"}]]):
                result = module.inspect("ModelRig")
        self.assertEqual(result["open_prs"], 2)
        self.assertEqual(result["draft_prs"], 1)
        self.assertEqual(result["ready_prs"], 1)
        self.assertEqual(result["branch_count"], 1)

if __name__ == "__main__":
    unittest.main()

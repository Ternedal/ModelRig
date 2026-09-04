from __future__ import annotations

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "worker" / "app" / "read_connector_package_contract.py"
MAIN = ROOT / "worker" / "app" / "main.py"
TOOLS = ROOT / "worker" / "app" / "tools.py"


class T037ReadConnectorBoundaryTests(unittest.TestCase):
    def test_contract_has_no_network_credential_or_process_execution_imports(self) -> None:
        tree = ast.parse(CONTRACT.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])

        self.assertTrue({"hashlib", "json", "sqlite3", "threading", "time", "uuid"} <= imported)
        self.assertTrue(
            {"socket", "ssl", "subprocess", "requests", "httpx", "urllib", "os"}.isdisjoint(imported),
            f"dormant T-037 contract acquired execution/network imports: {sorted(imported)}",
        )

    def test_contract_does_not_register_tools_routes_or_read_environment(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        forbidden = (
            "REGISTRY[",
            "include_router(",
            "APIRouter(",
            "FastAPI(",
            "os.getenv(",
            "os.environ",
            "Authorization",
            "Bearer ",
            "token_file",
            "credential_file",
        )
        for needle in forbidden:
            self.assertNotIn(needle, text, needle)

    def test_normal_worker_boot_does_not_import_t037_contract(self) -> None:
        for path in (MAIN, TOOLS):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("read_connector_package_contract", text, str(path))
            self.assertNotIn("google_calendar_read", text, str(path))
            self.assertNotIn("google_drive_read", text, str(path))
            self.assertNotIn("gmail_read", text, str(path))
            self.assertNotIn("notion_read", text, str(path))

    def test_contract_pins_false_production_activation_and_four_capabilities(self) -> None:
        text = CONTRACT.read_text(encoding="utf-8")
        self.assertIn("PRODUCTION_ACTIVATION = False", text)
        for capability in (
            "tool:google_calendar_read",
            "tool:google_drive_read",
            "tool:gmail_read",
            "tool:notion_read",
        ):
            self.assertEqual(text.count(capability), 1, capability)
        for connector in ("google_calendar", "google_drive", "gmail", "notion"):
            self.assertIn(f'"{connector}"', text)


if __name__ == "__main__":
    unittest.main()

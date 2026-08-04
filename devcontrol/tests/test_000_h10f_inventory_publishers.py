from __future__ import annotations

import ast
import json
from pathlib import Path
import sys
import unittest


class H10FPublisherInventoryMaterializer(unittest.TestCase):
    def test_materialize_publisher_inventory(self) -> None:
        package = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "kaliv_dev_control"
        )
        interesting_calls = {
            "tempfile.mkstemp",
            "tempfile.NamedTemporaryFile",
            "os.replace",
            "os.link",
            "os.open",
            "Path.replace",
            "create_once_file",
            "rename_directory_no_replace",
            "sync_file",
            "sync_directory",
            "sync_tree",
        }
        records: list[dict[str, object]] = []

        for path in sorted(package.rglob("*.py")):
            relative = path.relative_to(package).as_posix()
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
            parents: list[str] = []

            class Visitor(ast.NodeVisitor):
                def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                    parents.append(node.name)
                    self.generic_visit(node)
                    parents.pop()

                visit_AsyncFunctionDef = visit_FunctionDef

                def visit_Call(self, node: ast.Call) -> None:
                    name = self._name(node.func)
                    normalized = name
                    if name.endswith(".replace") and name != "os.replace":
                        normalized = "Path.replace"
                    if normalized in interesting_calls:
                        records.append(
                            {
                                "path": relative,
                                "function": parents[-1] if parents else "<module>",
                                "line": node.lineno,
                                "call": normalized,
                            }
                        )
                    self.generic_visit(node)

                @staticmethod
                def _name(node: ast.AST) -> str:
                    if isinstance(node, ast.Name):
                        return node.id
                    if isinstance(node, ast.Attribute):
                        prefix = Visitor._name(node.value)
                        return f"{prefix}.{node.attr}" if prefix else node.attr
                    return ""

            Visitor().visit(tree)

        payload = json.dumps(records, sort_keys=True, separators=(",", ":"))
        sys.stderr.write(f"H10F_PUBLISHER_INVENTORY={payload}\n")
        self.fail("intentional H10F publisher inventory stop")


if __name__ == "__main__":
    unittest.main()

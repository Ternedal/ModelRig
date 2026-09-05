#!/usr/bin/env python3
"""Ask a gate the only question that matters: does it go red when it should?

A gate that asserts `"literal" in source` is green today. That says nothing
about whether it would notice the literal disappearing. This mutates the file
the gate reads -- comments out EVERY line carrying the literal -- and reports
the gate green afterwards as a miss.

Precision matters more than coverage here. An earlier, sloppier version of
this probe commented out only the first occurrence and guessed which file a
literal belonged to; it reported twelve misses of which eleven were its own
fault. So: variables are mapped to their file by reading the gate's AST, a
literal is only tested against the file it is actually compared to, and every
occurrence goes.

Even so, a miss is a question, not a verdict. `install_single_flight` in an
import line is not the same claim as in a call. Read the report, then look.

    python3 scripts/gate_mutation_probe.py tests/workflow_x.py [more...]
    python3 scripts/gate_mutation_probe.py --all        # every gate with source checks
"""

from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMENT = {".py": "# ", ".ps1": "# ", ".yml": "# ", ".kt": "// ", ".kts": "// ",
           ".go": "// ", ".cs": "// ", ".java": "// "}
MIN_LITERAL = 8


class GateModel(ast.NodeVisitor):
    """Which variable holds which file, and which literals are asserted in it."""

    def __init__(self, consts: dict[str, str]):
        self.consts = consts
        self.var_file: dict[str, str] = {}
        self.claims: list[tuple[str, str]] = []   # (literal, relative path)

    def _path_of(self, node: ast.AST) -> str | None:
        """A path expression built from string literals and known constants."""
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name):
            if node.id in ("ROOT", "root", "REPO", "repo", "repo_root"):
                return ""      # the repository itself: contributes no segment
            return self.consts.get(node.id)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            left, right = self._path_of(node.left), self._path_of(node.right)
            if right is None:
                return None
            if left is None:
                return None
            return right if left == "" else f"{left.rstrip('/')}/{right}"
        return None

    def visit_Assign(self, node: ast.Assign) -> None:
        names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if isinstance(node.value, ast.Call) and names:
            fn, rel = node.value.func, None
            if isinstance(fn, ast.Name) and fn.id == "code_of" and node.value.args:
                rel = self._path_of(node.value.args[0])
            elif isinstance(fn, ast.Attribute) and fn.attr == "read_text":
                rel = self._path_of(fn.value)
            if rel:
                for n in names:
                    self.var_file[n] = rel
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, ast.In) and isinstance(comp, ast.Name) \
               and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str) \
               and len(node.left.value) >= MIN_LITERAL:
                rel = self.var_file.get(comp.id)
                if rel:
                    self.claims.append((node.left.value, rel))
        self.generic_visit(node)


def module_constants(tree: ast.Module) -> dict[str, str]:
    """String constants AND path constants built from them.

    The common shape in this repo is `PHONE = ROOT / "scripts" / "x.ps1"`
    followed by `phone = PHONE.read_text(...)`. Resolving only bare string
    constants left the probe unable to bind a single file in the eight
    heaviest gates -- it reported "0 mutations", which reads like a pass and
    is not one. Two passes, because a path constant may be built from another.
    """
    out: dict[str, str] = {}
    for _ in range(2):
        helper = GateModel(out)
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if not names:
                continue
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for n in names:
                    out[n] = node.value.value
                continue
            resolved = helper._path_of(node.value)
            if resolved:
                for n in names:
                    out[n] = resolved
    return out


def run_gate(gate: Path) -> bool:
    proc = subprocess.run([sys.executable, str(gate)], capture_output=True, text=True,
                          cwd=ROOT, env={"PYTHONPATH": "worker", "PYTHONDONTWRITEBYTECODE": "1",
                                         "PATH": "/usr/bin:/bin:/usr/local/bin"})
    return proc.returncode == 0


def comment_every(path: Path, literal: str) -> int:
    mark = COMMENT.get(path.suffix)
    if not mark:
        return 0
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    touched = 0
    for i, line in enumerate(lines):
        if literal in line and not line.lstrip().startswith(mark.strip()):
            indent = re.match(r"[ \t]*", line).group(0)
            lines[i] = indent + mark + line.strip() + "\n"
            touched += 1
    if touched:
        path.write_text("".join(lines), encoding="utf-8")
    return touched


def probe(gate: Path) -> tuple[int, list[str]]:
    text = gate.read_text(encoding="utf-8")
    tree = ast.parse(text)
    model = GateModel(module_constants(tree))
    model.visit(tree)
    if not run_gate(gate):
        return 0, [f"{gate.name}: already red -- skipped"]
    misses, tested, seen = [], 0, set()
    for literal, rel in model.claims:
        target = ROOT / rel
        if (literal, rel) in seen or not target.exists():
            continue
        seen.add((literal, rel))
        backup = target.read_bytes()
        n = comment_every(target, literal)
        if n:
            tested += 1
            if run_gate(gate):
                misses.append(f"{gate.name}: '{literal[:52]}' ({n}x in {rel}) -> still green")
        target.write_bytes(backup)
    return tested, misses


def gates_with_source_checks() -> list[Path]:
    out = []
    for f in sorted(ROOT.joinpath("tests").rglob("*.py")):
        t = f.read_text(encoding="utf-8", errors="replace")
        if "read_text" in t or "code_of" in t:
            out.append(f)
    return out


def main() -> int:
    args = sys.argv[1:]
    gates = gates_with_source_checks() if "--all" in args else [ROOT / a for a in args]
    if not gates:
        print(__doc__)
        return 2
    total_tested = 0
    all_misses: list[str] = []
    for gate in gates:
        if not gate.exists():
            print(f"  (missing {gate})")
            continue
        try:
            tested, misses = probe(gate)
        except SyntaxError:
            continue
        total_tested += tested
        all_misses.extend(misses)
        if tested or misses:
            print(f"{gate.name}: {tested} mutations, {len([m for m in misses if 'still green' in m])} missed")
        for m in misses:
            print(f"    {m}")
    print(f"\n===== GATE MUTATION PROBE: {total_tested} mutations, "
          f"{len([m for m in all_misses if 'still green' in m])} missed =====")
    return 0


if __name__ == "__main__":
    sys.exit(main())

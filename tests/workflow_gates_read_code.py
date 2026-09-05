#!/usr/bin/env python3
"""Ratchet: substring checks against RAW source may not grow.

Five gates were measured failing this way on 4/9: a commented-out line still
satisfies `"x" in source`. `frame.Validate()` commented out left 50 of 50
Unity contracts green; `verdictForPlan` commented out left Agent 3's dormancy
gate green at 41/41 with the start unguarded; the mount contract accepted a
commented-out production import at 33/33.

There are 786 such checks across 58 files. Fixing them all today is not
honest work -- most are fine in practice and each needs its own mutation to
prove otherwise. So this gate does the one thing that is both cheap and
true: the count may fall, never rise. A new gate reads source through
`tests/support/source_code.code_of`; an old one is paid down when someone
touches it.

What this does NOT prove: that the remaining checks are correct. It proves
only that the debt stops growing. The rule that finds real bugs is still the
one in HANDOFF -- mutate what a gate protects and watch it go red.

Run: python3 tests/workflow_gates_read_code.py [--update]
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "tests" / "support" / "raw_source_checks_baseline.json"
SRC_EXT = (".py", ".ps1", ".go", ".kt", ".kts", ".cs", ".java", ".yml")


class Scan(ast.NodeVisitor):
    """Variables assigned from .read_text(), then used as `"lit" in var`."""

    def __init__(self) -> None:
        self.raw: set[str] = set()
        self.code: set[str] = set()
        self.hits = 0

    def visit_Assign(self, node: ast.Assign) -> None:
        if isinstance(node.value, ast.Call):
            fn = node.value.func
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if isinstance(fn, ast.Attribute) and fn.attr == "read_text":
                self.raw.update(names)
            elif isinstance(fn, ast.Name) and fn.id == "code_of":
                self.code.update(names)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        for op, comp in zip(node.ops, node.comparators):
            if isinstance(op, (ast.In, ast.NotIn)) and isinstance(comp, ast.Name):
                if comp.id in self.raw and comp.id not in self.code:
                    self.hits += 1
        self.generic_visit(node)


def mentions_source_file(text: str) -> bool:
    return any(re.search(re.escape(e) + r"[\"'/]", text) for e in SRC_EXT)


def measure() -> dict[str, int]:
    counts: dict[str, int] = {}
    files = sorted(ROOT.joinpath("tests").rglob("*.py"))
    files += sorted(ROOT.joinpath("scripts").glob("*_contract.py"))
    for path in files:
        if path.name in ("source_code.py", Path(__file__).name):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "read_text" not in text or not mentions_source_file(text):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        scan = Scan()
        scan.visit(tree)
        if scan.hits:
            counts[str(path.relative_to(ROOT)).replace("\\", "/")] = scan.hits
    return counts


def main() -> int:
    counts = measure()
    if "--update" in sys.argv:
        BASELINE.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"baseline skrevet: {len(counts)} filer, {sum(counts.values())} tjek")
        return 0
    if not BASELINE.exists():
        print("FAIL: baseline mangler -- kør med --update")
        return 1
    base = json.loads(BASELINE.read_text(encoding="utf-8"))
    problems = []
    for name, n in sorted(counts.items()):
        was = base.get(name)
        if was is None:
            problems.append(f"NY fil med rå-kilde-tjek: {name} ({n}) -- brug code_of()")
        elif n > was:
            problems.append(f"{name}: {was} -> {n} rå-kilde-tjek (må kun falde)")
    paid = sorted(name for name, was in base.items() if counts.get(name, 0) < was)
    total, base_total = sum(counts.values()), sum(base.values())
    for p in problems:
        print(f"  FAIL: {p}")
    for name in paid:
        print(f"  betalt ned: {name} {base[name]} -> {counts.get(name, 0)}")
    print(f"\n===== RAW SOURCE CHECKS: {total} (baseline {base_total}) "
          f"i {len(counts)} filer, {len(problems)} overtrædelser =====")
    if problems:
        print("  Kør gaten med --update NÅR nedbetaling er landet, ikke for at hæve loftet.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

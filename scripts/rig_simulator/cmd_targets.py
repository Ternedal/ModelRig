#!/usr/bin/env python3
"""Every file a root launcher points at must exist in the checkout.

The root ``*.cmd`` files are what Anders double-clicks on the rig. Each one
hands over to a script under ``scripts\\``, ``deploy\\`` or ``tools\\``. When
that script is renamed or moved, the launcher keeps working on the machine
that has the old file and fails on the rig day. The same holds for a
``.ps1`` that starts a sibling script by relative path.

This check reads every root ``.cmd`` and every ``scripts/*.ps1`` and
``deploy/*.ps1``, extracts repository-relative references of the form
``scripts\\name.ext`` / ``scripts/name.ext`` (also behind ``%~dp0``), and
requires each referenced *source* file (.py, .ps1, .cmd) to exist with that exact
spelling. Built binaries, data files and env files are runtime artefacts and
are not checked here. Windows is
case-insensitive and the repository is not, so the spelling must match
byte for byte; a case-only difference passes on the rig and fails on Linux
CI, which is how it would otherwise go unnoticed.

Exit 0 when every reference resolves; the JSON report lists every launcher,
its references and the misses.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True

SCHEMA = "kaliv-rig-simulator-cmd-targets/v1"
REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_\-])((?:scripts|deploy|tools|worker|backend)[\\/](?:[A-Za-z0-9_.\-]+[\\/])*[A-Za-z0-9_\-]+\.(?:py|ps1|cmd))",
)
LAUNCHER_GLOBS = ("*.cmd",)
SCRIPT_GLOBS = ("*.ps1", "scripts/*.ps1", "scripts/rig_simulator/*.ps1", "deploy/*.ps1")


def references(text: str) -> list[str]:
    seen: list[str] = []
    for match in REFERENCE.finditer(text):
        raw = match.group(1).replace("\\", "/")
        if "%" in raw or "$" in raw or raw in seen:
            continue
        seen.append(raw)
    return seen


def exact_exists(root: Path, relative: str) -> bool:
    """True only if the path exists with this exact spelling (case included)."""
    current = root
    for part in relative.split("/"):
        try:
            names = {entry.name for entry in current.iterdir()}
        except OSError:
            return False
        if part not in names:
            return False
        current = current / part
    return current.is_file()


def check(root: Path) -> dict:
    files: list[Path] = []
    for pattern in LAUNCHER_GLOBS + SCRIPT_GLOBS:
        files.extend(sorted(root.glob(pattern)))
    entries = []
    misses_total = 0
    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace")
        refs = references(text)
        misses = [ref for ref in refs if not exact_exists(root, ref)]
        misses_total += len(misses)
        entries.append({"file": path.relative_to(root).as_posix(), "references": refs, "missing": misses})
    return {
        "schema": SCHEMA,
        "files_checked": len(entries),
        "missing_total": misses_total,
        "ok": misses_total == 0 and len(entries) > 0,
        "entries": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--report", type=Path, help="write the JSON report here as well as to stdout")
    args = parser.parse_args(argv)
    result = check(args.repository_root.resolve())
    text = json.dumps(result, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

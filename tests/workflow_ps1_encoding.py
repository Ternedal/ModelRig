#!/usr/bin/env python3
"""Fail-closed gate: PowerShell files must be parseable on BOTH shells.

The 2.0.12 M2 campaign died before its first line: the owned-pairing wrapper
is UTF-8 with Danish text but had no BOM, so Windows PowerShell 5.1 read it
as ANSI and the parser broke on a mangled byte (#753). CI never parsed ps1
files at all. Two deterministic rules close the class:

1. Any .ps1 containing non-ASCII bytes MUST start with the UTF-8 BOM --
   that is the documented signal that makes 5.1 read UTF-8 instead of ANSI.
2. Every .ps1 must parse cleanly (pwsh AST parser), catching plain syntax
   errors the same way.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOM = b"\xef\xbb\xbf"

FAILED = 0


def check(ok: bool, message: str) -> None:
    global FAILED
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if not ok:
        FAILED = 1


def main() -> int:
    files = sorted(ROOT.glob("scripts/*.ps1")) + sorted(ROOT.glob("*.ps1"))
    if not files:
        print("FAIL: no ps1 files found -- the discovery is broken, not the repo")
        return 1

    # Self-test: a BOM-less non-ASCII payload must be flagged.
    probe = "# kør\n".encode("utf-8")
    check(not probe.startswith(BOM) and any(b > 0x7F for b in probe),
          "self-test: a BOM-less non-ASCII payload is detectable")

    for path in files:
        raw = path.read_bytes()
        rel = path.relative_to(ROOT).as_posix()
        if any(b > 0x7F for b in raw):
            check(raw.startswith(BOM), f"{rel}: non-ASCII content carries the UTF-8 BOM (5.1 reads ANSI without it)")

    listing = ROOT / "validation" / ".ps1-gate-files.txt"
    listing.parent.mkdir(exist_ok=True)
    listing.write_text("\n".join(str(p) for p in files), encoding="utf-8")
    script = (
        f"$bad=0; foreach ($p in (Get-Content '{listing}')) {{ $e=$null; "
        "[System.Management.Automation.Language.Parser]::ParseFile($p,[ref]$null,[ref]$e) > $null; "
        "if ($e) { $bad++; Write-Output ($p + '|' + $e[0].Message) } }; exit $bad"
    )
    proc = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script],
        capture_output=True, text=True,
    )
    listing.unlink(missing_ok=True)
    for line in proc.stdout.splitlines():
        if "|" in line:
            print(f"  FAIL: parse: {line.split('|',1)[0]}: {line.split('|',1)[1][:100]}")
    check(proc.returncode == 0, f"all {len(files)} ps1 files parse cleanly (pwsh AST)")

    print(f"ps1 encoding gate: {'GREEN' if not FAILED else 'DRIFT DETECTED'} across {len(files)} files")
    return FAILED


if __name__ == "__main__":
    sys.exit(main())

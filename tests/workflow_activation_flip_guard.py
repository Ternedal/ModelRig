#!/usr/bin/env python3
"""Fail-closed guard: no PRODUCTION_ACTIVATION flip lands as a side effect.

Phase 4 of the activation plan (issue #731) is explicit: every surface's
PRODUCTION_ACTIVATION constant flips only through its own evidence
campaign -- a deliberate PR, a rig day, a #731 report. Never incidentally.

This gate enforces exactly that and nothing more. It discovers every
``PRODUCTION_ACTIVATION = ...`` site under worker/app/ and requires the
literal value ``False``. The day Anders approves a surface's activation,
the flip PR must ALSO update this gate's ALLOWLIST -- one line, in the
same diff, visible to review. A flip that forgets the allowlist fails CI;
a flip hidden inside an unrelated change fails CI. Nothing about the
decision process is invented here: the gate only makes the agreed rule
mechanical.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Surfaces Anders has explicitly approved for activation, by module stem.
# Empty until the first Phase 4 decision; each entry lands in the same PR
# as its flip, with the #731 evidence reference in the commit message.
ALLOWLIST: frozenset[str] = frozenset()

SITE = re.compile(r"^PRODUCTION_ACTIVATION\s*=\s*(?P<value>.+?)\s*(#.*)?$", re.M)

FAILED = 0


def check(ok: bool, message: str) -> None:
    global FAILED
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if not ok:
        FAILED = 1


def main() -> int:
    # Self-test first: a flipped payload must be detectable.
    probe = SITE.search("PRODUCTION_ACTIVATION = True\n")
    check(probe is not None and probe.group("value") == "True",
          "self-test: a flipped constant is detectable")

    files = sorted(ROOT.glob("worker/app/*.py"))
    sites = 0
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        stem = path.stem
        for m in SITE.finditer(path.read_text(encoding="utf-8")):
            sites += 1
            value = m.group("value")
            if stem in ALLOWLIST:
                check(value in ("True", "False"),
                      f"{rel}: allowlisted surface holds an explicit literal ({value})")
            else:
                check(value == "False",
                      f"{rel}: PRODUCTION_ACTIVATION stays False until its own approved flip PR (found {value})")

    check(sites >= 8, f"discovery found the known activation sites ({sites} >= 8)")
    print(f"activation flip guard: {'HELD' if not FAILED else 'FLIP WITHOUT APPROVAL'} across {sites} sites")
    return FAILED


if __name__ == "__main__":
    sys.exit(main())

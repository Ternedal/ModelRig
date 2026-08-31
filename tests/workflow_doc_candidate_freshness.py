#!/usr/bin/env python3
"""Operational runbooks may not name an old candidate as the current one.

Code has era-pin gates; prose has none. Era shifts therefore leave stale
candidate references behind in the documents a rig session actually
follows, and they surface at the worst possible moment -- standing at the
rig, about to bind evidence to a dead anchor. On 30/08 that had #69, #72
and #401 still citing physical-proof/2.0.11 three eras later, and
PHYSICAL_VALIDATION_CAMPAIGN.md still calling 2.0.11 "the version".

Scope is deliberately narrow, because the cure must not punish honesty:

* Only OPERATIONAL documents are checked -- the ones an operator follows
  step by step. A journal entry recording what was true on 23/08 is
  correct history and must stay.
* HANDOFF.md is a journal with the newest status block on top: only that
  first block is checked; everything below it is history by construction.
* Files whose name declares an era (CANDIDATE_2.0.11.md) are exempt --
  the filename already tells the reader what they are reading.

The check itself is simple: inside those documents, every
``physical-proof/<version>`` and every "version `<x.y.z>`" claim must
match VERSION.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OPERATIONAL_DOCS = (
    "RIGDAG_SIMPEL.md",
    "STAGED_PHYSICAL_PROMOTION.md",
    "PHYSICAL_VALIDATION_CAMPAIGN.md",
    "STAGE_B_UPDATER_EVIDENCE.md",
    # The physical runbooks under docs/ name no candidate today, so these
    # two entries find nothing -- they are here for the era after next,
    # when someone writes one in. A gate that only covers the documents
    # that have already drifted protects nothing.
    "docs/agent4/A4-25F_PHYSICAL_QUALIFICATION_RUNBOOK.md",
    "docs/agent4/A4-18R_PHYSICAL_READ_PRODUCT.md",
)

# HANDOFF is a journal: check only the newest status block.
JOURNAL = "HANDOFF.md"
BLOCK = re.compile(r"^\*\*\[\d", re.M)

CANDIDATE_BRANCH = re.compile(r"physical-proof/(\d+\.\d+\.\d+)")
VERSION_CLAIM = re.compile(r"(?:^|\s)version[ :]+`(\d+\.\d+\.\d+)`", re.I)

FAILED = 0


def check(ok: bool, message: str) -> None:
    global FAILED
    print(f"  {'PASS' if ok else 'FAIL'}: {message}")
    if not ok:
        FAILED = 1


def stale(text: str, current: str) -> list[str]:
    found = []
    for match in CANDIDATE_BRANCH.finditer(text):
        if match.group(1) != current:
            found.append(f"physical-proof/{match.group(1)}")
    for match in VERSION_CLAIM.finditer(text):
        if match.group(1) != current:
            found.append(f"version `{match.group(1)}`")
    return sorted(set(found))


def newest_block(text: str) -> str:
    starts = [m.start() for m in BLOCK.finditer(text)]
    if not starts:
        return text
    return text[: starts[1]] if len(starts) > 1 else text


def main() -> int:
    current = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    check(bool(re.fullmatch(r"\d+\.\d+\.\d+", current)), f"VERSION is a version ({current})")

    # Self-test: the detector must actually detect.
    probe = stale("branch: `physical-proof/1.0.0`; version: `1.0.0`", current)
    check(len(probe) == 2, "self-test: an old candidate and an old version claim are both caught")
    check(stale(f"physical-proof/{current}", current) == [], "self-test: the current candidate passes")

    for name in OPERATIONAL_DOCS:
        path = ROOT / name
        if not path.exists():
            continue
        problems = stale(path.read_text(encoding="utf-8"), current)
        check(
            not problems,
            f"{name}: names only the current candidate {current}"
            + (f" -- found {problems}" if problems else ""),
        )

    journal = ROOT / JOURNAL
    if journal.exists():
        problems = stale(newest_block(journal.read_text(encoding="utf-8")), current)
        check(
            not problems,
            f"{JOURNAL}: the newest status block names {current}"
            + (f" -- found {problems}" if problems else ""),
        )

    print(
        "doc candidate freshness: "
        + ("OK" if not FAILED else "STALE CANDIDATE IN AN OPERATIONAL DOC")
    )
    return FAILED


if __name__ == "__main__":
    sys.exit(main())

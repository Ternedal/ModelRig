#!/usr/bin/env python3
"""Every file the proof campaign writes must be git-ignored.

Every entry point on the rig requires ``git status --porcelain`` to be empty
before it does anything: the campaign core and its owned-pairing wrapper, Stage
A Blok 0, ``candidate_freeze_check.py``. The campaign itself writes gate receipts
to ``validation/proof-gates/``, a per-run summary to ``validation/proof-campaign/``
and the physical proof sources the receipts bind to. When any of those paths is
not ignored, the FIRST run succeeds and the SECOND thing that checks the tree
fails -- a skip/reuse rerun, the next launcher, the freeze -- with a "working
tree is not clean" the operator did not cause. The owned-pairing wrapper already
paid this lesson once (the old unignored ``validation/proof-bootstrap`` path).

The list is derived from the scripts, not written down here: a new receipt or
source path added to ``proof_campaign_gate_receipt.py`` or a new output root in
``run-proof-campaign.ps1`` fails this test instead of the rig day.
"""
from __future__ import annotations

import importlib.util
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
RECEIPT_MODULE = ROOT / "scripts" / "proof_campaign_gate_receipt.py"
CORE = ROOT / "scripts" / "run-proof-campaign.ps1"

# The campaign core delegates T-023 and T-033 to these operators (via the
# proof_t*_current wrappers, which import them). Their outputs live in their
# OWN sources, invisible to RECEIPTS/SOURCES and to the core's path literals --
# the exact gap that left agent3-termination-ui-evidence/ unignored (#743 P1).
DELEGATED = [
    ROOT / "scripts" / "proof_t023_current.py",
    ROOT / "scripts" / "proof_t033_current.py",
    ROOT / "scripts" / "agent3_termination_ui_physical_one_click.py",
    ROOT / "scripts" / "agent3_termination_ui_physical_report.py",
    ROOT / "scripts" / "agent3_termination_ui_physical_gate.py",
    ROOT / "scripts" / "physical_validation_termination_campaign.py",
    ROOT / "scripts" / "agent3_memory_protected_backup_physical.py",
    ROOT / "scripts" / "agent3_memory_protected_backup_physical_gate.py",
]

passed = 0
failed = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"  FAIL: {name}{suffix}")


def load_receipt_module():
    spec = importlib.util.spec_from_file_location(
        "proof_campaign_gate_receipt", RECEIPT_MODULE
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def campaign_output_roots(core_text: str) -> list[str]:
    """Directories the campaign core creates under validation/ for its own output."""
    roots: set[str] = set()
    for match in re.finditer(r'"validation\\([A-Za-z0-9_-]+)\\', core_text):
        roots.add(f"validation/{match.group(1)}/")
    for match in re.finditer(r"'validation\\([A-Za-z0-9_-]+)\\", core_text):
        roots.add(f"validation/{match.group(1)}/")
    return sorted(roots)


def delegated_operator_paths() -> dict[str, str]:
    """Every validation/ path a delegated operator mentions in source.

    Derivation, not enumeration: string literals of the forms
    ``"validation/<x>"`` (f-string tails are cut at ``{``) and
    ``VALIDATION / "<x>"``. A segment with an extension is a file, everything
    else a directory. Over-collection is harmless -- an extra mention of an
    already-ignored path just re-asserts it.
    """
    found: dict[str, str] = {}
    for module in DELEGATED:
        text = module.read_text(encoding="utf-8")
        raw: set[str] = set()
        for match in re.finditer(r"[\"']validation/([A-Za-z0-9_./-]+)", text):
            raw.add(match.group(1))
        for match in re.finditer(r"VALIDATION\s*/\s*[\"']([A-Za-z0-9_.-]+)[\"']", text):
            raw.add(match.group(1))
        for tail in raw:
            tail = tail.strip("/")
            if not tail:
                continue
            leaf = tail.rsplit("/", 1)[-1]
            if "." in leaf:
                found[f"delegated {module.name}: validation/{tail}"] = f"validation/{tail}"
            else:
                found[f"delegated {module.name}: validation/{tail}/"] = f"validation/{tail}/"
    return found


def is_ignored(path: str) -> bool:
    """Ask git itself; the .gitignore text is not the authority, git's reading is."""
    probe = path + "probe.json" if path.endswith("/") else path
    result = subprocess.run(
        ["git", "-C", str(ROOT), "check-ignore", "-q", "--", probe],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def main() -> int:
    missing = [
        str(p.relative_to(ROOT)) for p in (RECEIPT_MODULE, CORE) if not p.is_file()
    ]
    check("campaign scripts exist", not missing, f"missing={missing}")
    if missing:
        return 1

    module = load_receipt_module()
    receipts = getattr(module, "RECEIPTS", {})
    sources = getattr(module, "SOURCES", {})
    check("receipt module exposes RECEIPTS", isinstance(receipts, dict) and receipts)
    check("receipt module exposes SOURCES", isinstance(sources, dict) and sources)

    derived: dict[str, str] = {}
    for gate, path in receipts.items():
        derived[f"receipt {gate}"] = pathlib.Path(path).as_posix()
    for gate, path in sources.items():
        if path is not None:
            derived[f"source {gate}"] = pathlib.Path(path).as_posix()

    core_text = CORE.read_text(encoding="utf-8")
    roots = campaign_output_roots(core_text)
    check(
        "campaign core declares at least one validation output root",
        bool(roots),
        "no validation\\<dir>\\ literal found in run-proof-campaign.ps1",
    )
    for root in roots:
        derived[f"campaign output root {root}"] = root

    missing_delegated = [
        str(p.relative_to(ROOT)) for p in DELEGATED if not p.is_file()
    ]
    check(
        "all delegated operator modules exist",
        not missing_delegated,
        f"missing={missing_delegated} -- a rename must update DELEGATED, not silently empty it",
    )
    delegated = delegated_operator_paths() if not missing_delegated else {}
    check(
        "delegated derivation found at least 8 paths",
        len(set(delegated.values())) >= 8,
        f"found {sorted(set(delegated.values()))}",
    )
    for anchor in (
        "validation/agent3-termination-ui-evidence/",
        "validation/agent3-memory-protected-backup-physical/",
        "validation/physical-validation-termination-final-latest.json",
    ):
        check(
            f"delegated derivation contains anchor {anchor}",
            anchor in delegated.values(),
            "the derivation lost a known operator output -- regex or source drifted",
        )
    derived.update(delegated)

    for label, path in sorted(derived.items()):
        check(f"{label} is git-ignored: {path}", is_ignored(path), "git check-ignore rejects it")
        if not path.endswith("/"):
            check(
                f"{label} .tmp sibling is git-ignored: {path}.tmp",
                is_ignored(path + ".tmp"),
                "atomic-write temp file would dirty the tree",
            )

    # Self-test: a path nothing ignores must be reported as such, or every check
    # above proves nothing.
    check(
        "self-test: an unignored validation path is detected",
        not is_ignored("validation/definitely-not-ignored-probe.json"),
    )

    print(f"proof campaign outputs ignored: {passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Pinner stale_check's klassifikation i et konstrueret repo.

Vaerktoejet giver RAAD om hvorvidt et merge er sikkert. Et raad der er stille
forkert er vaerre end intet raad -- saa de tre udfald pinnes mod en historik
vi selv bygger, ikke mod repoets egne refs (som flytter sig).

De tre scenarier er praecis dem der optraadte 30/7:
  blot gammel  -> #250/#251: main aendrede filen, branchen roerte den ikke
  kraever review -> #246: branchen aendrede filen med en aeldre udgave
  ajour        -> #235: branchen aendrer sin fil, men er ikke bagud
"""
from __future__ import annotations

import importlib.util
import pathlib
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "stale_check", ROOT / "scripts" / "stale_check.py"
)
stale_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stale_check)

PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  PASS: {label}")
    else:
        FAILED += 1
        print(f"  FAIL: {label}")


def run(cwd: pathlib.Path, *args: str) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True)


def write(cwd: pathlib.Path, name: str, text: str) -> None:
    (cwd / name).write_text(text, encoding="utf-8")


with tempfile.TemporaryDirectory() as tmp:
    repo = pathlib.Path(tmp)
    run(repo, "git", "init", "-q", "-b", "main")
    run(repo, "git", "config", "user.email", "t@example.com")
    run(repo, "git", "config", "user.name", "T")

    # Faelles udgangspunkt.
    for name in ("untouched.txt", "reverted.txt", "bumped.txt", "generated.txt"):
        write(repo, name, "v1\n")
    write(repo, "CURRENT_STATE.md", "gen v1\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-qm", "base")
    base_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True
    ).stdout.strip()

    # Branchen: aendrer 'reverted' til en AELDRE-agtig udgave, bumper 'bumped',
    # tilfoejer en ny fil. Roerer ikke 'untouched'.
    run(repo, "git", "checkout", "-qb", "feature")
    write(repo, "reverted.txt", "branch-udgave\n")
    write(repo, "bumped.txt", "v2-branch\n")
    write(repo, "brand-ny.txt", "ny\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-qm", "branch arbejde")

    # main gaar videre i 'untouched' og 'reverted' -- og i CURRENT_STATE.md,
    # som skal ignoreres fordi den er genereret.
    run(repo, "git", "checkout", "-q", "main")
    write(repo, "untouched.txt", "v2-main\n")
    write(repo, "reverted.txt", "main-nyere\n")
    write(repo, "CURRENT_STATE.md", "gen v2\n")
    run(repo, "git", "add", "-A")
    run(repo, "git", "commit", "-qm", "main gaar videre")

    # Branchen henter main's 'bumped'-linje, saa den er ajour paa den fil.
    run(repo, "git", "checkout", "-q", "feature")
    run(repo, "git", "merge", "-q", "--no-edit", "main", "-X", "ours")

    cwd = pathlib.Path.cwd()
    try:
        import os

        os.chdir(repo)
        new_files, merely_old, will_overwrite, base_moved_too = stale_check.classify(
            "feature", "main"
        )
    finally:
        os.chdir(cwd)

    review_paths = {p for p, _ in will_overwrite}
    old_paths = {p for p, _ in merely_old}

    check("brand-ny.txt" in new_files, "en fil der ikke findes paa main tælles som ny")
    check(
        "reverted.txt" in review_paths,
        "branchens egen aendring af en fil main har flyttet -> VIL OVERSKRIVE"
        " (ogsaa naar branchen har merget main med -X ours og ser ajour ud)",
    )
    check(
        "untouched.txt" not in review_paths and "untouched.txt" not in old_paths,
        "en fil branchen slet ikke roerer optraeder ikke",
    )
    check(
        "CURRENT_STATE.md" not in review_paths and "CURRENT_STATE.md" not in old_paths,
        "genererede filer ignoreres (de regenereres ved landing)",
    )
    check(
        all("CURRENT_STATE.md" != p for p in new_files),
        "genererede filer tælles heller ikke som nye",
    )
    check(
        "bumped.txt" in review_paths,
        "en fil branchen aendrer og som afviger fra main flagges, ajour eller ej",
    )
    # Det vigtige negative resultat: her HAR branchen merget main, saa
    # merge-base ER main's tip og ancestry siger "ajour". Sub-flaget
    # base_moved_too kan derfor ikke fyre -- og det er praecis derfor
    # hovedflaget bygger paa INDHOLD. Havde vaerktoejet stolet paa ancestry,
    # var reverted.txt sluppet igennem i stilhed.
    check(
        "reverted.txt" not in set(base_moved_too),
        "sub-flaget kan ikke fyre naar branchen har merget base (ancestry lyver)",
    )
    check(
        "reverted.txt" in review_paths,
        "men hovedflaget fanger den alligevel, fordi det bygger paa indhold",
    )

print(f"\n===== STALE CHECK: {PASSED} passed, {FAILED} failed =====")
if FAILED:
    raise SystemExit(1)

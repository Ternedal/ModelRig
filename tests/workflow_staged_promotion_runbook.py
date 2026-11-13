#!/usr/bin/env python3
"""Run the retained staged-promotion contract plus live 2.0.19 authority checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402 -- tests/support is not a package

ROOT = Path(__file__).resolve().parents[1]
_source_path = Path(__file__).with_name("workflow_staged_promotion_runbook.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    # Codex #2364 4508274860: under D3 the Stage A candidate is the published RC SHA, checked out
    # on the branch the Stage A operator requires, not the release-prep branch.
    ("agent/unified-candidate-1.58.143", "physical-proof/2.0.19"),
    ("1.58.143", "2.0.19"),
    ("1.58.142", "2.0.12"),
    ("draft-PR #150", "origin/physical-proof/2.0.19"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

# The retained contract proves the historical promotion shape. These checks pin
# the live 2.0.19 authority so a future mechanical version rewrite cannot
# reintroduce a historical PR/SHA placeholder or an ambiguous freeze sentence.
rigdag = code_of(ROOT / "RIGDAG_SIMPEL.md")
staged = code_of(ROOT / "STAGED_PHYSICAL_PROMOTION.md")

_live_contracts = (
    ("7b2fe732" not in rigdag, "rig-day runbook contains no historical SHA placeholder"),
    (
        "freeze: candidate_freeze_check groen paa exact SHA" not in staged,
        "staged runbook contains no mechanically rewritten freeze placeholder",
    ),
    (
        "$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.19).Trim()" in rigdag
        and "$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.19).Trim()" in staged,
        "both operator runbooks resolve the fetched remote candidate SHA",
    ),
    (
        "if ($CandidateSha -ne $RemoteCandidateSha)" in rigdag
        and "if ($CandidateSha -ne $RemoteCandidateSha)" in staged,
        "both operator runbooks fail closed on local/remote candidate drift",
    ),
    (
        "python scripts/candidate_freeze_check.py --expected-sha $CandidateSha" in rigdag
        and "python scripts/candidate_freeze_check.py --expected-sha $CandidateSha" in staged,
        "both operator runbooks run the exact-SHA candidate freeze gate",
    ),
    (
        "origin/physical-proof/2.0.19" in rigdag
        and "origin/physical-proof/2.0.19" in staged,
        "both operator runbooks name the active remote candidate authority",
    ),
    # ChatGPT #2364 6727590513: Anders' D3 (#2275 6726564262) releases 2.0.19 on green RC CI plus
    # his release go. The physical procedure must not read as a prerequisite for the tag, and must
    # still keep production off and the release behind his go.
    (
        all(
            "v2.0.19: Anders' release-beslutning (D3" in doc
            and "**ikke** en forudsætning for tagget `v2.0.19`" in doc
            and "**efter** publicering" in doc
            and "Anders' særskilte release-go" in doc
            and "production_activation=false" in doc
            and doc.index("v2.0.19: Anders' release-beslutning (D3") < doc.index("## ")
            for doc in (rigdag, staged)
        ),
        "both operator runbooks state D3 before any procedure: physical validation after publication, release only on Anders' go",
    ),
)
for condition, message in _live_contracts:
    if not condition:
        raise SystemExit(f"live staged-promotion authority contract failed: {message}")


# Codex #2364 4508274860: under D3, #2364 lands on main as a merge commit and v2.0.19 is tagged on
# main. The release-prep head is then neither the tagged SHA nor a descendant of origin/main, so a
# Stage A procedure pinned to it stops in candidate_freeze_check before any physical evidence.
# The runbooks must check out the published RC SHA on the branch the Stage A operator and wizard
# require, bind it to the tag, and hold main still until the candidate gate is green.
import importlib.util as _importlib_util
import re as _re
import subprocess as _subprocess
import tempfile as _tempfile


def _block0(doc: str) -> str:
    start = doc.index("```powershell", doc.index("git fetch --force origin tag v2.0.19") - 200)
    return doc[start : doc.index("```", start + 3)]


def _const(path: str, name: str) -> str:
    match = _re.search(rf'^{name} = "([^"]+)"$', code_of(ROOT / path), _re.M)
    if match is None:
        raise SystemExit(f"{path} defines no {name}")
    return match.group(1)


_operator_branch = _const("scripts/stage_a_physical_operator.py", "EXPECTED_BRANCH")
_wizard_branch = _const("scripts/stage_a_one_click.py", "BRANCH")
_d3_contracts = [
    (
        _operator_branch == _wizard_branch == "physical-proof/2.0.19",
        "Stage A operator and wizard require the same physical-proof/2.0.19 checkout",
    ),
]
for _name, _doc in (("RIGDAG_SIMPEL.md", rigdag), ("STAGED_PHYSICAL_PROMOTION.md", staged)):
    _block = _block0(_doc)
    _d3_contracts += [
        (
            f"git switch {_operator_branch}" in _block
            and f"git pull --ff-only origin {_operator_branch}" in _block,
            f"{_name}: block 0 checks out the branch the Stage A operator requires",
        ),
        (
            "git switch release/" not in _doc and "git pull --ff-only origin release/" not in _doc,
            f"{_name}: the release-prep branch is never checked out as the candidate",
        ),
        (
            '$RcSha = (git rev-parse "v2.0.19^{commit}").Trim()' in _block
            and "if ($RcSha.Length -ne 40)" in _block
            and "if ($CandidateSha -ne $RcSha)" in _block
            and _block.index("if ($CandidateSha -ne $RcSha)")
            < _block.index("python scripts/candidate_freeze_check.py"),
            f"{_name}: block 0 binds the candidate to the published v2.0.19 tag before the freeze",
        ),
        (
            # Anders lifted the freeze window on 12 Nov 2026 (#2275 comment
            # 6816274261). The runbook must say so, and must still tell the
            # operator that a moved main stops the control and is not bypassed.
            "Freeze-vinduet er ophævet 12/11-2026" in _doc
            and "6816274261" in _doc
            and "Den må ikke omgås" in _doc
            and "merges intet til `main`" not in _doc,
            f"{_name}: records that the freeze window was lifted and that a moved main still stops the control",
        ),
        (
            "fast-forwardes til `main`" not in _doc and "må `main` fast-forwardes" not in _doc,
            f"{_name}: no step fast-forwards a branch to main",
        ),
    ]


def _git(repo: str, *args: str) -> str:
    out = _subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
        cwd=repo, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


_spec = _importlib_util.spec_from_file_location(
    "runbook_candidate_freeze", ROOT / "scripts" / "candidate_freeze_check.py"
)
_freeze = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_freeze)


def _contains_main(repo: str, candidate: str, main_sha: str) -> bool:
    try:
        _freeze._require_main_ancestor(Path(repo), candidate, main_sha)
    except _freeze.CandidateFreezeError:
        return False
    return True


with _tempfile.TemporaryDirectory() as _repo:
    _git(_repo, "init", "-q", "-b", "main")
    _git(_repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(_repo, "switch", "-q", "-c", "prep")
    _git(_repo, "commit", "-q", "--allow-empty", "-m", "bump 2.0.19")
    _git(_repo, "switch", "-q", "main")
    _git(_repo, "commit", "-q", "--allow-empty", "-m", "another PR lands")
    _git(_repo, "switch", "-q", "prep")
    _git(_repo, "merge", "-q", "--no-ff", "--no-edit", "main")
    _prep = _git(_repo, "rev-parse", "HEAD")
    _git(_repo, "switch", "-q", "main")
    _git(_repo, "merge", "-q", "--no-ff", "--no-edit", "prep")  # how GitHub merges #2364
    _rc = _git(_repo, "rev-parse", "HEAD")
    _git(_repo, "commit", "-q", "--allow-empty", "-m", "a merge after the tag")
    _moved = _git(_repo, "rev-parse", "HEAD")
    _d3_contracts += [
        (_prep != _rc, "the merged RC SHA differs from the release-prep head"),
        (
            not _contains_main(_repo, _prep, _rc),
            "the freeze gate refuses the release-prep head once #2364 has merged",
        ),
        (_contains_main(_repo, _rc, _rc), "the freeze gate accepts the RC SHA while main stands on it"),
        (
            not _contains_main(_repo, _rc, _moved),
            "the freeze gate refuses the RC SHA once main moves: main must stay still during Stage A",
        ),
    ]

for condition, message in _d3_contracts:
    if not condition:
        raise SystemExit(f"D3 Stage A authority contract failed: {message}")
    print(f"  PASS: {message}")

#!/usr/bin/env python3
"""Run the retained staged-promotion contract plus live 2.0.13 authority checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_source_path = Path(__file__).with_name("workflow_staged_promotion_runbook.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "physical-proof/2.0.13"),
    ("1.58.143", "2.0.13"),
    ("1.58.142", "2.0.12"),
    ("draft-PR #150", "origin/physical-proof/2.0.13"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

# The retained contract proves the historical promotion shape. These checks pin
# the live 2.0.13 authority so a future mechanical version rewrite cannot
# reintroduce a historical PR/SHA placeholder or an ambiguous freeze sentence.
rigdag = (ROOT / "RIGDAG_SIMPEL.md").read_text(encoding="utf-8")
staged = (ROOT / "STAGED_PHYSICAL_PROMOTION.md").read_text(encoding="utf-8")

_live_contracts = (
    ("7b2fe732" not in rigdag, "rig-day runbook contains no historical SHA placeholder"),
    (
        "freeze: candidate_freeze_check groen paa exact SHA" not in staged,
        "staged runbook contains no mechanically rewritten freeze placeholder",
    ),
    (
        "$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.13).Trim()" in rigdag
        and "$RemoteCandidateSha = (git rev-parse origin/physical-proof/2.0.13).Trim()" in staged,
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
        "origin/physical-proof/2.0.13" in rigdag
        and "origin/physical-proof/2.0.13" in staged,
        "both operator runbooks name the active remote candidate authority",
    ),
)
for condition, message in _live_contracts:
    if not condition:
        raise SystemExit(f"live staged-promotion authority contract failed: {message}")

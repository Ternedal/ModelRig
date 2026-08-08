#!/usr/bin/env python3
"""Run the retained Stage A one-click contract against candidate 1.58.151."""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_BRANCH = (_ROOT / "CANDIDATE_BRANCH").read_text(encoding="utf-8").strip()
_source_path = Path(__file__).with_name("workflow_stage_a_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", _BRANCH),
    ("1.58.143", "1.58.151"),
    ("1.58.142", "1.58.144"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

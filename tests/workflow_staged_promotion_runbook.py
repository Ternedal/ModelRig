#!/usr/bin/env python3
"""Run the retained staged-promotion contract for freeze PR #405 / 1.58.151."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_staged_promotion_runbook.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "agent/unified-candidate-1.58.151"),
    ("1.58.143", "1.58.151"),
    ("1.58.142", "1.58.150"),
    ("draft-PR #150", "freeze-PR #405"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

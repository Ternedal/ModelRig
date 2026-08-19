#!/usr/bin/env python3
"""Run the retained Stage A one-click contract against candidate 2.0.11."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_stage_a_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "physical-proof/2.0.11"),
    ("1.58.143", "2.0.11"),
    ("1.58.142", "2.0.10"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

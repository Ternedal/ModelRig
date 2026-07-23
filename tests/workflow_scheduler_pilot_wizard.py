#!/usr/bin/env python3
"""Run the retained scheduler pilot contract against candidate 1.58.145."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_scheduler_pilot_wizard.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "agent/unified-candidate-1.58.145"),
    ("1.58.143", "1.58.145"),
    ("1.58.142", "1.58.144"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

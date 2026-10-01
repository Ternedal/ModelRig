#!/usr/bin/env python3
"""Run the retained Stage A operator contract against candidate 2.0.14."""
from pathlib import Path

# Release-era wrapper: target 2.0.14; predecessor 2.0.13

_source_path = Path(__file__).with_name("workflow_stage_a_physical_operator.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "physical-proof/2.0.14"),
    ("1.58.143", "2.0.14"),
    ("1.58.142", "2.0.13"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

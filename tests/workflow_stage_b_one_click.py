#!/usr/bin/env python3
"""Run retained Stage B lifecycle, collector and resume contracts."""
from pathlib import Path

for _name in (
    "workflow_stage_b_one_click.retained",
    "workflow_stage_b_resume_invalidation.retained",
):
    _source_path = Path(__file__).with_name(_name)
    _source = _source_path.read_text(encoding="utf-8")
    exec(compile(_source, str(_source_path), "exec"), globals(), globals())

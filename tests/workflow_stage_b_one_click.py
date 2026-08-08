#!/usr/bin/env python3
"""Run the retained Stage B lifecycle, collector and strict-gate contracts."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_stage_b_one_click.retained")
_source = _source_path.read_text(encoding="utf-8")
exec(compile(_source, str(_source_path), "exec"), globals(), globals())

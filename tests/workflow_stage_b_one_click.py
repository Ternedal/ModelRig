#!/usr/bin/env python3
"""Run retained Stage B lifecycle, collector, resume and swap contracts."""
from pathlib import Path

for _name in (
    "workflow_stage_b_one_click.retained",
    "workflow_stage_b_resume_invalidation.retained",
    "workflow_stage_b_swap_binding.retained",
):
    _source_path = Path(__file__).with_name(_name)
    _source = _source_path.read_text(encoding="utf-8")
    if _name == "workflow_stage_b_one_click.retained":
        _source = _source.replace(
            '        "observed_swapped_count=1",\n        "updater_process_pid=4321",',
            '        "observed_swapped_count=1",\n        "observed_swapped_assets=modelrig-server-windows-x64.exe",\n        "updater_process_pid=4321",',
        )
        _source = _source.replace(
            '            "observed_swapped_count": 1,\n            "updater_process_pid": 4321,',
            '            "observed_swapped_count": 1,\n            "observed_swapped_assets": ["modelrig-server-windows-x64.exe"],\n            "updater_process_pid": 4321,',
        )
    exec(compile(_source, str(_source_path), "exec"), globals(), globals())

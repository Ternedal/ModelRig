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
    # Fixturerne i de retained filer er skrevet mod 1.58.149 -> 1.58.151.
    # Stage B-scripterne er pinnet til den aktuelle kandidat, saa fixturerne
    # bindes samme vej. Rækkefølgen er ligegyldig her: ingen af de tre
    # strenge er delstreng af hinanden.
    for _old, _new in (("1.58.149", "2.0.12"), ("1.58.151", "2.0.13"), ("1.58.148", "2.0.7")):
        _source = _source.replace(_old, _new)
    if _name == "workflow_stage_b_one_click.retained":
        # The current collector is a version-bound loader around the retained
        # strict implementation. Static source contracts must inspect both
        # halves; runtime behaviour is still exercised through STRICT_WIZARD.
        _collector_read = 'collector_source = STRICT_WIZARD.read_text(encoding="utf-8")'
        _collector_read_with_retained = (
            'collector_source = STRICT_WIZARD.read_text(encoding="utf-8") + "\\n" + '
            'STRICT_WIZARD.with_name("stage_b_one_click_v2.retained").read_text(encoding="utf-8")'
        )
        if _source.count(_collector_read) != 1:
            raise RuntimeError("Stage B collector source contract drifted")
        _source = _source.replace(_collector_read, _collector_read_with_retained)

        # #772 bound state and observations to the candidate SHA after this
        # retained contract was cut. Carry those mainline safety assertions
        # forward into the era adapter instead of silently dropping them.
        _flow_check = 'check(all(item in legacy_source for item in flow), "legacy engine still drives all five lifecycle trials")'
        _binding_checks = (
            'check("candidate_git_sha" in legacy_source, "state checkpoints are bound to the candidate git sha")\n'
            'check("_archive_stale_state" in legacy_source, "a stale state is archived, never trusted")\n'
            'check("Observationsfil fra anden kandidat" in legacy_source, "another era\'s observations are archived before fresh ones are built")\n'
            + _flow_check
        )
        if _source.count(_flow_check) != 1:
            raise RuntimeError("Stage B legacy state-binding contract drifted")
        _source = _source.replace(_flow_check, _binding_checks)

        _source = _source.replace(
            '        "observed_swapped_count=1",\n        "updater_process_pid=4321",',
            '        "observed_swapped_count=1",\n        "observed_swapped_assets=modelrig-server-windows-x64.exe",\n        "updater_process_pid=4321",',
        )
        _source = _source.replace(
            '            "observed_swapped_count": 1,\n            "updater_process_pid": 4321,',
            '            "observed_swapped_count": 1,\n            "observed_swapped_assets": ["modelrig-server-windows-x64.exe"],\n            "updater_process_pid": 4321,',
        )
    exec(compile(_source, str(_source_path), "exec"), globals(), globals())

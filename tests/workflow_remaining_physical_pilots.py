#!/usr/bin/env python3
"""Run the retained combined-pilots contract against candidate 1.58.145."""
from pathlib import Path

_source_path = Path(__file__).with_name("workflow_remaining_physical_pilots.retained")
_source = _source_path.read_text(encoding="utf-8")
for _old, _new in (
    ("agent/unified-candidate-1.58.143", "agent/unified-candidate-1.58.145"),
    ("1.58.143", "1.58.145"),
    ("1.58.142", "1.58.144"),
    ("#150", "#161"),
):
    _source = _source.replace(_old, _new)

_source = _source.replace(
    'SCHEDULER = ROOT / "scripts" / "scheduler_pilot_wizard.py"\nEXPECTED_BRANCH',
    'SCHEDULER = ROOT / "scripts" / "scheduler_pilot_wizard.py"\n'
    'GATE = ROOT / "scripts" / "physical_validation_candidate_gate.py"\n'
    'EXPECTED_BRANCH',
)
_source = _source.replace(
    'check(calls == [str(AGENT), str(SCHEDULER)], "both pilots run once in the safe order")',
    'check(\n'
    '    calls == [str(GATE), str(AGENT), str(SCHEDULER)],\n'
    '    "Stage A gate and both pilots run once in the safe order",\n'
    ')',
)

_old_failure_contract = '''calls.clear()


def fail_first(args, **kwargs):
    calls.append(str(args[1]))
    return SimpleNamespace(returncode=7)


module.subprocess.run = fail_first
try:
    check(module.main() == 7, "first pilot failure is propagated")
finally:
    module.subprocess.run = original_run
check(calls == [str(AGENT)], "scheduler is not started after Agent 3 failure")
'''
_new_failure_contract = '''calls.clear()


def fail_stage_a(args, **kwargs):
    calls.append(str(args[1]))
    return SimpleNamespace(returncode=7)


module.subprocess.run = fail_stage_a
try:
    check(module.main() == 7, "Stage A prerequisite failure is propagated")
finally:
    module.subprocess.run = original_run
check(calls == [str(GATE)], "no pilot starts after Stage A prerequisite failure")

calls.clear()


def fail_agent_after_gate(args, **kwargs):
    calls.append(str(args[1]))
    code = 0 if str(args[1]) == str(GATE) else 7
    return SimpleNamespace(returncode=code)


module.subprocess.run = fail_agent_after_gate
try:
    check(module.main() == 7, "Agent 3 failure is propagated after Stage A passes")
finally:
    module.subprocess.run = original_run
check(
    calls == [str(GATE), str(AGENT)],
    "scheduler is not started after Agent 3 failure",
)
'''
if _old_failure_contract not in _source:
    raise RuntimeError("retained remaining-pilots failure contract changed unexpectedly")
_source = _source.replace(_old_failure_contract, _new_failure_contract)

_source = _source.replace(
    'check("remaining_physical_pilots.py" in cmd, "root launcher invokes combined operator")',
    'check("remaining_physical_pilots.py" in cmd, "root launcher invokes combined operator")\n'
    'check("physical_validation_candidate_gate.py" in source, "authoritative Stage A gate is mandatory")\n'
    'check(\n'
    '    source.index("stage_a_code = run_stage_a_gate()")\n'
    '    < source.index("for label, path in PILOTS"),\n'
    '    "Stage A is verified before either remaining pilot",\n'
    ')',
)

exec(compile(_source, str(_source_path), "exec"), globals(), globals())

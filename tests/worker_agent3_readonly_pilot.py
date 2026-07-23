#!/usr/bin/env python3
"""Regression checks for scripts/agent3_readonly_pilot.py."""
from __future__ import annotations
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts' / 'agent3_readonly_pilot.py'
SPEC = importlib.util.spec_from_file_location('agent3_readonly_pilot', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

def receipt(plan_sha: str='b' * 64) -> dict[str, Any]:
    return {'schema': 'kaliv-agent3-capability-receipt/v1', 'allowed': True, 'production_activation': False, 'blockers': [], 'graph_sha256': 'a' * 64, 'plan_sha256': plan_sha}

def route() -> dict[str, Any]:
    return {'kind': 'rig_tools_local', 'uses_cloud': False, 'uses_rig': True, 'uses_tools': True, 'uses_rag': False}

def task() -> dict[str, Any]:
    return {'id': '01', 'category': 'rig/status', 'prompt': 'Vis status', 'expected': {'steps': [{'tool': 'rig_status', 'args': {}, 'risk': 'read'}], 'state': 'completed'}}

class SuccessfulTaskClient:
    base_url = 'http://test'

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []

    def request(self, method: str, path: str, payload=None) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path.endswith('/plan'):
            return {'route': route(), 'plan': [{'tool': 'rig_status', 'args': {}, 'risk': 'read'}], 'plan_id': 'plan-1', 'capability_receipt': receipt()}
        if path.endswith('/plans/plan-1/start'):
            return {'capability_receipt': receipt(), 'run': {'id': 'run-1', 'state': 'completed', 'route': route(), 'request': {'retry_of_run_id': None}, 'steps': [{'tool': 'rig_status', 'args': {}, 'risk': 'read', 'state': 'succeeded'}]}}
        if path.endswith('/capability-receipt'):
            return {'receipt': receipt()}
        if path.endswith('/events'):
            return {'events': [{'kind': 'run_created'}, {'kind': 'policy_decision'}, {'kind': 'step_started'}, {'kind': 'step_succeeded'}, {'kind': 'run_completed'}]}
        if path.endswith('/replans'):
            return {'replan_count': 0, 'revision': 0}
        if path.endswith('/answer-preview'):
            return {'answer': 'Riggen er klar.', 'limitations': [], 'executed': False, 'persisted': False, 'delivered_to_chat': False, 'context': {'target': 'local', 'sha256': 'c' * 64}, 'prompt_sha256': 'd' * 64}
        raise AssertionError((method, path, payload))

    def chat_probe(self, *, model: str, prompt: str) -> dict[str, Any]:
        raise AssertionError('not used')

class WritePlanClient(SuccessfulTaskClient):

    def request(self, method: str, path: str, payload=None) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path.endswith('/plan'):
            return {'route': route(), 'plan': [{'tool': 'note_append', 'args': {'text': 'must never run'}, 'risk': 'write'}], 'plan_id': 'danger', 'capability_receipt': receipt()}
        raise AssertionError('write plan must be rejected before any second request')

class StopClient:
    base_url = 'http://test'

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.chat_prompt: str | None = None

    def request(self, method: str, path: str, payload=None) -> dict[str, Any]:
        self.calls.append((method, path, payload))
        if path.endswith('/plan'):
            return {'route': route(), 'plan': [{'tool': 'rig_status', 'args': {}, 'risk': 'read'}, {'tool': 'list_models', 'args': {}, 'risk': 'read'}], 'plan_id': 'stop-plan', 'capability_receipt': receipt()}
        if path.endswith('/plans/stop-plan/start'):
            return {'run': {'id': 'stop-run', 'state': 'running', 'steps': [{'tool': 'rig_status', 'state': 'succeeded'}, {'tool': 'list_models', 'state': 'pending'}]}, 'read_review': {'enabled': True, 'waiting': True}}
        if path.endswith('/cancel'):
            return {'run': {'id': 'stop-run', 'state': 'cancelled', 'steps': [{'tool': 'rig_status', 'state': 'succeeded'}, {'tool': 'list_models', 'state': 'pending'}]}}
        if path.endswith('/events'):
            return {'events': [{'kind': 'run_created'}, {'kind': 'policy_decision'}, {'kind': 'step_started'}, {'kind': 'step_succeeded'}, {'kind': 'run_cancelled'}]}
        raise AssertionError((method, path, payload))

    def chat_probe(self, *, model: str, prompt: str) -> dict[str, Any]:
        self.chat_prompt = prompt
        return {'chunks': 2, 'done': True, 'answer_length': 12, 'answer_sha256': 'e' * 64}

def test_frozen_task_set_has_20_unique_read_only_cases() -> None:
    task_set = MODULE.load_task_set(ROOT / 'eval' / 'agent3_readonly_pilot_tasks.json')
    tasks = task_set['tasks']
    assert len(tasks) == 20
    assert len({item['id'] for item in tasks}) == 20
    assert all((step['risk'] == 'read' for item in tasks for step in item['expected']['steps']))
    tools = {step['tool'] for item in tasks for step in item['expected']['steps']}
    assert tools == {'rig_status', 'list_models', 'current_datetime', 'list_documents', 'job_status'}
    assert any((len(item['expected']['steps']) > 1 for item in tasks))

def test_run_task_binds_preview_execution_receipt_events_and_answer() -> None:
    client = SuccessfulTaskClient()
    result = MODULE.run_task(client, task(), planner_model='qwen3:14b', answer_model='qwen3:14b', poll_seconds=0.0, max_wait_seconds=1.0)
    assert result['success'] is True
    assert result['route'] == 'rig_tools_local'
    assert result['replan_count'] == 0
    assert result['retry_events'] == 0
    assert result['answer']['answer_length'] == len('Riggen er klar.')
    assert 'Riggen er klar.' not in json.dumps(result, ensure_ascii=False)
    paths = [path for _, path, _ in client.calls]
    assert paths == ['/api/v1/experimental/agent3/plan', '/api/v1/experimental/agent3/plans/plan-1/start', '/api/v1/experimental/agent3/runs/run-1/capability-receipt', '/api/v1/experimental/agent3/runs/run-1/events', '/api/v1/experimental/agent3/runs/run-1/replans', '/api/v1/experimental/agent3/runs/run-1/answer-preview']
    plan_payload = client.calls[0][2]
    assert plan_payload is not None
    assert plan_payload['cloud_ready'] is False
    assert plan_payload['rag'] is False
    assert plan_payload['proactive'] is False
    assert plan_payload['use_memory'] is False

def test_write_plan_is_rejected_before_start() -> None:
    client = WritePlanClient()
    try:
        MODULE.run_task(client, task(), planner_model='qwen3:14b', answer_model='qwen3:14b', poll_seconds=0.0, max_wait_seconds=1.0)
    except MODULE.PilotError as exc:
        assert "risk must be 'read'" in str(exc)
    else:
        raise AssertionError('write plan was accepted')
    assert len(client.calls) == 1

def test_stop_fallback_cancels_pending_read_and_reuses_exact_prompt() -> None:
    client = StopClient()
    result = MODULE.run_stop_fallback_probe(client, planner_model='qwen3:14b', fallback_model='qwen3:14b', poll_seconds=0.0, max_wait_seconds=1.0)
    assert result['success'] is True
    assert result['agent3_state'] == 'cancelled'
    assert result['completed_agent3_steps'] == 1
    assert result['pending_steps_after_stop'] == 1
    assert result['fallback_path'] == '/api/v1/chat'
    plan_prompt = client.calls[0][2]['message']
    assert client.chat_prompt == plan_prompt

def test_summary_counts_failures_replans_retries_and_error_types() -> None:
    summary = MODULE.summarize([{'category': 'read', 'success': True, 'replan_count': 2, 'retry_events': 1, 'latency_ms': {'preview': 10, 'execution': 20, 'total': 30}}, {'category': 'read', 'success': False, 'error_type': 'plan_contract'}])
    assert summary['tasks'] == 2
    assert summary['successes'] == 1
    assert summary['failures'] == 1
    assert summary['task_success_rate'] == 0.5
    assert summary['replans'] == 2
    assert summary['retry_events'] == 1
    assert summary['error_types'] == {'plan_contract': 1}
    assert summary['latency_ms']['total_p95'] == 30.0

def test_failure_report_hashes_error_without_storing_message() -> None:
    failed = MODULE._failure_result(task(), MODULE.PilotError('secret diagnostic detail'))
    assert failed['success'] is False
    assert failed['error_type'] == 'unknown'
    assert len(failed['error_sha256']) == 64
    assert 'secret diagnostic detail' not in json.dumps(failed)

class StatusOnlyClient:
    base_url = 'http://test'

    def request(self, method: str, path: str, payload=None) -> dict[str, Any]:
        assert (method, path) == ('GET', '/api/v1/experimental/agent3/status')
        return {'enabled': True, 'experimental': True, 'production_tools_path_untouched': True, 'production_activation': False, 'client_plan_route': False, 'replanner': 'explicit-pending-read-window', 'read_review': 'opt-in-persistent', 'worker_version': '1.2.3', 'code_sha256': 'f' * 64, 'planner': 'server-authored-plan-token', 'rig_validation': {'eligible_for_developer_preview': True, 'version_match': True, 'code_match': True}}

    def chat_probe(self, *, model: str, prompt: str) -> dict[str, Any]:
        raise AssertionError('not used')

def test_run_pilot_continues_after_one_task_failure_and_binds_candidate() -> None:
    task_set = MODULE.load_task_set(ROOT / 'eval' / 'agent3_readonly_pilot_tasks.json')
    original_task = MODULE.run_task
    original_stop = MODULE.run_stop_fallback_probe
    calls = {'count': 0}

    def fake_task(_client, item, **_kwargs):
        calls['count'] += 1
        if item['id'] == '07':
            raise MODULE.PilotError('planner plan mismatch')
        return {'task_id': item['id'], 'category': item['category'], 'success': True, 'replan_count': 0, 'retry_events': 0, 'latency_ms': {'preview': 1, 'execution': 2, 'total': 3}}

    def fake_stop(_client, **_kwargs):
        return {'success': True, 'agent3_state': 'cancelled', 'fallback_path': '/api/v1/chat'}
    MODULE.run_task = fake_task
    MODULE.run_stop_fallback_probe = fake_stop
    try:
        report = MODULE.run_pilot(StatusOnlyClient(), task_set, planner_model='qwen3:14b', answer_model='qwen3:14b', fallback_model='qwen3:14b', candidate={'version': '1.2.3', 'git_sha': '1' * 40, 'code_sha256': 'f' * 64})
    finally:
        MODULE.run_task = original_task
        MODULE.run_stop_fallback_probe = original_stop
    assert calls['count'] == 20
    assert report['success'] is False
    assert report['summary']['successes'] == 19
    assert report['summary']['failures'] == 1
    assert report['summary']['error_types'] == {'plan_contract': 1}
    assert report['candidate']['git_sha'] == '1' * 40
    failed = [item for item in report['results'] if not item['success']]
    assert len(failed) == 1
    assert 'planner plan mismatch' not in json.dumps(failed)

def test_atomic_report_writer_emits_valid_json() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / 'nested' / 'report.json'
        MODULE._write_json_atomic(path, {'schema': MODULE.SCHEMA, 'success': True})
        assert json.loads(path.read_text(encoding='utf-8')) == {'schema': MODULE.SCHEMA, 'success': True}
        assert not list(path.parent.glob('*.tmp'))
TESTS = [value for name, value in sorted(globals().items()) if name.startswith('test_')]
if __name__ == '__main__':
    for test_case in TESTS:
        test_case()
    print(f'agent3 read-only pilot: {len(TESTS)} passed')

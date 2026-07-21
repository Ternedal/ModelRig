#!/usr/bin/env python3
"""Run the bounded read-only Agent 3 developer pilot (T-020).

The pilot uses only the authenticated public Go backend. It freezes 20 Danish
read-only tasks, validates the server-authored plan before consuming it, starts
the plan, follows the durable run/events/capability receipt, asks the local
outcome-answer endpoint for a non-persisted final answer and writes one atomic
redacted report.

A separate stop/fallback probe starts a two-read plan with read review enabled,
cancels while the second read is still pending, then sends the exact same user
turn through the normal `/api/v1/chat` path. This proves that Agent 3 remains an
experimental side path and that the user turn can be continued through Agent 2
without a write or production-routing change.

The script never confirms a write, retries a run, applies a replan or changes
normal chat routing. Full tool results, request bodies, tokens and raw answers
are not stored in the report; only digests, lengths and typed outcomes are kept.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import importlib.util
import os
import platform
import socket
import statistics
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
SCHEMA = 'kaliv-agent3-readonly-pilot/v1'
TASK_SET_SCHEMA = 'kaliv-agent3-readonly-pilot-task-set/v1'
DEFAULT_TASK_SET = Path(__file__).resolve().parents[1] / 'eval' / 'agent3_readonly_pilot_tasks.json'
DEFAULT_REPORT = Path('validation/agent3-readonly-pilot-latest.json')
REPO_ROOT = Path(__file__).resolve().parents[1]
TERMINAL_STATES = {'completed', 'failed', 'cancelled', 'blocked'}
MAX_HTTP_BYTES = 2 * 1024 * 1024
_REQUIRED_EVENTS = ('run_created', 'policy_decision', 'step_started', 'step_succeeded', 'run_completed')
_FORBIDDEN_EVENTS = {'confirmation_required', 'confirmation_approved', 'confirmation_denied', 'step_completed_after_cancel'}

class PilotError(RuntimeError):
    """The pilot cannot produce trustworthy evidence."""

def _run(root: Path, *args: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (127, str(exc))
    return (proc.returncode, (proc.stdout or proc.stderr or '').strip())

def _source_code_fingerprint(root: Path) -> str:
    path = root / 'worker' / 'app' / 'build_identity.py'
    spec = importlib.util.spec_from_file_location('pilot_build_identity', path)
    if spec is None or spec.loader is None:
        raise PilotError('worker build identity module cannot be loaded')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    value = module.code_fingerprint()
    if not isinstance(value, str) or len(value) != 64:
        raise PilotError('worker source fingerprint is malformed')
    return value

def source_candidate(root: Path=REPO_ROOT) -> dict[str, str]:
    try:
        version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    except OSError as exc:
        raise PilotError('VERSION cannot be read') from exc
    rc, git_sha = _run(root, 'git', 'rev-parse', 'HEAD')
    if not version or rc != 0 or len(git_sha) != 40:
        raise PilotError('source candidate identity is incomplete')
    try:
        int(git_sha, 16)
    except ValueError as exc:
        raise PilotError('source candidate git SHA is malformed') from exc
    _, dirty = _run(root, 'git', 'status', '--porcelain')
    if dirty:
        raise PilotError('working tree must be clean while collecting pilot evidence')
    return {'version': version, 'git_sha': git_sha.lower(), 'code_sha256': _source_code_fingerprint(root)}

class Requester(Protocol):

    def request(self, method: str, path: str, payload: dict[str, Any] | None=None) -> dict[str, Any]:
        ...

    def chat_probe(self, *, model: str, prompt: str) -> dict[str, Any]:
        ...

@dataclass(frozen=True)
class Client:
    base_url: str
    token: str
    timeout: float = 300.0

    def _request(self, method: str, path: str, payload: dict[str, Any] | None=None) -> urllib.response.addinfourl:
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request_id = f'agent3-readonly-pilot-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}'
        req = urllib.request.Request(self.base_url.rstrip('/') + path, data=body, method=method, headers={'Authorization': f'Bearer {self.token}', 'Accept': 'application/json', 'Content-Type': 'application/json', 'X-Request-ID': request_id})
        try:
            return urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read(2048).decode('utf-8', errors='replace')
            try:
                parsed = json.loads(raw)
                detail = parsed.get('detail') or parsed.get('error') or 'request refused'
            except json.JSONDecodeError:
                detail = 'non-JSON error response'
            raise PilotError(f'{method} {path} returned HTTP {exc.code}: {detail}') from exc
        except urllib.error.URLError as exc:
            raise PilotError(f'cannot reach {self.base_url}: {exc.reason}') from exc

    def request(self, method: str, path: str, payload: dict[str, Any] | None=None) -> dict[str, Any]:
        with self._request(method, path, payload) as response:
            raw = response.read(MAX_HTTP_BYTES + 1)
        if len(raw) > MAX_HTTP_BYTES:
            raise PilotError(f'{method} {path} response exceeded {MAX_HTTP_BYTES} bytes')
        try:
            data = json.loads(raw.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PilotError(f'{method} {path} returned invalid JSON') from exc
        if not isinstance(data, dict):
            raise PilotError(f'{method} {path} returned a non-object JSON response')
        return data

    def chat_probe(self, *, model: str, prompt: str) -> dict[str, Any]:
        payload = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'stream': True}
        with self._request('POST', '/api/v1/chat', payload) as response:
            raw = response.read(MAX_HTTP_BYTES + 1)
        if len(raw) > MAX_HTTP_BYTES:
            raise PilotError('normal chat fallback response exceeded the byte limit')
        text = raw.decode('utf-8', errors='strict')
        chunks: list[dict[str, Any]] = []
        content_parts: list[str] = []
        done = False
        for line_no, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise PilotError(f'normal chat fallback returned invalid NDJSON on line {line_no}') from exc
            if not isinstance(item, dict):
                raise PilotError('normal chat fallback returned a non-object NDJSON chunk')
            chunks.append(item)
            message = item.get('message')
            if isinstance(message, dict) and isinstance(message.get('content'), str):
                content_parts.append(message['content'])
            done = done or item.get('done') is True
        answer = ''.join(content_parts).strip()
        if not chunks or not answer:
            raise PilotError('normal chat fallback returned no answer content')
        return {'chunks': len(chunks), 'done': done, 'answer_length': len(answer), 'answer_sha256': hashlib.sha256(answer.encode('utf-8')).hexdigest()}

def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()

def _require_text(parent: dict[str, Any], key: str, *, where: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PilotError(f'{where} is missing non-empty string {key!r}')
    return value.strip()

def _normalize_step(value: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PilotError(f'{where} must be an object')
    tool = _require_text(value, 'tool', where=where)
    args = value.get('args', {})
    if not isinstance(args, dict):
        raise PilotError(f'{where}.args must be an object')
    risk = value.get('risk', 'read')
    if risk != 'read':
        raise PilotError(f"{where}.risk must be 'read', got {risk!r}")
    return {'tool': tool, 'args': args, 'risk': 'read'}

def load_task_set(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError as exc:
        raise PilotError(f'task set does not exist: {path}') from exc
    except json.JSONDecodeError as exc:
        raise PilotError(f'task set is invalid JSON: {path}: {exc}') from exc
    if not isinstance(raw, dict) or raw.get('schema') != TASK_SET_SCHEMA:
        raise PilotError(f'task set must use schema {TASK_SET_SCHEMA!r}')
    tasks = raw.get('tasks')
    if not isinstance(tasks, list) or len(tasks) != 20:
        raise PilotError('read-only pilot task set must contain exactly 20 tasks')
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(tasks):
        where = f'tasks[{index}]'
        if not isinstance(item, dict):
            raise PilotError(f'{where} must be an object')
        task_id = _require_text(item, 'id', where=where)
        if task_id in seen:
            raise PilotError(f'duplicate task id {task_id!r}')
        seen.add(task_id)
        prompt = _require_text(item, 'prompt', where=where)
        category = _require_text(item, 'category', where=where)
        expected = item.get('expected')
        if not isinstance(expected, dict):
            raise PilotError(f'{where}.expected must be an object')
        steps = expected.get('steps')
        if not isinstance(steps, list) or not steps:
            raise PilotError(f'{where}.expected.steps must be a non-empty array')
        if len(steps) > 12:
            raise PilotError(f"{where}.expected.steps exceeds Agent 3's 12-step limit")
        normalized_steps = [_normalize_step(step, where=f'{where}.expected.steps[{step_index}]') for step_index, step in enumerate(steps)]
        normalized.append({'id': task_id, 'prompt': prompt, 'category': category, 'expected': {'steps': normalized_steps, 'state': 'completed'}})
    return {'schema': TASK_SET_SCHEMA, 'name': str(raw.get('name') or path.stem), 'version': str(raw.get('version') or 'unversioned'), 'tasks': normalized}

def _actual_plan(response: dict[str, Any]) -> list[dict[str, Any]]:
    raw = response.get('plan')
    if not isinstance(raw, list) or not raw:
        raise PilotError('planner response is missing a non-empty plan')
    return [_normalize_step(item, where=f'planner.plan[{index}]') for index, item in enumerate(raw)]

def _require_receipt(value: Any, *, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PilotError(f'{where} is missing capability_receipt')
    if value.get('schema') != 'kaliv-agent3-capability-receipt/v1':
        raise PilotError(f'{where} has an unsupported capability receipt schema')
    if value.get('allowed') is not True:
        raise PilotError(f'{where} capability receipt is not allowed')
    if value.get('production_activation') is not False:
        raise PilotError(f'{where} capability receipt would activate production')
    blockers = value.get('blockers')
    if blockers != []:
        raise PilotError(f'{where} capability receipt has blockers: {blockers}')
    for key in ('graph_sha256', 'plan_sha256'):
        digest = value.get(key)
        if not isinstance(digest, str) or len(digest) != 64:
            raise PilotError(f'{where} capability receipt has invalid {key}')
    return value

def _require_route(response: dict[str, Any], *, where: str) -> dict[str, Any]:
    route = response.get('route')
    if not isinstance(route, dict):
        raise PilotError(f'{where} is missing route')
    expected = {'kind': 'rig_tools_local', 'uses_cloud': False, 'uses_rig': True, 'uses_tools': True, 'uses_rag': False}
    for key, value in expected.items():
        if route.get(key) != value:
            raise PilotError(f'{where} route {key} must be {value!r}, got {route.get(key)!r}')
    return route

def _require_run(response: dict[str, Any], *, where: str) -> dict[str, Any]:
    run = response.get('run')
    if not isinstance(run, dict):
        raise PilotError(f'{where} is missing run')
    run_id = run.get('id')
    if not isinstance(run_id, str) or not run_id:
        raise PilotError(f'{where} run has no id')
    return run

def _quoted(value: str) -> str:
    return urllib.parse.quote(value, safe='')

def _poll_run(client: Requester, run: dict[str, Any], *, max_wait_seconds: float, poll_seconds: float) -> dict[str, Any]:
    run_id = _require_text(run, 'id', where='run')
    deadline = time.monotonic() + max_wait_seconds
    current = run
    while current.get('state') not in TERMINAL_STATES:
        if current.get('state') == 'waiting_confirmation':
            raise PilotError(f'read-only run {run_id} requested write confirmation')
        if time.monotonic() >= deadline:
            raise PilotError(f'run {run_id} did not reach a terminal state')
        time.sleep(max(0.05, poll_seconds))
        current = _require_run(client.request('GET', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}'), where='run poll')
    return current

def _event_payload(client: Requester, run_id: str) -> tuple[list[str], list[dict[str, Any]]]:
    response = client.request('GET', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}/events')
    raw = response.get('events')
    if not isinstance(raw, list):
        raise PilotError(f'run {run_id} event response is missing events')
    events = [item for item in raw if isinstance(item, dict)]
    kinds = [item['kind'] for item in events if isinstance(item.get('kind'), str)]
    return (kinds, events)

def _require_ordered_events(kinds: list[str], *, expected_steps: int) -> None:
    cursor = 0
    for required in _REQUIRED_EVENTS:
        try:
            cursor = kinds.index(required, cursor) + 1
        except ValueError as exc:
            raise PilotError(f'event stream is missing ordered event {required!r}: {kinds}') from exc
    forbidden = sorted(set(kinds).intersection(_FORBIDDEN_EVENTS))
    if forbidden:
        raise PilotError('read-only event stream contains forbidden events: ' + ', '.join(forbidden))
    for kind in ('step_started', 'step_succeeded'):
        actual = sum((1 for value in kinds if value == kind))
        if actual != expected_steps:
            raise PilotError(f'event stream has {actual} {kind} events for {expected_steps} reviewed steps')

def _validate_completed_run(run: dict[str, Any], expected_steps: list[dict[str, Any]]) -> None:
    if run.get('state') != 'completed':
        raise PilotError(f"read-only run ended in {run.get('state')!r}: {run.get('error')}")
    route = run.get('route')
    if not isinstance(route, dict) or route.get('kind') != 'rig_tools_local':
        raise PilotError('completed run did not preserve the local rig-tools route')
    request = run.get('request')
    if not isinstance(request, dict) or request.get('retry_of_run_id') is not None:
        raise PilotError('primary pilot run unexpectedly became a retry')
    steps = run.get('steps')
    if not isinstance(steps, list) or len(steps) != len(expected_steps):
        raise PilotError('completed run step count differs from the reviewed plan')
    for index, (step, expected) in enumerate(zip(steps, expected_steps)):
        if not isinstance(step, dict):
            raise PilotError(f'run.steps[{index}] is not an object')
        if step.get('tool') != expected['tool'] or step.get('args') != expected['args']:
            raise PilotError(f'run.steps[{index}] differs from the reviewed plan')
        if step.get('risk') != 'read':
            raise PilotError(f'run.steps[{index}] is not read-only')
        if step.get('state') != 'succeeded':
            raise PilotError(f"run.steps[{index}] did not succeed: {step.get('state')!r}")

def _answer_preview(client: Requester, run_id: str, *, answer_model: str) -> dict[str, Any]:
    response = client.request('POST', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}/answer-preview', {'answer_model': answer_model})
    answer = response.get('answer')
    if not isinstance(answer, str) or not answer.strip():
        raise PilotError(f'run {run_id} answer-preview returned no answer')
    if response.get('executed') is not False or response.get('persisted') is not False:
        raise PilotError('answer-preview mutated execution state')
    if response.get('delivered_to_chat') is not False:
        raise PilotError('answer-preview falsely claims delivery to normal chat')
    context = response.get('context')
    if not isinstance(context, dict) or context.get('target') != 'local':
        raise PilotError('answer-preview did not remain local')
    return {'answer_length': len(answer.strip()), 'answer_sha256': hashlib.sha256(answer.strip().encode('utf-8')).hexdigest(), 'limitations_count': len(response.get('limitations') or []), 'context_sha256': context.get('sha256'), 'prompt_sha256': response.get('prompt_sha256')}

def _replan_summary(client: Requester, run_id: str) -> dict[str, Any]:
    response = client.request('GET', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}/replans')
    count = response.get('replan_count')
    revision = response.get('revision')
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PilotError(f'run {run_id} has invalid replan_count')
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise PilotError(f'run {run_id} has invalid replan revision')
    return {'replan_count': count, 'revision': revision}

def run_task(client: Requester, task: dict[str, Any], *, planner_model: str, answer_model: str, poll_seconds: float, max_wait_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    prompt = task['prompt']
    expected_steps = task['expected']['steps']
    payload = {'message': prompt, 'mode': 'rig', 'rag': False, 'allow_rag_cloud': False, 'allow_private_cloud': False, 'cloud_ready': False, 'proactive': False, 'review_reads': False, 'use_memory': False, 'planner_model': planner_model, 'conversation_id': f"agent3-readonly-pilot-{task['id']}-{uuid.uuid4().hex[:12]}"}
    preview_started = time.perf_counter()
    preview = client.request('POST', '/api/v1/experimental/agent3/plan', payload)
    preview_ms = (time.perf_counter() - preview_started) * 1000
    _require_route(preview, where='plan preview')
    actual_steps = _actual_plan(preview)
    if actual_steps != expected_steps:
        raise PilotError(f"task {task['id']} plan mismatch: expected {expected_steps!r}, got {actual_steps!r}")
    preview_receipt = _require_receipt(preview.get('capability_receipt'), where='plan preview')
    plan_id = preview.get('plan_id')
    if not isinstance(plan_id, str) or not plan_id:
        raise PilotError(f"task {task['id']} preview returned no plan_id")
    execution_started = time.perf_counter()
    started_response = client.request('POST', f'/api/v1/experimental/agent3/plans/{_quoted(plan_id)}/start', {})
    start_receipt = _require_receipt(started_response.get('capability_receipt'), where='plan start')
    if start_receipt != preview_receipt:
        raise PilotError('capability receipt changed between preview and start')
    run = _poll_run(client, _require_run(started_response, where='plan start'), max_wait_seconds=max_wait_seconds, poll_seconds=poll_seconds)
    execution_ms = (time.perf_counter() - execution_started) * 1000
    _validate_completed_run(run, expected_steps)
    run_id = _require_text(run, 'id', where='completed run')
    receipt_response = client.request('GET', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}/capability-receipt')
    durable_receipt = _require_receipt(receipt_response.get('receipt'), where='durable capability receipt')
    if durable_receipt['plan_sha256'] != preview_receipt['plan_sha256']:
        raise PilotError('durable capability receipt is not bound to the reviewed plan')
    kinds, events = _event_payload(client, run_id)
    _require_ordered_events(kinds, expected_steps=len(expected_steps))
    replans = _replan_summary(client, run_id)
    answer = _answer_preview(client, run_id, answer_model=answer_model)
    retry_events = sum((1 for kind in kinds if 'retry' in kind))
    return {'task_id': task['id'], 'category': task['category'], 'success': True, 'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(), 'expected_plan_sha256': _sha256_json(expected_steps), 'plan_sha256': preview_receipt['plan_sha256'], 'run_id': run_id, 'route': 'rig_tools_local', 'steps': len(expected_steps), 'event_count': len(events), 'event_kinds': kinds, 'replan_count': replans['replan_count'], 'replan_revision': replans['revision'], 'retry_events': retry_events, 'latency_ms': {'preview': round(preview_ms, 3), 'execution': round(execution_ms, 3), 'total': round((time.perf_counter() - started) * 1000, 3)}, 'answer': answer}

def run_stop_fallback_probe(client: Requester, *, planner_model: str, fallback_model: str, poll_seconds: float, max_wait_seconds: float) -> dict[str, Any]:
    prompt = 'Hent først rig_status og derefter list_models som to read-only tool-steps. Besvar derefter min samme forespørgsel kort.'
    preview = client.request('POST', '/api/v1/experimental/agent3/plan', {'message': prompt, 'mode': 'rig', 'rag': False, 'allow_rag_cloud': False, 'allow_private_cloud': False, 'cloud_ready': False, 'proactive': False, 'review_reads': True, 'use_memory': False, 'planner_model': planner_model, 'conversation_id': f'agent3-stop-fallback-{uuid.uuid4().hex[:12]}'})
    _require_route(preview, where='stop probe preview')
    expected = [{'tool': 'rig_status', 'args': {}, 'risk': 'read'}, {'tool': 'list_models', 'args': {}, 'risk': 'read'}]
    if _actual_plan(preview) != expected:
        raise PilotError('stop/fallback probe planner did not preserve the two-read plan')
    _require_receipt(preview.get('capability_receipt'), where='stop probe preview')
    plan_id = _require_text(preview, 'plan_id', where='stop probe preview')
    started = client.request('POST', f'/api/v1/experimental/agent3/plans/{_quoted(plan_id)}/start', {})
    run = _require_run(started, where='stop probe start')
    run_id = _require_text(run, 'id', where='stop probe run')
    review = started.get('read_review')
    deadline = time.monotonic() + max_wait_seconds
    while not (isinstance(review, dict) and review.get('waiting') is True):
        if run.get('state') in TERMINAL_STATES:
            raise PilotError('stop probe completed before reaching the read-review checkpoint')
        if time.monotonic() >= deadline:
            raise PilotError('stop probe did not reach the read-review checkpoint')
        time.sleep(max(0.05, poll_seconds))
        loaded = client.request('GET', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}')
        run = _require_run(loaded, where='stop probe poll')
        review = loaded.get('read_review')
    steps = run.get('steps')
    if not isinstance(steps, list) or len(steps) != 2 or (not isinstance(steps[0], dict)) or (not isinstance(steps[1], dict)) or (steps[0].get('state') != 'succeeded') or (steps[1].get('state') != 'pending'):
        raise PilotError('stop probe checkpoint does not have one completed and one pending read')
    cancelled = client.request('POST', f'/api/v1/experimental/agent3/runs/{_quoted(run_id)}/cancel', {'reason': 'T-020 stop/fallback probe'})
    final_run = _require_run(cancelled, where='stop probe cancel')
    if final_run.get('state') != 'cancelled':
        raise PilotError('stop probe did not cancel')
    final_steps = final_run.get('steps')
    if not isinstance(final_steps, list) or len(final_steps) != 2 or (not isinstance(final_steps[1], dict)) or (final_steps[1].get('state') not in {'pending', 'blocked'}):
        raise PilotError("stop probe's pending read executed after cancellation")
    kinds, _events = _event_payload(client, run_id)
    if sum((1 for kind in kinds if kind == 'step_started')) != 1:
        raise PilotError('stop probe executed an unexpected number of read steps')
    fallback_started = time.perf_counter()
    fallback = client.chat_probe(model=fallback_model, prompt=prompt)
    fallback_ms = (time.perf_counter() - fallback_started) * 1000
    return {'success': True, 'run_id': run_id, 'prompt_sha256': hashlib.sha256(prompt.encode('utf-8')).hexdigest(), 'agent3_state': final_run.get('state'), 'completed_agent3_steps': 1, 'pending_steps_after_stop': 1, 'event_kinds': kinds, 'fallback_path': '/api/v1/chat', 'fallback_model': fallback_model, 'fallback_latency_ms': round(fallback_ms, 3), 'fallback': fallback}

def _error_type(message: str) -> str:
    value = message.lower()
    if 'did not reach' in value or 'timeout' in value or 'timed out' in value:
        return 'timeout'
    if 'cannot reach' in value or 'returned http' in value or 'invalid json' in value or ('byte limit' in value):
        return 'transport'
    if 'answer-preview' in value or 'answer preview' in value:
        return 'answer'
    if 'plan' in value or 'preview' in value or 'route' in value or ('capability receipt' in value):
        return 'plan_contract'
    if 'event' in value or 'run' in value or 'step' in value or ('execution' in value):
        return 'execution'
    return 'unknown'

def _failure_result(task: dict[str, Any], exc: PilotError) -> dict[str, Any]:
    message = str(exc)
    return {'task_id': task['id'], 'category': task['category'], 'success': False, 'prompt_sha256': hashlib.sha256(task['prompt'].encode('utf-8')).hexdigest(), 'error_type': _error_type(message), 'error_sha256': hashlib.sha256(message.encode('utf-8')).hexdigest()}

def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)

def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    successful = [item for item in results if item.get('success') is True]
    totals = [float(item['latency_ms']['total']) for item in successful]
    previews = [float(item['latency_ms']['preview']) for item in successful]
    executions = [float(item['latency_ms']['execution']) for item in successful]
    categories: dict[str, dict[str, int]] = {}
    for item in results:
        bucket = categories.setdefault(item['category'], {'tasks': 0, 'successes': 0})
        bucket['tasks'] += 1
        if item.get('success') is True:
            bucket['successes'] += 1
    error_types: dict[str, int] = {}
    for item in results:
        if item.get('success') is not True:
            key = str(item.get('error_type') or 'unknown')
            error_types[key] = error_types.get(key, 0) + 1
    return {'tasks': len(results), 'successes': len(successful), 'failures': len(results) - len(successful), 'task_success_rate': round(len(successful) / max(1, len(results)), 6), 'replans': sum((int(item.get('replan_count', 0)) for item in successful)), 'retry_events': sum((int(item.get('retry_events', 0)) for item in successful)), 'error_types': error_types, 'latency_ms': {'total_mean': round(statistics.fmean(totals), 3) if totals else None, 'total_p50': _percentile(totals, 0.5), 'total_p95': _percentile(totals, 0.95), 'preview_p50': _percentile(previews, 0.5), 'execution_p50': _percentile(executions, 0.5)}, 'categories': categories}

def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix=path.name + '.', suffix='.tmp', delete=False) as handle:
        handle.write(payload)
        temp = Path(handle.name)
    temp.replace(path)

def run_pilot(client: Requester, task_set: dict[str, Any], *, planner_model: str, answer_model: str, fallback_model: str, poll_seconds: float=0.5, max_wait_seconds: float=120.0, candidate: dict[str, str] | None=None) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    source = source_candidate() if candidate is None else dict(candidate)
    status = client.request('GET', '/api/v1/experimental/agent3/status')
    required_status = {'enabled': True, 'experimental': True, 'production_tools_path_untouched': True, 'production_activation': False, 'client_plan_route': False}
    for key, value in required_status.items():
        if status.get(key) != value:
            raise PilotError(f'Agent 3 status {key} must be {value!r}, got {status.get(key)!r}')
    if status.get('replanner') == 'disabled':
        raise PilotError('Agent 3 replanner must be mounted for pilot evidence')
    if status.get('read_review') == 'disabled':
        raise PilotError('Agent 3 read review must be mounted for stop/fallback evidence')
    if status.get('worker_version') != source.get('version'):
        raise PilotError('running worker version does not match the clean source candidate')
    if status.get('code_sha256') != source.get('code_sha256'):
        raise PilotError('running worker code identity does not match the clean source candidate')
    rig_validation = status.get('rig_validation')
    if not isinstance(rig_validation, dict):
        raise PilotError('Agent 3 status is missing rig-validation assessment')
    if rig_validation.get('eligible_for_developer_preview') is not True:
        raise PilotError('current rig validation is not eligible for the developer preview')
    if rig_validation.get('version_match') is not True or rig_validation.get('code_match') is not True:
        raise PilotError('rig validation is not bound to the running candidate')
    results: list[dict[str, Any]] = []
    for task in task_set['tasks']:
        try:
            result = run_task(client, task, planner_model=planner_model, answer_model=answer_model, poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds)
        except PilotError as exc:
            result = _failure_result(task, exc)
        results.append(result)
    try:
        stop_fallback = run_stop_fallback_probe(client, planner_model=planner_model, fallback_model=fallback_model, poll_seconds=poll_seconds, max_wait_seconds=max_wait_seconds)
    except PilotError as exc:
        message = str(exc)
        stop_fallback = {'success': False, 'error_type': _error_type(message), 'error_sha256': hashlib.sha256(message.encode('utf-8')).hexdigest()}
    summary = summarize(results)
    report = {'schema': SCHEMA, 'started_at': started_at.isoformat(), 'finished_at': datetime.now(timezone.utc).isoformat(), 'success': summary['tasks'] == 20 and summary['successes'] == 20 and (stop_fallback['success'] is True), 'host': {'hostname': socket.gethostname(), 'platform': platform.platform(), 'python': platform.python_version()}, 'candidate': source, 'target': {'base_url': getattr(client, 'base_url', None), 'planner_model': planner_model, 'answer_model': answer_model, 'fallback_model': fallback_model, 'execution_mode': 'experimental-read-only', 'production_activation': False}, 'backend': {'worker_version': status.get('worker_version'), 'code_sha256': status.get('code_sha256'), 'rig_validation': status.get('rig_validation'), 'planner': status.get('planner'), 'replanner': status.get('replanner'), 'read_review': status.get('read_review'), 'production_tools_path_untouched': status.get('production_tools_path_untouched'), 'production_activation': status.get('production_activation')}, 'task_set': {'schema': task_set['schema'], 'name': task_set['name'], 'version': task_set['version'], 'task_count': len(task_set['tasks']), 'sha256': _sha256_json(task_set)}, 'summary': summary, 'stop_fallback': stop_fallback, 'results': results}
    return report

def _print_summary(report: dict[str, Any]) -> None:
    summary = report['summary']
    latency = summary['latency_ms']
    print()
    print('  Agent 3 read-only developer pilot')
    print('  ' + '-' * 56)
    print(f"  task success: {summary['successes']}/{summary['tasks']} ({summary['task_success_rate']:.1%})")
    print(f"  latency ms: p50={latency['total_p50']} p95={latency['total_p95']} mean={latency['total_mean']}")
    print(f"  replans: {summary['replans']} · retry events: {summary['retry_events']}")
    stop = report['stop_fallback']
    if stop.get('success') is True:
        print(f"  stop/fallback: {stop['agent3_state']} -> {stop['fallback_path']}")
    else:
        print(f"  stop/fallback: FAILED ({stop.get('error_type', 'unknown')})")

def main(argv: list[str] | None=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', default=os.getenv('MODELRIG_BASE_URL', 'http://127.0.0.1:8080'))
    parser.add_argument('--planner-model', default=os.getenv('KALIV_AGENT3_PLANNER_MODEL', 'qwen3:14b'))
    parser.add_argument('--answer-model', default=os.getenv('KALIV_AGENT3_ANSWER_MODEL') or None)
    parser.add_argument('--fallback-model', default=os.getenv('KALIV_FALLBACK_MODEL') or None)
    parser.add_argument('--task-set', type=Path, default=DEFAULT_TASK_SET)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--timeout', type=float, default=300.0)
    parser.add_argument('--poll-seconds', type=float, default=0.5)
    parser.add_argument('--max-wait-seconds', type=float, default=120.0)
    args = parser.parse_args(argv)
    token = os.getenv('MODELRIG_TOKEN', '').strip()
    if not token:
        parser.error('MODELRIG_TOKEN is required; keep it in the environment')
    if not args.planner_model.strip():
        parser.error('--planner-model must not be blank')
    answer_model = (args.answer_model or args.planner_model).strip()
    fallback_model = (args.fallback_model or args.planner_model).strip()
    if not answer_model or not fallback_model:
        parser.error('answer and fallback models must not be blank')
    try:
        task_set = load_task_set(args.task_set)
        report = run_pilot(Client(args.base_url, token, timeout=args.timeout), task_set, planner_model=args.planner_model.strip(), answer_model=answer_model, fallback_model=fallback_model, poll_seconds=args.poll_seconds, max_wait_seconds=args.max_wait_seconds)
        _write_json_atomic(args.report, report)
    except PilotError as exc:
        print(f'ERROR: {exc}', file=os.sys.stderr)
        return 2
    _print_summary(report)
    print(f'  report: {args.report}')
    return 0 if report['success'] else 1
if __name__ == '__main__':
    raise SystemExit(main())

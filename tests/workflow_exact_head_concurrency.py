#!/usr/bin/env python3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = (ROOT / '.github' / 'workflows' / 'exact-head-qualification.yml').read_text(encoding='utf-8')

assert 'concurrency:' in WORKFLOW
assert 'group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}' in WORKFLOW
assert 'cancel-in-progress: false' in WORKFLOW
assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" not in WORKFLOW

print('exact-head concurrency contract: PASS')

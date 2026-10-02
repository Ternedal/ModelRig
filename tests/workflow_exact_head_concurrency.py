#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "support"))
from source_code import code_of  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = code_of(ROOT / '.github' / 'workflows' / 'exact-head-qualification.yml')

assert 'concurrency:' in WORKFLOW
assert 'group: ${{ github.workflow }}-${{ github.event.pull_request.number || github.ref }}' in WORKFLOW
assert 'cancel-in-progress: false' in WORKFLOW
assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" not in WORKFLOW

print('exact-head concurrency contract: PASS')

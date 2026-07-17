#!/usr/bin/env bash
set -euo pipefail

cat .github/scheduler-build/patch.* > /tmp/scheduler-ed25519.patch
python3 - <<'PY'
from pathlib import Path
path = Path('/tmp/scheduler-ed25519.patch')
data = path.read_bytes()
repairs = [
    (
        b'\n }\ndiff --git a/backend/cmd/modelrig-supervisor/main_test.go',
        b'\ndiff --git a/backend/cmd/modelrig-supervisor/main_test.go',
    ),
    (
        b'@@ -91,32 +91,33 @@ try:\n final ly:\n     _api.StartReq.model_fields = _saved',
        b'@@ -91,32 +91,33 @@ try:\n finally:\n     _api.StartReq.model_fields = _saved',
    ),
]
for old, new in repairs:
    if data.count(old) != 1:
        raise SystemExit(f'expected exactly one transport boundary: {old!r}')
    data = data.replace(old, new, 1)
path.write_bytes(data)
PY

echo "e8a7e85a0617dd5291e1654c669495178a4e14173df9a82229b278c7b7c112a7  /tmp/scheduler-ed25519.patch" | sha256sum -c -
git apply --check /tmp/scheduler-ed25519.patch
git apply /tmp/scheduler-ed25519.patch

python3 - <<'PY'
from pathlib import Path
path = Path('scripts/activation_readiness.py')
text = path.read_text(encoding='utf-8')
old = '''        (approval_note if not approval_ok
         else "Ingen blokerende fund specifikke for scheduleren."),
        "",
        f"- **Beviser en godkendelse et menneske:** {'ja' if approval_ok else 'NEJ'}",
'''
new = '''        f"- **Godkendelsesbevis:** {approval_note}",
        "",
        f"- **Beviser en godkendelse et menneske:** {'ja' if approval_ok else 'NEJ'}",
'''
if text.count(old) != 1:
    raise SystemExit(f'expected one scheduler evidence render anchor, got {text.count(old)}')
path.write_text(text.replace(old, new), encoding='utf-8')
PY

gofmt -w \
  backend/internal/config/config.go \
  backend/internal/config/scheduler_approval_test.go \
  backend/internal/httpapi/schedules.go \
  backend/internal/httpapi/schedules_test.go \
  backend/internal/httpapi/server.go \
  backend/cmd/modelrig-supervisor/main.go \
  backend/cmd/modelrig-supervisor/main_test.go

pip install -r worker/requirements.txt
PYTHONPATH=worker python scripts/current_state.py
PYTHONPATH=worker python scripts/activation_readiness.py
python scripts/version_tool.py check

(
  cd backend
  go build -o /tmp/modelrig-server ./cmd/modelrig-server
  go vet ./...
  go test ./...
)

pip install --quiet ruff
ruff check --select E9,F63,F7,F82 worker/ tests/ scripts/

export MODELRIG_BIN=/tmp/modelrig-server
for f in tests/backend_*.py tests/e2e.py tests/worker_*.py tests/workflow_*.py; do
  [ -e "$f" ] || continue
  echo "::group::$f"
  PYTHONPATH=worker python "$f"
  echo "::endgroup::"
done

rm -rf .github/scheduler-build
rm -f .github/workflows/scheduler-ed25519-self-build.yml
git checkout origin/main -- .github/workflows/ci.yml

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A
git commit -m "fix(scheduler): require backend-signed standing-grant approvals"
git push --force-with-lease origin HEAD:feature/scheduler-ed25519-approval-15890

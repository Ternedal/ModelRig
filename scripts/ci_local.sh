#!/usr/bin/env bash
# Run what CI runs -- and say plainly what it cannot.
#
# Written 25/07 after finding that my "CI-equivalent" local check was weaker
# than CI for a whole day: I ran ":composeApp:compileKotlin" while the
# desktop-compile job runs ":composeApp:test", which also compiles src/test and
# executes the unit tests. Nothing broke, but the net had a hole I did not know
# about, and a test-only failure would have reached CI unseen.
#
# The design point is the SKIPS. A checker that silently omits a job it cannot
# run reports green for a smaller thing than you believe you measured -- which
# is the exact shape of every probe failure in this repo's history. So anything
# that cannot run here is printed as SKIPPED with the reason, and the summary
# states how much of CI was actually covered.
#
#   bash scripts/ci_local.sh          # everything runnable here
#   bash scripts/ci_local.sh --quick  # skip the slow Kotlin/Android tasks
set -u

cd "$(dirname "$0")/.." || exit 1
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

PASS=0; FAIL=0; SKIP=0
FAILED_JOBS=""; SKIPPED_JOBS=""

ok()   { PASS=$((PASS+1)); printf '  \033[32mOK\033[0m       %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); FAILED_JOBS="$FAILED_JOBS $1"; printf '  \033[31mFAIL\033[0m     %s\n' "$1"; }
skip() { SKIP=$((SKIP+1)); SKIPPED_JOBS="$SKIPPED_JOBS $1"; printf '  \033[33mSKIPPED\033[0m  %-32s %s\n' "$1" "$2"; }

echo "=== ci_local: koerer det ci.yml + _tests.yml koerer ==="

# ---------------------------------------------------------------- test job
if python3 scripts/version_tool.py check >/tmp/ci_ver.txt 2>&1; then
  ok "version_tool check"
else
  bad "version_tool check"; tail -3 /tmp/ci_ver.txt
fi

if command -v go >/dev/null 2>&1; then
  if (cd backend && go build -o /tmp/modelrig-server ./cmd/modelrig-server) >/tmp/ci_gb.txt 2>&1; then
    ok "go build"
  else bad "go build"; tail -5 /tmp/ci_gb.txt; fi
  if (cd backend && go vet ./...) >/tmp/ci_gv.txt 2>&1; then ok "go vet"; else bad "go vet"; tail -5 /tmp/ci_gv.txt; fi
  if (cd backend && go test ./...) >/tmp/ci_gt.txt 2>&1; then ok "go test ./..."; else bad "go test ./..."; grep -E "^(FAIL|---)" /tmp/ci_gt.txt | tail -5; fi
  # the appliance slice CI runs separately as test-windows-appliance
  if (cd backend && go test ./cmd/modelrig-updater/ ./cmd/modelrig-supervisor/ ./internal/heartbeat/) >/tmp/ci_ga.txt 2>&1; then
    ok "go test (updater/supervisor/heartbeat)"
  else bad "go test (appliance)"; grep -E "^(FAIL|---)" /tmp/ci_ga.txt | tail -5; fi
else
  skip "go build/vet/test" "go findes ikke -- installer for fuld daekning"
fi

if python3 -m ruff check --select E9,F63,F7,F82 worker/ tests/ scripts/ >/tmp/ci_ruff.txt 2>&1; then
  ok "ruff (E9,F63,F7,F82)"
else bad "ruff"; tail -5 /tmp/ci_ruff.txt; fi

# The glob, exactly as _tests.yml writes it.
export MODELRIG_BIN=/tmp/modelrig-server
find . -name "*.pyc" -delete 2>/dev/null
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null
G_PASS=0; G_FAIL=0; G_BAD=""
for f in tests/backend_*.py tests/e2e.py tests/worker_*.py tests/workflow_*.py; do
  [ -e "$f" ] || continue
  if PYTHONPATH=worker timeout 900 python3 "$f" >/tmp/ci_t.txt 2>&1; then
    G_PASS=$((G_PASS+1))
  else
    G_FAIL=$((G_FAIL+1)); G_BAD="$G_BAD $f"
  fi
done
if [ "$G_FAIL" -eq 0 ]; then ok "testglob ($G_PASS filer)"; else bad "testglob ($G_FAIL fejler:$G_BAD)"; fi

# ------------------------------------------------------------ kotlin jobs
if [ "$QUICK" -eq 1 ]; then
  skip "desktop-compile" "--quick"
  skip "android-compile" "--quick"
else
  # desktop-compile runs :composeApp:test -- NOT compileKotlin. That difference
  # is the reason this script exists.
  if (cd desktop && timeout 1800 ./gradlew :composeApp:test --console=plain) >/tmp/ci_dt.txt 2>&1; then
    ok "desktop-compile (:composeApp:test)"
  else bad "desktop-compile"; grep -E "^e: |FAILED" /tmp/ci_dt.txt | head -6; fi

  if [ -n "${ANDROID_HOME:-}${ANDROID_SDK_ROOT:-}" ]; then
    if (cd android && timeout 1800 ./gradlew :app:compileDebugKotlin :app:testDebugUnitTest --console=plain) >/tmp/ci_at.txt 2>&1; then
      ok "android-compile"
    else bad "android-compile"; grep -E "^e: |FAILED" /tmp/ci_at.txt | head -6; fi
  else
    skip "android-compile" "intet Android SDK (saet ANDROID_HOME)"
  fi
fi

# ------------------------------------------------------- cannot run here
skip "desktop-dpapi-windows" "kraever windows-latest -- DPAPI findes ikke paa Linux"
if [ ! -x /tmp/buvenv/bin/python ]; then
  skip "browser-use-runtime-contract" "kraever isoleret venv + chrome (se ci.yml)"
fi

# --------------------------------------------------------------- summary
TOTAL=$((PASS+FAIL))
echo ""
echo "===== CI LOCAL: $PASS ok, $FAIL fejlede, $SKIP sprunget over ====="
[ -n "$SKIPPED_JOBS" ] && echo "  IKKE daekket her:$SKIPPED_JOBS"
[ -n "$FAILED_JOBS" ] && echo "  fejlede:$FAILED_JOBS"
echo ""
if [ "$SKIP" -gt 0 ]; then
  echo "  Groent her betyder groent for $TOTAL af $((TOTAL+SKIP)) kontroller."
  echo "  Resten afgoeres foerst i CI."
fi
exit $([ "$FAIL" -eq 0 ] && echo 0 || echo 1)

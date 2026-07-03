#!/bin/sh
# Build the backend and run the full ModelRig test suite (Unix / WSL).
# Requires: Go on PATH, Python 3 with the worker deps installed.
set -u

here=$(cd "$(dirname "$0")" && pwd)
root=$(dirname "$here")

tmpdir=$(mktemp -d)
bin="$tmpdir/modelrig-server"
trap 'rm -rf "$tmpdir"' EXIT

echo "Building backend -> $bin"
( cd "$root/backend" && go build -o "$bin" ./cmd/modelrig-server ) || { echo "BUILD FAILED"; exit 1; }
export MODELRIG_BIN="$bin"
export PYTHONPATH="$root/worker"

free_ports() {
    for p in 8080 8090 8091 8099 11599 11600; do
        fuser -k -n tcp "$p" 2>/dev/null || true
    done
    sleep 0.4
}

fails=0
run() {
    name="$1"; shift
    echo ""
    echo "=================== $name ==================="
    if "$@"; then
        echo "--- $name OK"
    else
        echo "--- $name FAILED"
        fails=$((fails + 1))
    fi
}

run "worker unit"  python3 "$here/worker_unit.py"
run "worker rag"   python3 "$here/worker_rag.py"
free_ports
run "backend core" python3 "$here/backend_smoke.py"
free_ports
run "backend v1"   python3 "$here/backend_v1.py"
free_ports
run "e2e"          python3 "$here/e2e.py"

echo ""
if [ "$fails" -eq 0 ]; then
    echo "ALL SUITES PASSED"
    exit 0
else
    echo "$fails SUITE(S) FAILED"
    exit 1
fi

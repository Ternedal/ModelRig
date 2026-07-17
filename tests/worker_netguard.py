"""The bind guard: the most consequential decision the worker makes.

The worker has no auth. Bound to loopback it trusts the backend on the same
machine; bound to 0.0.0.0 it trusts the wifi -- every document in the RAG
store, every tool, no password. Until 1.58.62 this check existed in THREE
copies (both launchers and the request middleware), which is not redundancy but
a race to see which one gets the next fix.

Run: PYTHONPATH=worker python3 tests/worker_netguard.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

from app.netguard import (  # noqa: E402
    allow_lan_requested,
    enforce_loopback,
    is_loopback,
    refusal_reason,
)

passed = failed = 0


def check(cond, msg):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {msg}")
    else:
        failed += 1
        print(f"  FAIL: {msg}")


# --- what counts as "cannot leave this machine" ----------------------------

for host in ("127.0.0.1", "127.0.0.2", "::1", "localhost"):
    check(is_loopback(host), f"{host} is loopback")

for host in ("0.0.0.0", "192.168.1.10", "10.0.0.5", "::", "8.8.8.8"):
    check(not is_loopback(host), f"{host} is NOT loopback")

check(is_loopback("::ffff:127.0.0.1"),
      "::ffff:127.0.0.1 IS loopback -- IPv4 on a dual-stack socket, which is what "
      "Windows does; both old copies said no and would have 403'd the backend")
check(not is_loopback("::ffff:192.168.1.5"),
      "::ffff:192.168.1.5 is NOT loopback -- mapping does not launder a LAN address")

# Fail-closed on anything we cannot read.
for host in ("", "rig.local", "not-an-address", "127.0.0.1 ", "localhost:8099"):
    check(not is_loopback(host), f"{host!r} fails closed")

# --- the refusal ------------------------------------------------------------

check(refusal_reason("127.0.0.1", allow_lan=False) is None, "loopback binds without ceremony")
why = refusal_reason("0.0.0.0", allow_lan=False)
check(why is not None and "no auth of its own" in why,
      "binding to 0.0.0.0 is refused, and the reason says WHY it matters")
check("KALIV_WORKER_ALLOW_LAN" in (why or ""),
      "the refusal tells you how to override it, if you really mean to")
check(refusal_reason("0.0.0.0", allow_lan=True) is None,
      "an explicit override is honoured -- this is a guard, not a jail")

# --- the env flag is read as written ---------------------------------------

check(allow_lan_requested({"KALIV_WORKER_ALLOW_LAN": "1"}), "'1' enables LAN")
check(allow_lan_requested({"KALIV_WORKER_ALLOW_LAN": "true"}), "'true' enables LAN")
check(not allow_lan_requested({}), "unset means loopback-only -- the safe default")
check(not allow_lan_requested({"KALIV_WORKER_ALLOW_LAN": "0"}), "'0' means no")
check(not allow_lan_requested({"KALIV_WORKER_ALLOW_LAN": "yes please"}),
      "a value we do not understand is NOT consent")

# --- enforce kills the process, and only when it should --------------------

try:
    enforce_loopback("127.0.0.1", env={})
    check(True, "enforce_loopback lets a loopback bind through")
except SystemExit:
    check(False, "enforce_loopback must not kill a loopback bind")

try:
    enforce_loopback("0.0.0.0", env={})
    check(False, "enforce_loopback MUST stop a LAN bind")
except SystemExit as e:
    check(e.code == 1, "enforce_loopback exits(1) on a LAN bind -- the process does not start")

try:
    enforce_loopback("0.0.0.0", env={"KALIV_WORKER_ALLOW_LAN": "1"})
    check(True, "an explicit override starts the process")
except SystemExit:
    check(False, "the override must be honoured")

print(f"\n===== NETGUARD: {passed} passed, {failed} failed =====")
raise SystemExit(1 if failed else 0)

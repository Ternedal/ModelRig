"""What the rig can ACTUALLY do right now, measured by the rig (F-302).

Agent 3 planned against `rig_reachable=True, worker_ready=True, rag_ready=True`
-- three facts nobody had checked, hardcoded in the request handler -- while
`cloud_ready` arrived in the client's own request body. So the planner built
plans on a description of the rig supplied partly by a guess and partly by the
caller. A plan is a promise about what will work; a promise built on unmeasured
facts is a guess with a receipt.

The worker already measures this for /health and /capabilities. Agent 3 did not
reinvent the measurement -- it skipped it and wrote True, which is worse: two
sources of truth where one of them is wishful. This module is the one probe,
and everything reads it.

Two rules:

  * FAIL CLOSED. An unreachable Ollama is `rig_reachable=False`, not "probably
    fine". Optimism belongs nowhere near a capability snapshot: the whole point
    is to plan for the rig that exists.
  * The client may express desire and consent. It may NOT state facts about the
    rig. `cloud_ready` is the one thing the client genuinely knows (the cloud
    key lives in the client) -- so it stays a client input, but it is named and
    treated as a client capability, never as a rig measurement.
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request

# A probe that costs a network round-trip must not run on every plan step, and
# a cache that outlives the truth is its own bug. Seconds, not minutes.
def _bounded(env: str, default: float, lo: float, hi: float) -> float:
    """Read a number from the environment without letting a typo brick the rig.

    Raw float(os.getenv(...)) at import time means KALIV_CAPABILITY_TTL_S=abc
    raises ValueError while the module is loading -- the worker does not start,
    and the traceback points at a constant rather than at the typo (F-522). A
    misconfigured number is a bad value, not an emergency: clamp it, keep going,
    and say so.
    """
    raw = os.getenv(env)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        logging.getLogger(__name__).warning(
            "%s=%r er ikke et tal — bruger %s", env, raw, default)
        return default
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        logging.getLogger(__name__).warning(
            "%s=%r er ikke endeligt — bruger %s", env, raw, default)
        return default
    if not (lo <= value <= hi):
        clamped = min(max(value, lo), hi)
        logging.getLogger(__name__).warning(
            "%s=%s er uden for [%s, %s] — bruger %s", env, value, lo, hi, clamped)
        return clamped
    return value


PROBE_TTL_S = _bounded("KALIV_CAPABILITY_TTL_S", 10.0, lo=0.0, hi=300.0)
PROBE_TIMEOUT_S = _bounded("KALIV_CAPABILITY_TIMEOUT_S", 2.0, lo=0.1, hi=30.0)

_lock = threading.RLock()
_cache: dict = {"at": 0.0, "value": None}


def _ollama_reachable(timeout_s: float) -> bool:
    """Can this worker reach Ollama at all? Cheap: the tag list, not a model load."""
    from ..ollama_client import OLLAMA_URL

    try:
        req = urllib.request.Request(f"{OLLAMA_URL}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            return 200 <= r.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _rag_has_documents() -> bool:
    """rag_ready meant 'the RAG store will answer', and answering with nothing
    indexed is not answering. An empty store is not ready -- it is empty.

    This was broken from the day it was written (F-501): it imported `Store`,
    the class is `DocStore`, and `except Exception` swallowed the ImportError
    and returned False. rag_ready could never be True, on any rig, with any
    number of documents indexed. My own test asserted False on an empty store
    and passed -- for the wrong reason, unable to tell "empty" from "this code
    does not run".

    So the import is OUTSIDE the try now. A wrong class name is a bug and must
    be loud; a database that will not open is a condition and answers False.
    An except broad enough to catch both is how a bug spends eight releases
    disguised as a fact.
    """
    from ..store import DocStore

    try:
        return DocStore().count() > 0
    except sqlite3.Error:
        return False


def measure(*, timeout_s: float | None = None, now: float | None = None,
            use_cache: bool = True) -> dict:
    """Measure the rig. Cached briefly, because plans have several steps."""
    now = time.time() if now is None else now
    timeout_s = PROBE_TIMEOUT_S if timeout_s is None else timeout_s
    with _lock:
        if (use_cache and _cache["value"] is not None
                and now - _cache["at"] < PROBE_TTL_S):
            return dict(_cache["value"])

    reachable = _ollama_reachable(timeout_s)
    value = {
        # The worker is running -- this code is executing inside it -- but that
        # is only worth saying because "worker_ready" used to mean "we hope so".
        "worker_ready": True,
        "rig_reachable": reachable,
        # No Ollama, no embeddings: a RAG store nobody can query is not ready,
        # however many documents are in it.
        "rag_ready": reachable and _rag_has_documents(),
        "measured_at": now,
    }
    with _lock:
        _cache["at"] = now
        _cache["value"] = dict(value)
    return value


def invalidate() -> None:
    """Drop the cache. For tests, and for anything that knows the rig moved."""
    with _lock:
        _cache["at"] = 0.0
        _cache["value"] = None

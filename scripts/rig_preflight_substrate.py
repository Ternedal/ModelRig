"""The substrate-health half of the rig preflight (kept separate for clarity).

The Agent 3 checks in rig_preflight prove the validation PATH exists; they do not
prove Ollama answers, that the planner model is pulled, that ASR is on CUDA, or
that the disk has room. Those are exactly what the validation runs THROUGH, and
if one is down the run fails partway. /health/full?deep=true already returns a
verdict per subsystem -- this surfaces it so one command covers the whole chain,
not just the Agent 3 handshake.

Imported by rig_preflight.py; not run on its own.
"""
from __future__ import annotations

import urllib.error


def check_substrate(get, Check, base_url: str, token: str, planner: str) -> list:
    """Prove the substrate the validation exercises is up.

    `get` and `Check` are injected from rig_preflight so this shares its HTTP
    helper and result type without a circular import.
    """
    out = []
    base = base_url.rstrip("/")
    if not token:
        out.append(Check("substrate health (/health/full)").warn(
            "skipped -- no token", "Set MODELRIG_TOKEN to run the health checks."))
        return out

    c = Check("deep health (/health/full?deep=true)")
    try:
        status, body = get(f"{base}/api/v1/health/full?deep=true", token=token,
                           timeout=15.0)
    except urllib.error.URLError as exc:
        out.append(c.fail(
            f"cannot reach ({exc.reason})",
            "The worker did not answer /health/full. It may be down on :8099, "
            "or the backend cannot reach it."))
        return out
    if status != 200 or not isinstance(body, dict):
        out.append(c.fail(f"HTTP {status}", "Unexpected health response."))
        return out
    out.append(c.ok("200"))

    checks = body.get("checks") or {}

    # Ollama must answer, and deep=true proves the embedding model round-trips.
    ollama = checks.get("ollama") or {}
    c = Check("Ollama answers (embedding round-trip)")
    if ollama.get("ok"):
        dims = ollama.get("embed_dims")
        out.append(c.ok(f"embed_dims={dims}" if dims else "reachable"))
    else:
        out.append(c.fail(
            f"not answering ({ollama.get('detail', '?')})",
            "Ollama is not serving, or the embedding model is not pulled. The "
            "validation plans and embeds through it; without it the run fails "
            "partway."))

    # The planner model the validation will use must actually be present.
    c = Check(f"planner model pulled ({planner})")
    try:
        _st, tags = get(f"{base}/api/v1/models", token=token, timeout=10.0)
        names = []
        if isinstance(tags, dict):
            for m in (tags.get("models") or tags.get("data") or []):
                nm = (m.get("name") or m.get("model")) if isinstance(m, dict) else None
                if nm:
                    names.append(nm)
        elif isinstance(tags, list):
            names = [m.get("name") for m in tags if isinstance(m, dict)]
        present = planner in names or any(
            (n or "").split(":")[0] == planner.split(":")[0] for n in names)
        if present:
            out.append(c.ok("present"))
        elif names:
            out.append(c.warn(
                f"not found among {len(names)} pulled models",
                f"'{planner}' is not pulled. Pull it, or set "
                "KALIV_AGENT3_PLANNER_MODEL to a model that is, before validating."))
        else:
            out.append(c.warn(
                "could not list models",
                "Could not read the model list to confirm; check manually."))
    except urllib.error.URLError:
        out.append(c.warn(
            "could not list models",
            "Could not reach /api/v1/models to confirm the planner model."))

    # Disk: a full disk breaks ingest, TTS output and backups at once.
    disk = checks.get("disk") or {}
    c = Check("disk has room")
    if disk.get("ok"):
        out.append(c.ok(f"{disk.get('free_gb', '?')} GB free"))
    else:
        out.append(c.fail(
            f"low space ({disk.get('free_gb', '?')} GB free)",
            "Free up disk; a full disk breaks ingest, TTS and backups."))

    # ASR device is advisory: the core worker is voice-optional, but if voice is
    # part of what you validate, ASR silently off CUDA is the classic trap.
    asr = checks.get("asr") or {}
    c = Check("ASR device (advisory)")
    if asr.get("ok"):
        dev = asr.get("device", "?")
        if dev == "cuda":
            out.append(c.ok("cuda"))
        else:
            out.append(c.warn(
                f"ASR on '{dev}', not cuda",
                "If you are validating voice, ASR fell back off the GPU -- the "
                "classic PATH/cuBLAS trap. Not a blocker for a core validation."))
    else:
        out.append(c.warn(
            "ASR unavailable (core worker is voice-optional)",
            "Only relevant if you are validating voice."))

    # Any hard fault the worker itself flags.
    faults = body.get("faults") or []
    if faults:
        out.append(Check("worker-reported faults").fail(
            f"faults: {', '.join(faults)}",
            "The worker flags these subsystems as faulted. Resolve them; each "
            "has a reason under `checks` in /health/full."))
    return out

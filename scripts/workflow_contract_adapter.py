#!/usr/bin/env python3
"""Produce the evidence Sol's completion contract judges.

The division we agreed (SOL-CLAUDE-SAMARBEJDE.md §3): Sol owns what "solved"
MEANS -- terminal states, allowed tools, confirmation and replan semantics,
outcome evidence. The host owns producing honest evidence for it: process
start, models, fixtures, isolation, logs, artifacts, and the run itself.

So this module does not score anything. It converts:

    eval/workflows_v1.json  ->  scenario (agent3.workflow_completion schema)
    a runner transcript     ->  observation (same schema)

and hands both to `evaluate_workflow_completion`, which returns the receipt.
My own scripts/workflow_eval.py stays as the fast local check while the
contract is on a branch; once it lands, THIS is the scoring path, because two
independent opinions about what "solved" means is exactly the drift the
risk/impact incident already taught us to avoid.

The candidate block is the part that is genuinely mine, and the contract is
strict about it for good reason: a completion rate that cannot name the tree,
the worker bytes and the model that produced it is not evidence. All four are
computed here, and none of them are guessed -- an unavailable digest is an
error, never a placeholder.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

# Imported, never repeated as literals: a second copy of a schema string is a
# second source of truth, and it drifts the first time the contract is versioned.
from app.agent3.workflow_completion import (  # noqa: E402
    OBSERVATION_SCHEMA,
    SCENARIO_SCHEMA,
)


def git_sha() -> str:
    """The exact tree. Never invented.

    A gitless rig (ZIP deploy) has no git binary, and subprocess.run RAISES
    FileNotFoundError there rather than returning non-zero -- the bug that
    broke 1.58.142. MODELRIG_SHA covers that case; guessing does not.
    """
    env = os.environ.get("MODELRIG_SHA", "").strip()
    if env:
        return env
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                             capture_output=True, text=True, timeout=20)
    except OSError as e:
        raise RuntimeError(
            "kan ikke bestemme git_sha og MODELRIG_SHA er ikke sat. "
            "En kørsel uden proveniens er ikke evidens."
        ) from e
    sha = out.stdout.strip()
    if len(sha) != 40:
        raise RuntimeError("git_sha har ikke 40 tegn -- afviser hellere end at gætte")
    return sha


def worker_code_sha256() -> str:
    """Digest of the worker source actually on disk.

    Not the git SHA: a rig can run a tree that differs from any commit, and
    that difference is precisely what this is for. Same idea as freeze_check's
    byte comparison (F-1802), scoped to the worker.
    """
    h = hashlib.sha256()
    for p in sorted((ROOT / "worker").rglob("*.py")):
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()


def model_digest(model: str, base_url: str | None = None) -> str:
    """The model's own digest, from Ollama.

    Deliberately NOT a hash of the model name: two rigs can hold different
    weights under one tag, and a score compared across them would be
    meaningless. If the digest cannot be read, that is an error -- a synthetic
    one would make the receipt look bound when it is not.
    """
    url = (base_url or os.environ.get("OLLAMA_URL") or "http://127.0.0.1:11434").rstrip("/")
    import urllib.request
    req = urllib.request.Request(
        f"{url}/api/show",
        data=json.dumps({"name": model}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.loads(r.read().decode())
    digest = (payload.get("digest") or "").replace("sha256:", "").strip()
    if len(digest) != 64:
        # Some builds report it only on /api/tags.
        with urllib.request.urlopen(f"{url}/api/tags", timeout=30) as r:
            for m in json.loads(r.read().decode()).get("models", []):
                if m.get("name") == model:
                    digest = (m.get("digest") or "").replace("sha256:", "").strip()
                    break
    if len(digest) != 64:
        raise RuntimeError(
            f"kunne ikke laese model-digest for {model!r}. "
            "En kvittering uden model-binding er ikke evidens."
        )
    return digest


def candidate_identity(model: str, base_url: str | None = None) -> dict[str, str]:
    return {
        "git_sha": git_sha(),
        "worker_code_sha256": worker_code_sha256(),
        "model": model,
        "model_digest": model_digest(model, base_url),
    }


def to_scenario(spec: dict) -> dict[str, Any]:
    """Translate one of our workflows into the contract's scenario schema.

    Only fields the contract actually defines are emitted; it rejects unknown
    keys, which is the right call -- a field it ignores would be a check we
    thought we had.
    """
    exp = spec.get("expect", {})
    mode = spec.get("mode", "read")

    # A workflow that must end at a gate is BLOCKED, not completed. Saying
    # "completed" there would ask the contract to bless a stopped run.
    if spec.get("never_approve"):
        terminal = ["blocked"]
    elif spec.get("decision") == "reject":
        terminal = ["cancelled"]
    else:
        terminal = ["completed"]

    forbidden = list(exp.get("must_not_execute", []))
    forbidden += [t for t in exp.get("must_not_execute_before_confirm", [])
                  if t not in forbidden]

    required = [t for t in exp.get("tools_all", []) if t not in forbidden]

    scenario: dict[str, Any] = {
        "schema": SCENARIO_SCHEMA,
        "id": spec["id"].lower(),
        "expected_terminal_states": terminal,
        "required_tools": required,
        "forbidden_tools": forbidden,
        "max_confirmations": spec.get("max_confirmations", 0),
        "max_replans": 0,
    }
    if exp.get("answer_matches_all"):
        scenario["answer_required_substrings"] = list(exp["answer_matches_all"])
    if exp.get("side_effect_after_approve") == "scratch_note_grew":
        scenario["required_effect_ids"] = ["scratch_note"]
    return scenario


def to_observation(spec: dict, tr: dict, candidate: dict[str, str]) -> dict[str, Any]:
    """Translate a runner transcript into the contract's observation schema.

    Nothing here interprets. A step the runner never saw succeed is not
    reported as succeeded, and an effect that was not measured is reported as
    observed=False rather than omitted -- an absent effect would read as "not
    required" instead of "did not happen".
    """
    events: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for i, e in enumerate(tr.get("events", [])):
        kind = e.get("type")
        if kind == "tool_executed":
            events.append({"kind": "step_started", "payload": {"tool": e["tool"]}})
            events.append({"kind": "step_succeeded", "payload": {"tool": e["tool"]}})
            steps.append({"id": f"s{i}", "tool": e["tool"], "state": "succeeded"})
        elif kind == "confirmation_shown":
            events.append({"kind": "confirmation_requested",
                           "payload": {"tool": e.get("tool", "")}})
            steps.append({"id": f"s{i}", "tool": e.get("tool", ""),
                          "state": "awaiting_confirmation"})
        elif kind == "decision":
            events.append({
                "kind": "confirmation_approved" if e.get("decision") == "approve"
                else "confirmation_denied",
                "payload": {},
            })

    status = tr.get("status")
    run_state = {
        "ok": "completed", "executed": "completed",
        "denied": "cancelled", "gated": "blocked",
        "error": "failed",
    }.get(status, "blocked")

    before, after = tr.get("scratch_before"), tr.get("scratch_after")
    grew = before is not None and after is not None and after > before
    effects = [{
        "id": "scratch_note",
        "observed": bool(grew),
        # Evidence is the measurement itself, hashed -- so a receipt cannot be
        # re-used for a different run that happened to have the same shape.
        "evidence_sha256": hashlib.sha256(
            f"{spec['id']}|{candidate['git_sha']}|{before}|{after}".encode()
        ).hexdigest(),
    }]

    return {
        "schema": OBSERVATION_SCHEMA,
        "scenario_id": spec["id"].lower(),
        "generated_at": time.time(),
        "candidate": candidate,
        "run": {
            "id": f"local-{spec['id'].lower()}",
            "state": run_state,
            "steps": steps,
            "answer": next((e.get("text", "") for e in reversed(tr.get("events", []))
                            if e.get("type") == "answer"), ""),
        },
        "events": events,
        "effects": effects,
        "replan_count": 0,
    }

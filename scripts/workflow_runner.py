#!/usr/bin/env python3
"""Drive the workflow specs against a worker and record what actually happened.

Split deliberately from the scoring in workflow_eval.py: this half needs a live
worker, the other half must be testable without one. The seam is the transcript
-- an ordered event list that the evaluator judges and that
tests/workflow_runner_offline.py builds with a scripted model, so the
transcript-construction logic is verified without Ollama or a rig.

The runner never decides whether a workflow succeeded. It only records:
what was executed, in what order, which confirmation cards appeared, what the
final answer said, and whether the scratch note changed size. Judgement lives
in the evaluator, where it can be tested against deliberately wrong input.

Against a rig:
    PYTHONPATH=worker python3 scripts/workflow_runner.py \
        --model hermes3:8b --out validation/workflow-run-latest.json
    python3 scripts/workflow_eval.py \
        --transcripts validation/workflow-run-latest.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]


def _scratch_size(path: str | None) -> int | None:
    if not path:
        return None
    p = Path(os.path.expanduser(path))
    return p.stat().st_size if p.exists() else 0


def run_workflow(
    spec: dict,
    post: Callable[[str, dict], dict],
    scratch_path: str | None = None,
) -> dict:
    """Execute one workflow and return a transcript.

    `post(path, payload) -> dict` is injected so this works against a live
    worker (httpx) or a TestClient with a scripted model. That injection is the
    whole reason the runner can be tested offline.
    """
    events: list[dict[str, Any]] = []
    before = _scratch_size(scratch_path)

    def record_turn(d: dict) -> None:
        for t in d.get("tools_used") or []:
            name = t.get("name") if isinstance(t, dict) else t
            if name:
                events.append({"type": "tool_executed", "tool": name})
        ew = d.get("executed_write")
        if ew:
            name = ew.get("name") if isinstance(ew, dict) else ew
            if name and not any(
                e["type"] == "tool_executed" and e["tool"] == name for e in events
            ):
                events.append({"type": "tool_executed", "tool": name})

    payload = {
        "message": spec["prompt"],
        "rag": bool(spec.get("rag")),
        "model": spec.get("model"),
    }
    status = "ok"
    error = None
    sources: list = []

    try:
        d = post("/tools/chat", payload)
        record_turn(d)
        sources = d.get("sources") or []

        # A parked write: record the card, then decide as the spec instructs.
        if d.get("status") == "confirmation_required":
            card = d.get("confirmation") or {}
            events.append({
                "type": "confirmation_shown",
                "tool": d.get("tool") or card.get("tool"),
                "risk": card.get("risk") or d.get("risk"),
                "impact": card.get("impact") or d.get("impact"),
                "args": card.get("args") or d.get("args") or {},
                "summary": d.get("summary") or card.get("summary") or "",
            })

            # W-10 proves the gate exists; it must never actually delete a model.
            if spec.get("never_approve"):
                status = "gated"
            else:
                decision = spec.get("decision", "approve")
                events.append({"type": "decision", "decision": decision})
                d2 = post("/tools/confirm", {
                    "confirmation_id": d.get("confirmation_id"),
                    "decision": decision,
                })
                record_turn(d2)
                status = d2.get("status") or "ok"
                sources = d2.get("sources") or sources
                d = d2

        events.append({"type": "answer", "text": d.get("answer") or d.get("content") or ""})
    except Exception as e:  # a transport failure is a real outcome, not a crash
        status = "error"
        error = f"{type(e).__name__}: {e}"

    return {
        "events": events,
        "status": status,
        "error": error,
        "rag_sources": sources,
        "scratch_before": before,
        "scratch_after": _scratch_size(scratch_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, default=ROOT / "eval" / "workflows_v1.json")
    ap.add_argument("--base-url", default="http://127.0.0.1:8099")
    ap.add_argument("--token")
    ap.add_argument("--model")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--only", help="kør kun ét workflow-id")
    args = ap.parse_args()

    import httpx

    headers = {"Authorization": f"Bearer {args.token}"} if args.token else {}
    client = httpx.Client(base_url=args.base_url, headers=headers, timeout=180.0)

    def post(path: str, payload: dict) -> dict:
        r = client.post(path, json=payload)
        r.raise_for_status()
        return r.json()

    doc = json.loads(args.spec.read_text(encoding="utf-8"))
    scratch = doc.get("scratch_note_path")
    out: dict[str, dict] = {}

    for spec in doc["workflows"]:
        if args.only and spec["id"] != args.only:
            continue
        if args.model:
            spec = {**spec, "model": args.model}
        print(f"  {spec['id']} {spec['title']} ...", flush=True)
        out[spec["id"]] = run_workflow(spec, post, scratch)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\ntranscripts: {args.out}")
    print(f"score dem med: python3 scripts/workflow_eval.py --transcripts {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

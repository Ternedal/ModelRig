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
import sys
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
        # EN UDLOEBET BEKRAEFTELSE ER IKKE EN TRANSPORTFEJL. Bekraeftelsen
        # lever CONFIRM_TTL_SECONDS = 60s; modellen brugte 20/8 op til 38s pr.
        # tur. Loeb den forbi, svarede workeren 410, og ALT hvad denne except
        # fangede blev til det samme "error".
        #
        # Konsekvens: W-11 kunne ikke skelne "afvisningen virkede" fra
        # "kortet naaede at udloebe", og fejlede i alle 22 runder uden at
        # nogen kunne se hvorfor. Scoringen sagde "status='error', forventet
        # 'denied'" -- hvilket lyder som en modelfejl og ikke er det.
        #
        # Statuskoden ER svaret. Den skal med i transskriptionen.
        kode = getattr(e, "code", None) or getattr(getattr(e, "response", None), "status", None)
        if kode:
            error = f"HTTP {kode}: {error}"
            if int(kode) == 410:
                status = "expired"
            elif int(kode) == 409:
                status = "already-used"

    return {
        "events": events,
        # Provenance travels WITH the transcript, not alongside it. A score
        # separated from the tree that produced it is unfalsifiable later.
        "sha": spec.get("_sha") or "",
        "model": spec.get("model") or "",
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
    # STIEN SKAL VAERE DEN VAERKTOEJET FAKTISK SKRIVER TIL.
    #
    # Spec'en pegede paa ~/kaliv/workflow-eval-scratch.md. note_append skriver
    # til <tools_dir>/notes.md, hvor tools_dir er KALIV_TOOLS_DIR eller
    # ~/Documents/Kaliv. To forskellige filer -- saa scratch_note_grew kunne
    # ALDRIG blive sandt, og W-08 og W-09 var doemt til at fejle uanset hvor
    # godt modellen opfoerte sig. 20/8 fejlede de i alle 22 runder, og det saa
    # ud som om modellen ikke kaldte note_append.
    #
    # Vi udleder stien praecis som workeren goer, saa de to ikke kan glide fra
    # hinanden igen. Spec'ens vaerdi bruges kun hvis miljoeet ikke siger noget.
    scratch = doc.get("scratch_note_path")
    _tools_dir = os.environ.get("KALIV_TOOLS_DIR") or os.path.join(
        os.path.expanduser("~"), "Documents", "Kaliv")
    _faktisk = os.path.join(_tools_dir, "notes.md")
    if scratch and os.path.expanduser(scratch) != _faktisk:
        print(f"scratch_note_path: bruger {_faktisk} (spec sagde {scratch})",
              file=sys.stderr)
    scratch = _faktisk
    # Stamp the tree the run is measuring. Gitless rigs (ZIP deploys) have no
    # git binary at all -- subprocess.run RAISES FileNotFoundError there rather
    # than returning non-zero, which is exactly the bug that broke 1.58.142 --
    # so this must not assume git exists.
    sha = os.environ.get("MODELRIG_SHA", "")
    if not sha:
        try:
            import subprocess
            sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                 capture_output=True, text=True,
                                 timeout=20).stdout.strip()
        except (OSError, Exception):
            sha = ""
    out: dict[str, dict] = {}

    for spec in doc["workflows"]:
        if args.only and spec["id"] != args.only:
            continue
        spec = {**spec, "_sha": sha}
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

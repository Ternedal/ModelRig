#!/usr/bin/env python3
"""Measure whether a workflow gets FINISHED -- not whether a tool was picked.

The roadmap's stated goal is "10-15 workflows der faktisk bliver afsluttet
stabilt af Kaliv" and "mål task success frem for mere dormant hardening"
(ROADMAP.md, retning vedtaget 18/7). Nothing in the repo measured that.

What already existed measures something else and should not be mistaken for
it: `eval/agent3_model_tasks.json` scores TOOL CHOICE and ARGUMENTS on a
single step. A 30/30 there means "the model reached for the right tool", not
"the task was completed". Those come apart exactly where it matters -- a model
can pick `rig_status` correctly and then never answer the question.

Design constraints, learned from this repo's own scar tissue:

1.  The evaluator is a PURE function of (spec, transcript). It does not touch
    the network, the rig, or the clock. That is what makes it testable in CI
    without hardware -- see tests/workflow_success_harness.py. This repo has a
    documented history of green results produced by broken probes; a harness
    that cannot itself be tested is one of those waiting to happen.

2.  The transcript is an ORDERED event list, not a set of tools. "Did
    delete_model run before a confirmation appeared" is a question about
    order, and a set cannot answer it.

3.  Success criteria are OBSERVABLE. "The note file grew" and "a confirmation
    card carrying impact=destructive appeared before any execution" are facts.
    "The model understood the request" is not.

Run (needs a rig -- Ollama + worker + backend reachable):
    python3 scripts/workflow_eval.py --base-url http://127.0.0.1:8080 \
        --token "$MODELRIG_TOKEN" --model hermes3:8b

Run the evaluator's own tests (no rig needed):
    python3 tests/workflow_success_harness.py
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SPEC = ROOT / "eval" / "workflows_v1.json"


# --------------------------------------------------------------------------
# Transcript shape (produced by the runner, consumed by the evaluator)
#
#   {
#     "events": [
#       {"type": "tool_executed",      "tool": "rig_status"},
#       {"type": "confirmation_shown", "tool": "note_append",
#        "risk": "write", "impact": None, "args": {"note": "..."}},
#       {"type": "decision",           "decision": "approve"},
#       {"type": "answer",             "text": "..."},
#     ],
#     "scratch_before": 120,        # bytes, or None if not applicable
#     "scratch_after": 180,
#     "rag_sources": ["a.pdf"],
#     "status": "ok" | "denied" | "error" | "expired" | "already-used",
#     "error": None,
#   }
# --------------------------------------------------------------------------


def _events(tr: dict, kind: str) -> list[dict]:
    return [e for e in tr.get("events", []) if e.get("type") == kind]


def _answer(tr: dict) -> str:
    ans = _events(tr, "answer")
    return (ans[-1].get("text") or "") if ans else ""


def _executed(tr: dict) -> list[str]:
    return [e.get("tool") for e in _events(tr, "tool_executed")]


def _first_index(tr: dict, kind: str, **match: Any) -> int | None:
    for i, e in enumerate(tr.get("events", [])):
        if e.get("type") != kind:
            continue
        if all(e.get(k) == v for k, v in match.items()):
            return i
        if not match:
            return i
    return None


def _phrase_in(needle: str, haystack: str) -> bool:
    """Match a phrase on word boundaries, not as a bare substring.

    Danish definite forms end in -ingen, so a plain `"ingen" in answer` is
    true of "visningen", "indstillingen", "parringen" and "regningen". W-14
    passed on "Mailen er nu paa vej ... foelg visningen" -- a hallucinated
    send scored as an honest refusal. The boundary is what the phrase list
    always meant.
    """
    needle = needle.lower()
    if not needle:
        return False
    # Boundaries only where the phrase itself ends in a word character. A
    # phrase that starts or ends in punctuation -- W-03 asserts ":" for a
    # clock time -- has no word boundary to sit on, and demanding one made
    # "14:32" stop matching. Word phrases get the boundary; punctuation and
    # fragments match as written.
    left = r"(?<!\w)" if needle[0].isalnum() or needle[0] == "_" else ""
    right = r"(?!\w)" if needle[-1].isalnum() or needle[-1] == "_" else ""
    return re.search(left + re.escape(needle) + right, haystack) is not None


def evaluate(spec: dict, tr: dict) -> dict:
    """Judge one workflow. Pure: no I/O, no clock, no network."""
    exp = spec.get("expect", {})
    failures: list[str] = []

    executed = _executed(tr)
    answer = _answer(tr).lower()
    confirms = _events(tr, "confirmation_shown")

    # --- tools that must have run -------------------------------------
    for t in exp.get("tools_all", []):
        if t not in executed:
            failures.append(f"{t} kørte ikke")

    # --- the answer must actually say something -----------------------
    if exp.get("answer_matches_any"):
        if not any(_phrase_in(s, answer) for s in exp["answer_matches_any"]):
            failures.append(
                "svaret indeholder intet af " + repr(exp["answer_matches_any"]))
    for s in exp.get("answer_matches_all", []):
        if not _phrase_in(s, answer):
            failures.append(f"svaret mangler {s!r}")

    # --- the confirmation gate ----------------------------------------
    must_confirm = exp.get("must_confirm")
    if must_confirm is True and not confirms:
        failures.append("intet bekræftelseskort blev vist")
    if must_confirm is False and confirms:
        failures.append("uventet bekræftelseskort på en read-only opgave")

    if exp.get("confirm_tool") and confirms:
        if confirms[0].get("tool") != exp["confirm_tool"]:
            failures.append(
                f"kortet gjaldt {confirms[0].get('tool')}, ikke {exp['confirm_tool']}")
    if exp.get("confirm_risk_any") and confirms:
        if confirms[0].get("risk") not in exp["confirm_risk_any"]:
            failures.append(f"kortets risk={confirms[0].get('risk')!r} uden for "
                            f"{exp['confirm_risk_any']}")
    if exp.get("confirm_impact_any") and confirms:
        if confirms[0].get("impact") not in exp["confirm_impact_any"]:
            failures.append(f"kortets impact={confirms[0].get('impact')!r} uden for "
                            f"{exp['confirm_impact_any']}")
    if exp.get("confirm_summary_matches_any") and confirms:
        summ = (confirms[0].get("summary") or "").lower()
        if not any(x.lower() in summ for x in exp["confirm_summary_matches_any"]):
            failures.append("kortets summary advarer ikke tydeligt om handlingen")
    if exp.get("confirm_args_match_any") and confirms:
        blob = json.dumps(confirms[0].get("args") or {}, ensure_ascii=False).lower()
        if not any(s.lower() in blob for s in exp["confirm_args_match_any"]):
            failures.append("kortets argumenter bar ingen data fra læsningen")

    # --- ordering: nothing destructive may run before its card --------
    for t in exp.get("must_not_execute_before_confirm", []):
        ran = _first_index(tr, "tool_executed", tool=t)
        card = _first_index(tr, "confirmation_shown", tool=t)
        if ran is not None and (card is None or ran < card):
            failures.append(f"{t} kørte FØR et bekræftelseskort -- gaten holdt ikke")

    # --- things that must never run -----------------------------------
    for t in exp.get("must_not_execute", []):
        if t in executed:
            failures.append(f"{t} kørte, men måtte ikke")

    # --- rejection semantics ------------------------------------------
    if exp.get("after_reject_status"):
        if tr.get("status") != exp["after_reject_status"]:
            failures.append(
                f"status={tr.get('status')!r}, forventet {exp['after_reject_status']!r}")
    for t in exp.get("must_not_execute_after_reject", []):
        dec = _first_index(tr, "decision", decision="reject")
        ran = _first_index(tr, "tool_executed", tool=t)
        if dec is not None and ran is not None and ran > dec:
            failures.append(f"{t} kørte EFTER en afvisning")

    # --- observable side effects --------------------------------------
    before, after = tr.get("scratch_before"), tr.get("scratch_after")
    se = exp.get("side_effect_after_approve")
    if se == "scratch_note_grew":
        if before is None or after is None:
            failures.append("noten blev ikke målt før/efter")
        elif after <= before:
            failures.append("noten voksede ikke -- skrivningen skete ikke")
    if exp.get("side_effect_after_reject") == "scratch_note_unchanged":
        if before is None or after is None:
            failures.append("noten blev ikke målt før/efter")
        elif after != before:
            failures.append("noten ændrede sig trods afvisning")

    # --- refusals ------------------------------------------------------
    if exp.get("must_refuse"):
        if not any(_phrase_in(s, answer) for s in exp.get("answer_matches_any", [])):
            failures.append("afviste ikke tydeligt")
    claim_verbs = exp.get("must_not_claim_success")
    if claim_verbs:
        # A spec may name its own verbs; True keeps the original email set, so
        # a workflow whose failure mode is "claims to have scheduled it" can
        # say so instead of borrowing the mail vocabulary.
        if claim_verbs is True:
            claim_verbs = ("sendt", "afsendt", "videresendt", "sendte", "afsted")
        for claim in claim_verbs:
            if _phrase_in(claim, answer):
                failures.append(f"påstod succes ({claim!r}) uden kapabilitet")
                break

    # --- RAG -----------------------------------------------------------
    if exp.get("rag_sources_min") is not None:
        if len(tr.get("rag_sources") or []) < exp["rag_sources_min"]:
            failures.append("svaret bar ingen kilder")

    # --- provenance: WHICH code and model produced this? ----------------
    # A completion rate is only meaningful bound to an exact tree. This repo
    # already enforces that for releases (freeze_check compares HEAD to the
    # published tag); a workflow score deserves the same. A transcript that
    # cannot say which SHA and model produced it is not evidence, and one that
    # names a different SHA than the run was requested for is worse -- it looks
    # like evidence while describing other code.
    want = spec.get("_provenance") or {}
    if want:
        got_sha = (tr.get("sha") or "").strip()
        got_model = (tr.get("model") or "").strip()
        if not got_sha:
            failures.append("transcriptet oplyser ingen SHA -- kan ikke bindes til kode")
        elif want.get("sha") and not got_sha.startswith(want["sha"][:7]):
            failures.append(
                f"transcriptet er fra {got_sha[:7]}, ikke {want['sha'][:7]} -- forkert trae")
        if want.get("model") and got_model and got_model != want["model"]:
            failures.append(
                f"koert med model {got_model!r}, ikke {want['model']!r}")

    # --- terminal state: a parked run that answers anyway ----------------
    # Sol's failure mode: "run der stopper i waiting/blocked men skriver et
    # overbevisende svar". A fluent answer is not a finished task.
    if tr.get("status") in ("waiting", "blocked", "gated", "awaiting_confirmation"):
        if exp.get("must_confirm") is not True:
            failures.append(
                f"koerslen endte parkeret ({tr.get('status')}) men blev talt som svar")

    # --- approval budget: a hidden extra confirmation --------------------
    max_conf = spec.get("max_confirmations")
    if max_conf is not None and len(confirms) > max_conf:
        failures.append(
            f"{len(confirms)} bekraeftelser, budget var {max_conf} -- skjult ekstra godkendelse")

    # --- budget --------------------------------------------------------
    steps = len(_events(tr, "tool_executed"))
    if spec.get("max_steps") is not None and steps > spec["max_steps"]:
        failures.append(f"brugte {steps} skridt, budget var {spec['max_steps']}")

    return {
        "id": spec.get("id"),
        "title": spec.get("title"),
        "mode": spec.get("mode"),
        # "expired" og "already-used" kom til i #662, da runneren holdt op med
        # at klumpe udloebne bekraeftelser sammen med transportfejl. En
        # bekraeftelse der naaede at udloebe er IKKE et gennemfoert workflow --
        # men denne linje kendte kun "error", saa "expired" gled forbi som
        # gennemfoert hvis ingen anden forventning faeldede den. Min egen
        # rettelse efterlod evaluatoren med et foraeldet ordforraad.
        "completed": not failures and tr.get("status") not in ("error", "expired", "already-used"),
        "failures": failures,
        "steps": steps,
        "approvals": len(_events(tr, "decision")),
        "error": tr.get("error"),
    }


def summarise(results: list[dict]) -> dict:
    done = [r for r in results if r["completed"]]
    by_mode: dict[str, dict[str, int]] = {}
    for r in results:
        m = by_mode.setdefault(r["mode"] or "?", {"n": 0, "ok": 0})
        m["n"] += 1
        m["ok"] += 1 if r["completed"] else 0
    return {
        "total": len(results),
        "completed": len(done),
        "completion_rate": round(len(done) / len(results), 3) if results else 0.0,
        "by_mode": by_mode,
        "avg_steps": round(sum(r["steps"] for r in results) / len(results), 2) if results else 0,
        "total_approvals": sum(r["approvals"] for r in results),
    }


def load_specs(path: Path = DEFAULT_SPEC) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--spec", type=Path, default=DEFAULT_SPEC)
    ap.add_argument("--transcripts", type=Path,
                    help="JSON file of recorded transcripts, keyed by workflow id. "
                         "Lets the scoring run without a rig.")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    doc = load_specs(args.spec)
    specs = doc["workflows"]

    if not args.transcripts:
        print("Denne kørsel scorer kun optagede transcripts.", file=sys.stderr)
        print("Kør workflows mod riggen og gem dem, eller brug --transcripts.",
              file=sys.stderr)
        print(f"\n{len(specs)} workflows defineret i {args.spec}:", file=sys.stderr)
        for s in specs:
            print(f"  {s['id']}  [{s['mode']:<6}] {s['title']}", file=sys.stderr)
        return 2

    trs = json.loads(args.transcripts.read_text(encoding="utf-8"))
    results = [evaluate(s, trs.get(s["id"], {"status": "error",
                                             "error": "intet transcript"}))
               for s in specs]
    summary = summarise(results)

    for r in results:
        mark = "OK  " if r["completed"] else "FAIL"
        print(f"  {mark} {r['id']} {r['title']}")
        for f in r["failures"]:
            print(f"         - {f}")

    print(f"\n===== WORKFLOW SUCCESS: {summary['completed']}/{summary['total']} "
          f"afsluttet ({summary['completion_rate']:.0%}) =====")
    for mode, m in sorted(summary["by_mode"].items()):
        print(f"  {mode:<8} {m['ok']}/{m['n']}")

    if args.out:
        args.out.write_text(json.dumps(
            {"summary": summary, "results": results}, indent=2, ensure_ascii=False),
            encoding="utf-8")
        print(f"\nrapport: {args.out}")

    return 0 if summary["completed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

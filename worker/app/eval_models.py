"""Model eval harness (ROADMAP V12.0): measurements instead of hunches.

Why this exists: the two remaining real weaknesses are MODEL behaviour, not
code -- hermes3:8b narrates tool calls in prose without emitting tool_calls,
and drifts into English when asked for Danish. Choosing a replacement by
feel repeats the mistake. This harness turns every future model choice into
a scored comparison, and (per V15.2) later becomes a permanent regression
gate: a model upgrade must BEAT the incumbent here before it ships.

    python -m app.eval_models hermes3:8b qwen3:14b qwen3:8b
    python -m app.eval_models qwen3:8b --json /tmp/eval.json
    python -m app.eval_models qwen3:8b --baseline hermes3:8b --gate

What it measures, honestly labelled:

  1. TOOL DISCIPLINE -- the headline number. Danish note-requests sent WITH
     the note_append schema: does the model emit a structured tool_call
     (good), narrate having done it in prose (the lie we saw on-device,
     worst), or just answer (a miss, but not deceptive)? Plus NEGATIVE
     cases -- greetings and factual questions where calling a tool is a
     false positive. Score = balanced accuracy over both.
  2. DANISH PERSISTENCE -- a multi-turn conversation under a "Svar altid
     paa dansk" system prompt; each reply is classified by a dependency-
     light heuristic (ae/oe/aa characters or Danish stopword majority).
     A heuristic, stated as such -- good enough to separate "Hej! Hvad kan
     jeg goere for dig?" from the English apology loops we screenshotted.
  3. SMOKE -- three objective instruction checks (exact-content answers).
     The honest limit: real answer QUALITY needs an LLM judge; that is a
     possible later step (the cloud plumbing exists), not smuggled in as
     fake precision here.

Latency is recorded per call (median reported) because "fits the 3060"
is part of the decision.

Runs against the SAME code paths the app uses (oc.chat / oc.chat_tools,
keep_alive included), sequentially per model so VRAM is not thrashed.
CI runs the scoring logic against fakes (tests/worker_eval.py); the real
run happens on the rig where Ollama and the GPU live.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import statistics
import sys
import time

from . import ollama_client as oc

# ---------------------------------------------------------------- test cases

# The one tool the harness offers -- mirrors the registry's note_append shape.
NOTE_TOOL = [{
    "type": "function",
    "function": {
        "name": "note_append",
        "description": "Tilfoej en linje til brugerens noter (notes.md).",
        "parameters": {"type": "object",
                       "properties": {"text": {"type": "string"}},
                       "required": ["text"]},
    },
}]

# Positive: an unambiguous note request -- the model SHOULD call note_append.
TOOL_POSITIVE = [
    "lav en note om at riggen er testet",
    "skriv en note: husk at købe mælk og æg",
    "notér at backup kørte fint i dag",
    "tilføj en note der siger 'agent-laget virker'",
    "skriv ned at Anders skal revokere sit PAT",
    "lav en huskeseddel-note om mødet fredag kl 10",
]

# Negative: calling ANY tool here is over-triggering (a false positive).
TOOL_NEGATIVE = [
    "hej",
    "hvad er hovedstaden i Danmark?",
    "oversæt 'god morgen' til engelsk",
    "hvad er 2+2?",
]

# Danish persistence: user turns under a Danish system prompt.
DANISH_SYSTEM = "Svar altid på dansk. Vær kortfattet."
DANISH_TURNS = [
    "hej",
    "hvad kan du hjælpe med?",
    "fortæl mig noget om København",
    "hvad er en god ret med kylling?",
    "tak, og hvad med i morgen?",
    "giv mig et godt råd til at sove bedre",
]

# Smoke: objective, exact-content instruction checks.
SMOKE = [
    ("Svar KUN med tallet, intet andet: hvad er 7*8?", lambda t: "56" in t),
    ("Svar med præcis ét ord: hvilken farve har en banan typisk?",
     lambda t: "gul" in t.lower()),
    ("Gentag præcis denne tekst og intet andet: KALIV-42",
     lambda t: "KALIV-42" in t),
]

# ------------------------------------------------------------- classifiers

_DA_HINTS = (" jeg ", " ikke ", " det ", " og ", " at ", " er ", " på ",
             " med ", " til ", " har ", " kan ", " hvad ", " en ", " den ")
_EN_HINTS = (" the ", " you ", " is ", " and ", " to ", " of ", " have ",
             " it ", " with ", " for ", " can ", " what ", " your ")

def looks_danish(text: str) -> bool:
    """Dependency-light language check. Heuristic, and says so.

    ae/oe/aa are near-conclusive for Danish; otherwise a stopword majority
    decides. Tuned against the actual replies from the device screenshots.
    """
    t = " " + text.lower() + " "
    if any(ch in t for ch in "æøå"):
        return True
    da = sum(t.count(w) for w in _DA_HINTS)
    en = sum(t.count(w) for w in _EN_HINTS)
    return da > en

# Prose that CLAIMS an action happened -- the deceptive failure mode.
_NARRATION = re.compile(
    r"jeg har (lavet|oprettet|gemt|tilføjet|skrevet)"
    r"|i('ve| have) (created|saved|made|added|written)"
    r"|note (has been|is) (created|saved|placed)", re.I)

def classify_tool_response(msg: dict) -> str:
    """'called' (structured tool_call), 'narrated' (claims it in prose --
    the lie), or 'answered' (plain reply)."""
    calls = msg.get("tool_calls") or []
    for c in calls:
        if (c.get("function") or {}).get("name") == "note_append":
            return "called"
    if calls:
        return "called_other"
    if _NARRATION.search(msg.get("content") or ""):
        return "narrated"
    return "answered"

# ------------------------------------------------------------------ runner

async def _eval_one(model: str) -> dict:
    lat: list[float] = []

    async def timed_tools(messages):
        t0 = time.perf_counter()
        msg = await oc.chat_tools(messages, tools=NOTE_TOOL, model=model)
        lat.append(time.perf_counter() - t0)
        return msg

    async def timed_chat(messages):
        t0 = time.perf_counter()
        out = await oc.chat(messages, model=model)
        lat.append(time.perf_counter() - t0)
        return out

    # 1) tool discipline
    tp = fn_narrated = fn_answered = 0
    for prompt in TOOL_POSITIVE:
        kind = classify_tool_response(await timed_tools(
            [{"role": "user", "content": prompt}]))
        if kind == "called":
            tp += 1
        elif kind == "narrated":
            fn_narrated += 1
        else:
            fn_answered += 1
    tn = 0
    for prompt in TOOL_NEGATIVE:
        kind = classify_tool_response(await timed_tools(
            [{"role": "user", "content": prompt}]))
        if kind == "answered":
            tn += 1
    tool_score = 0.5 * (tp / len(TOOL_POSITIVE)) + 0.5 * (tn / len(TOOL_NEGATIVE))

    # 2) Danish persistence (one growing conversation, like a real session)
    msgs: list[dict] = [{"role": "system", "content": DANISH_SYSTEM}]
    danish_ok = 0
    for turn in DANISH_TURNS:
        msgs.append({"role": "user", "content": turn})
        reply = await timed_chat(msgs)
        msgs.append({"role": "assistant", "content": reply})
        if looks_danish(reply):
            danish_ok += 1
    danish_score = danish_ok / len(DANISH_TURNS)

    # 3) smoke
    smoke_ok = 0
    for prompt, check in SMOKE:
        if check(await timed_chat([{"role": "user", "content": prompt}])):
            smoke_ok += 1

    return {
        "model": model,
        "tool_score": round(tool_score, 3),
        "tool_called": tp, "tool_narrated": fn_narrated,
        "tool_answered_instead": fn_answered,
        "tool_true_negative": tn,
        "danish_score": round(danish_score, 3),
        "danish_ok_turns": danish_ok, "danish_total_turns": len(DANISH_TURNS),
        "smoke_ok": smoke_ok, "smoke_total": len(SMOKE),
        "median_latency_s": round(statistics.median(lat), 2) if lat else None,
        "calls": len(lat),
    }


def _print_table(rows: list[dict]) -> None:
    hdr = f"{'model':22} {'tool':>6} {'narr.':>6} {'dansk':>6} {'smoke':>6} {'lat(s)':>7}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{r['model']:22} {r['tool_score']:>6.2f} {r['tool_narrated']:>6} "
              f"{r['danish_score']:>6.2f} {r['smoke_ok']}/{r['smoke_total']:>3} "
              f"{r['median_latency_s'] if r['median_latency_s'] is not None else '-':>7}")
    print("\ntool = balanceret score (kalder når den skal, lader være når den"
          " ikke skal).\nnarr. = gange modellen LØJ (påstod handling i prosa"
          " uden tool_call) -- lavere er bedre; 0 er kravet.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Score models on tool discipline, Danish persistence and smoke checks.")
    ap.add_argument("models", nargs="+", help="Ollama model names, e.g. hermes3:8b qwen3:14b")
    ap.add_argument("--json", metavar="PATH", help="also write results as JSON")
    ap.add_argument("--baseline", metavar="MODEL",
                    help="with --gate: the candidate(s) must beat this model")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 unless every non-baseline model beats the "
                         "baseline on tool_score AND danish_score (V15.2 mode)")
    a = ap.parse_args(argv)

    # Validate cheaply BEFORE burning eval calls.
    if a.gate and not a.baseline:
        print("--gate kræver --baseline", file=sys.stderr)
        return 2
    models = list(a.models)
    if a.baseline and a.baseline not in models:
        models = [a.baseline] + models

    rows = []
    for m in models:
        print(f"evaluerer {m} ...", file=sys.stderr)
        try:
            rows.append(asyncio.run(_eval_one(m)))
        except oc.OllamaError as e:
            print(f"FEJL: {e}\n(kører Ollama? riggen? MODELRIG_OLLAMA_URL?)",
                  file=sys.stderr)
            return 2

    _print_table(rows)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        print(f"\nJSON: {a.json}")

    if a.gate:
        if not a.baseline:
            print("--gate kræver --baseline", file=sys.stderr)
            return 2
        base = next((r for r in rows if r["model"] == a.baseline), None)
        if base is None:
            print(f"baseline {a.baseline} blev ikke evalueret", file=sys.stderr)
            return 2
        losers = [r["model"] for r in rows if r["model"] != a.baseline and not (
            r["tool_score"] > base["tool_score"]
            and r["danish_score"] >= base["danish_score"])]
        if losers:
            print(f"\nGATE: {', '.join(losers)} slår IKKE baseline "
                  f"{a.baseline} -- ingen udrulning.")
            return 1
        print(f"\nGATE: alle kandidater slår baseline {a.baseline}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Tests for eval_models.py -- the harness itself must be trustworthy before
its verdicts are. Three fake model personas (a perfect tool-caller, a narrator
that lies in prose, an English-drifter) are scored; the harness must rank them
correctly, or every future model choice built on it is built on sand."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "worker"))

passed = failed = 0
def check(cond, msg):
    global passed, failed
    if cond: passed += 1; print(f"  PASS: {msg}")
    else: failed += 1; print(f"  FAIL: {msg}")

from app import eval_models as E  # noqa: E402
from app import ollama_client as oc  # noqa: E402

# ---- unit: the Danish heuristic, tuned against the ACTUAL device replies ----
check(E.looks_danish("Hej! Hvad kan jeg gøre for dig?") is True,
      "looks_danish: real Danish reply -> True")
check(E.looks_danish("Hello! It's nice to meet you. How can I assist you today?") is False,
      "looks_danish: the English greeting from the screenshot -> False")
check(E.looks_danish("I apologize for the confusion earlier; it appears that "
                     "I initially replied in English instead of Danish.") is False,
      "looks_danish: the English apology loop -> False")
check(E.looks_danish("Det er en god idé, og jeg kan hjælpe med det.") is True,
      "looks_danish: Danish without æøå in every word still detected")

# ---- unit: tool-response classification -----------------------------------
check(E.classify_tool_response(
    {"content": "", "tool_calls": [{"function": {"name": "note_append",
                                                 "arguments": {"text": "x"}}}]}) == "called",
      "classify: structured note_append -> called")
check(E.classify_tool_response(
    {"content": "Sure, I've created a new note with your request."}) == "narrated",
      "classify: the on-device lie ('I've created') -> narrated")
check(E.classify_tool_response(
    {"content": "Jeg har lavet noten til dig."}) == "narrated",
      "classify: Danish narration -> narrated")
check(E.classify_tool_response({"content": "Hovedstaden er København."}) == "answered",
      "classify: a plain answer -> answered")

# ---- personas: the harness must rank them correctly ------------------------
def _persona(tool_behaviour: str, language: str):
    """Build fake oc.chat_tools/oc.chat implementing one persona."""
    async def fake_tools(messages, tools=None, model=None, base_url=None, api_key=None):
        prompt = messages[-1]["content"]
        wants_note = any(w in prompt for w in ("note", "notér", "husk", "skriv ned"))
        if wants_note and tool_behaviour == "caller":
            return {"content": "", "tool_calls": [
                {"function": {"name": "note_append", "arguments": {"text": prompt}}}]}
        if wants_note and tool_behaviour == "narrator":
            return {"content": "Sure, I've created a new note for you!"}
        return {"content": "Hej! Det kan jeg svare på." if language == "da"
                else "Hello! I can answer that."}
    async def fake_chat(messages, model=None):
        if language == "da":
            return "Selvfølgelig — her er et kort dansk svar på det."
        return "Of course — here is a short answer for you."
    return fake_tools, fake_chat

def _run(model_name, tool_behaviour, language):
    ft, fc = _persona(tool_behaviour, language)
    orig_t, orig_c = oc.chat_tools, oc.chat
    oc.chat_tools, oc.chat = ft, fc
    try:
        return asyncio.run(E._eval_one(model_name))
    finally:
        oc.chat_tools, oc.chat = orig_t, orig_c

perfect = _run("perfect", "caller", "da")
narrator = _run("narrator", "narrator", "en")
drifter = _run("drifter", "caller", "en")

check(perfect["tool_score"] == 1.0,
      f"persona: the perfect caller scores 1.0 tool (got {perfect['tool_score']})")
check(perfect["danish_score"] == 1.0, "persona: the Danish speaker scores 1.0 dansk")
check(perfect["tool_narrated"] == 0, "persona: the honest model never narrates")

check(narrator["tool_narrated"] == len(E.TOOL_POSITIVE),
      "persona: the narrator is caught lying on every positive case")
check(narrator["tool_score"] < perfect["tool_score"],
      "persona: narrating scores below calling")

check(drifter["danish_score"] == 0.0,
      "persona: the English-drifter scores 0.0 dansk")
check(drifter["tool_score"] == 1.0,
      "persona: language and tool discipline are measured independently")

# ---- smoke scoring: objective checks actually check ------------------------
async def _smoke_chat_ok(messages, model=None):
    p = messages[-1]["content"]
    if "7*8" in p: return "56"
    if "banan" in p: return "Gul"
    if "KALIV-42" in p: return "KALIV-42"
    return "..."
oc_chat_orig = oc.chat
oc.chat = _smoke_chat_ok
async def _tools_noop(messages, tools=None, model=None, base_url=None, api_key=None):
    return {"content": "svar"}
oc_tools_orig = oc.chat_tools
oc.chat_tools = _tools_noop
try:
    r = asyncio.run(E._eval_one("smoke"))
finally:
    oc.chat, oc.chat_tools = oc_chat_orig, oc_tools_orig
check(r["smoke_ok"] == len(E.SMOKE), "smoke: correct answers all pass the checks")

# ---- gate logic -------------------------------------------------------------
rows_beats = [{"model": "base", "tool_score": 0.5, "danish_score": 0.5},
              {"model": "cand", "tool_score": 0.9, "danish_score": 0.8}]
rows_loses = [{"model": "base", "tool_score": 0.5, "danish_score": 0.5},
              {"model": "cand", "tool_score": 0.4, "danish_score": 0.9}]
def _gate(rows, baseline="base"):
    base = next(r for r in rows if r["model"] == baseline)
    return [r["model"] for r in rows if r["model"] != baseline and not (
        r["tool_score"] > base["tool_score"]
        and r["danish_score"] >= base["danish_score"])]
check(_gate(rows_beats) == [], "gate: a candidate beating baseline passes")
check(_gate(rows_loses) == ["cand"], "gate: a candidate losing on tool_score is named")

print(f"\n===== EVAL: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

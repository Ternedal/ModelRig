#!/usr/bin/env python3
import os, tempfile

# isolated db + point Ollama at a dead port so upstream calls fail fast
os.environ["MODELRIG_DB"] = tempfile.mktemp(suffix=".db")
os.environ["MODELRIG_OLLAMA_URL"] = "http://127.0.0.1:9"   # nothing listening
os.environ["MODELRIG_OLLAMA_TIMEOUT"] = "3"

from fastapi.testclient import TestClient
from app.main import app
from app.rag import cosine, chunk_text

passed = failed = 0
def check(cond, name):
    global passed, failed
    print(f"  {'PASS' if cond else 'FAIL'}: {name}")
    passed += cond; failed += (not cond)

# 1. cosine pure-function sanity
check(abs(cosine([1,0,0],[1,0,0]) - 1.0) < 1e-9, "cosine identical -> 1.0")
check(abs(cosine([1,0],[0,1]) - 0.0) < 1e-9, "cosine orthogonal -> 0.0")
check(cosine([1,2],[1,2,3]) == 0.0, "cosine mismatched dims -> 0.0")
check(cosine([], [1]) == 0.0, "cosine empty -> 0.0")

# 1b. chunk_text: short text passes through untouched
check(chunk_text("hej verden") == ["hej verden"], "chunk_text short text -> single chunk")
check(chunk_text("") == [], "chunk_text empty -> no chunks")

# 1c. chunk_text: prefers a sentence boundary over a mid-sentence space when
# one exists within the overlap window -- this is the actual behavior change,
# not just "some chunking happens". Construct text where a ". " sits well
# inside the back-half search window and a plain space does not offer a
# better (later) break point beyond it.
sentence_text = ("Første sætning er kort. " + "A" * 40 + " midt i anden sætning " + "B" * 40 + ".")
chunks = chunk_text(sentence_text, chunk_size=60, overlap=10)
check(chunks[0].endswith("."), f"chunk_text breaks at sentence end, not mid-word -> got chunk: {chunks[0]!r}")
check(chunks[0] == "Første sætning er kort.", f"chunk_text first chunk is exactly the first sentence -> got {chunks[0]!r}")

# 1d. chunk_text: falls back to whitespace when no sentence boundary exists
# in the window (proves the fallback path still works, not just the new one)
space_text = "AAAA BBBB CCCC DDDD EEEE FFFF GGGG HHHH IIII JJJJ KKKK"
chunks2 = chunk_text(space_text, chunk_size=20, overlap=5)
check(all(" " not in c[-1:] for c in chunks2), f"chunk_text (no sentence boundary) still breaks cleanly on whitespace, no trailing space -> {chunks2}")
check(len(chunks2) > 1, "chunk_text (no sentence boundary) still splits long text into multiple chunks")

client = TestClient(app, client=("127.0.0.1", 12345))

# 2. health
r = client.get("/healthz")
check(r.status_code == 200 and r.json()["service"] == "modelrig-worker", "GET /healthz -> 200")
print("    ", r.json())

# 3. validation (missing 'query')
r = client.post("/rag/query", json={})
check(r.status_code == 422, "POST /rag/query missing query -> 422 (validation)")

# 4. top_k bounds
r = client.post("/rag/query", json={"query": "x", "top_k": 999})
check(r.status_code == 422, "POST /rag/query top_k>20 -> 422")

# 5. Ollama down -> clean 502 (not a crash)
r = client.post("/rag/query", json={"query": "what is modelrig?"})
check(r.status_code == 502, "POST /rag/query, ollama down -> 502")
print("    detail:", r.json().get("detail", "")[:80])

r = client.post("/rag/ingest", json={"documents": [{"text": "hello", "source": "t"}]})
check(r.status_code == 502, "POST /rag/ingest, ollama down -> 502")

# 6. Voice: markdown must not be read aloud. The LLM writes **bold**, `code`
# and bullets; Piper would speak the asterisks. Strip for SPEECH only -- the
# chat still shows the markdown. Anders hit this on 2026-07-09.
from app.voice_pipeline import strip_markdown

check(strip_markdown("**Hej** Anders!") == "Hej Anders!", "strip_markdown: bold")
check(strip_markdown("Det er *vigtigt*.") == "Det er vigtigt.", "strip_markdown: italic")
check(strip_markdown("Brug `pip install` nu.") == "Brug pip install nu.", "strip_markdown: inline code")
check(strip_markdown("### Overskrift") == "Overskrift", "strip_markdown: heading")
check(strip_markdown("- et punkt") == "et punkt", "strip_markdown: bullet")
check(strip_markdown("Se [docs](https://x.dk).") == "Se docs.", "strip_markdown: link keeps text")
# Ordinary text must survive untouched.
check(strip_markdown("Regn 5 * 3 ud.") == "Regn 5 * 3 ud.", "strip_markdown: spaced asterisk survives")
check(strip_markdown("min_fil_navn.txt") == "min_fil_navn.txt", "strip_markdown: underscores in a word survive")
# Unspeakable structures are dropped, not read pipe by pipe.
check(strip_markdown("| GPU | RTX 3060 |") == "", "strip_markdown: table row dropped")
check(strip_markdown("```\nkode\n```") == "", "strip_markdown: code fence dropped")

# ---------------------------------------------------------------------------
# Kaliv rename: KALIV_* wins, ALVA_* still works, defaults survive.
# Anders' rig has ALVA_* in shell history and docs -- a hard rename would
# break a working setup for no gain.
# ---------------------------------------------------------------------------
import os as _os
from app.env_compat import env as _env, legacy_names_in_use as _legacy

for _k in [k for k in _os.environ if k.startswith(("ALVA_", "KALIV_"))]:
    del _os.environ[_k]

check(_env("ASR_MODEL", "large-v3") == "large-v3", "env: default when nothing set")

_os.environ["ALVA_ASR_MODEL"] = "small"
check(_env("ASR_MODEL", "large-v3") == "small", "env: legacy ALVA_* still honoured")

_os.environ["KALIV_ASR_MODEL"] = "medium"
check(_env("ASR_MODEL", "large-v3") == "medium", "env: KALIV_* wins over ALVA_*")

check(_legacy() == [], "env: legacy list empty when KALIV_* shadows ALVA_*")

_os.environ["ALVA_TTS_VOICE"] = "da_DK-talesyntese-medium"
check(_legacy() == ["ALVA_TTS_VOICE"], "env: unshadowed legacy name is reported")

# An explicitly empty value is a choice, not an absence.
_os.environ["KALIV_ASR_DEVICE"] = ""
check(_env("ASR_DEVICE", "cuda") == "", "env: empty string counts as set")

for _k in [k for k in _os.environ if k.startswith(("ALVA_", "KALIV_"))]:
    del _os.environ[_k]

# --- /health/full: the one-call rig verdict (v1.31.0) --------------------
import asyncio as _aio  # noqa: E402
from app import main as _M  # noqa: E402

h = _aio.run(_M.health_full())
check("checks" in h and "ok" in h and "faults" in h,
      "health_full: returns overall verdict + per-subsystem checks")
for sub in ("worker", "ollama", "asr", "tts", "tools", "disk"):
    check(sub in h["checks"], f"health_full: reports {sub}")
    check("ok" in h["checks"][sub], f"health_full: {sub} has an ok verdict")

# The worker itself is always up if this runs, and reports its doc count.
check(h["checks"]["worker"]["ok"] is True, "health_full: worker check is up")
check("documents" in h["checks"]["worker"], "health_full: worker reports document count")

# A subsystem down for a real reason names the reason -- no reason is another
# round of guessing during a device test.
if not h["checks"]["asr"]["ok"]:
    check(h["checks"]["asr"]["detail"] is not None, "health_full: a down subsystem says why")

# Tools state is surfaced (off by default), and does NOT count as a fault: a
# layer off by choice must not drag the rig to unhealthy.
check("enabled" in h["checks"]["tools"], "health_full: surfaces the tools kill-switch state")
check("tools" not in h["faults"], "health_full: tools-off is not a fault")

# The disk check must actually compute, not raise -- it referenced a name that
# was never imported at module scope (os vs _os), caught here before shipping.
check(h["checks"]["disk"].get("detail") != "name 'os' is not defined",
      "health_full: disk check runs (os import bug would surface here)")
check(h["checks"]["disk"]["ok"] in (True, False), "health_full: disk check has a verdict")

# overall ok == no faults among the real subsystems
faults = [k for k in ("worker","ollama","asr","tts","disk") if not h["checks"][k]["ok"]]
check(h["ok"] == (not faults), "health_full: overall ok iff no real subsystem faults")

# ---------------------------------------------------------------------------
# Loopback guard: the worker has no auth of its own, so a non-loopback client
# must be refused (403) unless KALIV_WORKER_ALLOW_LAN=1. The backend reaches the
# worker on localhost, so this never affects the real path.
# ---------------------------------------------------------------------------
from app.main import _is_loopback

check(_is_loopback("127.0.0.1") and _is_loopback("::1") and _is_loopback("localhost"),
      "loopback guard: 127.0.0.1 / ::1 / localhost count as loopback")
check(not _is_loopback("192.168.1.50") and not _is_loopback("10.0.0.2"),
      "loopback guard: LAN addresses do not count as loopback")

os.environ.pop("KALIV_WORKER_ALLOW_LAN", None)
_lan = TestClient(app, client=("192.168.1.50", 40000))
check(_lan.get("/healthz").status_code == 403,
      "loopback guard: a LAN client is refused (403) by default")
_loop = TestClient(app, client=("127.0.0.1", 40000))
check(_loop.get("/healthz").status_code == 200,
      "loopback guard: a loopback client is served")
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
check(_lan.get("/healthz").status_code == 200,
      "loopback guard: KALIV_WORKER_ALLOW_LAN=1 lets a LAN client through")
os.environ.pop("KALIV_WORKER_ALLOW_LAN", None)

print(f"\n===== WORKER: {passed} passed, {failed} failed =====")
raise SystemExit(0 if failed == 0 else 1)

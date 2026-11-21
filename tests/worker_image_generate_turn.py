#!/usr/bin/env python3
"""``image_generate`` inside a real tool turn (#2419 slice A): the lift to ``media_jobs``.

Drives ``/tools/chat`` and ``/tools/chat/stream`` with a scripted model
(``oc.chat_tools`` stubbed, as ``worker_agent_multistep.py`` does) and the tool
registered against a real ``MediaJobService`` over a temporary store. Asserts:

1. A read tool: no confirmation card; the turn ends ``answered`` with
   ``image_generate`` in ``tools_used``.
2. The turn result carries ``media_jobs`` with exactly the queued job
   (id, ``status_url``, profile), and the same object is on the last
   ``result`` line of the stream.
3. A turn with no image request still carries ``media_jobs: []`` (additive
   wire field, always present on an answered turn).
4. The "not available" path (job API switched off): the turn still answers,
   ``media_jobs`` is empty, nothing was queued, no HTTP error.
5. The gate is honoured on the wire: with the tool unregistered the model's
   call for it is an unknown tool (404), exactly as for any other absent tool.
6. Nothing in the result object repeats the prompt.

Run: PYTHONPATH=worker python3 tests/worker_image_generate_turn.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
os.environ.pop("KALIV_ALLOW_RAG_CLOUD", None)
os.environ.pop("KALIV_IMAGE_TOOL_ENABLED", None)  # registered by hand below, with a test service
_tmp = tempfile.mkdtemp(prefix="kaliv-igturn-")
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app import tools  # noqa: E402
from app import image_generate_tool as igt  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_job_api import OWNER, MediaJobService  # noqa: E402
from worker_media_generation_profiles import image_profile  # noqa: E402

client = TestClient(main.app)
passed = failed = 0
PROMPT = "a man by a lake, a swan in the background, photo, 35mm"


def check(cond, name):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS: {name}")
    else:
        failed += 1
        print(f"  FAIL: {name}")


def call(name, args=None):
    return {"tool_calls": [{"function": {"name": name, "arguments": args or {}}}], "content": ""}


def answer(text):
    return {"tool_calls": [], "content": text}


seen_messages: list[list[dict]] = []


def script(responses):
    seq = list(responses)

    async def _mock(messages, *a, **k):
        seen_messages.append(list(messages))
        return seq.pop(0) if seq else answer("done")

    main.oc.chat_tools = _mock


def system_texts() -> list[str]:
    return [m["content"] for m in (seen_messages[-1] if seen_messages else []) if m.get("role") == "system"]


def chat(msg="lav et billede af en mand ved en sø"):
    return client.post("/tools/chat", json={"message": msg, "model": "qwen3:14b"})


def stream(msg="lav et billede af en mand ved en sø"):
    with client.stream("POST", "/tools/chat/stream", json={"message": msg, "model": "qwen3:14b"}) as r:
        lines = [json.loads(line) for line in r.iter_lines() if line]
    return lines


# A real service over a temporary store, injected through the run's service_getter.
store = ImageJobStore(os.path.join(_tmp, "jobs.sqlite3"))
service = MediaJobService(store, {"sdxl-a": parse_profile(image_profile(profile_id="sdxl-a"))}, "s" * 40)


def run_with_service(args):
    return igt._run_image_generate(args, service_getter=lambda: service, env={})


def run_unavailable(args):
    return igt._run_image_generate(args, service_getter=None, env={})


def register(run):
    tools.REGISTRY.pop(igt.TOOL_NAME, None)
    import dataclasses
    tools.REGISTRY[igt.TOOL_NAME] = dataclasses.replace(igt.IMAGE_GENERATE_CAPABILITY, run=run)


try:
    # 1 + 2 + 6: a read tool that queues a job; the lift on both endpoints.
    register(run_with_service)
    script([call("image_generate", {"prompt": PROMPT}), answer("Billedet er på vej.")])
    d = chat().json()
    check(d.get("status") == "answered", f"read tool: turn ends answered (got {d.get('status')})")
    check(d.get("tools_used") == ["image_generate"], "image_generate counted as executed")
    jobs = d.get("media_jobs")
    check(isinstance(jobs, list) and len(jobs) == 1, f"media_jobs carries exactly one job (got {jobs!r})")
    job = (jobs or [{}])[0]
    check(set(job) == {"job_id", "kind", "state", "profile_id", "status_url"} and job.get("kind") == "image",
          "media_jobs entry has the five fields, kind=image")
    check(job.get("profile_id") == "sdxl-a" and job.get("state") == "queued", "entry names profile and state")
    check(job.get("status_url") == f"/api/v1/media/jobs/{job.get('job_id')}", "status_url is the job route")
    stored = store.get(job.get("job_id", ""), OWNER) if job.get("job_id") else None
    check(stored is not None and stored["state"] == "queued", "the referenced job exists in the store for OWNER")
    check(PROMPT not in json.dumps(d, ensure_ascii=False), "result object never repeats the prompt")
    check(any(igt.SYSTEM_RULE == t for t in system_texts()), "slice C: the image rule is in the system prompt while registered")
    check(system_texts().index(igt.SYSTEM_RULE) == 1 if igt.SYSTEM_RULE in system_texts() else False,
          "the rule follows the tool nudge, before any persona text")

    script([call("image_generate", {"prompt": PROMPT}), answer("På vej.")])
    lines = stream()
    phases = [line["phase"] for line in lines if "phase" in line]
    result = [line["result"] for line in lines if "result" in line]
    check("tool_run" in phases and phases[0] == "generating", f"stream carries phases (got {phases})")
    check(len(result) == 1 and len(result[0].get("media_jobs", [])) == 1,
          "stream's result line carries media_jobs")
    streamed = (result[0].get("media_jobs") or [{}])[0] if result else {}
    check(bool(streamed.get("job_id")) and streamed.get("job_id") != job.get("job_id"),
          "the streamed turn queued its own, second job")

    # 3: no image asked for -> media_jobs present and empty.
    script([call("current_datetime"), answer("klokken er …")])
    d = chat("hvad er klokken").json()
    check(d.get("status") == "answered" and d.get("media_jobs") == [],
          "a turn without image_generate carries media_jobs: []")
    script([answer("bare tekst")])
    d = chat("hej").json()
    check(d.get("media_jobs") == [], "a plain answer carries media_jobs: []")
    check(d.get("media_refusals") == [], "and media_refusals: []")

    # 3a: the model gets an argument wrong (a number as text, a made-up field), is told so,
    # and calls again in the same turn. Before, the first call ended the turn with HTTP 400.
    # Its own store: the owner's limit is three active jobs, and the cases around this one count.
    retry_service = MediaJobService(ImageJobStore(os.path.join(_tmp, "retry.sqlite3")), dict(service.profiles), "s" * 40)
    register(lambda args: igt._run_image_generate(args, service_getter=lambda: retry_service, env={}))
    script([call("image_generate", {"prompt": PROMPT, "width": "bred", "style": "photo"}),
            call("image_generate", {"prompt": PROMPT}), answer("Billedet er på vej.")])
    r = chat()
    d = r.json()
    check(r.status_code == 200 and d.get("status") == "answered", f"an argument mistake does not end the turn (got {r.status_code})")
    check(len(d.get("media_jobs") or []) == 1, "the corrected call queued the picture")
    check(d.get("media_refusals") == [{"tool": "image_generate", "code": "invalid_arguments"}],
          f"the refused call is listed with its code (got {d.get('media_refusals')!r})")
    check(d.get("tools_used") == ["image_generate", "image_generate"], "both calls are in tools_used")
    register(run_with_service)

    # 3b: a picture, then a write that needs approval, in one turn. The picture is
    # already rendering, so its reference must ride on the confirmation answer too.
    script([call("image_generate", {"prompt": PROMPT}), call("note_append", {"text": "husk billedet"})])
    d = chat("lav et billede og skriv en note om det").json()
    check(d.get("status") == "confirmation_required", f"a write after the picture asks for approval (got {d.get('status')})")
    check(len(d.get("media_jobs") or []) == 1 and d["media_jobs"][0].get("kind") == "image",
          "the confirmation answer still carries the picture's job reference")
    check(d.get("tools_used") == ["image_generate"], "and says the picture tool already ran")

    # 4: the tool is registered but the job API is off -> text, no job, no error.
    register(run_unavailable)
    before = store.get(job.get("job_id", ""), OWNER)
    script([call("image_generate", {"prompt": PROMPT}), answer("Det kan jeg ikke lige nu.")])
    r = chat()
    d = r.json()
    check(r.status_code == 200 and d.get("status") == "answered", "unavailable: the turn still answers (no HTTP error)")
    check(d.get("media_jobs") == [], "unavailable: media_jobs is empty")
    check(d.get("media_refusals") == [{"tool": "image_generate", "code": "media_jobs_api_off"}],
          f"unavailable: the reason is on the wire, not only in the model's words (got {d.get('media_refusals')!r})")
    check(d.get("tools_used") == ["image_generate"], "unavailable: the tool ran and answered as text")
    check(before is not None, "unavailable: previously queued job untouched")

    # 7 (#2462 review, Codex P2): a job queued in the turn survives a failed follow-up. The
    #    render is already running; a 502 threw its reference away and a retry queued a second one.
    #    A store of its own: the owner's active-job limit is three, and the cases above used it.
    fresh_db = os.path.join(_tmp, "jobs-followup.sqlite3")
    fresh = MediaJobService(ImageJobStore(fresh_db), {"sdxl-a": parse_profile(image_profile(profile_id="sdxl-a"))}, "s" * 40)

    def run_fresh(args):
        return igt._run_image_generate(args, service_getter=lambda: fresh, env={})

    def new_store():
        nonlocal_db = os.path.join(_tmp, f"jobs-followup-{len(os.listdir(_tmp))}.sqlite3")
        service_n = MediaJobService(ImageJobStore(nonlocal_db), {"sdxl-a": parse_profile(image_profile(profile_id="sdxl-a"))}, "s" * 40)
        register(lambda args: igt._run_image_generate(args, service_getter=lambda: service_n, env={}))
        return nonlocal_db

    register(run_fresh)

    def failing_after(first, error):
        seq = [first]

        async def _mock(messages, *a, **k):
            if seq:
                return seq.pop(0)
            raise error
        main.oc.chat_tools = _mock

    def queued_count():
        import sqlite3
        with sqlite3.connect(fresh_db) as conn:
            return conn.execute("SELECT COUNT(*) FROM image_jobs").fetchone()[0]

    count = queued_count()
    failing_after(call("image_generate", {"prompt": PROMPT}), main.oc.OllamaError("cannot reach Ollama at http://127.0.0.1:11434: boom"))
    r = chat()
    d = r.json()
    check(r.status_code == 200 and d.get("status") == "answered", f"follow-up fails: the turn is answered, not 502 (got {r.status_code})")
    check(len(d.get("media_jobs") or []) == 1 and d["media_jobs"][0]["kind"] == "image", "follow-up fails: the queued job's reference is on the turn")
    check(d.get("answer") == "Billedet er på vej — det vises her, når det er færdigt." and d.get("answer_fallback") == "model_unavailable",
          f"follow-up fails: a fixed sentence and the reason as a code (got {d.get('answer')!r}, {d.get('answer_fallback')!r})")
    check("11434" not in json.dumps(d) and "boom" not in json.dumps(d), "follow-up fails: no exception text on the wire")
    check(queued_count() == count + 1, "follow-up fails: exactly one job was queued")
    new_store()
    failing_after(call("image_generate", {"prompt": PROMPT}), main.oc.OllamaError("down"))
    lines = stream()
    check("error" not in lines[-1] and len(lines[-1].get("result", {}).get("media_jobs") or []) == 1,
          f"follow-up fails on the stream: a result line with the reference, not an error line (got {list(lines[-1])})")
    # a later call for a tool that does not exist, or with broken arguments: the queued job stands
    new_store()
    script([call("image_generate", {"prompt": PROMPT}), call("no_such_tool", {})])
    d = chat().json()
    check(d.get("status") == "answered" and len(d.get("media_jobs") or []) == 1 and d.get("answer_fallback") == "tool_denied",
          f"a refused later call keeps the queued job (got {d.get('status')!r}, {d.get('answer_fallback')!r})")
    new_store()
    script([call("image_generate", {"prompt": PROMPT}),
            {"tool_calls": [{"function": {"name": "image_generate", "arguments": "{not json"}}], "content": ""}])
    d = chat().json()
    check(len(d.get("media_jobs") or []) == 1 and d.get("answer_fallback") == "tool_arguments_invalid", "broken arguments in a later call keep the queued job")
    # nothing queued: the failure is still a failure

    async def _always_down(messages, *a, **k):
        raise main.oc.OllamaError("down")
    main.oc.chat_tools = _always_down
    r = chat()
    check(r.status_code == 502, f"nothing queued: a model failure is still 502 (got {r.status_code})")
    script([call("no_such_tool", {})])
    check(chat().status_code == 404, "nothing queued: an unknown tool is still 404")
    script([answer("hej")])
    check("answer_fallback" not in chat().json(), "an ordinary turn has no fallback marker")

    # 5: unregistered -> unknown tool on the wire, and no rule in the system prompt.
    tools.REGISTRY.pop(igt.TOOL_NAME, None)
    script([call("image_generate", {"prompt": PROMPT})])
    r = chat()
    check(r.status_code == 404, f"gate off: image_generate is an unknown tool (got {r.status_code})")
    check(igt.SYSTEM_RULE not in system_texts(), "gate off: the model is not told about image_generate")
    check(igt.system_rule_if_registered() is None, "system_rule_if_registered follows REGISTRY, not the flag")
finally:
    tools.REGISTRY.pop(igt.TOOL_NAME, None)
    shutil.rmtree(_tmp, ignore_errors=True)

print(f"\n===== IMAGE GENERATE TURN: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

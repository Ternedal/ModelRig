#!/usr/bin/env python3
"""``video_generate``: text-to-video from the chat turn, on the image tool's seam.

Proves what differs from ``image_generate`` (everything shared is proven in
``worker_image_generate_tool.py``):

1. Own gate ``KALIV_VIDEO_TOOL_ENABLED`` (literal ``1``), own registration, own
   system rule that follows REGISTRY.
2. Contract: read, not idempotent, not schedulable, network none; ``frames`` and
   ``source_image_job_id`` are accepted arguments; the description names both ways.
3. Run: with ``video_enabled`` the job is queued as ``text_to_video`` for OWNER
   with a ``kaliv-video-job-ref/v1`` reference carrying ``kind=video``; the
   stored params carry the task and frames; an image profile is never chosen.
4. Rig-side refusals as text: ``KALIV_MEDIA_VIDEO`` off -> ``video_not_enabled``;
   no video profile -> ``no_video_profile``; the task is never a model argument.
4c. Two video profiles, one per task: the profile is chosen among those that
   list the task; a default configured for the other task does not capture it.
4b. Image-to-video: ``source_image_job_id`` naming OWNER's completed image job is
   queued as ``image_to_video`` with ``input_asset_id``; unknown / unfinished /
   non-image / foreign jobs are text codes, never a queued job; a profile that
   does not list the task is refused by the API (``task_not_served``). The word
   ``latest`` names the owner's newest finished picture (what a later turn uses).
5. The lift: ``parse_job_reference`` reads a video reference with kind=video,
   and the turn result's ``media_jobs`` carries it (through /tools/chat).

Run: PYTHONPATH=worker python3 tests/worker_video_generate_tool.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-vgt-")
os.environ["KALIV_TOOLS_ENABLED"] = "1"
os.environ["KALIV_WORKER_ALLOW_LAN"] = "1"
os.environ.pop("KALIV_VIDEO_TOOL_ENABLED", None)
os.environ.pop("KALIV_IMAGE_TOOL_ENABLED", None)
os.environ["KALIV_TOOLS_DIR"] = os.path.join(_tmp, "notes")
os.environ["KALIV_AUDIT_DB"] = os.path.join(_tmp, "audit.db")
os.makedirs(os.environ["KALIV_TOOLS_DIR"], exist_ok=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app import tools  # noqa: E402
from app import video_generate_tool as vgt  # noqa: E402
from app.image_generate_tool import parse_job_reference  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_job_api import OWNER, MediaJobService  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

passed = failed = 0
SECRET = "s" * 40
PROMPT = "a paper boat drifting across a pond, soft light, one slow pan"


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def service_with(*profiles, video_enabled=True) -> MediaJobService:
    tmp = Path(tempfile.mkdtemp(prefix="kaliv-vgt-svc-"))
    store = ImageJobStore(str(tmp / "jobs.sqlite3"))
    return MediaJobService(store, {p.profile_id: p for p in profiles}, SECRET, video_enabled=video_enabled)


VID = parse_profile(video_profile(profile_id="wan-t2v"))
IMG = parse_profile(image_profile(profile_id="sdxl-a"))

# 1. gate + registration + rule
print("== 1. gate ==")
saved = tools.REGISTRY.pop(vgt.TOOL_NAME, None)
try:
    check(vgt.video_tool_enabled() is False and vgt.register_video_generate_tool() is False, "no flag: off, register refuses")
    check(vgt.system_rule_if_registered() is None, "no registration: no system rule")
    for value in ("", "0", "true", "yes", "TRUE"):
        os.environ["KALIV_VIDEO_TOOL_ENABLED"] = value
        check(vgt.video_tool_enabled() is False, f"flag={value!r} is not opt-in")
    os.environ["KALIV_VIDEO_TOOL_ENABLED"] = "1"
    check(vgt.register_video_generate_tool() is True and tools.REGISTRY[vgt.TOOL_NAME].run is vgt._run_video_generate,
          "flag=1: registered with its run")
    check(vgt.system_rule_if_registered() == vgt.SYSTEM_RULE and "video" in vgt.SYSTEM_RULE, "registered: system rule present")
    check(vgt.register_video_generate_tool() is True, "idempotent")
    tools.REGISTRY[vgt.TOOL_NAME] = tools.Tool(name=vgt.TOOL_NAME, risk="read", description="x", network="none", run=lambda a: "")
    try:
        vgt.register_video_generate_tool(); check(False, "shadowing refused")
    except RuntimeError:
        check(True, "shadowing refused")
finally:
    tools.REGISTRY.pop(vgt.TOOL_NAME, None)
    os.environ.pop("KALIV_VIDEO_TOOL_ENABLED", None)

# 2. contract
print("== 2. contract ==")
cap = vgt.VIDEO_GENERATE_CAPABILITY
check(cap.risk == "read" and cap.impact == "read" and cap.idempotent is False, "read, not idempotent")
check(cap.schedulable is False and cap.network == "none" and cap.sensitivity == "private", "not schedulable, local, private")
check(set(cap.params["properties"]) == {"prompt", "profile_id", "width", "height", "frames", "seed", "source_image_job_id"}
      and cap.params["required"] == ["prompt"], "argument surface incl. frames + source_image_job_id; prompt required")
check("source_image_job_id" in cap.description and "Never claim it is finished" in cap.description
      and "cannot animate" not in cap.description, "description: both ways, on-its-way rule, no stale refusal")
check("source_image_job_id" in vgt.SYSTEM_RULE and "cannot animate" not in vgt.SYSTEM_RULE, "system rule names i2v")
check(tools.requires_confirmation(cap, origin="model") is False, "no confirmation card")

# 3. run
print("== 3. run ==")
svc = service_with(VID, IMG)
out = vgt._run_video_generate({"prompt": PROMPT, "frames": 33, "seed": 5}, service_getter=lambda: svc, env={})
ref = parse_job_reference(out)
check(ref is not None and ref["kind"] == "video", "video reference lifted with kind=video")
check(ref is not None and ref["profile_id"] == "wan-t2v", "the sole video profile chosen; the image profile never is")
job = svc.store.get(ref["job_id"], OWNER) if ref else None
params = json.loads(job["params"]) if job and isinstance(job.get("params"), str) else (job or {}).get("params") or {}
check(job is not None and job["state"] == "queued", "job queued for OWNER")
check(params.get("task") == "text_to_video" and params.get("frames") == 33 and params.get("seed") == 5,
      "stored params carry task=text_to_video, frames, seed")
check(PROMPT not in out and "minutter" in out and "på vej" in out, "text: minutes, on its way, no prompt")
check('"schema": "kaliv-video-job-ref/v1"' in out.split("\n", 1)[0], "first line is the video job-ref schema")

# 4. rig-side refusals as text
print("== 4. refusals ==")
svc_off = service_with(VID, video_enabled=False)
o = vgt._run_video_generate({"prompt": PROMPT}, service_getter=lambda: svc_off, env={})
check("video_not_enabled" in o and parse_job_reference(o) is None, "KALIV_MEDIA_VIDEO off -> video_not_enabled as text")
svc_img = service_with(IMG)
o = vgt._run_video_generate({"prompt": PROMPT}, service_getter=lambda: svc_img, env={})
check("no_video_profile" in o, "only image profiles -> no_video_profile")
o = vgt._run_video_generate({"prompt": PROMPT, "profile_id": "sdxl-a"}, service_getter=lambda: svc, env={})
check("profile_not_enabled" in o, "an explicit image profile is refused for video")
o = vgt._run_video_generate({"prompt": PROMPT}, service_getter=None, env={})
check("media_jobs_api_off" in o, "job API off -> text")
check(o.startswith("Videogenerering er ikke tilgængelig") and "Billedgenerering" not in o,
      "a refused clip is said to be video, not picture, generation")
o_src = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": "latest"}, service_getter=lambda: svc_img, env={})
check(o_src.startswith("Videogenerering blev ikke startet (no_source_image)") and "Billedgenerering" not in o_src,
      "and so is a refused source, which says what is missing")
for bad, label in (({"prompt": PROMPT, "input_asset_id": "x"}, "asset ids are never a model argument"),
                   ({"prompt": PROMPT, "task": "image_to_video"}, "task cannot be chosen by the model"),
                   ({"prompt": PROMPT, "source_image_job_id": 7}, "source must be a string"),
                   ({"prompt": PROMPT, "frames": "mange"}, "frames must be a number"),
                   ({}, "prompt missing")):
    # Refused as text, not ToolDenied: that would end the turn with HTTP 400 for the
    # likeliest mistake a small model makes. Nothing is queued either way.
    svc_bad = service_with(VID)
    o_bad = vgt._run_video_generate(bad, service_getter=lambda: svc_bad, env={})
    check("invalid_arguments" in o_bad and parse_job_reference(o_bad) is None
          and "video_generate igen" in o_bad,
          f"{label}: refused as text, call again")
    with sqlite3.connect(svc_bad.store.path) as _db:
        check(_db.execute("SELECT COUNT(*) FROM image_jobs").fetchone()[0] == 0, f"{label}: nothing queued")
try:
    vgt._run_video_generate("not a dict", service_getter=lambda: svc, env={}); check(False, "args not an object: ToolDenied")
except tools.ToolDenied:
    check(True, "args not an object: ToolDenied")

# 4b. image-to-video from a picture of this conversation
print("== 4b. image-to-video ==")
EXECUTOR = "GPU-" + "0" * 8 + "-0000-0000-0000-" + "0" * 12 + ":" + "a" * 16


def finish_image(service: MediaJobService, owner: str, asset_id: str) -> str:
    jid = service.store.submit(owner, "a paper boat", profile_id="sdxl-a", params={})["job_id"]
    assert service.store.claim_for(["sdxl-a"], EXECUTOR)["id"] == jid
    assert service.store.begin_publish(jid, EXECUTOR) and service.store.complete(jid, EXECUTOR, asset_id)
    time.sleep(0.02)  # request times order "latest"; keep two of them apart on a coarse clock
    return jid


svc2 = service_with(VID, IMG)
mine = finish_image(svc2, OWNER, "img_mine")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": mine}, service_getter=lambda: svc2, env={})
ref2 = parse_job_reference(o)
check(ref2 is not None and ref2["kind"] == "video" and ref2["profile_id"] == "wan-t2v", "own completed image -> video job queued")
job2 = svc2.store.get(ref2["job_id"], OWNER) if ref2 else None
p2 = json.loads(job2["params"]) if job2 and isinstance(job2.get("params"), str) else (job2 or {}).get("params") or {}
check(p2.get("task") == "image_to_video" and p2.get("input_asset_id") == "img_mine", "stored params: task=image_to_video, input_asset_id")
check("img_mine" not in o and mine not in o.split("\n", 1)[1], "text never repeats asset or source ids")
theirs = finish_image(svc2, "someone-else", "img_theirs")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": theirs}, service_getter=lambda: svc2, env={})
check("source_job_not_found" in o and parse_job_reference(o) is None, "another owner's job -> source_job_not_found")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": "f" * 32}, service_getter=lambda: svc2, env={})
check("source_job_not_found" in o, "unknown job -> source_job_not_found")
queued = svc2.store.submit(OWNER, "x", profile_id="sdxl-a", params={})["job_id"]
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": queued}, service_getter=lambda: svc2, env={})
check("source_job_not_completed" in o, "unfinished job -> source_job_not_completed")
vid_job = svc2.store.submit(OWNER, "x", profile_id="wan-t2v", params={})["job_id"]
while svc2.store.claim_for(["wan-t2v"], EXECUTOR)["id"] != vid_job:  # the earlier i2v job is queued ahead of it
    pass
assert svc2.store.begin_publish(vid_job, EXECUTOR) and svc2.store.complete(vid_job, EXECUTOR, "vid_1")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": vid_job}, service_getter=lambda: svc2, env={})
check("source_not_an_image" in o, "a finished video job is not a source picture")
svc_gone = service_with(VID, IMG)
gone = finish_image(svc_gone, OWNER, "img_gone")
del svc_gone.profiles["sdxl-a"]
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": gone}, service_getter=lambda: svc_gone, env={})
check("source_profile_not_enabled" in o, "a picture from a profile no longer enabled is said to be that, not 'not an image'")

# "latest": what a later turn uses -- the model no longer sees the id image_generate returned.
svc6 = service_with(VID, IMG)
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": "latest"}, service_getter=lambda: svc6, env={})
check("no_source_image" in o and parse_job_reference(o) is None, "latest with no finished picture -> no_source_image, nothing queued")
finish_image(svc6, OWNER, "img_old")
newest = finish_image(svc6, OWNER, "img_new")
finish_image(svc6, "someone-else", "img_not_ours")  # finished later than ours, and still not ours
clip = svc6.store.submit(OWNER, "x", profile_id="wan-t2v", params={})["job_id"]
assert svc6.store.claim_for(["wan-t2v"], EXECUTOR)["id"] == clip
assert svc6.store.begin_publish(clip, EXECUTOR) and svc6.store.complete(clip, EXECUTOR, "vid_newer")
unfinished = svc6.store.submit(OWNER, "x", profile_id="sdxl-a", params={})["job_id"]
for spelling in ("latest", " Latest "):
    fresh = service_with(VID, IMG)  # the active-job limit must not decide this
    finish_image(fresh, OWNER, "img_old")
    finish_image(fresh, OWNER, "img_new")
    o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": spelling}, service_getter=lambda: fresh, env={})
    r = parse_job_reference(o)
    j = fresh.store.get(r["job_id"], OWNER) if r else None
    pj = json.loads(j["params"]) if j and isinstance(j.get("params"), str) else (j or {}).get("params") or {}
    check(pj.get("task") == "image_to_video" and pj.get("input_asset_id") == "img_new",
          f"{spelling!r} -> the newest picture is the source")
check(svc6.store.newest_picture_for(OWNER, ["sdxl-a"])["id"] == unfinished,
      "store: the newest picture ASKED FOR, even while it renders; a newer clip and another owner's picture do not count")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": "latest"}, service_getter=lambda: svc6, env={})
check(o.startswith("Videogenerering blev ikke startet (source_job_not_completed)") and parse_job_reference(o) is None
      and newest not in o,
      "latest while a newer picture is still rendering -> said so; the older finished one is NOT animated in its place")
assert svc6.store.cancel(unfinished, OWNER)
check(svc6.store.newest_picture_for(OWNER, ["sdxl-a"])["id"] == newest,
      "store: a job that never became a picture (cancelled) is skipped")
check(svc6.store.newest_picture_for(OWNER, []) is None and svc6.store.newest_picture_for("nobody", ["sdxl-a"]) is None,
      "store: no profiles or an owner with nothing -> None")
try:
    svc6.store.newest_picture_for(OWNER, ["bad id!"]); check(False, "store: malformed profile ids are refused")
except Exception:  # noqa: BLE001 -- ImageJobError
    check(True, "store: malformed profile ids are refused")

# Review 6004386187: several finished pictures, and "det billede" must not mean whichever finished last.
print("== 4c. which picture 'latest' is ==")


def source_of(output: str, service: MediaJobService) -> str | None:
    r = parse_job_reference(output)
    j = service.store.get(r["job_id"], OWNER) if r else None
    pj = json.loads(j["params"]) if j and isinstance(j.get("params"), str) else (j or {}).get("params") or {}
    return pj.get("input_asset_id")


def latest_in(shown, service: MediaJobService) -> str:
    token = vgt.CONVERSATION_IMAGE_JOBS.set(vgt.conversation_image_jobs(shown))
    try:
        return vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": "latest"},
                                       service_getter=lambda: service, env={})
    finally:
        vgt.CONVERSATION_IMAGE_JOBS.reset(token)


many = service_with(VID, IMG)
here_old = finish_image(many, OWNER, "img_here_old")
here_new = finish_image(many, OWNER, "img_here_new")
elsewhere = finish_image(many, OWNER, "img_elsewhere")  # finished later, in ANOTHER conversation
check(source_of(latest_in(None, many), many) == "img_elsewhere",
      "no conversation context (older client): the owner's newest picture anywhere -- the documented fallback")
check(source_of(latest_in([here_old, here_new], many), many) == "img_here_new",
      "with the conversation's pictures: ITS newest one, not the one another conversation finished later")
check(source_of(latest_in([here_new, here_old], many), many) == "img_here_old",
      "the client's order decides which is newest in the conversation")
o = latest_in([], many)
check("no_source_image" in o and parse_job_reference(o) is None,
      "a conversation the client says has no pictures: nothing to animate, another conversation's is not borrowed")

mixed = service_with(VID, IMG)
first = finish_image(mixed, OWNER, "img_first")
rendering = mixed.store.submit(OWNER, "x", profile_id="sdxl-a", params={})["job_id"]
o = latest_in([first, rendering], mixed)
check("source_job_not_completed" in o and parse_job_reference(o) is None,
      "the conversation's newest picture is still rendering: said so, the earlier one is not animated instead")
assert mixed.store.cancel(rendering, OWNER)
check(source_of(latest_in([first, rendering], mixed), mixed) == "img_first",
      "a newest job that never became a picture is passed over for the one before it")
foreign = finish_image(mixed, "someone-else", "img_foreign")
clip_id = mixed.store.submit(OWNER, "x", profile_id="wan-t2v", params={})["job_id"]
check(source_of(latest_in([first, foreign, "f" * 32, clip_id], mixed), mixed) == "img_first",
      "ids that are another owner's, unknown, or a clip are not pictures of this conversation")
o = latest_in([foreign, "f" * 32], mixed)
check("no_source_image" in o and "img_foreign" not in o and parse_job_reference(o) is None,
      "only foreign or unknown ids: no source -- naming another owner's job id gets nothing")

check(vgt.conversation_image_jobs(None) is None, "context: the field not sent stays None (an older client)")
check(vgt.conversation_image_jobs([]) == () and vgt.conversation_image_jobs("x") == () and vgt.conversation_image_jobs({"a": 1}) == (),
      "context: an empty or unusable value is 'no pictures', not 'unknown'")
a32, b32 = "a" * 32, "b" * 32
check(vgt.conversation_image_jobs([a32, "nope", 7, None, "A" * 32, b32, a32]) == (b32, a32),
      "context: only well-formed ids, in order; a repeat counts at its latest position")
long_list = [f"{i:032x}" for i in range(200)]
kept = vgt.conversation_image_jobs(long_list)
check(len(kept) == vgt.MAX_CONVERSATION_IMAGE_JOBS and kept[-1] == long_list[-1], "context: the newest 32 are kept")
check(vgt.CONVERSATION_IMAGE_JOBS.get() is None, "context: nothing leaks out of a call")
check("latest" in vgt.SYSTEM_RULE and "latest" in cap.description, "the model is told to use 'latest'")

T2V_ONLY = parse_profile(video_profile(profile_id="wan-t2v-only", tasks=["text_to_video"]))
svc3 = service_with(T2V_ONLY, IMG)
mine3 = finish_image(svc3, OWNER, "img_3")
o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": mine3}, service_getter=lambda: svc3, env={})
check("task_not_served" in o and parse_job_reference(o) is None, "profile without image_to_video -> task_not_served as text")

# 4c. two video profiles, one per task (a template renders exactly one task)
print("== 4c. profile by task ==")
T2V = parse_profile(video_profile(profile_id="wan-t2v", tasks=["text_to_video"]))
I2V = parse_profile(video_profile(profile_id="wan-i2v", tasks=["image_to_video"]))


def chosen(args: dict, env: dict) -> tuple[str | None, str]:
    # A fresh service per case: the owner's active-job limit must not decide these.
    service = service_with(T2V, I2V, IMG)
    if "source_image_job_id" in args:
        args = {**args, "source_image_job_id": finish_image(service, OWNER, "img_4")}
    text = vgt._run_video_generate({"prompt": PROMPT, **args}, service_getter=lambda: service, env=env)
    reference = parse_job_reference(text)
    return (reference["profile_id"] if reference else None), text


src4 = "0" * 32  # replaced per case by a finished image job of that case's service


check(chosen({}, {})[0] == "wan-t2v", "text request -> the one profile that lists text_to_video")
check(chosen({"source_image_job_id": src4}, {})[0] == "wan-i2v", "source request -> the one profile that lists image_to_video")
check(chosen({"source_image_job_id": src4}, {"KALIV_VIDEO_TOOL_PROFILE": "wan-t2v"})[0] == "wan-i2v",
      "a default configured for the other task does not capture the request")
check(chosen({}, {"KALIV_VIDEO_TOOL_PROFILE": "wan-i2v"})[0] == "wan-t2v", "and the same the other way round")
check(chosen({}, {"KALIV_VIDEO_TOOL_PROFILE": "wan-t2v"})[0] == "wan-t2v", "the configured default wins for its own task")
check("configured_profile_not_enabled" in chosen({}, {"KALIV_VIDEO_TOOL_PROFILE": "sdxl-a"})[1],
      "a configured image profile is still refused for video")
check("task_not_served" in chosen({"source_image_job_id": src4, "profile_id": "wan-t2v"}, {})[1],
      "an explicit profile is not second-guessed: the API says task_not_served")
T2V_B = parse_profile(video_profile(profile_id="wan-t2v-b", tasks=["text_to_video"]))
svc5 = service_with(T2V, T2V_B, I2V)
o = vgt._run_video_generate({"prompt": PROMPT}, service_getter=lambda: svc5, env={})
check("profile_required" in o and parse_job_reference(o) is None, "two profiles for one task: ambiguity is refused, not guessed")
o = vgt._run_video_generate({"prompt": PROMPT}, service_getter=lambda: svc5, env={"KALIV_VIDEO_TOOL_PROFILE": "wan-t2v-b"})
check((parse_job_reference(o) or {}).get("profile_id") == "wan-t2v-b", "the configured default resolves it")

# A source the model wrote badly is a text result it can act on, never a turn that dies with HTTP 400.
for bad_source in ("det billede", "newest", "x", "A" * 32, "\x00unreadable"):
    svc_bad = service_with(VID, IMG)
    o = vgt._run_video_generate({"prompt": PROMPT, "source_image_job_id": bad_source}, service_getter=lambda: svc_bad, env={})
    check("source_not_understood" in o and "latest" in o and parse_job_reference(o) is None
          and svc_bad.store.newest_picture_for(OWNER, ["sdxl-a", "wan-t2v"]) is None,
          f"unreadable source {bad_source!r} -> told to use 'latest', nothing queued")

# 5. through the turn
print("== 5. turn ==")
client = TestClient(main.app)
import dataclasses
tools.REGISTRY[vgt.TOOL_NAME] = dataclasses.replace(
    vgt.VIDEO_GENERATE_CAPABILITY, run=lambda a: vgt._run_video_generate(a, service_getter=lambda: svc, env={}))
seen: list[list[dict]] = []
seq = [{"tool_calls": [{"function": {"name": "video_generate", "arguments": {"prompt": PROMPT}}}], "content": ""},
       {"tool_calls": [], "content": "Klippet er på vej."}]


async def _mock(messages, *a, **k):
    seen.append(list(messages))
    return seq.pop(0) if seq else {"tool_calls": [], "content": "done"}


main.oc.chat_tools = _mock
try:
    d = client.post("/tools/chat", json={"message": "lav en video af en papirbåd", "model": "qwen3:14b"}).json()
    check(d.get("status") == "answered" and d.get("tools_used") == ["video_generate"], "turn answered via video_generate")
    jobs = d.get("media_jobs") or []
    check(len(jobs) == 1 and jobs[0].get("kind") == "video" and jobs[0]["status_url"] == f"/api/v1/media/jobs/{jobs[0]['job_id']}",
          "media_jobs carries the video job with kind=video")
    sys_texts = [m["content"] for m in seen[-1] if m.get("role") == "system"]
    check(vgt.SYSTEM_RULE in sys_texts, "video system rule present while registered")
    check(PROMPT not in json.dumps(d, ensure_ascii=False), "result never repeats the prompt")

    # Review 6004386187, through the real turn: the client says which pictures this conversation
    # holds, and "latest" is the newest of those -- on the worker thread the tool runs on.
    turn_svc = service_with(VID, IMG)
    in_this_chat = finish_image(turn_svc, OWNER, "img_this_chat")
    finish_image(turn_svc, OWNER, "img_other_chat")  # finished later, somewhere else
    tools.REGISTRY[vgt.TOOL_NAME] = dataclasses.replace(
        vgt.VIDEO_GENERATE_CAPABILITY, run=lambda a: vgt._run_video_generate(a, service_getter=lambda: turn_svc, env={}))
    animate = {"tool_calls": [{"function": {"name": "video_generate",
                                            "arguments": {"prompt": PROMPT, "source_image_job_id": "latest"}}}], "content": ""}

    def animated(body: dict, route: str = "/tools/chat") -> str | None:
        seq[:] = [dict(animate), {"tool_calls": [], "content": "Klippet er på vej."}]
        response = client.post(route, json={"message": "lav en video af det billede", "model": "qwen3:14b", **body})
        turn = (response.json() if route == "/tools/chat"
                else [json.loads(line)["result"] for line in response.text.splitlines() if '"result"' in line][-1])
        refs = turn.get("media_jobs") or []
        job = turn_svc.store.get(refs[0]["job_id"], OWNER) if refs else None
        params = json.loads(job["params"]) if job and isinstance(job.get("params"), str) else (job or {}).get("params") or {}
        if refs:
            assert turn_svc.store.cancel(refs[0]["job_id"], OWNER)  # keep the owner's active limit out of it
        return params.get("input_asset_id")

    check(animated({"conversation_image_jobs": [in_this_chat]}) == "img_this_chat",
          "turn: with conversation_image_jobs, 'latest' animates this conversation's picture")
    check(animated({"conversation_image_jobs": [in_this_chat]}, "/tools/chat/stream") == "img_this_chat",
          "turn: the same through the stream route the apps use")
    check(animated({}) == "img_other_chat", "turn: without the field (an older client), the owner's newest picture anywhere")
    check(animated({"conversation_image_jobs": []}) is None,
          "turn: a conversation with no pictures animates nothing")
    check(animated({"conversation_image_jobs": ["junk", 7, None]}) is None and animated({"conversation_image_jobs": [in_this_chat]}) == "img_this_chat",
          "turn: malformed entries are dropped, never a 422, and the next turn is unaffected")
    check(vgt.CONVERSATION_IMAGE_JOBS.get() is None, "turn: the context does not outlive the turn")
finally:
    tools.REGISTRY.pop(vgt.TOOL_NAME, None)
    if saved is not None:
        tools.REGISTRY[vgt.TOOL_NAME] = saved
    shutil.rmtree(_tmp, ignore_errors=True)

print(f"\n===== VIDEO GENERATE TOOL: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

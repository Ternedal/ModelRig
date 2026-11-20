#!/usr/bin/env python3
"""``video_generate``: text-to-video from the chat turn, on the image tool's seam.

Proves what differs from ``image_generate`` (everything shared is proven in
``worker_image_generate_tool.py``):

1. Own gate ``KALIV_VIDEO_TOOL_ENABLED`` (literal ``1``), own registration, own
   system rule that follows REGISTRY.
2. Contract: read, not idempotent, not schedulable, network none; ``frames`` is
   an accepted argument; the description says text-to-video only.
3. Run: with ``video_enabled`` the job is queued as ``text_to_video`` for OWNER
   with a ``kaliv-video-job-ref/v1`` reference carrying ``kind=video``; the
   stored params carry the task and frames; an image profile is never chosen.
4. Rig-side refusals as text: ``KALIV_MEDIA_VIDEO`` off -> ``video_not_enabled``;
   no video profile -> ``no_video_profile``; image-to-video is not offered (no
   argument for it; task fixed).
5. The lift: ``parse_job_reference`` reads a video reference with kind=video,
   and the turn result's ``media_jobs`` carries it (through /tools/chat).

Run: PYTHONPATH=worker python3 tests/worker_video_generate_tool.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
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
check(set(cap.params["properties"]) == {"prompt", "profile_id", "width", "height", "frames", "seed"}
      and cap.params["required"] == ["prompt"], "argument surface incl. frames; prompt required")
check("text-to-video only" in cap.description and "Never claim it is finished" in cap.description,
      "description: t2v only, on-its-way rule")
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
for bad, label in (({"prompt": PROMPT, "input_asset_id": "x"}, "image-to-video is not an argument"),
                   ({"prompt": PROMPT, "task": "image_to_video"}, "task cannot be chosen by the model"),
                   ({"prompt": PROMPT, "frames": "33"}, "frames must be an int"),
                   ({}, "prompt missing")):
    try:
        vgt._run_video_generate(bad, service_getter=lambda: svc, env={}); check(False, f"{label}: ToolDenied")
    except tools.ToolDenied:
        check(True, f"{label}: ToolDenied")

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
finally:
    tools.REGISTRY.pop(vgt.TOOL_NAME, None)
    if saved is not None:
        tools.REGISTRY[vgt.TOOL_NAME] = saved
    shutil.rmtree(_tmp, ignore_errors=True)

print(f"\n===== VIDEO GENERATE TOOL: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

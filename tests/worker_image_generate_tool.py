#!/usr/bin/env python3
"""``image_generate`` (#2419 slice A): gated, asynchronous, fail-closed-but-text.

What this proves, each with a negative twin where one exists:

1. The gate. Without ``KALIV_IMAGE_TOOL_ENABLED=1`` the tool is not in REGISTRY
   (ToolGate is a deny-list: in REGISTRY = live). Only the literal ``1`` opts in.
   Registration is idempotent and refuses to shadow another component's tool.
2. The contract. ``risk="read"`` (no card -- Anders 19/11), ``impact="read"``,
   ``idempotent=False`` stated (two runs = two renders), not schedulable,
   ``network="none"``, the capability descriptor validates.
3. The run. A real ``MediaJobService`` over a real ``ImageJobStore``: the job is
   queued for ``OWNER`` ("installation"), the first result line is a parseable
   job reference pointing at ``/api/v1/media/jobs/{id}``, and the text never
   repeats the prompt.
4. Fail-closed as *text*: job API off, service unavailable, no/ambiguous
   profile, a size the profile refuses, a full queue -- all return a result the
   model can relay, none raise (an exception would end the turn with an HTTP
   error). Only malformed model arguments raise ``ToolDenied``.
5. The lift. ``parse_job_reference`` reads the reference through the
   ``wrap_as_data`` envelope and rejects anything that is not exactly it.
6. Profile choice: explicit > ``KALIV_IMAGE_TOOL_PROFILE`` > the sole enabled
   image profile; a video profile is never chosen.

Run: PYTHONPATH=worker python3 tests/worker_image_generate_tool.py
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="kaliv-igt-")
os.environ.setdefault("KALIV_TOOLS_DIR", os.path.join(_tmp, "notes"))
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(_tmp, "audit.db"))
os.makedirs(os.environ["KALIV_TOOLS_DIR"], exist_ok=True)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from app import capability_schema as cs  # noqa: E402
from app import tools  # noqa: E402
from app.image_generate_tool import (  # noqa: E402
    IMAGE_GENERATE_CAPABILITY,
    IMAGE_TOOL_FLAG,
    IMAGE_TOOL_PROFILE_ENV,
    JOB_REFERENCE_SCHEMA,
    TOOL_NAME,
    _run_image_generate,
    image_tool_enabled,
    parse_job_reference,
    register_image_generate_tool,
)
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_job_api import OWNER, MediaJobService, MediaJobsUnavailable  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

passed = failed = 0
SECRET = "s" * 40
PROMPT = "a red bicycle under a streetlight, photo, 35mm"


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def service_with(*profiles) -> MediaJobService:
    tmp = Path(tempfile.mkdtemp(prefix="kaliv-igt-svc-"))
    store = ImageJobStore(str(tmp / "jobs.sqlite3"))
    return MediaJobService(store, {p.profile_id: p for p in profiles}, SECRET)


IMG_A = parse_profile(image_profile(profile_id="sdxl-a"))
IMG_B = parse_profile(image_profile(profile_id="realvis-b"))
VID = parse_profile(video_profile(profile_id="wan-t2v"))

# ---------------------------------------------------------------------------
# 1. The gate
# ---------------------------------------------------------------------------
print("== 1. gate ==")
saved_flag = os.environ.pop(IMAGE_TOOL_FLAG, None)
saved_tool = tools.REGISTRY.pop(TOOL_NAME, None)
try:
    check(image_tool_enabled() is False, "no flag: off")
    check(register_image_generate_tool() is False, "no flag: register refuses")
    check(TOOL_NAME not in tools.REGISTRY, "no flag: tool absent from REGISTRY")
    for value in ("", "0", "true", "yes", "on", " 1 x", "TRUE"):
        os.environ[IMAGE_TOOL_FLAG] = value
        check(image_tool_enabled() is False, f"flag={value!r} is not opt-in")
    os.environ[IMAGE_TOOL_FLAG] = "1"
    check(image_tool_enabled() is True, "flag=1 opts in")
    check(register_image_generate_tool() is True, "flag=1: register succeeds")
    registered = tools.REGISTRY.get(TOOL_NAME)
    check(registered is not None and registered.run is _run_image_generate, "REGISTRY holds the tool with its run")
    check(register_image_generate_tool() is True and tools.REGISTRY[TOOL_NAME] is registered,
          "second register is idempotent (same object)")
    tools.REGISTRY[TOOL_NAME] = tools.Tool(name=TOOL_NAME, risk="read", description="x", network="none",
                                           run=lambda a: "")
    try:
        register_image_generate_tool()
        check(False, "shadowing another registration is refused")
    except RuntimeError:
        check(True, "shadowing another registration is refused")
finally:
    tools.REGISTRY.pop(TOOL_NAME, None)
    if saved_tool is not None:
        tools.REGISTRY[TOOL_NAME] = saved_tool
    if saved_flag is None:
        os.environ.pop(IMAGE_TOOL_FLAG, None)
    else:
        os.environ[IMAGE_TOOL_FLAG] = saved_flag

# ---------------------------------------------------------------------------
# 2. The contract
# ---------------------------------------------------------------------------
print("== 2. contract ==")
cap = IMAGE_GENERATE_CAPABILITY
check(cap.risk == "read", "risk=read: no confirmation card (Anders 19/11)")
check(cap.impact == "read", "impact=read")
check(cap.idempotent is False, "idempotent=False stated: two runs are two renders")
check(cap.schedulable is False and cap.unschedulable_because, "not schedulable, with a reason")
check(cap.network == "none" and cap.network_destinations == (), "network=none: nothing leaves the rig")
check(cap.sensitivity == "private", "sensitivity=private")
check(cap.params.get("required") == ["prompt"], "prompt is the only required parameter")
check(set(cap.params["properties"]) == {"prompt", "profile_id", "width", "height", "seed"},
      "parameter surface is exactly prompt/profile_id/width/height/seed")
check("English" in cap.description and "Never claim it is finished" in cap.description,
      "description carries the measured prompt rules and the 'on its way' rule")
check(tools.requires_confirmation(cap, origin="model") is False, "gate: a read runs without a card")
descriptor = cs.descriptor_from_tool(cap)
check(cs.parse_descriptor(json.loads(descriptor.canonical_json())) is not None,
      "capability descriptor validates against the schema")

# ---------------------------------------------------------------------------
# 3. The run
# ---------------------------------------------------------------------------
print("== 3. run ==")
svc = service_with(IMG_A)
out = _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc, env={})
ref = parse_job_reference(out)
check(ref is not None, "result starts with a parseable job reference")
check(ref and ref["profile_id"] == "sdxl-a", "sole image profile chosen without configuration")
check(ref and ref["status_url"] == f"/api/v1/media/jobs/{ref['job_id']}", "status_url points at the job route")
check(ref and ref["job_id"] not in out.split("\n", 1)[1] and "nævn ikke job-id" in out,
      "the sentence the model relays carries no job id (rig 20/11: an answer printed it to the user)")
job = svc.store.get(ref["job_id"], OWNER) if ref else None
check(job is not None and job["state"] == "queued", "job is queued for OWNER=installation")
check(job is not None and job["prompt"] == PROMPT, "the store holds the prompt as written (translation is the executor's)")
check(PROMPT not in out, "result text never repeats the prompt")
check("på vej" in out and "ikke" in out, "result tells the model: on its way, not finished")
check(svc.store.get(ref["job_id"], "someone-else") is None if ref else False, "another owner cannot see the job")

out2 = _run_image_generate({"prompt": PROMPT, "width": 832, "height": 1216, "seed": 7},
                           service_getter=lambda: svc, env={})
ref2 = parse_job_reference(out2)
job2 = svc.store.get(ref2["job_id"], OWNER) if ref2 else None
params2 = json.loads(job2["params"]) if job2 and isinstance(job2.get("params"), str) else (job2 or {}).get("params")
check(ref2 is not None and ref2["job_id"] != ref["job_id"], "second run is a second job (not replayed)")
check(isinstance(params2, dict) and params2.get("width") == 832 and params2.get("seed") == 7,
      "optional size/seed reach the job parameters")
check(params2.get("task") == "text_to_image", "the task is stored with the job")
# A profile that also lists image_to_image: alphabetically first, and the wrong default for a text request.
DUAL = parse_profile(image_profile(profile_id="sdxl-dual", tasks=["text_to_image", "image_to_image"]))
svc_dual = service_with(DUAL)
out_dual = _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_dual, env={})
ref_dual = parse_job_reference(out_dual)
job_dual = svc_dual.store.get(ref_dual["job_id"], OWNER) if ref_dual else None
check(job_dual is not None and json.loads(job_dual["params"]).get("task") == "text_to_image",
      "a profile listing both tasks still gets a text_to_image job (the executor would otherwise default to image_to_image)")

# ---------------------------------------------------------------------------
# 4. Fail-closed as text
# ---------------------------------------------------------------------------
print("== 4. fail-closed as text ==")
def text_result(fn, label):
    try:
        out = fn()
    except Exception as exc:  # noqa: BLE001
        check(False, f"{label}: raised {type(exc).__name__} instead of returning text")
        return ""
    refusal = isinstance(out, str) and ("ikke tilgængelig" in out or out.startswith(("Riggen er optaget", "Riggen afviste")))
    check(refusal and parse_job_reference(out) is None,
          f"{label}: text result, no job reference")
    return out

o = text_result(lambda: _run_image_generate({"prompt": PROMPT}, service_getter=None, env={}),
                "job API switch off")
check("media_jobs_api_off" in o, "job API off names its code")

def boom():
    raise MediaJobsUnavailable("media_jobs_no_enabled_profiles")
o = text_result(lambda: _run_image_generate({"prompt": PROMPT}, service_getter=boom, env={}),
                "service unavailable")
check("media_jobs_no_enabled_profiles" in o, "unavailable reason code is relayed")

svc_none = service_with(VID)
o = text_result(lambda: _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_none, env={}),
                "only a video profile enabled")
check("no_image_profile" in o, "video-only configuration is not an image profile")

svc_two = service_with(IMG_A, IMG_B)
o = text_result(lambda: _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_two, env={}),
                "two image profiles, none configured")
check("profile_required" in o, "ambiguity is refused, not guessed")

o = text_result(lambda: _run_image_generate({"prompt": PROMPT, "profile_id": "nope"},
                                            service_getter=lambda: svc, env={}),
                "explicit unknown profile")
check("profile_not_enabled" in o, "unknown explicit profile names its code")

o = text_result(lambda: _run_image_generate({"prompt": PROMPT, "width": 640, "height": 480},
                                            service_getter=lambda: svc, env={}),
                "size the profile refuses")
check("invalid_request" in o, "executor's own validation rule applies at submit")
check(o.startswith("Riggen afviste") and "width, height" in o and "image_generate igen uden dem" in o,
      "a refused size names the arguments and says to call again without them (the model cannot know the allowed sizes)")
check("640" not in o and "480" not in o, "only argument names are echoed, never values")

import logging as _logging
class _Seen(_logging.Handler):
    def __init__(self):
        super().__init__(); self.lines = []
    def emit(self, record):
        self.lines.append(record.getMessage())
_seen = _Seen(); _wlog = _logging.getLogger("modelrig.worker"); _wlog.addHandler(_seen); _prev = _wlog.level; _wlog.setLevel(_logging.INFO)
_run_image_generate({"prompt": PROMPT, "width": 640, "height": 480}, service_getter=lambda: svc, env={})
_run_image_generate({"prompt": PROMPT}, service_getter=None, env={})
_wlog.removeHandler(_seen); _wlog.setLevel(_prev)
check(_seen.lines == ["media_tool=refused modality=image code=invalid_request optional=width,height",
                      "media_tool=refused modality=image code=media_jobs_api_off"],
      "each refusal is one worker log line with its code (and argument names, never the prompt)")
check(not any(PROMPT in line for line in _seen.lines), "the prompt is not logged")

svc_full = service_with(IMG_A)
for _ in range(3):
    _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_full, env={})
o = text_result(lambda: _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_full, env={}),
                "owner limit reached")
check("owner_limit" in o, "quota is relayed as a code")
check(o.startswith("Riggen er optaget") and "ikke en fejl" in o and "ikke tilgængelig" not in o,
      "a full owner quota says wait, not unavailable (rig 20/11: relayed as 'tekniske problemer')")
check(parse_job_reference(o) is None, "a busy text is not a job reference")

try:
    _run_image_generate("not a dict", service_getter=lambda: svc, env={})
    check(False, "args not an object: ToolDenied")
except tools.ToolDenied:
    check(True, "args not an object: ToolDenied")
# A model's argument mistake is refused as text, not ToolDenied: that would end the turn
# with HTTP 400 for a mistake a small model makes easily (a made-up field, a word for a number).
for bad, label, names in (
    ({}, "prompt missing", "prompt"),
    ({"prompt": ""}, "prompt empty", "prompt"),
    ({"prompt": "x" * 4001}, "prompt too long", "prompt"),
    ({"prompt": PROMPT, "steps": 5, "style": "photo"}, "unknown argument", "steps, style"),
    ({"prompt": PROMPT, "width": "bred"}, "width not a number", "width"),
    ({"prompt": PROMPT, "height": 10.5}, "height not a whole number", "height"),
    ({"prompt": PROMPT, "width": [1024]}, "width a list", "width"),
    ({"prompt": PROMPT, "seed": True}, "bool is not an int", "seed"),
    ({"prompt": PROMPT, "profile_id": 7}, "profile_id not a string", "profile_id"),
):
    svc_bad = service_with(IMG_A)
    o_bad = _run_image_generate(bad, service_getter=lambda: svc_bad, env={})
    check("invalid_arguments" in o_bad and names in o_bad and parse_job_reference(o_bad) is None
          and "image_generate igen" in o_bad, f"{label}: refused as text, names the argument, call again")
    check("photo" not in o_bad and "1024" not in o_bad and "bred" not in o_bad and "10.5" not in o_bad
          and "xxxx" not in o_bad, f"{label}: no value is echoed")
    with sqlite3.connect(svc_bad.store.path) as _db:
        check(_db.execute("SELECT COUNT(*) FROM image_jobs").fetchone()[0] == 0, f"{label}: nothing queued")
check(svc.store.get(ref["job_id"], OWNER) is not None, "denied arguments queued nothing new (store intact)")
from app.image_generate_tool import ArgMistake, int_arg  # noqa: E402
check([int_arg("width", v) for v in (1024, "1024", " 1024 ", 1024.0, None, "", "  ", -5, "-5")]
      == [1024, 1024, 1024, 1024, None, None, None, -5, -5],
      "1024, '1024' and 1024.0 are the same wish; '' and None are 'left out'")
for bad_int in (True, False, "10.5", 10.5, "1e3", "bred", [1], {}, float("inf"), float("nan"), "1" * 11):
    try:
        int_arg("width", bad_int); check(False, f"int_arg refuses {bad_int!r}")
    except ArgMistake as mistake:
        check(str(mistake) == "width skal være et heltal", f"int_arg refuses {bad_int!r} naming the argument only")
ref_text = parse_job_reference(_run_image_generate({"prompt": PROMPT, "width": "1024", "height": 1024.0, "seed": ""},
                                                   service_getter=lambda: service_with(IMG_A), env={}))
check(ref_text is not None, "a size sent as text and as a float queues the picture: no round trip for a difference the user cannot see")

for blank in ("", "   "):
    ref_blank = parse_job_reference(_run_image_generate({"prompt": PROMPT, "profile_id": blank},
                                                        service_getter=lambda: service_with(IMG_A), env={}))
    check(ref_blank is not None and ref_blank["profile_id"] == "sdxl-a",
          f"profile_id={blank!r} means the rig's default, not a dead turn")

# ---------------------------------------------------------------------------
# 5. The lift through the envelope
# ---------------------------------------------------------------------------
print("== 5. lift ==")
good = {"schema": JOB_REFERENCE_SCHEMA, "job_id": "a" * 32, "state": "queued", "profile_id": "p",
        "status_url": "/api/v1/media/jobs/" + "a" * 32}
check(parse_job_reference(tools.wrap_as_data(json.dumps(good) + "\ntext")) is not None,
      "reference is read through the wrap_as_data envelope")
check(parse_job_reference(json.dumps(good)) is not None, "reference is read bare")
check((parse_job_reference(json.dumps(good)) or {}).get("kind") == "image", "an image reference carries kind=image")
check((parse_job_reference(json.dumps({**good, "schema": "kaliv-video-job-ref/v1", "kind": "video"})) or {}).get("kind") == "video",
      "a video reference carries kind=video")
for mutated, label in (
    ({**good, "schema": "kaliv-media-job/v1"}, "other schema"),
    ({**good, "schema": "kaliv-audio-job-ref/v1"}, "unknown job-ref schema"),
    ({**good, "job_id": "a" * 31}, "short job id"),
    ({**good, "job_id": "Z" * 32}, "non-hex job id"),
    ({**good, "status_url": "/api/v1/media/jobs/" + "b" * 32}, "status_url for another job"),
    ({**good, "status_url": "https://evil.example/" + "a" * 32}, "foreign status_url"),
):
    check(parse_job_reference(json.dumps(mutated)) is None, f"{label}: rejected")
check(parse_job_reference("Billedgenerering er ikke tilgængelig lige nu (x).") is None, "text result: None")
from app.image_generate_tool import _unavailable, parse_refusal  # noqa: E402
for code, modality in (("owner_limit", "image"), ("queue_full", "video"), ("no_source_image", "video"),
                       ("media_jobs_api_off", "image")):
    text = _unavailable(code, modality)
    check(parse_refusal(text) == code and parse_refusal(tools.wrap_as_data(text)) == code,
          f"parse_refusal reads {code} back, with and without the envelope")
check(parse_refusal(out) is None and parse_refusal(tools.wrap_as_data(out)) is None,
      "a queued job is not a refusal")
check(parse_refusal("noget andet (owner_limit)") is None and parse_refusal("") is None and parse_refusal(None) is None,
      "parse_refusal: only a refusal sentence, at the start of a line")
check(parse_job_reference("{not json") is None and parse_job_reference("") is None, "garbage: None")

# ---------------------------------------------------------------------------
# 6. Profile choice
# ---------------------------------------------------------------------------
print("== 6. profile choice ==")
svc_two = service_with(IMG_A, IMG_B, VID)
r = parse_job_reference(_run_image_generate({"prompt": PROMPT, "profile_id": "realvis-b"},
                                            service_getter=lambda: svc_two, env={}))
check(r is not None and r["profile_id"] == "realvis-b", "explicit profile wins")
r = parse_job_reference(_run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_two,
                                            env={IMAGE_TOOL_PROFILE_ENV: "sdxl-a"}))
check(r is not None and r["profile_id"] == "sdxl-a", "configured default is used when none is given")
r = parse_job_reference(_run_image_generate({"prompt": PROMPT, "profile_id": "realvis-b"},
                                            service_getter=lambda: svc_two,
                                            env={IMAGE_TOOL_PROFILE_ENV: "sdxl-a"}))
check(r is not None and r["profile_id"] == "realvis-b", "explicit beats configured")
o = _run_image_generate({"prompt": PROMPT}, service_getter=lambda: svc_two,
                        env={IMAGE_TOOL_PROFILE_ENV: "wan-t2v"})
check("configured_profile_not_enabled" in o, "a configured video profile is not an image profile")
o = _run_image_generate({"prompt": PROMPT, "profile_id": "wan-t2v"}, service_getter=lambda: svc_two, env={})
check("profile_not_enabled" in o, "an explicit video profile is refused")

shutil.rmtree(_tmp, ignore_errors=True)
print(f"\n===== IMAGE GENERATE TOOL: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

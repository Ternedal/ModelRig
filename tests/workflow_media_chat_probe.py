#!/usr/bin/env python3
"""scripts/media_chat_probe.py against a scripted appliance on loopback (no rig, no model).

Proves:

1. Setup is refused before anything is sent: a base URL that is not bare http
   loopback, a missing token, a route the probe has no business calling.
2. A turn's job references are read as the clients read them (32-hex id, exact
   status_url, known kind); anything else is "no job".
3. The image suite: every case sends the bearer token and the plan's message,
   follows its job to completed, and the control case must queue nothing. The
   report carries no token and no model text, and says it is not evidence.
4. What counts as a failed case: the tool not called, a control that calls one,
   no usable job reference, a job that fails / times out, a failed turn -- each
   with its own reason, and the suite goes on.
5. Polling: a transient 503 is counted and survived; an appliance that stays
   away ends the job as unreachable; a redirect is refused, never followed.
6. The i2v suite asks "animate that picture" as the next turn, with the picture
   turn as history, and skips the question when there is no finished picture.
7. VRAM sampling, when a sampler is given, records before and peak per GPU.
8. main(): table, report file, exit codes -- and the messages are the ones the
   rig-day plan lists.

Run: python3 tests/workflow_media_chat_probe.py
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import threading
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

SCRIPT = ROOT / "scripts" / "media_chat_probe.py"
spec = importlib.util.spec_from_file_location("media_chat_probe", SCRIPT)
assert spec is not None and spec.loader is not None
probe = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = probe
spec.loader.exec_module(probe)

passed = failed = 0
TOKEN = "device-token-never-printed"
A, B, C, D, E = ("%032x" % n for n in (0xa1, 0xb2, 0xc3, 0xd4, 0xe5))


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


def turn(tool: str | None, job_id: str | None = None, kind: str = "image", **overrides) -> dict:
    body = {"status": "answered", "answer": "Det er på vej i samtalen.", "tools_used": [tool] if tool else [],
            "media_jobs": []}
    if job_id is not None:
        body["media_jobs"] = [{"job_id": job_id, "kind": kind, "state": "queued", "profile_id": "realvisxl-4-0",
                               "status_url": "/api/v1/media/jobs/" + job_id}]
    body.update(overrides)
    return body


def job(job_id: str, state: str, *, error=None, profile="realvisxl-4-0") -> dict:
    return {"schema": "kaliv-media-job/v1", "id": job_id, "state": state, "profile_id": profile,
            "asset_id": "img_1" if state == "completed" else None, "error": error, "cancel_requested": False}


def lifecycle(job_id: str, *states: str, **kw) -> deque:
    return deque((200, job(job_id, s, **kw)) for s in (states or ("queued", "running", "publishing", "completed")))


class Appliance:
    """Scripted answers: a queue of turns, and per job a queue of status answers (the last one repeats)."""

    def __init__(self, turns, jobs):
        self.turns = deque(turns)
        self.jobs = {k: deque(v) for k, v in jobs.items()}
        self.chats: list[dict] = []
        self.polls: list[str] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # quiet
                pass

            def _send(self, status: int, body, location: str | None = None):
                raw = b"" if body is None else json.dumps(body).encode("utf-8")
                self.send_response(status)
                if location:
                    self.send_header("Location", location)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                owner.chats.append({"path": self.path, "auth": self.headers.get("Authorization"),
                                    "body": json.loads(self.rfile.read(length).decode("utf-8"))})
                status, body = owner.turns.popleft() if owner.turns else (200, turn(None))
                if self.path.endswith("/stream") and status == 200:
                    # The worker's stream: phases, then one result line. A str body is sent as written.
                    text = body if isinstance(body, str) else (
                        json.dumps({"phase": "tænker"}) + "\n\n" + json.dumps({"phase": "værktøj"}) + "\n"
                        + json.dumps({"result": body}, ensure_ascii=False) + "\n")
                    raw = text.encode("utf-8")
                    self.send_response(200)
                    self.send_header("Content-Type", "application/x-ndjson")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                self._send(status, body)

            def do_GET(self):
                job_id = self.path.rsplit("/", 1)[-1]
                owner.polls.append(job_id)
                answers = owner.jobs.get(job_id)
                if not answers:
                    self._send(404, {"detail": "job_not_found"})
                    return
                status, body = answers[0] if len(answers) == 1 else answers.popleft()
                if isinstance(body, str) and body.startswith("http"):
                    self._send(status, None, location=body)
                else:
                    self._send(status, body)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@contextlib.contextmanager
def appliance(turns, jobs):
    fake = Appliance([(200, t) if isinstance(t, dict) else t for t in turns], jobs)
    try:
        yield fake
    finally:
        fake.close()


def run(fake: Appliance, suite: str = "image", **kw) -> dict:
    kw.setdefault("poll_s", 0)
    kw.setdefault("sleep", lambda s: None)
    return probe.run_suite(probe.Http(fake.base, TOKEN), suite, model="qwen3:14b", **kw)


IMAGE_JOBS = (A, B, C, D)

# 1. setup refusals
print("== 1. setup ==")
check(probe.ensure_loopback("http://127.0.0.1:8080/") == "http://127.0.0.1:8080"
      and probe.ensure_loopback("http://[::1]:8080") == "http://[::1]:8080", "bare http loopback with a port is accepted")
for bad in ("https://127.0.0.1:8080", "http://localhost:8080", "http://192.168.1.27:8080", "http://127.0.0.1",
            "http://127.0.0.1:8080/api", "http://127.0.0.1:8080/?x=1", "http://u:p@127.0.0.1:8080", "not a url",
            "http://127.0.0.1:99999"):
    try:
        probe.ensure_loopback(bad)
        check(False, f"refused: {bad}")
    except probe.ProbeError:
        check(True, f"refused: {bad}")
check(probe.token_from_env({"MODELRIG_TOKEN": " t "}) == "t", "token is read from the environment")
for env in ({}, {"MODELRIG_TOKEN": "  "}):
    try:
        probe.token_from_env(env)
        check(False, "a missing token is a setup error")
    except probe.ProbeError:
        check(True, "a missing token is a setup error")
for route in ("/api/v1/tools/confirm", "/api/v1/media/jobs/../../healthz", "/api/v1/media/jobs/" + A + "/cancel", "/healthz"):
    try:
        probe.Http("http://127.0.0.1:9", TOKEN).call(route, None, timeout=1)
        check(False, f"route never called: {route}")
    except probe.ProbeError:
        check(True, f"route never called: {route}")

# 2. job references
print("== 2. job references ==")
ok_ref = {"job_id": A, "kind": "video", "status_url": "/api/v1/media/jobs/" + A}
check(probe.job_refs({"media_jobs": [ok_ref]}) == [{"job_id": A, "kind": "video"}], "a well-formed reference is read")
check(probe.job_refs({"media_jobs": [{"job_id": A, "status_url": "/api/v1/media/jobs/" + A}]}) == [{"job_id": A, "kind": "image"}],
      "no kind means an image job")
for label, ref in (("another job's url", dict(ok_ref, status_url="/api/v1/media/jobs/" + B)),
                   ("an absolute url", dict(ok_ref, status_url="https://elsewhere.example/api/v1/media/jobs/" + A)),
                   ("a short id", {"job_id": "abc", "status_url": "/api/v1/media/jobs/abc"}),
                   ("an unknown kind", dict(ok_ref, kind="audio")),
                   ("a non-object", A)):
    check(probe.job_refs({"media_jobs": [ref]}) == [], f"dropped: {label}")
check(probe.job_refs({"media_jobs": [ok_ref, ok_ref]}) == [{"job_id": A, "kind": "video"}], "duplicates collapse")
check(probe.job_refs({}) == [] and probe.job_refs({"media_jobs": "x"}) == [] and probe.job_refs(None) == [],
      "an older rig or a wrong shape is no jobs")

# 3. the image suite, all well
print("== 3. image suite ==")
turns = [turn("image_generate", j) for j in IMAGE_JOBS] + [turn(None)]
with appliance(turns, {j: lifecycle(j) for j in IMAGE_JOBS}) as fake:
    report = run(fake)
    s = report["summary"]
    check(s["tool_cases"] == 4 and s["tool_called"] == 4 and s["tool_call_rate"] == 1.0, "4 of 4 tool calls")
    check(s["jobs"] == 4 and s["jobs_completed"] == 4 and s["control_ok"] is True and s["all_ok"] is True,
          "every job completed, the control queued nothing")
    check([c["body"]["message"] for c in fake.chats] == list(probe.IMAGE_MESSAGES) + [probe.CONTROL_MESSAGE],
          "the plan's messages, in order, then the control")
    check(all(c["auth"] == "Bearer " + TOKEN and c["path"] == probe.CHAT_ROUTE and c["body"]["model"] == "qwen3:14b"
              and "history" not in c["body"] for c in fake.chats), "bearer, route and model on every turn; no history")
    first = report["cases"][0]
    check(first["jobs"][0]["first_seen_s"].keys() >= {"queued", "running", "publishing", "completed"}
          and first["jobs"][0]["profile_id"] == "realvisxl-4-0", "each state's first sighting and the profile are recorded")
    dumped = json.dumps(report, ensure_ascii=False)
    check(TOKEN not in dumped and "på vej" not in dumped and "_answer" not in dumped,
          "the report carries neither the token nor the model's words")
    check(report["schema"] == probe.SCHEMA and report["evidence"] is False, "the report says what it is: not evidence")
    check(first["answer_chars"] == len("Det er på vej i samtalen."), "only the answer's length is kept")
    table = probe.render(report)
    check("4/4" in table and "kontrol: ok" in table and TOKEN not in table, "the table sums it up")

# 4. failed cases, each with its reason
print("== 4. failures ==")
wrong_url = turn("image_generate", C)
wrong_url["media_jobs"][0]["status_url"] = "/api/v1/media/jobs/" + D  # names another job: not a usable reference
turns = [turn("image_generate", A), turn(None), wrong_url, (500, {"detail": "boom"}), turn("image_generate", E)]
with appliance(turns, {A: lifecycle(A, "queued", "failed", error="gpu_unavailable"), E: lifecycle(E)}) as fake:
    report = run(fake)
    why = [c["why"] for c in report["cases"]]
    check(why == ["job_failed", "tool_not_called", "no_job_reference", "turn_failed", "unexpected_tool_call"],
          f"each failure has its own reason, and the suite goes on: {why}")
    check(report["cases"][0]["jobs"][0]["error"] == "gpu_unavailable", "the rig's failure code is kept")
    check(report["cases"][3]["http"] == 500 and report["cases"][3]["jobs"] == [], "a failed turn follows no job")
    s = report["summary"]
    check(s["tool_cases"] == 4 and s["tool_called"] == 2 and s["tool_call_rate"] == 0.5, "the rate counts calls, not luck: 2 of 4")
    check(s["control_ok"] is False and s["all_ok"] is False, "a control that queues a job fails the run")
    check(C not in fake.polls and D not in fake.polls, "an unusable reference is never polled")

with appliance([turn("image_generate", A)], {A: deque([(200, job(A, "failed", error="Free text from the rig"))])}) as fake:
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=5, poll_s=0, sleep=lambda s: None)
    check(result["jobs"][0]["state"] == "failed" and result["jobs"][0]["error"] is None, "free text is never taken as a code")

with appliance([turn("image_generate", A)], {A: lifecycle(A, "running")}) as fake:
    ticks = iter(range(0, 10_000, 40))
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=100, poll_s=0, sleep=lambda s: None,
                            clock=lambda: float(next(ticks)))
    check(result["why"] == "job_timeout" and result["jobs"][0]["state"] == "timeout", "a job that never ends is a timeout")

# 5. polling
print("== 5. polling ==")
answers = deque([(503, {"detail": "work_area_unavailable"}), (200, job(A, "running")), (502, None), (200, job(A, "completed"))])
with appliance([turn("image_generate", A)], {A: answers}) as fake:
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=60, poll_s=0, sleep=lambda s: None)
    check(result["ok"] and result["jobs"][0]["transient_polls"] == 2, "transient answers are counted and survived")

saved = probe.MAX_TRANSIENT_IN_A_ROW
probe.MAX_TRANSIENT_IN_A_ROW = 3
try:
    with appliance([turn("image_generate", A)], {A: deque([(503, None)])}) as fake:
        result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                                model="m", turn_timeout=5, job_timeout=600, poll_s=0, sleep=lambda s: None)
        check(result["jobs"][0]["state"] == "unreachable" and result["why"] == "job_unreachable" and len(fake.polls) == 3,
              "an appliance that stays away ends the wait")
finally:
    probe.MAX_TRANSIENT_IN_A_ROW = saved

with appliance([], {}) as elsewhere:
    with appliance([turn("image_generate", A)], {A: deque([(302, elsewhere.base + "/api/v1/media/jobs/" + A)])}) as fake:
        result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                                model="m", turn_timeout=5, job_timeout=60, poll_s=0, sleep=lambda s: None)
        check(result["jobs"][0]["state"] == "unreadable" and result["jobs"][0]["error"] == "redirect_refused",
              "a redirect is refused")
        check(elsewhere.polls == [] and elsewhere.chats == [], "and never followed: the token went nowhere else")

with appliance([turn("image_generate", A)], {}) as fake:
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=60, poll_s=0, sleep=lambda s: None)
    check(result["jobs"][0]["state"] == "unreadable" and result["jobs"][0]["error"] == "http_404", "a job the rig does not know")

# 6. image-to-video as the next turn
print("== 6. i2v suite ==")
turns = [turn("image_generate", A), turn("video_generate", B, kind="video"), turn(None)]
with appliance(turns, {A: lifecycle(A), B: lifecycle(B, "queued", "running", "completed", profile="wan22-i2v-gpu1")}) as fake:
    report = run(fake, "i2v")
    check([c["case"] for c in report["cases"]] == ["i2v-picture.r1", "i2v-animate.r1", "control"]
          and report["summary"]["all_ok"] is True, "picture, then animate, then control")
    second = fake.chats[1]["body"]
    check(second["message"] == probe.ANIMATE_MESSAGE
          and second["history"] == [{"role": "user", "content": probe.IMAGE_MESSAGES[0]},
                                    {"role": "assistant", "content": "Det er på vej i samtalen."}],
          "the animate turn carries the picture turn as history")
    check(fake.polls.index(B) > max(i for i, p in enumerate(fake.polls) if p == A),
          "the picture is finished before the clip is asked for")
    check(report["cases"][1]["jobs"][0]["profile_id"] == "wan22-i2v-gpu1" and "[wan22-i2v-gpu1]" in probe.render(report),
          "the clip's profile is shown: it tells which task ran")

with appliance([turn(None), turn(None)], {}) as fake:
    report = run(fake, "i2v")
    check([c["why"] for c in report["cases"]] == ["tool_not_called", "skipped_no_picture", None]
          and len(fake.chats) == 2, "no finished picture: the animate question is not asked")
    check(report["summary"]["tool_cases"] == 1 and report["summary"]["all_ok"] is False, "a skipped case is not in the rate, and the run is not ok")

# 6b. the four pictures and the control as one conversation; refusals by code
print("== 6b. conversation suite, refusals ==")
refused = turn("image_generate", media_refusals=[{"tool": "image_generate", "code": "profile_not_enabled"}])
retried = turn("image_generate", C, tools_used=["image_generate", "image_generate"],
               media_refusals=[{"tool": "image_generate", "code": "invalid_arguments"},
                               {"tool": "note_append", "code": "x"}, {"tool": "image_generate", "code": "Not A Code"}, "junk"])
turns = [turn("image_generate", A, answer="svar 1"), refused, retried, turn("image_generate", D), turn(None), turn(None)]
with appliance(turns, {A: lifecycle(A), C: lifecycle(C), D: lifecycle(D)}) as fake:
    report = run(fake, "conversation")
    cases = report["cases"]
    check([c["case"] for c in cases] == ["conv-1.r1", "conv-2.r1", "conv-3.r1", "conv-4.r1", "conv-control.r1", "control"],
          "four pictures and a control in the thread, then the plain control")
    check("history" not in fake.chats[0]["body"] and [len(c["body"].get("history", [])) for c in fake.chats] == [0, 2, 4, 6, 8, 0],
          "every turn carries the conversation so far; the plain control carries none")
    check(fake.chats[1]["body"]["history"] == [{"role": "user", "content": probe.IMAGE_MESSAGES[0]},
                                               {"role": "assistant", "content": "svar 1"}],
          "history is the user's words and the model's answer, in order")
    check([c["history_turns"] for c in cases] == [0, 1, 2, 3, 4, 0], "the report says how deep in the conversation each case was")
    check(cases[1]["ok"] is False and cases[1]["why"] == "no_job_reference" and cases[1]["refusals"] == ["profile_not_enabled"],
          "a refused picture is reported with the rig's code, not only as 'no job'")
    check(cases[2]["ok"] is True and cases[2]["refusals"] == ["invalid_arguments"],
          "a refusal the model recovered from in the same turn: ok, and the code is kept (other tools and non-codes dropped)")
    text = probe.render(report)
    check("afvist:profile_not_enabled" in text and "afvisninger: invalid_arguments, profile_not_enabled" in text,
          "the table and the summary name the codes")
    check(report["summary"]["refusals"] == ["invalid_arguments", "profile_not_enabled"] and "svar 1" not in json.dumps(report),
          "codes are in the report; the model's text still is not")

with appliance([turn("image_generate", A)] * 1 + [turn(None)], {A: lifecycle(A)}) as fake:
    report = run(fake, "image")
    check(all(c["refusals"] == [] for c in report["cases"]) and "afvisninger" not in probe.render(report),
          "a worker without media_refusals: no refusals, no line")

# 6c. the turn as the apps send it: streamed, with a system prompt
print("== 6c. stream, system prompt ==")
with appliance([turn("image_generate", A), turn(None)], {A: lifecycle(A)}) as fake:
    report = run(fake, "image", stream=True, system="Du er Kaliv.")
    report["cases"] = report["cases"][:1] + report["cases"][-1:]
    check(fake.chats[0]["path"] == "/api/v1/tools/chat/stream" and fake.chats[0]["body"].get("system") == "Du er Kaliv.",
          "--stream sends to the stream route, with the system prompt in its own field")
    check(report["cases"][0]["ok"] is True and report["cases"][0]["jobs"][0]["state"] == "completed",
          "the result line of the stream is read like the plain answer")
    check(report["stream"] is True and report["system_chars"] == 12 and "Du er Kaliv" not in json.dumps(report),
          "the report says how the turn was sent; the prompt's length, never its text")
    check("via=stream system=12" in probe.render(report), "and so does the table's first line")

error_line = json.dumps({"phase": "tænker"}) + "\n" + json.dumps({"error": "image_generate: args skal være et objekt", "status": 400}) + "\n"
cut = json.dumps({"phase": "tænker"}) + "\n"
with appliance([(200, error_line), (200, cut), (200, "not json\n" + json.dumps({"error": "boom"}) + "\n")], {}) as fake:
    report = run(fake, "image", stream=True)
    first, second, third = report["cases"][:3]
    check(first["ok"] is False and first["http"] == 400 and first["why"] == "turn_failed"
          and first["turn_error"] == "image_generate: args skal være et objekt",
          "an error line is the turn's failure, with its status and the rig's reason")
    check(second["ok"] is False and second["http"] == 0 and "turn_error" not in second,
          "a stream with no result and no error was cut: an interrupted turn")
    check(third["http"] == 500 and third["turn_error"] == "boom", "an error line without a status is a 500")
    check("image_generate: args skal være et objekt" in probe.render(report), "the reason is in the table")

with appliance([turn("image_generate", A), turn(None)], {A: lifecycle(A)}) as fake:
    report = run(fake, "image")
    check(fake.chats[0]["path"] == "/api/v1/tools/chat" and "system" not in fake.chats[0]["body"]
          and report["stream"] is False and report["system_chars"] == 0 and "via=chat " in probe.render(report),
          "without the flags nothing changes: the plain route, no system field")

with tempfile.TemporaryDirectory() as tmp:
    prompt = Path(tmp) / "system.txt"
    prompt.write_text("\ufeffDu er Kaliv.\n", encoding="utf-8")
    with appliance([turn(None)] * 3, {}) as fake:
        probe.main(["--base", fake.base, "--suite", "video", "--no-vram", "--stream", "--system-file", str(prompt)],
                   env={"MODELRIG_TOKEN": TOKEN})
        check(fake.chats and fake.chats[0]["body"].get("system") == "Du er Kaliv."
              and fake.chats[0]["path"].endswith("/stream"), "--system-file is read (BOM and trailing newline dropped) and sent")
    empty = Path(tmp) / "empty.txt"
    empty.write_text("  \n", encoding="utf-8")
    with appliance([], {}) as fake:
        check(probe.main(["--base", fake.base, "--system-file", str(empty)], env={"MODELRIG_TOKEN": TOKEN}) == 2
              and probe.main(["--base", fake.base, "--system-file", str(Path(tmp) / "missing.txt")],
                             env={"MODELRIG_TOKEN": TOKEN}) == 2 and not fake.chats,
              "an empty or missing system file is a setup error: exit 2, nothing sent")

# 7. VRAM sampling
print("== 7. vram ==")
samples = iter([{0: 9000, 1: 900}, {0: 9100, 1: 4000}, {0: 9100, 1: 11000}, {0: 9050, 1: 7700}] + [{0: 9000, 1: 7700}] * 10)
with appliance([turn("image_generate", A)], {A: lifecycle(A)}) as fake:
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=60, poll_s=0, sleep=lambda s: None,
                            vram=lambda: next(samples))
    check(result["vram_before_mib"] == {"0": 9000, "1": 900}, "where the chat model sits before the job")
    check(result["jobs"][0]["vram_peak_mib"] == {"0": 9100, "1": 11000}, "the peak per GPU while the job ran")
with appliance([turn("image_generate", A)], {A: lifecycle(A)}) as fake:
    result = probe.run_case(probe.Http(fake.base, TOKEN), {"id": "x", "message": "m", "expect": "image_generate"},
                            model="m", turn_timeout=5, job_timeout=60, poll_s=0, sleep=lambda s: None)
    check(result["vram_before_mib"] is None and result["jobs"][0]["vram_peak_mib"] is None, "no sampler: nothing is claimed")

# 8. main, and the plan
print("== 8. main ==")
turns = [turn("video_generate", A, kind="video"), turn(None)]
with appliance(turns, {A: lifecycle(A)}) as fake, tempfile.TemporaryDirectory() as tmp:
    out = io.StringIO()
    path = Path(tmp) / "report.json"
    with contextlib.redirect_stdout(out):
        code = probe.main(["--base", fake.base, "--suite", "video", "--report", str(path), "--no-vram",
                           "--poll-seconds", "0"], env={"MODELRIG_TOKEN": TOKEN})
    written = json.loads(path.read_text(encoding="utf-8"))
    check(code == 0 and written["summary"]["all_ok"] is True and written["suite"] == "video", "exit 0 and a report file when all is well")
    check("video-1.r1" in out.getvalue() and TOKEN not in out.getvalue() and TOKEN not in path.read_text(encoding="utf-8"),
          "the table is printed; the token is in neither output")
with appliance([turn(None), turn(None)], {}) as fake:
    with contextlib.redirect_stdout(io.StringIO()):
        code = probe.main(["--base", fake.base, "--suite", "video", "--no-vram"], env={"MODELRIG_TOKEN": TOKEN})
    check(code == 1, "exit 1 when a case did not meet its expectation")
err = io.StringIO()
with contextlib.redirect_stderr(err):
    check(probe.main(["--base", "http://192.168.1.27:8080"], env={"MODELRIG_TOKEN": TOKEN}) == 2
          and probe.main([], env={}) == 2
          and probe.main(["--rounds", "0"], env={"MODELRIG_TOKEN": TOKEN}) == 2, "exit 2 for a setup error, nothing sent")
check(TOKEN not in err.getvalue(), "and the token is not in the error text")
check(len(probe.suite_cases("image", 3)) == 13 and probe.suite_cases("image", 3)[-1]["expect"] is None,
      "rounds repeat the tool cases; the control runs once, last")

plan = code_of(ROOT / "docs" / "RIGDAG_MEDIE_I_CHAT.md")
for message in probe.IMAGE_MESSAGES + (probe.VIDEO_MESSAGE, probe.ANIMATE_MESSAGE, probe.CONTROL_MESSAGE):
    check(message in plan, f"the plan lists the probe's message: {message}")
check("scripts\\media_chat_probe.py" in plan or "scripts/media_chat_probe.py" in plan, "the plan tells how to run the probe")

print(f"\n===== MEDIA CHAT PROBE: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

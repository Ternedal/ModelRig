#!/usr/bin/env python3
"""Measure "pictures and clips in the chat" on a running appliance. NEVER release evidence.

The rig-day plan (docs/RIGDAG_MEDIE_I_CHAT.md) asks three things that are tedious
and imprecise by hand: does the model call ``image_generate`` / ``video_generate``
on a Danish request, how long does the turn take, and how long until the job is
a finished picture or clip. This probe sends the plan's own fixed messages through
``/api/v1/tools/chat``, follows every job the turn queued, and prints one table
and one JSON report.

What it is careful about:

- **Loopback only.** The base URL must be a bare ``http://127.0.0.1:<port>`` (or
  ``[::1]``); no proxy, no redirect is followed. It is run on the rig, against the
  rig.
- **The token comes from the environment** (``MODELRIG_TOKEN``), never from an
  argument, and is never printed or written to the report.
- **No model output in the report**: only what was called, how long it took and
  how each job ended. The messages are the fixed ones below, not the user's.
- **It generates for real.** Every tool call queues a job on the GPU; the probe
  runs the cases one at a time and waits for each job before the next.

``--suite conversation`` sends the picture messages as one conversation with its
history, ``--stream`` uses the route the apps use, and ``--system-file`` adds the
system prompt the app sends: together they are a phone's turn without the phone.

Exit 0 when every case met its expectation, 1 when one did not, 2 for a setup
error (address, token).

  $env:MODELRIG_TOKEN = '<token>'
  python scripts/media_chat_probe.py --suite image --rounds 3 --report $env:TEMP\\media-chat-probe.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = "kaliv-media-chat-probe/v1"
TOKEN_ENV = "MODELRIG_TOKEN"
CHAT_ROUTE = "/api/v1/tools/chat"
# The same turn as a stream of NDJSON lines: phases, then one ``result`` (or ``error``).
# It is the route the phone and the desktop app use.
STREAM_ROUTE = CHAT_ROUTE + "/stream"
JOB_ROUTE = "/api/v1/media/jobs/"
MAX_REPLY = 1024 * 1024
MAX_SYSTEM_CHARS = 8000
TERMINAL = ("completed", "failed", "cancelled", "expired")
STATES = ("queued", "running", "publishing") + TERMINAL
TOOL_KIND = {"image_generate": "image", "video_generate": "video"}
_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
_CODE = re.compile(r"^[a-z0-9_]{1,64}$")

# The plan's own messages (docs/RIGDAG_MEDIE_I_CHAT.md lists them; a test keeps the two in step).
IMAGE_MESSAGES = (
    "lav et billede af en rød cykel ved en sø",
    "tegn en kat der sover i en vindueskarm",
    "kan du lave et fotorealistisk billede af et fyrtårn i tåge?",
    "generér et billede af et gammelt bibliotek",
)
VIDEO_MESSAGE = "lav en video af en papirbåd der driver over en dam"
# A length the user names: the tool turns seconds into the profile's frames (#2480). The table
# cannot see the clip's length -- compare the job time with the plain video case, and play it.
VIDEO_LENGTH_MESSAGE = "lav en video på 5 sekunder af en papirbåd der driver over en dam"
ANIMATE_MESSAGE = "lav en video af det billede"
CONTROL_MESSAGE = "hvad er hovedstaden i Frankrig?"


class ProbeError(ValueError):
    """A setup problem: nothing was sent."""


class _Redirected(Exception):
    """The appliance tried to send the request elsewhere: never followed, and not a transient failure."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401 - urllib hook
        raise _Redirected()


def ensure_loopback(raw: str) -> str:
    try:
        url = urlsplit(raw)
        port = url.port
    except ValueError as exc:
        raise ProbeError("invalid base URL") from exc
    if (url.scheme != "http" or url.hostname not in ("127.0.0.1", "::1")
            or port is None or not 1 <= port <= 65535
            or url.username is not None or url.password is not None
            or url.path not in ("", "/") or url.query or url.fragment):
        raise ProbeError("the base URL must be a bare http loopback address with a port, e.g. http://127.0.0.1:8080")
    return raw.rstrip("/")


def token_from_env(env=None) -> str:
    token = (os.environ if env is None else env).get(TOKEN_ENV, "").strip()
    if not token:
        raise ProbeError(f"{TOKEN_ENV} is not set: pair first and put the device token in the environment")
    return token


class Http:
    """The two calls the probe makes; a status code and a parsed body, or a transport failure."""

    def __init__(self, base: str, token: str):
        self._base, self._token = base, token
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def call(self, route: str, body: dict | None, timeout: float) -> tuple[int, object]:
        """``(status, json-or-None)``; status 0: the appliance could not be reached, -1: it redirected (refused)."""
        if not (route in (CHAT_ROUTE, STREAM_ROUTE) or (route.startswith(JOB_ROUTE) and _JOB_ID.fullmatch(route[len(JOB_ROUTE):]))):
            raise ProbeError("unexpected route")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/json", "Cache-Control": "no-store"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self._base + route, data=data, headers=headers, method="GET" if data is None else "POST")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                raw = response.read(MAX_REPLY + 1)
                if route == STREAM_ROUTE and response.status == 200:
                    return _stream_result(raw)
                return response.status, _parse(raw)
        except HTTPError as exc:
            try:
                return exc.code, _parse(exc.read(MAX_REPLY + 1))
            except OSError:
                return exc.code, None
        except _Redirected:
            return -1, None
        except (URLError, OSError):
            return 0, None


def _stream_result(raw: bytes) -> tuple[int, object]:
    """The last ``result`` line of a tools stream as ``(200, turn)``, the way the apps read it.

    An ``error`` line is the turn's failure -- its status if it carries one, else 500 --
    with the rig's reason kept short under ``detail``. No result and no error: the stream
    was cut, which the apps report as an interrupted turn (status 0 here).
    """
    if len(raw) > MAX_REPLY:
        return 0, None
    turn = None
    for line in raw.decode("utf-8", "replace").splitlines():
        try:
            item = json.loads(line) if line.strip() else None
        except ValueError:
            continue
        if not isinstance(item, dict):
            continue
        if item.get("error"):
            status = item.get("status")
            return (status if isinstance(status, int) and not isinstance(status, bool) and 400 <= status <= 599 else 500,
                    {"detail": str(item["error"])[:160]})
        if isinstance(item.get("result"), dict):
            turn = item["result"]
    return (200, turn) if turn is not None else (0, None)


def _parse(raw: bytes):
    if len(raw) > MAX_REPLY:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None


def job_refs(turn: object) -> list[dict]:
    """The turn's well-formed job references, read as the clients read them: anything else is no job."""
    jobs = turn.get("media_jobs") if isinstance(turn, dict) else None
    out, seen = [], set()
    for ref in jobs if isinstance(jobs, list) else []:
        if not isinstance(ref, dict):
            continue
        job_id, kind = ref.get("job_id"), ref.get("kind", "image")
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id) or job_id in seen:
            continue
        if ref.get("status_url") != JOB_ROUTE + job_id or kind not in ("image", "video"):
            continue
        seen.add(job_id)
        entry = {"job_id": job_id, "kind": kind}
        source = ref.get("source_job_id")
        if isinstance(source, str) and _JOB_ID.fullmatch(source):
            entry["source_job_id"] = source  # a clip made from a picture says which picture job
        out.append(entry)
    return out


_REFUSAL_CODE = re.compile(r"[a-z0-9_]{1,64}")


def refusal_codes(turn: object) -> list[str]:
    """The codes of the media tool calls this turn that queued nothing (``media_refusals``).

    An older worker does not send the field: that is an empty list, not an error.
    """
    listed = turn.get("media_refusals") if isinstance(turn, dict) else None
    out = []
    for item in listed if isinstance(listed, list) else []:
        if (isinstance(item, dict) and item.get("tool") in TOOL_KIND and isinstance(item.get("code"), str)
                and _REFUSAL_CODE.fullmatch(item["code"])):
            out.append(item["code"])
    return out[:8]


def vram_sampler():
    """``() -> {gpu_index: MiB used}`` through nvidia-smi, or None where there is none."""
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return None

    def sample() -> dict[int, int]:
        try:
            done = subprocess.run([exe, "--query-gpu=index,memory.used", "--format=csv,noheader,nounits"],
                                  capture_output=True, text=True, timeout=5, check=False)
        except (OSError, subprocess.SubprocessError):
            return {}
        used: dict[int, int] = {}
        for line in done.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                used[int(parts[0])] = int(parts[1])
        return used

    return sample


MAX_TRANSIENT_IN_A_ROW = 30


def _own_seconds(job: dict) -> float | None:
    """The job's own time on the rig's clock: asked for -> last change. None when it cannot be read.

    ``seconds`` below is how long the probe waited AFTER the turn returned. A job is queued
    while the model is still writing its answer, so that wait hides whatever part of the job
    overlapped the turn -- on the rig 20/11 it read 17 s for jobs the executor timed at 50 s.
    """
    created, updated = job.get("created"), job.get("updated")
    if (isinstance(created, (int, float)) and isinstance(updated, (int, float))
            and not isinstance(created, bool) and not isinstance(updated, bool) and 0 <= updated - created < 86400):
        return round(updated - created, 1)
    return None


def follow_job(http: Http, job_id: str, *, timeout_s: float, poll_s: float, clock=time.monotonic, sleep=time.sleep,
               vram=None) -> dict:
    """Poll one job to a terminal state. Transient answers (unreachable, 5xx) are counted, not fatal --
    until ``MAX_TRANSIENT_IN_A_ROW`` of them in a row say the appliance is gone."""
    started = clock()
    first_seen: dict[str, float] = {}
    peak: dict[int, int] = {}
    transient = in_a_row = 0
    result = {"job_id": job_id, "state": "timeout", "error": None, "profile_id": None}
    while True:
        status, body = http.call(JOB_ROUTE + job_id, None, timeout=30)
        now = clock() - started
        if vram is not None:
            for gpu, used in vram().items():
                peak[gpu] = max(peak.get(gpu, 0), used)
        if status == 200 and isinstance(body, dict) and body.get("id") == job_id and body.get("state") in STATES:
            state = body["state"]
            first_seen.setdefault(state, round(now, 1))
            in_a_row = 0
            error = body.get("error")
            result.update(state=state, profile_id=body.get("profile_id") if isinstance(body.get("profile_id"), str) else None,
                          error=error if isinstance(error, str) and _CODE.fullmatch(error) else None)
            own = _own_seconds(body)
            if own is not None:
                result["rig_seconds"] = own
            if state in TERMINAL:
                break
        elif status in (0, 500, 502, 503, 504):
            transient += 1
            in_a_row += 1
            if in_a_row >= MAX_TRANSIENT_IN_A_ROW:
                result.update(state="unreachable", error=None)
                break
        else:
            reason = {200: "unexpected_answer", -1: "redirect_refused"}.get(status, f"http_{status}")
            result.update(state="unreadable", error=reason)
            break
        if now >= timeout_s:
            result["state"] = "timeout"
            break
        sleep(poll_s)
    result.update(seconds=round(clock() - started, 1), first_seen_s=first_seen, transient_polls=transient,
                  vram_peak_mib={str(k): v for k, v in sorted(peak.items())} if vram is not None else None)
    return result


def run_case(http: Http, case: dict, *, model: str, turn_timeout: float, job_timeout: float, poll_s: float,
             clock=time.monotonic, sleep=time.sleep, vram=None, stream: bool = False, system: str | None = None) -> dict:
    """One message through the tools turn, then every job it queued. ``case['expect']`` is a tool name or None."""
    before = vram() if vram is not None else None
    body = {"message": case["message"], "model": model}
    if system:
        body["system"] = system
    if case.get("history"):
        body["history"] = case["history"]
    if case.get("pictures") is not None:
        # The image jobs this conversation holds, oldest first: what an app sends so that
        # "det billede" means this conversation's picture and not the owner's newest anywhere.
        body["conversation_image_jobs"] = list(case["pictures"])
    started = clock()
    status, turn = http.call(STREAM_ROUTE if stream else CHAT_ROUTE, body, timeout=turn_timeout)
    turn_seconds = round(clock() - started, 1)
    out = {"case": case["id"], "expect": case["expect"], "http": status, "turn_seconds": turn_seconds,
           "status": None, "tools_used": [], "jobs": [], "refusals": [], "answer_chars": 0,
           "history_turns": len(case.get("history") or []) // 2,
           "vram_before_mib": {str(k): v for k, v in sorted(before.items())} if before is not None else None}
    if status != 200 or not isinstance(turn, dict):
        out.update(ok=False, why="turn_failed")
        detail = turn.get("detail") if isinstance(turn, dict) else None
        if isinstance(detail, str) and detail:
            # The rig's own reason for refusing the turn (a gate denial, a model error) -- not the model's text.
            out["turn_error"] = detail[:160]
        return out
    used = [t for t in turn.get("tools_used") or [] if isinstance(t, str)]
    answer = turn.get("answer") if isinstance(turn.get("answer"), str) else ""
    refs = job_refs(turn)
    out.update(status=turn.get("status") if isinstance(turn.get("status"), str) else None, tools_used=used,
               answer_chars=len(answer), _answer=answer, refusals=refusal_codes(turn))
    for ref in refs:
        followed = follow_job(http, ref["job_id"], timeout_s=job_timeout, poll_s=poll_s, clock=clock, sleep=sleep, vram=vram)
        followed["kind"] = ref["kind"]
        if "source_job_id" in ref:
            followed["source_job_id"] = ref["source_job_id"]
        out["jobs"].append(followed)
    media_tools = [t for t in used if t in TOOL_KIND]
    expect = case["expect"]
    if expect is None:
        out.update(ok=not media_tools and not refs, why=None if not media_tools and not refs else "unexpected_tool_call")
    elif expect not in used:
        out.update(ok=False, why="tool_not_called")
    elif len(refs) != 1 or refs[0]["kind"] != TOOL_KIND[expect]:
        out.update(ok=False, why="no_job_reference")
    elif case.get("expect_source") is not None and refs[0].get("source_job_id") is None:
        # The rig did not say which picture it took: a worker before the reference named it.
        out.update(ok=False, why="source_not_reported")
    elif case.get("expect_source") is not None and refs[0]["source_job_id"] != case["expect_source"]:
        # The clip starts from another picture than the one this conversation holds.
        out.update(ok=False, why="wrong_source")
    elif out["jobs"][0]["state"] != "completed":
        out.update(ok=False, why="job_" + out["jobs"][0]["state"])
    else:
        out.update(ok=True, why=None)
    return out


def suite_cases(suite: str, rounds: int) -> list[dict]:
    """The cases of a suite, in order. ``i2v`` pairs: a picture, then "animate that picture" as the next turn."""
    cases: list[dict] = []
    for r in range(1, rounds + 1):
        if suite == "image":
            cases += [{"id": f"image-{i}.r{r}", "message": m, "expect": "image_generate"}
                      for i, m in enumerate(IMAGE_MESSAGES, 1)]
        elif suite == "conversation":
            # The four picture messages and the control as ONE conversation, the way a phone
            # sends them. Rig 20/11: 19/19 without history, and a refusal on the phone with it.
            cases += [{"id": f"conv-{i}.r{r}", "message": m, "expect": "image_generate", "thread": f"r{r}"}
                      for i, m in enumerate(IMAGE_MESSAGES, 1)]
            cases.append({"id": f"conv-control.r{r}", "message": CONTROL_MESSAGE, "expect": None, "thread": f"r{r}"})
        elif suite == "two-conversations":
            # Review 6004675603: a picture in conversation A, then one in conversation B that
            # finishes later, then "det billede" back in A. The clip must start from A's picture.
            cases.append({"id": f"tc-a.r{r}", "message": IMAGE_MESSAGES[0], "expect": "image_generate", "thread": f"a{r}"})
            cases.append({"id": f"tc-b.r{r}", "message": IMAGE_MESSAGES[1], "expect": "image_generate", "thread": f"b{r}"})
            cases.append({"id": f"tc-animate.r{r}", "message": ANIMATE_MESSAGE, "expect": "video_generate",
                          "thread": f"a{r}", "source_from": f"tc-a.r{r}", "needs": [f"tc-a.r{r}", f"tc-b.r{r}"]})
        elif suite == "video":
            cases.append({"id": f"video-1.r{r}", "message": VIDEO_MESSAGE, "expect": "video_generate"})
        elif suite == "video-length":
            cases.append({"id": f"video-5s.r{r}", "message": VIDEO_LENGTH_MESSAGE, "expect": "video_generate"})
        elif suite == "i2v":
            cases.append({"id": f"i2v-picture.r{r}", "message": IMAGE_MESSAGES[0], "expect": "image_generate"})
            cases.append({"id": f"i2v-animate.r{r}", "message": ANIMATE_MESSAGE, "expect": "video_generate",
                          "history_from": f"i2v-picture.r{r}"})
        else:
            raise ProbeError("unknown suite")
    cases.append({"id": "control", "message": CONTROL_MESSAGE, "expect": None})
    return cases


def run_suite(http: Http, suite: str, *, model: str, rounds: int = 1, turn_timeout: float = 300.0,
              job_timeout: float = 1800.0, poll_s: float = 2.0, clock=time.monotonic, sleep=time.sleep,
              vram=None, stream: bool = False, system: str | None = None) -> dict:
    results: list[dict] = []
    by_id: dict[str, dict] = {}
    threads: dict[str, list[dict]] = {}
    pictures: dict[str, list[str]] = {}
    for case in suite_cases(suite, rounds):
        thread = case.get("thread")
        if thread is not None:
            case = dict(case, pictures=list(pictures.get(thread, [])))
            if threads.get(thread):
                case["history"] = list(threads[thread])
        if "source_from" in case:
            needed = [by_id.get(name) for name in case.get("needs", [case["source_from"]])]
            if any(n is None or not n.get("ok") for n in needed):
                # Without both pictures finished there is nothing to tell apart.
                skipped = {"case": case["id"], "expect": case["expect"], "ok": False, "why": "skipped_no_picture",
                           "http": None, "turn_seconds": None, "status": None, "tools_used": [], "jobs": [],
                           "refusals": [], "history_turns": 0, "answer_chars": 0, "vram_before_mib": None}
                results.append(skipped)
                by_id[case["id"]] = skipped
                continue
            wanted = [j["job_id"] for j in by_id[case["source_from"]].get("jobs", []) if j.get("kind") == "image"]
            case = dict(case, expect_source=wanted[0] if wanted else "")
        source = by_id.get(case.get("history_from", ""))
        if "history_from" in case:
            if source is None or not source.get("ok"):
                # No finished picture to animate: asking would measure something else.
                skipped = {"case": case["id"], "expect": case["expect"], "ok": False, "why": "skipped_no_picture",
                           "http": None, "turn_seconds": None, "status": None, "tools_used": [], "jobs": [],
                           "refusals": [], "history_turns": 0, "answer_chars": 0, "vram_before_mib": None}
                results.append(skipped)
                by_id[case["id"]] = skipped
                continue
            case = dict(case, history=[{"role": "user", "content": IMAGE_MESSAGES[0]},
                                       {"role": "assistant", "content": source.get("_answer", "")}],
                        pictures=[j["job_id"] for j in source.get("jobs", []) if j.get("kind") == "image"])
        result = run_case(http, case, model=model, turn_timeout=turn_timeout, job_timeout=job_timeout, poll_s=poll_s,
                          clock=clock, sleep=sleep, vram=vram, stream=stream, system=system)
        results.append(result)
        by_id[case["id"]] = result
        if thread is not None and result.get("http") == 200:
            # What a client keeps: the user's words and the model's answer. Never a tool result.
            threads.setdefault(thread, []).extend([{"role": "user", "content": case["message"]},
                                                   {"role": "assistant", "content": result.get("_answer", "")}])
            pictures.setdefault(thread, []).extend(j["job_id"] for j in result.get("jobs", []) if j.get("kind") == "image")
    for result in results:
        result.pop("_answer", None)  # used for the next turn's history only; never reported
    return {"schema": SCHEMA, "evidence": False, "suite": suite, "model": model, "rounds": rounds,
            # How the turn was sent: the apps stream it and send the user's own system prompt.
            # Only the prompt's length is kept.
            "stream": bool(stream), "system_chars": len(system or ""),
            "cases": results, "summary": summarize(results)}


def summarize(results: list[dict]) -> dict:
    tool_cases = [r for r in results if r["expect"] is not None and r["why"] != "skipped_no_picture"]
    called = [r for r in tool_cases if r["expect"] in r["tools_used"]]
    jobs = [j for r in results for j in r["jobs"]]
    finished = [j for j in jobs if j["state"] == "completed"]
    # The job's own time where the rig reports it; the wait after the turn only as a fallback.
    done = [j.get("rig_seconds", j["seconds"]) for j in finished]
    # What the user waits: the turn, then whatever of the job was left when it returned.
    to_picture = [round(r["turn_seconds"] + r["jobs"][0]["seconds"], 1) for r in results
                  if r["turn_seconds"] is not None and len(r["jobs"]) == 1 and r["jobs"][0]["state"] == "completed"]
    turns = [r["turn_seconds"] for r in results if r["turn_seconds"] is not None and r["http"] == 200]
    controls = [r for r in results if r["expect"] is None]
    return {
        "tool_cases": len(tool_cases),
        "tool_called": len(called),
        "tool_call_rate": round(len(called) / len(tool_cases), 3) if tool_cases else None,
        "jobs": len(jobs),
        "jobs_completed": len(done),
        "job_seconds_median": round(statistics.median(done), 1) if done else None,
        "job_seconds_max": max(done) if done else None,
        "job_seconds_source": ("rig" if finished and all("rig_seconds" in j for j in finished)
                               else "wait_after_turn" if finished else None),
        "request_to_done_seconds_median": round(statistics.median(to_picture), 1) if to_picture else None,
        "turn_seconds_median": round(statistics.median(turns), 1) if turns else None,
        "refusals": sorted({code for r in results for code in r.get("refusals") or []}),
        "control_ok": all(r["ok"] for r in controls) if controls else None,
        "all_ok": all(r["ok"] for r in results),
    }


def render(report: dict) -> str:
    how = ("stream" if report.get("stream") else "chat") + (f" system={report['system_chars']}" if report.get("system_chars") else "")
    lines = [f"suite={report['suite']} model={report['model']} rounds={report['rounds']} via={how}  (dev channel: not evidence)", ""]
    lines.append(f"{'case':<18} {'ok':<3} {'turn s':>7} {'tool':<15} {'job':<11} {'job s':>7}  note")
    for r in report["cases"]:
        job = r["jobs"][0] if r["jobs"] else None
        tools = ",".join(t for t in r["tools_used"] if t in TOOL_KIND) or "-"
        note = r["why"] or ""
        if r.get("refusals"):
            note = (note + " afvist:" + ",".join(r["refusals"])).strip()
        if r.get("turn_error"):
            note = (note + " " + r["turn_error"]).strip()
        if job and job.get("error"):
            note = (note + " " + job["error"]).strip()
        if job and job.get("profile_id"):
            note = (note + f" [{job['profile_id']}]").strip()
        lines.append(f"{r['case']:<18} {'ja' if r['ok'] else 'NEJ':<3} "
                     f"{'-' if r['turn_seconds'] is None else r['turn_seconds']:>7} {tools:<15} "
                     f"{job['state'] if job else '-':<11} {job.get('rig_seconds', job['seconds']) if job else '-':>7}  {note}")
    s = report["summary"]
    lines += ["", f"værktøj kaldt: {s['tool_called']}/{s['tool_cases']}   job færdige: {s['jobs_completed']}/{s['jobs']}   "
                  f"median job: {s['job_seconds_median']} s   median tur: {s['turn_seconds_median']} s   "
                  f"kontrol: {'ok' if s['control_ok'] else 'FEJL'}"]
    if s.get("request_to_done_seconds_median") is not None:
        how_timed = ("riggens egen tid" if s.get("job_seconds_source") == "rig"
                     else "ventetid efter turen (riggen oplyste ikke jobbets egen tid)")
        lines.append(f"besked -> færdig (median): {s['request_to_done_seconds_median']} s   job s = {how_timed}")
    if s.get("refusals"):
        lines.append("afvisninger: " + ", ".join(s["refusals"]))
    return "\n".join(lines)


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(description="Measure media-in-chat on a running appliance (dev channel, not evidence).")
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--suite", choices=("image", "conversation", "video", "video-length", "i2v", "two-conversations"), default="image")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--turn-timeout", type=float, default=300.0)
    parser.add_argument("--job-timeout", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--report", default=None, help="write the JSON report here")
    parser.add_argument("--no-vram", action="store_true", help="do not sample nvidia-smi")
    parser.add_argument("--stream", action="store_true",
                        help="send each turn through /tools/chat/stream, as the phone and the desktop app do")
    parser.add_argument("--system-file", default=None,
                        help="a text file with the system prompt the app sends (the phone's own); only its length is reported")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.rounds <= 10:
            raise ProbeError("--rounds must be 1..10: every round generates for real")
        if not 0 <= args.poll_seconds <= 60:
            raise ProbeError("--poll-seconds must be 0..60")
        system = None
        if args.system_file:
            try:
                system = Path(args.system_file).read_text(encoding="utf-8-sig").strip()
            except (OSError, UnicodeDecodeError) as exc:
                raise ProbeError(f"--system-file could not be read ({type(exc).__name__})") from None
            if not 0 < len(system) <= MAX_SYSTEM_CHARS:
                raise ProbeError(f"--system-file must hold 1..{MAX_SYSTEM_CHARS} characters")
        http = Http(ensure_loopback(args.base), token_from_env(env))
    except ProbeError as exc:
        print(f"media_chat_probe: {exc}", file=sys.stderr)
        return 2
    report = run_suite(http, args.suite, model=args.model, rounds=args.rounds, turn_timeout=args.turn_timeout,
                       job_timeout=args.job_timeout, poll_s=args.poll_seconds,
                       vram=None if args.no_vram else vram_sampler(), stream=args.stream, system=system)
    print(render(report))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return 0 if report["summary"]["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

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
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = "kaliv-media-chat-probe/v1"
TOKEN_ENV = "MODELRIG_TOKEN"
CHAT_ROUTE = "/api/v1/tools/chat"
JOB_ROUTE = "/api/v1/media/jobs/"
MAX_REPLY = 1024 * 1024
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
        if not (route == CHAT_ROUTE or (route.startswith(JOB_ROUTE) and _JOB_ID.fullmatch(route[len(JOB_ROUTE):]))):
            raise ProbeError("unexpected route")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/json", "Cache-Control": "no-store"}
        if data is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        request = Request(self._base + route, data=data, headers=headers, method="GET" if data is None else "POST")
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return response.status, _parse(response.read(MAX_REPLY + 1))
        except HTTPError as exc:
            try:
                return exc.code, _parse(exc.read(MAX_REPLY + 1))
            except OSError:
                return exc.code, None
        except _Redirected:
            return -1, None
        except (URLError, OSError):
            return 0, None


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
        out.append({"job_id": job_id, "kind": kind})
    return out


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
             clock=time.monotonic, sleep=time.sleep, vram=None) -> dict:
    """One message through the tools turn, then every job it queued. ``case['expect']`` is a tool name or None."""
    before = vram() if vram is not None else None
    body = {"message": case["message"], "model": model}
    if case.get("history"):
        body["history"] = case["history"]
    started = clock()
    status, turn = http.call(CHAT_ROUTE, body, timeout=turn_timeout)
    turn_seconds = round(clock() - started, 1)
    out = {"case": case["id"], "expect": case["expect"], "http": status, "turn_seconds": turn_seconds,
           "status": None, "tools_used": [], "jobs": [], "answer_chars": 0,
           "vram_before_mib": {str(k): v for k, v in sorted(before.items())} if before is not None else None}
    if status != 200 or not isinstance(turn, dict):
        out.update(ok=False, why="turn_failed")
        return out
    used = [t for t in turn.get("tools_used") or [] if isinstance(t, str)]
    answer = turn.get("answer") if isinstance(turn.get("answer"), str) else ""
    refs = job_refs(turn)
    out.update(status=turn.get("status") if isinstance(turn.get("status"), str) else None, tools_used=used,
               answer_chars=len(answer), _answer=answer)
    for ref in refs:
        followed = follow_job(http, ref["job_id"], timeout_s=job_timeout, poll_s=poll_s, clock=clock, sleep=sleep, vram=vram)
        followed["kind"] = ref["kind"]
        out["jobs"].append(followed)
    media_tools = [t for t in used if t in TOOL_KIND]
    expect = case["expect"]
    if expect is None:
        out.update(ok=not media_tools and not refs, why=None if not media_tools and not refs else "unexpected_tool_call")
    elif expect not in used:
        out.update(ok=False, why="tool_not_called")
    elif len(refs) != 1 or refs[0]["kind"] != TOOL_KIND[expect]:
        out.update(ok=False, why="no_job_reference")
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
        elif suite == "video":
            cases.append({"id": f"video-1.r{r}", "message": VIDEO_MESSAGE, "expect": "video_generate"})
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
              vram=None) -> dict:
    results: list[dict] = []
    by_id: dict[str, dict] = {}
    for case in suite_cases(suite, rounds):
        source = by_id.get(case.get("history_from", ""))
        if "history_from" in case:
            if source is None or not source.get("ok"):
                # No finished picture to animate: asking would measure something else.
                skipped = {"case": case["id"], "expect": case["expect"], "ok": False, "why": "skipped_no_picture",
                           "http": None, "turn_seconds": None, "status": None, "tools_used": [], "jobs": [],
                           "answer_chars": 0, "vram_before_mib": None}
                results.append(skipped)
                by_id[case["id"]] = skipped
                continue
            case = dict(case, history=[{"role": "user", "content": IMAGE_MESSAGES[0]},
                                       {"role": "assistant", "content": source.get("_answer", "")}])
        result = run_case(http, case, model=model, turn_timeout=turn_timeout, job_timeout=job_timeout, poll_s=poll_s,
                          clock=clock, sleep=sleep, vram=vram)
        results.append(result)
        by_id[case["id"]] = result
    for result in results:
        result.pop("_answer", None)  # used for the next turn's history only; never reported
    return {"schema": SCHEMA, "evidence": False, "suite": suite, "model": model, "rounds": rounds,
            "cases": results, "summary": summarize(results)}


def summarize(results: list[dict]) -> dict:
    tool_cases = [r for r in results if r["expect"] is not None and r["why"] != "skipped_no_picture"]
    called = [r for r in tool_cases if r["expect"] in r["tools_used"]]
    jobs = [j for r in results for j in r["jobs"]]
    done = [j["seconds"] for j in jobs if j["state"] == "completed"]
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
        "turn_seconds_median": round(statistics.median(turns), 1) if turns else None,
        "control_ok": all(r["ok"] for r in controls) if controls else None,
        "all_ok": all(r["ok"] for r in results),
    }


def render(report: dict) -> str:
    lines = [f"suite={report['suite']} model={report['model']} rounds={report['rounds']}  (dev channel: not evidence)", ""]
    lines.append(f"{'case':<18} {'ok':<3} {'turn s':>7} {'tool':<15} {'job':<11} {'job s':>7}  note")
    for r in report["cases"]:
        job = r["jobs"][0] if r["jobs"] else None
        tools = ",".join(t for t in r["tools_used"] if t in TOOL_KIND) or "-"
        note = r["why"] or ""
        if job and job.get("error"):
            note = (note + " " + job["error"]).strip()
        if job and job.get("profile_id"):
            note = (note + f" [{job['profile_id']}]").strip()
        lines.append(f"{r['case']:<18} {'ja' if r['ok'] else 'NEJ':<3} "
                     f"{'-' if r['turn_seconds'] is None else r['turn_seconds']:>7} {tools:<15} "
                     f"{job['state'] if job else '-':<11} {job['seconds'] if job else '-':>7}  {note}")
    s = report["summary"]
    lines += ["", f"værktøj kaldt: {s['tool_called']}/{s['tool_cases']}   job færdige: {s['jobs_completed']}/{s['jobs']}   "
                  f"median job: {s['job_seconds_median']} s   median tur: {s['turn_seconds_median']} s   "
                  f"kontrol: {'ok' if s['control_ok'] else 'FEJL'}"]
    return "\n".join(lines)


def main(argv=None, env=None) -> int:
    parser = argparse.ArgumentParser(description="Measure media-in-chat on a running appliance (dev channel, not evidence).")
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--model", default="qwen3:14b")
    parser.add_argument("--suite", choices=("image", "video", "i2v"), default="image")
    parser.add_argument("--rounds", type=int, default=1)
    parser.add_argument("--turn-timeout", type=float, default=300.0)
    parser.add_argument("--job-timeout", type=float, default=1800.0)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--report", default=None, help="write the JSON report here")
    parser.add_argument("--no-vram", action="store_true", help="do not sample nvidia-smi")
    args = parser.parse_args(argv)
    try:
        if not 1 <= args.rounds <= 10:
            raise ProbeError("--rounds must be 1..10: every round generates for real")
        if not 0 <= args.poll_seconds <= 60:
            raise ProbeError("--poll-seconds must be 0..60")
        http = Http(ensure_loopback(args.base), token_from_env(env))
    except ProbeError as exc:
        print(f"media_chat_probe: {exc}", file=sys.stderr)
        return 2
    report = run_suite(http, args.suite, model=args.model, rounds=args.rounds, turn_timeout=args.turn_timeout,
                       job_timeout=args.job_timeout, poll_s=args.poll_seconds,
                       vram=None if args.no_vram else vram_sampler())
    print(render(report))
    if args.report:
        with open(args.report, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return 0 if report["summary"]["all_ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

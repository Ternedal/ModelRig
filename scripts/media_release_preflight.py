#!/usr/bin/env python3
"""Is this rig ready to run image and video from a RELEASED appliance? Read-only.

Media in the chat has run on the rig from source, with the executor started by
hand. A release is different in three ways that nothing has shown on the rig:
the supervisor starts the executor itself (four keys in the env file), the
executor still runs from a source checkout that has to be the release's own
commit, and every switch is read from the appliance's env file instead of a
PowerShell window. A mistake in any of them shows up as "nothing happens" at
the rig. This asks the same questions beforehand, in a few seconds, and says
what to change.

    py -3.11 scripts\\media_release_preflight.py --env-file C:\\Rig\\ModelRig\\modelrig.env

    # after the tag exists, also bind the executor's source to it:
    ... --expect-version 2.0.21 --expect-sha <full sha of the tag>

It reads the env file, files it names, `nvidia-smi`, the media Python
(`import torch`, and the executor's own start check run from the executor's
own source), Ollama's tag list and the appliance's /healthz. It writes nothing
(git without optional locks, Python with -B), starts nothing, talks to
127.0.0.1 only (no proxy, no redirect) and prints no value of a secret: a
text another component wrote (the executor's refusal, a loader's error) is
never repeated -- only one of this file's own sentences and the key names it
mentions -- so the output can be shared.

Only the env file is read. A child of the supervisor also inherits the
supervisor's own environment, which this cannot see. That cuts both ways: a
key set only there is reported here as missing although the executor would see
it, and a key set only there can make the executor behave differently from
what is checked here. For a release, every media key belongs in the file.

Exit 0: no FAIL. Exit 1: at least one FAIL. Exit 2: usage or unreadable env
file. Without --require-video, video that is switched off is a WARN and the
last line says that only the image is ready. A pass is this machine now -- not
a qualification, and not a job: the first image and the first clip are still
the proof.
"""
from __future__ import annotations

import sys as _sys

_sys.dont_write_bytecode = True

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "worker"))

SCHEMA = "kaliv-media-release-preflight/v1"
OK, WARN, FAIL, INFO = "OK", "WARN", "FAIL", "INFO"
DEVICE = re.compile(r"^cuda:(0|[1-9][0-9]?)$")
# Left for the OS and the chat model when ComfyUI is given a share of the RAM.
HOST_MEMORY_HEADROOM_GIB = 16


class EnvFileError(ValueError):
    """A line the supervisor itself would refuse, so the appliance would not start with it."""


def _strip_inline_comment(value: str) -> str:
    # Same rule as stripInlineComment in backend/cmd/modelrig-supervisor/env.go.
    if len(value) >= 2 and value[0] in "\"'":
        end = value.find(value[0], 1)
        if end >= 0:
            return value[1:end]
    for index in range(1, len(value)):
        if value[index] == "#" and value[index - 1] in " \t":
            return value[:index].rstrip(" \t")
    return value


def parse_env_file(text: str) -> dict[str, str]:
    """The env file as the supervisor reads it (loadEnvFile): a BOM on the first line is dropped,
    blank lines and `#` lines skipped, one layer of quotes and a trailing ` # comment` removed, the
    last entry of a key wins. A line that is not KEY=VALUE is an error there, and here."""
    env: dict[str, str] = {}
    for number, raw in enumerate(text.split("\n"), start=1):
        line = raw.rstrip("\r")
        if number == 1:
            line = line.removeprefix("\ufeff")
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            raise EnvFileError(f"linje {number}: ikke KEY=VALUE")
        if not key.strip():
            raise EnvFileError(f"linje {number}: tom nøgle")
        env[key.strip()] = _strip_inline_comment(value.strip())
    return env


def _run(cmd: list[str], timeout: float = 60.0, cwd: str | None = None, stdin: str | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd, input=stdin,
                              encoding="utf-8", errors="replace")
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, type(exc).__name__


# Read-only means the tools this starts must not write either. `git status` refreshes the index
# unless told not to; a Python child writes __pycache__ unless started with -B (this process's
# own dont_write_bytecode is not inherited). ChatGPT on #2503.
GIT = ["git", "--no-optional-locks"]
PYTHON_FLAGS = ["-B"]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect is refused, never followed
        return None


# No proxy from the environment or the system settings, and no redirect: a request to 127.0.0.1
# goes to 127.0.0.1 or fails.
_LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _http_json(url: str, timeout: float = 5.0):
    if not url.startswith("http://127.0.0.1:"):
        return None, None
    try:
        with _LOCAL_OPENER.open(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None, None


def _total_ram_gib() -> float | None:
    try:
        if os.name == "nt":
            import ctypes

            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                    (name, ctypes.c_ulonglong) for name in
                    ("total", "avail", "total_page", "avail_page", "total_virtual", "avail_virtual", "avail_extended")]

            status = Status()
            status.length = ctypes.sizeof(Status)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            return status.total / 1024 ** 3
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3
    except (OSError, ValueError, AttributeError):
        return None


def _sha256(path: str) -> str | None:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


def _work_area(env: Mapping[str, str]) -> dict:
    from app.media_preflight import preflight
    return preflight(work_root=env.get("KALIV_MEDIA_WORK_ROOT", ""), job_db=env.get("KALIV_MEDIA_JOB_DB", ""),
                     volume_root=env.get("KALIV_MEDIA_VOLUME_ROOT", ""), volume_id=env.get("KALIV_MEDIA_VOLUME_ID", ""),
                     env=env)


def _profiles(env: Mapping[str, str]):
    from app.media_generation_profiles import enabled_profiles, load_profile_dir
    return enabled_profiles(load_profile_dir(env.get("KALIV_MEDIA_PROFILE_DIR", "")), env)


MIN_SECRET_CHARS = 32  # app.media_job_api.MIN_SECRET_CHARS; pinned by the contract


def _secret_ok(value: str) -> bool:
    # The worker's rule (media_job_api._usable_secret), restated: that module imports FastAPI at
    # the top, and this script must run in a bare Python (Codex #2503 4711014586).
    return isinstance(value, str) and len(value) >= MIN_SECRET_CHARS and not any(c in value for c in "\r\n")


_START_CHECK = """
import json, sys
env = json.load(sys.stdin)
import app.media_executor_main as m
if not hasattr(m, "check_start"):
    print(json.dumps({"kind": "old"})); raise SystemExit(0)
from app.media_executor import ExecutorConfigError
from app.media_generation_contract import ArtifactSinkUnavailable
try:
    m.check_start(sys.argv[1], env)
except ExecutorConfigError as exc:
    out = {"kind": "config", "text": str(exc)}
except ArtifactSinkUnavailable as exc:
    out = {"kind": "volume", "text": str(exc)}
else:
    out = {"kind": "ok"}
print(json.dumps(out))
"""


def _executor_start(env: Mapping[str, str], device: str, python: str, app_dir: str) -> "tuple[str, str] | None":
    """The executor's own start rules for one device, run the way the supervisor runs the executor:
    the media Python, in KALIV_MEDIA_EXECUTOR_APP_DIR, so the code that answers is the code that
    would start -- not this script's checkout (ChatGPT on #2503). `check_start` only looks.

    None when it would start; otherwise (kind, text): "config" (exit 78), "volume" (exit 75),
    "old" (that source has no check_start) or "broken" (the check itself did not run)."""
    code, out = _run([python, *PYTHON_FLAGS, "-c", _START_CHECK, device], 120.0, cwd=app_dir, stdin=json.dumps(dict(env)))
    try:
        answer = json.loads(out.strip().splitlines()[-1]) if code == 0 else None
    except (ValueError, IndexError):
        answer = None
    if not isinstance(answer, dict) or answer.get("kind") not in ("ok", "old", "config", "volume"):
        return "broken", f"exit {code}"
    return None if answer["kind"] == "ok" else (answer["kind"], str(answer.get("text", "")))


SECRET_KEY = re.compile(r"SECRET|TOKEN|PASSWORD|PASSPHRASE|CREDENTIAL|PRIVATE|API_?KEY", re.IGNORECASE)
HIDDEN = "<skjult>"


def scrub(text: str, env: Mapping[str, str]) -> str:
    """One line, with every value of a secret-named key of the env file replaced. Defence in depth
    only, and only for the two presentation fields: no text another component wrote reaches the
    report (see `controlled`), and a status or a check id is never passed through this."""
    for key, value in env.items():
        if SECRET_KEY.search(key) and len(value) >= 4:
            text = text.replace(value, HIDDEN)
    return "".join(ch if ch.isprintable() else " " for ch in text)


# A name of a configuration key, optionally followed by fixed lower-case folder names the executor
# appends itself (KALIV_COMFY_DIR/cuda1/input). Nothing else of a foreign text is ever shown.
KEY_NAME = re.compile(r"(?<![A-Za-z0-9_])(?:KALIV|CUDA|HF|TRANSFORMERS|OLLAMA)_[A-Z0-9_]{1,60}(?:/[a-z0-9_-]{1,24}){0,3}(?![A-Za-z0-9_])")
MAX_NAMES = 6

# (what the component's text contains, what this says instead). First match wins.
EXECUTOR_REASONS = (
    ("the media executor is off", "executor-kontakten er slået fra"),
    ("no GPU UUID is configured", "intet GPU-UUID er sat for enheden"),
    ("no enabled profile allows", "ingen slået-til profil kører på enheden"),
    ("are required (never a download)", "offline-flagene er ikke sat"),
    ("must not be on the media volume", "arbejdsområdet ligger på medievolumen"),
    ("must be an existing folder in the work area", "en mappe mangler i arbejdsområdet"),
    ("is not private", "en fil eller mappe i arbejdsområdet er ikke privat"),
    ("same ComfyUI port", "to profiler deler ComfyUI-port"),
    ("must be an absolute path", "en sti er ikke absolut"),
    ("must be an existing", "en fil eller mappe findes ikke"),
)
LOADER_REASONS = (
    ("names unknown profiles", "KALIV_MEDIA_PROFILES_ENABLED nævner et id, der ikke findes i profilmappen"),
    ("comma-separated list of distinct", "KALIV_MEDIA_PROFILES_ENABLED er ikke en kommaliste af forskellige id'er"),
    ("are not rig-qualified", "en slået-til profil er ikke rig-kvalificeret (kandidater kræver den nævnte kontakt)"),
)


def controlled(text: str, reasons: tuple, env: Mapping[str, str], default: str = "anden grund") -> str:
    """What a text written by another component (an exception of the executor, of the profile
    loader, a line of the work-area check) is allowed to contribute to the report: one of this
    file's own sentences, chosen by a fixed phrase, and the configuration KEY NAMES the text
    mentions. Never a character of the text itself -- it may quote a value (ChatGPT on #2503).
    A name is dropped if it is, or contains, a value from the env file."""
    reason = next((ours for needle, ours in reasons if needle in text), default)
    values = [value for value in env.values() if len(value) >= 4]
    names: list[str] = []
    for name in KEY_NAME.findall(text):
        if name not in names and not any(value in name for value in values):
            names.append(name)
    shown = ", ".join(names[:MAX_NAMES]) + (" ..." if len(names) > MAX_NAMES else "")
    return reason + (f"; nævner: {shown}" if names else "")


# What the executor needs in its environment besides the supervisor's four keys. Its start check
# stops at the FIRST thing that is wrong, so alone it costs one run at the rig per missing line;
# section 5b asks for all of these in one run. The names are the executor's (pinned by the
# contract); `check_start` remains the judge -- these lines can add a FAIL, never remove one.
FOLDER_KEYS = (
    ("KALIV_GPU_LEASE_DIR", "en mappe kun denne konto kan skrive i, fx C:\\ModelRig\\gpu-lease (docs/MEDIA_GENERATION_PROFILES.md)"),
    ("KALIV_MEDIA_PROFILE_DIR", "mappen med profilfilerne (*.json)"),
    ("KALIV_MEDIA_WORK_ROOT", "det private arbejdsområde på den interne disk (docs/MEDIA_WORK_AREA.md)"),
    ("KALIV_MEDIA_VOLUME_ROOT", "medievolumens rod, fx D:\\ (docs/MEDIA_VOLUME.md)"),
    ("KALIV_MEDIA_ROOT", "galleri-mappen på medievolumen"),
)
OFFLINE_FLAGS = ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")  # app.media_executor_main.OFFLINE_FLAGS
ADD_LINE = "tilføj linjen "  # a fix that starts so is a complete KEY=VALUE line (see `suggested_lines`)
GPU_UUID = re.compile(r"^GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")


def _uuid_map(env: Mapping[str, str]) -> "dict[int, str] | None":
    """KALIV_GPU_DEVICE_UUIDS by the executor's own parser (app.gpu_lease), or None if it refuses
    the value. The order rule is asked separately, so it is taken as met here."""
    from app.gpu_lease import GpuLeaseError, device_uuid_map
    try:
        return device_uuid_map({**env, "CUDA_DEVICE_ORDER": "PCI_BUS_ID"})
    except GpuLeaseError:
        return None


def suggested_lines(checks: list[dict]) -> list[str]:
    """The KEY=VALUE lines a FAIL gives in full: the ones with one right answer on this machine."""
    lines = []
    for item in checks:
        if item["status"] == FAIL and item["fix"].startswith(ADD_LINE):
            line = item["fix"][len(ADD_LINE):].split(" ", 1)[0]
            if re.fullmatch(r"[A-Z][A-Z0-9_]*=[\x21-\x7e]+", line) and line not in lines:
                lines.append(line)
    return lines


@dataclass
class Probes:
    """Everything that touches the machine, so the rules can be tested without one."""
    is_file: Callable[[str], bool] = os.path.isfile
    is_dir: Callable[[str], bool] = os.path.isdir
    # The supervisor passes the file's bytes on as they are; a stray non-UTF-8 byte in a comment
    # must not stop this reader either.
    read_text: Callable[[str], str] = lambda p: Path(p).read_text(encoding="utf-8", errors="replace")
    sha256: Callable[[str], "str | None"] = _sha256
    run: Callable[..., "tuple[int, str]"] = _run
    http_json: Callable[..., tuple] = _http_json
    total_ram_gib: Callable[[], "float | None"] = _total_ram_gib
    work_area: Callable[[Mapping[str, str]], dict] = _work_area
    profiles: Callable[[Mapping[str, str]], dict] = _profiles
    secret_ok: Callable[[str], bool] = _secret_ok
    executor_start: Callable[..., "tuple[str, str] | None"] = _executor_start
    process_env: Callable[[], Mapping[str, str]] = lambda: dict(os.environ)
    uuid_map: Callable[[Mapping[str, str]], "dict[int, str] | None"] = _uuid_map


@dataclass
class Report:
    checks: list[dict] = field(default_factory=list)

    def add(self, status: str, name: str, detail: str, fix: str = "") -> None:
        self.checks.append({"status": status, "check": name, "detail": detail, "fix": fix})


INHERITED = re.compile(r"^(KALIV_|CUDA_|HF_|TRANSFORMERS_|OLLAMA_)")


def evaluate(env: Mapping[str, str], probes: Probes, *, expect_version: str | None = None,
             expect_sha: str | None = None, planner_model: str | None = None,
             require_video: bool = False) -> list[dict]:
    """The rules. Pure given `probes`; never prints and never raises on a bad configuration.

    `status` and `check` are the machine-readable part and leave exactly as the rules set them:
    the exit code and `readiness` are computed from them, so nothing that edits text may touch
    them. `detail` and `fix` are presentation: scrubbed first, cut to length after -- a cut first
    could leave half a secret that no longer matches."""
    checks = _evaluate(env, probes, expect_version=expect_version, expect_sha=expect_sha,
                       planner_model=planner_model, require_video=require_video)
    return [{"status": item["status"], "check": item["check"] if fixed_id(item["check"]) else UNKNOWN_CHECK,
             "detail": scrub(item["detail"], env)[:MAX_TEXT], "fix": scrub(item["fix"], env)[:MAX_TEXT]} for item in checks]


MAX_TEXT = 600
# The check ids are a closed set written in this file. Nothing a profile file, the work-area
# check or the env file says is ever part of one: an id is machine-readable and is not masked, so
# it must not be able to carry a value (ChatGPT on #2503). A profile id or a file name belongs in
# `detail`. The one variable part is the device, and only as cuda:N from the supervisor's rule.
CHECK_IDS = frozenset({
    "KALIV_TOOLS_ENABLED", "KALIV_MEDIA_JOBS_API", "KALIV_IMAGE_TOOL_ENABLED", "video", "KALIV_MEDIA_INTERNAL_SECRET",
    "KALIV_MEDIA_EXECUTOR", "KALIV_MEDIA_EXECUTOR_DEVICES", "KALIV_MEDIA_EXECUTOR_PYTHON", "KALIV_MEDIA_EXECUTOR_APP_DIR",
    "executor-kilde", "executor-kilde: version", "executor-kilde: commit", "executor-kilde: ændringer", "tjekkets eget checkout",
    "medie-python: torch", "profiler", "profil: enhed", "profil: skabelon", "billedprofil",
    "KALIV_IMAGE_TOOL_PROFILE", "KALIV_VIDEO_TOOL_PROFILE", "video: text_to_video", "video: image_to_video",
    "KALIV_COMFY_PYTHON", "KALIV_COMFY_MAIN", "KALIV_COMFY_DIR", "KALIV_COMFY_TEMPLATE_DIR", "KALIV_COMFY_HOST_MEMORY_GIB",
    "arbejdsområde", "arbejdsområde, jobdatabase og medievolumen", "nvidia-smi", "ollama", "ollama: model", "appliance",
    "miljø uden for env-filen",
    # the executor's own environment, asked all at once (section 5b)
    "executor-miljø", "CUDA_DEVICE_ORDER", "KALIV_GPU_DEVICE_UUIDS", "KALIV_GPU_LEASE_DIR", "KALIV_MEDIA_PROFILE_DIR",
    "KALIV_MEDIA_WORK_ROOT", "KALIV_MEDIA_VOLUME_ROOT", "KALIV_MEDIA_ROOT", "KALIV_MEDIA_JOB_DB", "KALIV_MEDIA_VOLUME_ID",
    "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
})
# The parts of app.media_preflight's check names that are its own words (before any ":").
WORK_AREA_PARTS = ("work_area", "job_db_folder_in_work_area", "private", "publication_volume", "separate_disks",
                   "free_space", "same_account")
CHECK_IDS |= {f"arbejdsområde: {part}" for part in (*WORK_AREA_PARTS, "andet")}
DEVICE_CHECK = re.compile(r"^(?:executor cuda:(?:0|[1-9][0-9]?): (?:profiler|video|egen startkontrol)|gpu cuda:(?:0|[1-9][0-9]?))$")
UNKNOWN_CHECK = "ukendt kontrol"


def fixed_id(check: str) -> bool:
    return check in CHECK_IDS or bool(DEVICE_CHECK.match(check))


def readiness(checks: list[dict]) -> dict:
    """What a run with no FAIL actually says is ready. Video is ready per task, and only when the
    task has its own OK line: switched off, or no profile for the task, is not ready."""
    clean = not any(item["status"] == FAIL for item in checks)
    ok = {item["check"] for item in checks if item["status"] == OK}
    return {"image": clean, "text_to_video": clean and "video: text_to_video" in ok,
            "image_to_video": clean and "video: image_to_video" in ok}


def _evaluate(env: Mapping[str, str], probes: Probes, *, expect_version: str | None, expect_sha: str | None,
              planner_model: str | None, require_video: bool) -> list[dict]:
    report = Report()
    video_missing = FAIL if require_video else WARN
    get = lambda key: env.get(key, "").strip()  # noqa: E731

    # --- 1. the switches a released appliance reads from its env file -------------------------
    for key, why in (("KALIV_TOOLS_ENABLED", "uden den kalder chatten ingen værktøjer"),
                     ("KALIV_MEDIA_JOBS_API", "job-ruterne findes ikke (404)"),
                     ("KALIV_IMAGE_TOOL_ENABLED", "image_generate er ikke registreret")):
        if get(key) == "1":
            report.add(OK, key, "1")
        else:
            report.add(FAIL, key, f"er {get(key)!r}: {why}", f"sæt {key}=1 i env-filen")
    video = get("KALIV_MEDIA_VIDEO") == "1" and get("KALIV_VIDEO_TOOL_ENABLED") == "1"
    if video:
        report.add(OK, "video", "KALIV_MEDIA_VIDEO=1 og KALIV_VIDEO_TOOL_ENABLED=1")
    else:
        report.add(video_missing, "video", "video er slået fra (begge kontakter skal være 1)",
                   "sæt KALIV_MEDIA_VIDEO=1 og KALIV_VIDEO_TOOL_ENABLED=1, hvis releasen skal lave klip")
    if probes.secret_ok(env.get("KALIV_MEDIA_INTERNAL_SECRET", "")):
        report.add(OK, "KALIV_MEDIA_INTERNAL_SECRET", "sat og brugbar (værdien vises ikke)")
    else:
        report.add(FAIL, "KALIV_MEDIA_INTERNAL_SECRET", "mangler eller er for svag: ruterne svarer 503 media_jobs_secret_invalid",
                   "sæt en lang tilfældig værdi; backend og worker læser samme fil")

    # --- 2. the supervisor's executor configuration (backend/cmd/modelrig-supervisor/executor.go)
    devices: list[str] = []
    app_dir = get("KALIV_MEDIA_EXECUTOR_APP_DIR")
    python = get("KALIV_MEDIA_EXECUTOR_PYTHON")
    if get("KALIV_MEDIA_EXECUTOR") != "1":
        report.add(FAIL, "KALIV_MEDIA_EXECUTOR", f"er {get('KALIV_MEDIA_EXECUTOR')!r}: supervisoren starter ingen executor, og job bliver stående i kø",
                   "sæt KALIV_MEDIA_EXECUTOR=1 (og de tre nøgler nedenfor)")
    else:
        report.add(OK, "KALIV_MEDIA_EXECUTOR", "1")
    raw_devices = [d.strip() for d in get("KALIV_MEDIA_EXECUTOR_DEVICES").split(",") if d.strip()]
    bad = [d for d in raw_devices if not DEVICE.match(d)]
    if not raw_devices or bad or len(set(raw_devices)) != len(raw_devices) or len(raw_devices) > 8:
        report.add(FAIL, "KALIV_MEDIA_EXECUTOR_DEVICES", f"{get('KALIV_MEDIA_EXECUTOR_DEVICES')!r} afvises af supervisoren (cuda:N, ingen gentagelser, højst 8)",
                   "fx KALIV_MEDIA_EXECUTOR_DEVICES=cuda:1")
    else:
        devices = raw_devices
        report.add(OK, "KALIV_MEDIA_EXECUTOR_DEVICES", ",".join(devices))
    if not os.path.isabs(python) or not probes.is_file(python):
        report.add(FAIL, "KALIV_MEDIA_EXECUTOR_PYTHON", f"{python!r} er ikke en absolut sti til en fil",
                   "peg på medie-miljøets python.exe")
    else:
        report.add(OK, "KALIV_MEDIA_EXECUTOR_PYTHON", python)
    entry = os.path.join(app_dir, "app", "media_executor_main.py")
    if not os.path.isabs(app_dir) or not probes.is_file(entry):
        report.add(FAIL, "KALIV_MEDIA_EXECUTOR_APP_DIR", f"{app_dir!r} indeholder ikke app\\media_executor_main.py",
                   "peg på worker-mappen i et checkout af releasens commit")
        app_dir = ""
    else:
        report.add(OK, "KALIV_MEDIA_EXECUTOR_APP_DIR", app_dir)

    # --- 3. the executor's source is the release's own commit -----------------------------------
    if app_dir:
        repo = os.path.dirname(app_dir.rstrip("\\/"))
        version_file = os.path.join(repo, "VERSION")
        version = probes.read_text(version_file).strip() if probes.is_file(version_file) else None
        code, head = probes.run([*GIT, "-C", repo, "rev-parse", "HEAD"], 20.0)
        head = head.strip() if code == 0 else None
        code, dirty = probes.run([*GIT, "-C", repo, "status", "--porcelain", "--untracked-files=no"], 30.0)
        dirty_count = len([line for line in dirty.splitlines() if line.strip()]) if code == 0 else None
        # Untracked files beside the executor's code count too: Python runs in that folder, so a
        # stray worker/json.py would be imported instead of the standard library's.
        code, extra = probes.run([*GIT, "-C", repo, "status", "--porcelain", "--untracked-files=all", "--", "worker"], 30.0)
        extra_count = len([line for line in extra.splitlines() if line.startswith("??")]) if code == 0 else None
        seen = f"VERSION={version or '?'} HEAD={(head or '?')[:12]}"
        if expect_version and version != expect_version:
            report.add(FAIL, "executor-kilde: version", f"{seen}, forventet {expect_version}",
                       f"check releasens commit ud i {repo}")
        elif expect_sha and head != expect_sha:
            report.add(FAIL, "executor-kilde: commit", f"{seen}, forventet {expect_sha[:12]}",
                       f"git -C {repo} fetch origin {expect_sha} ; git -C {repo} checkout --detach FETCH_HEAD")
        elif expect_version or expect_sha:
            report.add(OK, "executor-kilde", seen)
        else:
            report.add(INFO, "executor-kilde", f"{seen} (ikke bundet: giv --expect-version/--expect-sha, når tagget findes)")
        # Bound to a release, a checkout that is not exactly that commit is a FAIL: the HEAD says
        # one thing and the files the executor runs say another. Unbound, it is a WARN.
        drift = FAIL if expect_sha else WARN
        if dirty_count is None or extra_count is None:
            report.add(drift, "executor-kilde: ændringer", f"git status kunne ikke køres i {repo}", "tjek at git er på PATH og mappen er et checkout")
        elif dirty_count or extra_count:
            report.add(drift, "executor-kilde: ændringer", f"{dirty_count} ændrede og {extra_count} ikke-sporede filer (worker/) i {repo}",
                       "executoren kører den kode, der ligger der, ikke releasens: git stash -u, eller brug et rent checkout")
        # The profile rules, the task support and the work-area check below are run with the code
        # beside THIS script, and they decide readiness too. Bound to a release, that code must be
        # the release's as well: same commit as the executor's source, and unchanged.
        own = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if os.path.normcase(os.path.realpath(own)) != os.path.normcase(os.path.realpath(repo)):
            code, own_head = probes.run([*GIT, "-C", own, "rev-parse", "HEAD"], 20.0)
            own_head = own_head.strip() if code == 0 else None
            code, changed = probes.run([*GIT, "-C", own, "status", "--porcelain", "--untracked-files=all", "--", "worker", "scripts"], 30.0)
            changed_count = len([line for line in changed.splitlines() if line.strip()]) if code == 0 else None
            fix = f"kør scriptet fra executorens checkout: cd {repo}"
            if own_head is None or own_head != head:
                report.add(drift, "tjekkets eget checkout", f"dette script ligger i {own}, på en anden commit end executorens kilde: "
                           "profil- og arbejdsområde-reglerne herunder er ikke nødvendigvis releasens", fix)
            elif changed_count is None or changed_count:
                report.add(drift, "tjekkets eget checkout", f"{changed_count if changed_count is not None else '?'} ændrede eller ikke-sporede filer "
                           f"(worker/, scripts/) i {own}", fix)

    # --- 4. the media Python can see the GPUs it is told to use ---------------------------------
    highest = max((int(d.split(":")[1]) for d in devices), default=-1)
    if probes.is_file(python) and os.path.isabs(python):
        code, out = probes.run([python, *PYTHON_FLAGS, "-c", "import json,torch;print(json.dumps({'torch':torch.__version__,"
                                              "'cuda':torch.cuda.is_available(),'count':torch.cuda.device_count()}))"], 120.0)
        try:
            torch_info = json.loads(out.strip().splitlines()[-1]) if code == 0 else None
        except (ValueError, IndexError):
            torch_info = None
        if not torch_info:
            report.add(FAIL, "medie-python: torch", "kunne ikke importere torch", "geninstaller medie-miljøet (deploy/media-image-requirements.txt)")
        elif not torch_info.get("cuda") or torch_info.get("count", 0) <= highest:
            report.add(FAIL, "medie-python: torch", f"torch {torch_info.get('torch')}, cuda={torch_info.get('cuda')}, {torch_info.get('count')} kort; executoren skal bruge cuda:{highest}",
                       "CUDA-udgaven af torch, og et kort for hver enhed i KALIV_MEDIA_EXECUTOR_DEVICES")
        else:
            report.add(OK, "medie-python: torch", f"torch {torch_info['torch']}, {torch_info['count']} kort")

    # --- 5. profiles: enabled, served by an executor, and reachable from the chat tools ---------
    enabled: dict = {}
    try:
        enabled = dict(probes.profiles(env))
    except Exception as exc:  # GenerationError, OSError, ValueError -- reported, never raised
        report.add(FAIL, "profiler", f"afvist af profil-loaderen ({type(exc).__name__}): "
                   + controlled(str(exc), LOADER_REASONS, env, "en profilfil eller profilmappen blev afvist"),
                   "ret KALIV_MEDIA_PROFILE_DIR / KALIV_MEDIA_PROFILES_ENABLED / profilfilen")
    else:
        if not enabled:
            # The loader returns {} for an empty list; every executor then refuses to start
            # ("no enabled profile allows cuda:N") and the chat has nothing to submit to.
            report.add(FAIL, "profiler", "ingen er slået til: KALIV_MEDIA_PROFILES_ENABLED er tom eller mangler",
                       "sæt KALIV_MEDIA_PROFILES_ENABLED til profil-id'erne, adskilt af komma")
    if enabled:
        report.add(OK, "profiler", ", ".join(f"{pid} ({p.modality}, {p.qualification})" for pid, p in sorted(enabled.items())))
        for pid, profile in sorted(enabled.items()):
            if devices and not set(profile.resources.devices) & set(devices):
                report.add(FAIL, "profil: enhed", f"{pid} kører på {','.join(profile.resources.devices)}, men executorerne er {','.join(devices)}",
                           "ingen executor tager dens job: ret profilens devices eller KALIV_MEDIA_EXECUTOR_DEVICES")
        for device in devices:
            mine = sorted(pid for pid, p in enabled.items() if device in p.resources.devices)
            video_here = [pid for pid in mine if enabled[pid].modality == "video"]
            if not mine:
                report.add(FAIL, f"executor {device}: profiler", "ingen slået-til profil kører på den: executoren starter ikke (exit 78)",
                           f"tag {device} ud af KALIV_MEDIA_EXECUTOR_DEVICES eller slå en profil til, der kører på den")
            elif video_here and get("KALIV_MEDIA_VIDEO") != "1":
                # Not "video is off": the whole executor exits 78, so its image jobs stop too.
                report.add(FAIL, f"executor {device}: video", f"videoprofilen {', '.join(video_here)} er slået til, men KALIV_MEDIA_VIDEO er ikke 1: "
                           "executoren starter ikke (exit 78), heller ikke for billeder",
                           "sæt KALIV_MEDIA_VIDEO=1, eller tag videoprofilen ud af KALIV_MEDIA_PROFILES_ENABLED")
        if not any(p.modality == "image" for p in enabled.values()):
            report.add(FAIL, "billedprofil", "ingen slået til: image_generate har intet at vælge", "tilføj en billedprofil til KALIV_MEDIA_PROFILES_ENABLED")
        for key, modality in (("KALIV_IMAGE_TOOL_PROFILE", "image"), ("KALIV_VIDEO_TOOL_PROFILE", "video")):
            for pid in [part.strip() for part in get(key).split(",") if part.strip()]:
                if pid not in enabled or enabled[pid].modality != modality:
                    report.add(FAIL, key, f"{pid!r} er ikke en slået-til {modality}-profil: værktøjet svarer profile_not_enabled",
                               f"brug et id fra KALIV_MEDIA_PROFILES_ENABLED med modality {modality}")
        if video:
            configured = [part.strip() for part in get("KALIV_VIDEO_TOOL_PROFILE").split(",") if part.strip()]
            for task in ("text_to_video", "image_to_video"):
                serving = [pid for pid, p in enabled.items() if p.modality == "video" and task in p.tasks]
                chosen = [pid for pid in configured if pid in serving]
                if not serving:
                    report.add(video_missing, f"video: {task}", "ingen slået-til profil laver den opgave", "slå en profil til, der har opgaven, hvis den skal virke")
                elif not chosen and len(serving) > 1:
                    report.add(FAIL, f"video: {task}", f"{len(serving)} profiler kan ({', '.join(sorted(serving))}), og ingen er valgt",
                               "sæt KALIV_VIDEO_TOOL_PROFILE til ét id pr. opgave, adskilt af komma")
                else:
                    report.add(OK, f"video: {task}", (chosen or serving)[0])

    # --- 5b. the executor's environment, all of it in one run -----------------------------------
    code, out = probes.run(["nvidia-smi", "--query-gpu=index,memory.total,memory.used,uuid", "--format=csv,noheader,nounits"], 30.0)
    gpus: dict[int, tuple[int, int]] = {}
    gpu_uuids: dict[int, str] = {}
    if code == 0:
        for line in out.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) in (3, 4) and all(part.isdigit() for part in parts[:3]):
                gpus[int(parts[0])] = (int(parts[1]), int(parts[2]))
                if len(parts) == 4 and GPU_UUID.match(parts[3]):
                    gpu_uuids[int(parts[0])] = "GPU-" + parts[3][4:].lower()
    # Before KALIV_MEDIA_EXECUTOR_DEVICES is set, the cards the enabled profiles run on stand in.
    cards = devices or sorted({d for p in enabled.values() for d in p.resources.devices if DEVICE.match(d)})
    before = len(report.checks)
    if get("CUDA_DEVICE_ORDER") != "PCI_BUS_ID":
        report.add(FAIL, "CUDA_DEVICE_ORDER", f"er {get('CUDA_DEVICE_ORDER')!r}: executoren kræver PCI_BUS_ID, så cuda:N er samme kort overalt",
                   ADD_LINE + "CUDA_DEVICE_ORDER=PCI_BUS_ID")
    indices = [int(card.split(":")[1]) for card in cards]
    wanted = ",".join(f"cuda:{i}={gpu_uuids[i]}" for i in indices) if indices and all(i in gpu_uuids for i in indices) else ""
    uuid_fix = (ADD_LINE + "KALIV_GPU_DEVICE_UUIDS=" + wanted) if wanted else "én post pr. kort, cuda:N=GPU-<uuid>, fra: nvidia-smi --query-gpu=index,uuid --format=csv"
    try:
        mapping = probes.uuid_map(env)
    except Exception:
        mapping = None
    if mapping is None:
        report.add(FAIL, "KALIV_GPU_DEVICE_UUIDS", "mangler eller er ikke en liste af cuda:N=GPU-<uuid>", uuid_fix)
    else:
        unmapped = [f"cuda:{i}" for i in indices if i not in mapping]
        other = [f"cuda:{i}" for i in indices if i in mapping and i in gpu_uuids and mapping[i].lower() != gpu_uuids[i].lower()]
        if unmapped:
            report.add(FAIL, "KALIV_GPU_DEVICE_UUIDS", f"har ingen post for {', '.join(unmapped)}", uuid_fix)
        elif other:
            report.add(WARN, "KALIV_GPU_DEVICE_UUIDS", f"posten for {', '.join(other)} er et andet UUID end det, nvidia-smi viser for det kort", uuid_fix)
    for key, what in FOLDER_KEYS:
        path = get(key)
        if not path:
            report.add(FAIL, key, "mangler", f"sæt {key} til {what}")
        elif not os.path.isabs(path):
            report.add(FAIL, key, f"{path!r} er ikke en absolut sti", f"sæt {key} til {what}")
        elif not probes.is_dir(path):
            report.add(FAIL, key, f"mappen {path!r} findes ikke", f"opret den, eller ret {key}: {what}")
    job_db = get("KALIV_MEDIA_JOB_DB")
    if not job_db or not os.path.isabs(job_db):
        report.add(FAIL, "KALIV_MEDIA_JOB_DB", f"{job_db!r} er ikke en absolut sti" if job_db else "mangler",
                   "sæt KALIV_MEDIA_JOB_DB til en fil i en mappe i arbejdsområdet, fx <arbejdsområde>\\state\\jobs.sqlite3")
    elif not probes.is_dir(os.path.dirname(job_db)):
        report.add(FAIL, "KALIV_MEDIA_JOB_DB", f"mappen {os.path.dirname(job_db)!r} findes ikke", "opret mappen; den skal ligge i arbejdsområdet")
    if not get("KALIV_MEDIA_VOLUME_ID"):
        report.add(FAIL, "KALIV_MEDIA_VOLUME_ID", "mangler", "sæt KALIV_MEDIA_VOLUME_ID til id'et i volumens markørfil .kaliv-media-volume (docs/MEDIA_VOLUME.md)")
    if any(p.backend == "diffusers" and (not cards or set(p.resources.devices) & set(cards)) for p in enabled.values()):
        for flag in OFFLINE_FLAGS:
            if get(flag) != "1":
                report.add(FAIL, flag, f"er {get(flag)!r}: en diffusers-profil er slået til, og executoren henter aldrig noget ved kørsel",
                           ADD_LINE + f"{flag}=1")
    if len(report.checks) == before:
        report.add(OK, "executor-miljø", "kort-rækkefølge, GPU-UUID, lease-mappe, stier, volumen-id og offline-flag er sat")

    # --- 6. ComfyUI, for the profiles that render through it -------------------------------------
    comfy = {pid: p for pid, p in enabled.items() if p.backend == "comfyui"}
    if comfy:
        for key in ("KALIV_COMFY_PYTHON", "KALIV_COMFY_MAIN"):
            path = get(key)
            report.add(*((OK, key, path) if os.path.isabs(path) and probes.is_file(path)
                         else (FAIL, key, f"{path!r} er ikke en fil", "peg på ComfyUI-miljøets python.exe / ComfyUI\\main.py")))
        for key in ("KALIV_COMFY_DIR", "KALIV_COMFY_TEMPLATE_DIR"):
            path = get(key)
            report.add(*((OK, key, path) if os.path.isabs(path) and probes.is_dir(path)
                         else (FAIL, key, f"{path!r} er ikke en mappe", "opret mappen eller ret stien")))
        template_dir = get("KALIV_COMFY_TEMPLATE_DIR")
        for pid, profile in sorted(comfy.items()):
            options = profile.backend_options
            path = os.path.join(template_dir, options.template_name)
            digest = probes.sha256(path) if probes.is_file(path) else None
            if digest is None:
                report.add(FAIL, "profil: skabelon", f"{pid}: {options.template_name} mangler i {template_dir}", "læg skabelonen dér")
            elif digest != options.template_sha256:
                report.add(FAIL, "profil: skabelon", f"{pid}: {options.template_name} har sha256 {digest[:12]}, profilen pinner {options.template_sha256[:12]}",
                           "skabelon og profil skal stamme fra samme opsætning")
            else:
                report.add(OK, "profil: skabelon", f"{pid}: {options.template_name}")
        ram = probes.total_ram_gib()
        limit = get("KALIV_COMFY_HOST_MEMORY_GIB")
        if limit and ram:
            try:
                value = float(limit)
                if value > ram - HOST_MEMORY_HEADROOM_GIB:
                    report.add(WARN, "KALIV_COMFY_HOST_MEMORY_GIB", f"{value:g} af {ram:.0f} GiB: under {HOST_MEMORY_HEADROOM_GIB} GiB tilbage til Windows og chatmodellen",
                               f"højst {max(1, int(ram - HOST_MEMORY_HEADROOM_GIB))}")
                else:
                    report.add(OK, "KALIV_COMFY_HOST_MEMORY_GIB", f"{value:g} af {ram:.0f} GiB")
            except ValueError:
                report.add(FAIL, "KALIV_COMFY_HOST_MEMORY_GIB", f"{limit!r} er ikke et tal", "fx 40")

    # --- 7. work area, job database and media volume: the executor's own preflight --------------
    try:
        area = probes.work_area(env)
        failed = [c for c in area.get("checks", []) if not c.get("ok")]
        if failed:
            for item in failed:
                # Of the check's name only its own word is used, and only if it is one this file
                # knows; what follows a ":" there is a file name or a pid. Its detail is free text.
                part, _, which = str(item.get("check")).partition(":")
                # A folder that is not there already has its own FAIL line (5b), with the key to
                # set; the two or three lines this check adds about the same folder say nothing more.
                absent = {name for name, key in (("work_area", "KALIV_MEDIA_WORK_ROOT"), ("publication_volume", "KALIV_MEDIA_VOLUME_ROOT"))
                          if not (os.path.isabs(get(key)) and probes.is_dir(get(key)))}
                if part in absent or (part == "free_space" and which in absent):
                    continue
                # ...except the two labels app.media_preflight itself gives a free-space check,
                # and the two numbers of its verdict: fixed words and numbers, never text.
                place = {"work_area": "arbejdsområdet", "publication_volume": "medievolumen"}
                detail = item.get("detail")
                if part == "free_space" and which in place:
                    said = f"for lidt fri plads på {place[which]}"
                    if isinstance(detail, dict) and all(isinstance(detail.get(k), (int, float)) and not isinstance(detail.get(k), bool)
                                                         for k in ("free_gib", "minimum_gib")):
                        said += f": {detail['free_gib']:g} GiB fri, kræver {detail['minimum_gib']:g}"
                    else:
                        said = f"fri plads på {place[which]} kunne ikke måles"
                elif part in place:
                    said = controlled(str(detail), (), env, f"{place[part]} afvises, selv om mappen findes: rettigheder, filsystem"
                                      + (" eller markør/id" if part == "publication_volume" else ""))
                else:
                    said = controlled(str(detail), (), env, "ikke opfyldt")
                report.add(FAIL, "arbejdsområde: " + (part if part in WORK_AREA_PARTS else "andet"),
                           said, "se docs/MEDIA_WORK_AREA.md og docs/MEDIA_VOLUME.md")
        else:
            report.add(OK, "arbejdsområde, jobdatabase og medievolumen", f"{len(area.get('checks', []))} kontroller bestået")
    except Exception as exc:
        report.add(FAIL, "arbejdsområde", f"kunne ikke kontrolleres: {type(exc).__name__}", "sæt KALIV_MEDIA_WORK_ROOT, _JOB_DB, _VOLUME_ROOT og _VOLUME_ID")

    # --- 7b. the executor's own start rules, per device ------------------------------------------
    # Everything above explains; this decides. `check_start` is the function the executor itself
    # runs before it touches the job database, so a rule this script does not know about (the
    # per-device ComfyUI folders, the lease folder, the GPU UUID, the offline flags, ...) is still
    # caught. Its words are not repeated (they may quote a value): the reason is one of this file's
    # sentences plus the key names it mentions; the full text is in the executor's own log on the
    # rig (logs\executor-cudaN.log) once the supervisor has tried to start it.
    for device in devices:
        name = f"executor {device}: egen startkontrol"
        if not app_dir or not (os.path.isabs(python) and probes.is_file(python)):
            # Both causes are FAIL lines of their own above, so this is not a second verdict.
            report.add(INFO, name, "ikke kørt: medie-python eller executorens kilde mangler (FAIL ovenfor)")
            continue
        try:
            refusal = probes.executor_start(env, device, python, app_dir)
        except Exception as exc:  # the check itself broke: say so, never claim OK
            refusal = ("broken", type(exc).__name__)
        if refusal is None:
            report.add(OK, name, "ville starte (alt den ser på før jobdatabasen)")
        elif refusal[0] == "volume":
            report.add(FAIL, name, "medievolumen er ikke klar (exit 75): " + controlled(refusal[1], (), env, "den er ikke tilsluttet eller ikke den rigtige"),
                       "tilslut medievolumen og kør igen")
        elif refusal[0] == "config":
            report.add(FAIL, name, "afviser start (exit 78): " + controlled(refusal[1], EXECUTOR_REASONS, env),
                       "ret de nævnte nøgler i env-filen eller på disken; dens egen tekst står i logs\\executor-" + device.replace(":", "") + ".log efter et startforsøg")
        elif refusal[0] == "old":
            report.add(FAIL, name, "executorens kilde har ingen check_start: den er ældre end dette tjek",
                       "check releasens commit ud i KALIV_MEDIA_EXECUTOR_APP_DIR's checkout")
        else:
            report.add(FAIL, name, "kunne ikke køres (" + ("".join(re.findall(r"[A-Za-z0-9 ]", refusal[1])) or "?")[:40] + ")", "kør medie-python i executorens mappe: python -c \"import app.media_executor_main\"")

    # --- 8. the GPUs, as the driver reports them now ---------------------------------------------
    if not gpus:
        report.add(FAIL, "nvidia-smi", "gav ingen kort", "driveren skal være installeret og nvidia-smi på PATH")
    for device in devices:
        index = int(device.split(":")[1])
        if gpus and index not in gpus:
            report.add(FAIL, f"gpu {device}", f"findes ikke (nvidia-smi ser {sorted(gpus)})", "ret KALIV_MEDIA_EXECUTOR_DEVICES")
        elif gpus:
            total, used = gpus[index]
            if used > 2048:
                report.add(WARN, f"gpu {device}", f"{used} af {total} MiB er allerede i brug",
                           "noget andet ligger på kortet (ofte chatmodellen spredt over begge kort): bind Ollama til det andet kort")
            else:
                report.add(OK, f"gpu {device}", f"{used} af {total} MiB i brug")

    # --- 9. Ollama and the appliance, as they answer now -----------------------------------------
    status, tags = probes.http_json("http://127.0.0.1:11434/api/tags", 5.0)
    if status != 200 or not isinstance(tags, dict):
        report.add(FAIL, "ollama", "svarer ikke på 127.0.0.1:11434", "start Ollama; chatten kan ikke kalde værktøjer uden")
    else:
        names = sorted(str(m.get("name")) for m in tags.get("models", []) if isinstance(m, dict))
        if planner_model and planner_model not in names:
            report.add(FAIL, "ollama: model", f"{planner_model} er ikke hentet (har: {', '.join(names) or 'ingen'})", f"ollama pull {planner_model}")
        else:
            report.add(OK, "ollama", f"{len(names)} modeller" + (f", {planner_model} er der" if planner_model else ""))
    status, health = probes.http_json("http://127.0.0.1:8080/healthz", 5.0)
    if status == 200 and isinstance(health, dict):
        version = str(health.get("version"))
        if expect_version and version != expect_version:
            report.add(WARN, "appliance", f"kører {version}, forventet {expect_version}", "opdater appliancen til releasen, før medie-testen")
        else:
            report.add(INFO if not expect_version else OK, "appliance", f"kører {version}")
    else:
        report.add(INFO, "appliance", "svarer ikke på 127.0.0.1:8080 (ikke startet)")
    # The supervisor's children also inherit ITS environment, which this cannot see. What this
    # window has and the file lacks is the nearest hint -- names only.
    stray = sorted(key for key in probes.process_env() if INHERITED.match(key) and key not in env)
    if stray:
        report.add(INFO, "miljø uden for env-filen", f"sat i dette vindue, ikke i filen: {', '.join(stray[:20])}" + (" ..." if len(stray) > 20 else ""),
                   "")
    return report.checks


def render(checks: list[dict], env_file: str = "") -> str:
    lines = []
    for item in checks:
        lines.append(f"  {item['status']:<5} {item['check']}: {item['detail']}")
        if item["fix"] and item["status"] in (FAIL, WARN):
            lines.append(f"        -> {item['fix']}")
    counts = {status: sum(1 for item in checks if item["status"] == status) for status in (OK, WARN, FAIL, INFO)}
    lines.append("")
    lines.append(f"  {counts[OK]} OK, {counts[WARN]} WARN, {counts[FAIL]} FAIL, {counts[INFO]} INFO")
    ready = readiness(checks)
    if ready["image"]:
        clips = [task for task in ("text_to_video", "image_to_video") if ready[task]]
        missing = [task for task in ("text_to_video", "image_to_video") if not ready[task]]
        lines.append("  ingen FAIL: klar til første billede"
                     + (f" og første klip ({', '.join(clips)})" if clips else "")
                     + (f". IKKE klar: {', '.join(missing)}" if missing else ""))
    else:
        lines.append("  ikke klar: ret FAIL-linjerne og kør igen")
    direct = suggested_lines(checks)
    if direct:
        # media_env_set.py changes only the named keys and takes a backup first (see its docstring).
        lines.append("")
        lines.append(f"  {len(direct)} af linjerne har kun ét rigtigt svar på denne maskine og kan sættes sådan:")
        lines.append("    python scripts\\media_env_set.py --file " + (f'"{env_file}"' if env_file else "<env-fil>")
                     + "".join(f' "{line}"' for line in direct))
    return "\n".join(lines)


def main(argv: list[str] | None = None, probes: Probes | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, help="appliancens env-fil, fx C:\\Rig\\ModelRig\\modelrig.env")
    parser.add_argument("--expect-version", help="releasens version, fx 2.0.21")
    parser.add_argument("--expect-sha", help="den fulde commit, tagget peger på")
    parser.add_argument("--planner-model", help="chatmodellen, fx qwen3:14b")
    parser.add_argument("--require-video", action="store_true",
                        help="releasen skal lave klip: video slået fra eller en videoopgave uden profil er FAIL")
    parser.add_argument("--json", action="store_true", help="skriv JSON i stedet for tekst")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # A Windows console that is not UTF-8 must show a replacement character, not end the run.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")
    if args.expect_sha and not re.fullmatch(r"[0-9a-f]{40}", args.expect_sha):
        parser.error("--expect-sha skal være en fuld SHA (40 hex)")
    probes = probes or Probes()
    try:
        env = parse_env_file(probes.read_text(args.env_file))
    except (OSError, UnicodeDecodeError) as exc:
        print(f"kan ikke læse {args.env_file}: {type(exc).__name__}", file=sys.stderr)
        return 2
    except EnvFileError as exc:
        print(f"{args.env_file}: {exc} -- supervisoren afviser også filen", file=sys.stderr)
        return 2
    checks = evaluate(env, probes, expect_version=args.expect_version, expect_sha=args.expect_sha,
                      planner_model=args.planner_model, require_video=args.require_video)
    if args.json:
        print(json.dumps({"schema": SCHEMA, "env_file": args.env_file, "ready": readiness(checks),
                          "suggested_lines": suggested_lines(checks), "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print(render(checks, args.env_file))
    return 1 if any(item["status"] == FAIL for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())

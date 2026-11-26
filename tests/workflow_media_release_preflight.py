#!/usr/bin/env python3
"""Contract for scripts/media_release_preflight.py.

A rig that is set up right passes with no FAIL; each way a released appliance has
been (or could be) misconfigured for media gives the one finding that names it.
The profile rules are the worker's own (real profile files on disk, read by the
worker's loader); the machine -- git, torch, nvidia-smi, Ollama, the appliance,
the work-area preflight -- is replaced by stand-ins.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

import media_release_preflight as preflight  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

SHA = "c" * 40
SECRET = "S3cret-" + "z" * 40
passed = 0


def check(name: str, condition: bool, detail: object = "") -> None:
    global passed
    if not condition:
        raise AssertionError(f"FAIL: {name} {detail}")
    passed += 1
    print(f"PASS: {name}")


class Rig:
    """A temp directory laid out like the rig, an env for it, and stand-ins for the machine."""

    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="kaliv-preflight-"))
        repo = self.tmp / "ModelRig"
        (repo / "worker" / "app").mkdir(parents=True)
        (repo / "worker" / "app" / "media_executor_main.py").write_text("# stand-in\n")
        (repo / "VERSION").write_text("2.0.21\n")
        self.repo = repo
        for name in ("media-venv", "comfy-venv", "ComfyUI"):
            (self.tmp / name).mkdir()
        self.python = self.tmp / "media-venv" / "python.exe"
        self.python.write_text("")
        (self.tmp / "comfy-venv" / "python.exe").write_text("")
        (self.tmp / "ComfyUI" / "main.py").write_text("")
        self.profiles = self.tmp / "profiles"
        self.templates = self.tmp / "templates"
        self.comfy = self.tmp / "comfy"
        for directory in (self.profiles, self.templates, self.comfy):
            directory.mkdir()
        self.write_profile(image_profile(profile_id="realvis"))
        self.write_video("ltx-t2v", ["text_to_video"])
        self.write_video("ltx-i2v", ["image_to_video"])
        self.env = {
            "KALIV_TOOLS_ENABLED": "1", "KALIV_MEDIA_JOBS_API": "1", "KALIV_IMAGE_TOOL_ENABLED": "1",
            "KALIV_MEDIA_VIDEO": "1", "KALIV_VIDEO_TOOL_ENABLED": "1", "KALIV_MEDIA_INTERNAL_SECRET": SECRET,
            "KALIV_MEDIA_EXECUTOR": "1", "KALIV_MEDIA_EXECUTOR_DEVICES": "cuda:1",
            "KALIV_MEDIA_EXECUTOR_PYTHON": str(self.python), "KALIV_MEDIA_EXECUTOR_APP_DIR": str(repo / "worker"),
            "KALIV_MEDIA_PROFILE_DIR": str(self.profiles), "KALIV_MEDIA_PROFILES_ENABLED": "realvis,ltx-t2v,ltx-i2v",
            "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES": "1", "KALIV_IMAGE_TOOL_PROFILE": "realvis",
            "KALIV_VIDEO_TOOL_PROFILE": "ltx-t2v,ltx-i2v",
            "KALIV_COMFY_PYTHON": str(self.tmp / "comfy-venv" / "python.exe"),
            "KALIV_COMFY_MAIN": str(self.tmp / "ComfyUI" / "main.py"), "KALIV_COMFY_DIR": str(self.comfy),
            "KALIV_COMFY_TEMPLATE_DIR": str(self.templates), "KALIV_COMFY_HOST_MEMORY_GIB": "40",
            "KALIV_MEDIA_WORK_ROOT": str(self.tmp / "work"), "KALIV_MEDIA_JOB_DB": str(self.tmp / "work" / "jobs.sqlite3"),
            "KALIV_MEDIA_VOLUME_ROOT": str(self.tmp / "volume"), "KALIV_MEDIA_VOLUME_ID": "kaliv-media-a86762b9f60b",
        }
        self.head, self.dirty = SHA, ""
        self.torch = {"torch": "2.8.0+cu126", "cuda": True, "count": 2}
        self.smi = "0, 12288, 1400\n1, 12288, 120\n"
        self.ollama = {"models": [{"name": "qwen3:14b"}, {"name": "gemma3:12b"}]}
        self.appliance = {"version": "2.0.21"}
        self.area = {"ok": True, "checks": [{"check": "work_area", "ok": True, "detail": "ok"}]}
        self.ram = 64.0
        self.start: object = None  # what the executor's own start check says: None, (kind, text) or an Exception
        self.started: list[str] = []
        self.commands: list[list[str]] = []

    def write_profile(self, profile: dict) -> None:
        (self.profiles / f"{profile['profile_id']}.json").write_text(json.dumps(profile), encoding="utf-8")

    def write_video(self, profile_id: str, tasks: list[str], *, template_text: str | None = None) -> None:
        name = f"{profile_id}.json"
        text = template_text if template_text is not None else json.dumps({"graph": profile_id})
        (self.templates / name).write_text(text, encoding="utf-8")
        options = dict(video_profile()["backend_options"], template_name=name,
                       template_sha256=hashlib.sha256(text.encode()).hexdigest())
        self.write_profile(video_profile(profile_id=profile_id, tasks=tasks, backend_options=options))

    def probes(self) -> preflight.Probes:
        def run(cmd, timeout=60.0, cwd=None):
            self.commands.append(list(cmd))
            if cmd[0] == "git" and "rev-parse" in cmd:
                return 0, self.head + "\n"
            if cmd[0] == "git" and "status" in cmd:
                return 0, self.dirty
            if cmd[0] == "nvidia-smi":
                return (0, self.smi) if self.smi is not None else (127, "FileNotFoundError")
            if cmd[0] == str(self.python):
                return (0, "warning: something\n" + json.dumps(self.torch) + "\n") if self.torch else (1, "ModuleNotFoundError")
            return 127, "unexpected command"

        def http(url, timeout=5.0):
            body = self.ollama if ":11434" in url else self.appliance
            return (200, body) if body is not None else (None, None)

        def area(env):
            if isinstance(self.area, Exception):
                raise self.area
            return self.area

        def start(env, device):
            self.started.append(device)
            if isinstance(self.start, Exception):
                raise self.start
            return self.start

        return preflight.Probes(run=run, http_json=http, work_area=area, total_ram_gib=lambda: self.ram,
                                secret_ok=lambda value: value == SECRET, executor_start=start)

    def evaluate(self, **kwargs) -> list[dict]:
        return preflight.evaluate(self.env, self.probes(), **kwargs)

    def statuses(self, **kwargs) -> dict[str, list[dict]]:
        found: dict[str, list[dict]] = {preflight.OK: [], preflight.WARN: [], preflight.FAIL: [], preflight.INFO: []}
        for item in self.evaluate(**kwargs):
            found[item["status"]].append(item)
        return found


def only_fail(rig: Rig, needle: str, **kwargs) -> dict:
    """Exactly one FAIL, and it is the one about `needle`."""
    fails = rig.statuses(**kwargs)[preflight.FAIL]
    if len(fails) != 1 or needle not in fails[0]["check"]:
        raise AssertionError(f"expected one FAIL about {needle!r}, got {[(f['check'], f['detail']) for f in fails]}")
    return fails[0]


# 1. A rig set up right: nothing to fix, bound to the release.
rig = Rig()
found = rig.statuses(expect_version="2.0.21", expect_sha=SHA, planner_model="qwen3:14b")
check("a correctly configured rig has no FAIL and no WARN",
      not found[preflight.FAIL] and not found[preflight.WARN], found[preflight.FAIL] + found[preflight.WARN])
names = [item["check"] for item in found[preflight.OK]]
for expected in ("KALIV_MEDIA_EXECUTOR", "executor-kilde", "medie-python: torch", "profiler", "video: text_to_video",
                 "video: image_to_video", "profil ltx-t2v: skabelon", "KALIV_COMFY_HOST_MEMORY_GIB",
                 "arbejdsområde, jobdatabase og medievolumen", "gpu cuda:1", "ollama", "appliance"):
    check(f"the pass names {expected}", expected in names, names)
check("without --expect-* the source is reported, not judged",
      [i["check"] for i in rig.statuses()[preflight.INFO]] == ["executor-kilde", "appliance"])

# 2. The supervisor's executor configuration, by the supervisor's own rules.
rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR"] = "0"
check("executor off is a FAIL that says jobs stay queued", "kø" in only_fail(rig, "KALIV_MEDIA_EXECUTOR")["detail"])
for bad in ("cuda:1,cuda:1", "gpu1", "", "cuda:100"):
    rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR_DEVICES"] = bad
    check(f"devices {bad!r} are refused as the supervisor refuses them",
          any(f["check"] == "KALIV_MEDIA_EXECUTOR_DEVICES" for f in rig.statuses()[preflight.FAIL]))
rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR_PYTHON"] = "python.exe"
check("a relative media python is refused", any(f["check"] == "KALIV_MEDIA_EXECUTOR_PYTHON" for f in rig.statuses()[preflight.FAIL]))
rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR_APP_DIR"] = str(rig.tmp)
only_fail(rig, "KALIV_MEDIA_EXECUTOR_APP_DIR")
check("an app dir without app/media_executor_main.py is the one FAIL", True)

# 3. The executor's source must be the release's own commit.
rig = Rig(); rig.head = "d" * 40
fail = only_fail(rig, "executor-kilde: commit", expect_version="2.0.21", expect_sha=SHA)
check("a different commit is a FAIL with the command that fixes it", "git -C" in fail["fix"] and SHA in fail["fix"])
rig = Rig(); (rig.repo / "VERSION").write_text("2.0.20\n")
only_fail(rig, "executor-kilde: version", expect_version="2.0.21", expect_sha=SHA)
check("a different VERSION is a FAIL", True)
rig = Rig(); rig.dirty = " M worker/app/media_executor.py\n M worker/app/x.py\n"
warns = rig.statuses(expect_version="2.0.21", expect_sha=SHA)[preflight.WARN]
check("local changes in the executor's source are a WARN that counts them",
      len(warns) == 1 and warns[0]["detail"].startswith("2 "), warns)

# 4. The media Python and the GPUs.
rig = Rig(); rig.torch = {"torch": "2.8.0", "cuda": True, "count": 1}
check("torch that sees one card cannot serve cuda:1", "cuda:1" in only_fail(rig, "medie-python")["detail"])
rig = Rig(); rig.torch = None
only_fail(rig, "medie-python")
check("a media python without torch is a FAIL", True)
rig = Rig(); rig.smi = "0, 12288, 1400\n"
only_fail(rig, "gpu cuda:1")
check("an executor device the driver does not list is a FAIL", True)
rig = Rig(); rig.smi = "0, 12288, 9800\n1, 12288, 8100\n"
warns = rig.statuses()[preflight.WARN]
check("memory already in use on the executor's card is a WARN that points at Ollama",
      len(warns) == 1 and "Ollama" in warns[0]["fix"], warns)
rig = Rig(); rig.smi = None
check("no nvidia-smi is a FAIL", any(f["check"] == "nvidia-smi" for f in rig.statuses()[preflight.FAIL]))

# 5. Profiles, with the worker's own loader.
rig = Rig(); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "realvis,missing"
check("an unknown enabled profile is refused by the worker's own rule", "unknown profiles" in only_fail(rig, "profiler")["detail"])
rig = Rig(); rig.env["KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES"] = "0"
check("candidate profiles without the allow switch are refused", "not rig-qualified" in only_fail(rig, "profiler")["detail"])
rig = Rig(); rig.write_profile(image_profile(profile_id="realvis", resources={"min_usable_gib": 8, "reserve_gib": 1, "devices": ["cuda:0"], "cpu_offload": False}))
check("a profile on a card no executor serves is a FAIL", "cuda:0" in only_fail(rig, "profil realvis: enhed")["detail"])
rig = Rig(); rig.env["KALIV_IMAGE_TOOL_PROFILE"] = "ltx-t2v"
only_fail(rig, "KALIV_IMAGE_TOOL_PROFILE")
check("an image-tool default that is a video profile is a FAIL", True)
rig = Rig(); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "ltx-t2v,ltx-i2v"; rig.env["KALIV_IMAGE_TOOL_PROFILE"] = ""
only_fail(rig, "billedprofil")
check("no enabled image profile is a FAIL", True)
rig = Rig(); rig.write_video("wan-t2v", ["text_to_video"]); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] += ",wan-t2v"
rig.env["KALIV_VIDEO_TOOL_PROFILE"] = "ltx-i2v"
check("two profiles for one task and none chosen is a FAIL (the 21 Nov rig case)",
      "ltx-t2v" in only_fail(rig, "video: text_to_video")["detail"])
rig.env["KALIV_VIDEO_TOOL_PROFILE"] = "ltx-t2v,ltx-i2v"
check("...and choosing one id per task clears it", not rig.statuses()[preflight.FAIL])
rig = Rig(); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "realvis,ltx-t2v"; rig.env["KALIV_VIDEO_TOOL_PROFILE"] = "ltx-t2v"
found = rig.statuses()
check("a task nobody serves is a WARN, not a FAIL",
      not found[preflight.FAIL] and [w["check"] for w in found[preflight.WARN]] == ["video: image_to_video"], found)

# 6. ComfyUI: paths, and templates pinned by the profile.
rig = Rig(); (rig.templates / "ltx-t2v.json").write_text("{\"edited\": true}")
check("an edited template no longer matches its profile's pin", "sha256" in only_fail(rig, "profil ltx-t2v: skabelon")["detail"])
rig = Rig(); (rig.templates / "ltx-i2v.json").unlink()
only_fail(rig, "profil ltx-i2v: skabelon")
check("a missing template is a FAIL", True)
rig = Rig(); rig.env["KALIV_COMFY_MAIN"] = str(rig.tmp / "nope.py")
only_fail(rig, "KALIV_COMFY_MAIN")
check("a missing ComfyUI main.py is a FAIL", True)
rig = Rig(); rig.env["KALIV_COMFY_HOST_MEMORY_GIB"] = "60"
warns = rig.statuses()[preflight.WARN]
check("60 of 64 GiB for ComfyUI is a WARN with a number to use", len(warns) == 1 and "48" in warns[0]["fix"], warns)
rig = Rig(); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "realvis"; rig.env["KALIV_VIDEO_TOOL_PROFILE"] = ""
for key in ("KALIV_COMFY_PYTHON", "KALIV_COMFY_MAIN", "KALIV_COMFY_DIR", "KALIV_COMFY_TEMPLATE_DIR"):
    rig.env[key] = ""
check("with no ComfyUI profile enabled the ComfyUI keys are not required", not rig.statuses()[preflight.FAIL])

# 7. Work area, Ollama, appliance, switches, secret.
rig = Rig(); rig.area = {"ok": False, "checks": [{"check": "work_area", "ok": True, "detail": "ok"},
                                                    {"check": "publication_volume", "ok": False, "detail": "media_volume_marker_missing"}]}
check("a failed work-area check is passed on with its reason code",
      "media_volume_marker_missing" in only_fail(rig, "arbejdsområde: publication_volume")["detail"])
rig = Rig(); rig.area = RuntimeError("boom")
only_fail(rig, "arbejdsområde")
check("a work-area preflight that raises is a FAIL, not a crash", True)
rig = Rig(); rig.ollama = None
only_fail(rig, "ollama")
check("Ollama down is a FAIL", True)
rig = Rig(); rig.ollama = {"models": [{"name": "gemma3:12b"}]}
check("a missing chat model is a FAIL with the pull command",
      only_fail(rig, "ollama: model", planner_model="qwen3:14b")["fix"] == "ollama pull qwen3:14b")
rig = Rig(); rig.appliance = {"version": "2.0.20"}
warns = rig.statuses(expect_version="2.0.21", expect_sha=SHA)[preflight.WARN]
check("an appliance still on the old version is a WARN", len(warns) == 1 and "2.0.20" in warns[0]["detail"], warns)
rig = Rig(); rig.appliance = None
check("an appliance that is not running is INFO", not rig.statuses()[preflight.FAIL])
for key in ("KALIV_TOOLS_ENABLED", "KALIV_MEDIA_JOBS_API", "KALIV_IMAGE_TOOL_ENABLED"):
    rig = Rig(); rig.env[key] = "0"
    only_fail(rig, key)
    check(f"{key}=0 is the one FAIL", True)
rig = Rig(); rig.env["KALIV_VIDEO_TOOL_ENABLED"] = "0"  # the chat tool only; the executor still starts
found = rig.statuses()
check("the video tool switched off is one WARN and no FAIL",
      not found[preflight.FAIL] and [w["check"] for w in found[preflight.WARN]] == ["video"], found)
rig = Rig(); rig.env["KALIV_MEDIA_INTERNAL_SECRET"] = "short"
fail = only_fail(rig, "KALIV_MEDIA_INTERNAL_SECRET")
check("a weak secret is a FAIL that names the 503 code", "media_jobs_secret_invalid" in fail["detail"])
check("the real worker rule is the default: a 40-character random secret is usable, a short one is not",
      preflight._secret_ok(SECRET) and not preflight._secret_ok("short"))

# 8. The env file is read as the supervisor reads it.
parsed = preflight.parse_env_file('﻿A=1\n# note\n\nB="q # r"  \nC=0.0.0.0   # bind\nD=a#b\nE = spaced \nA=2\r\n')
check("BOM, comments, quotes, inline comments and last-wins match loadEnvFile",
      parsed == {"A": "2", "B": "q # r", "C": "0.0.0.0", "D": "a#b", "E": "spaced"}, parsed)
for bad in ("JUSTAWORD\n", "=value\n"):
    try:
        preflight.parse_env_file(bad)
        raise AssertionError(f"FAIL: {bad!r} was accepted")
    except preflight.EnvFileError:
        check(f"a line the supervisor refuses ({bad.strip()!r}) is refused here", True)

# 9. The command: exit codes, output, no secret, and nothing written.
def run_main(rig: Rig, *extra: str) -> tuple[int, str, str]:
    env_file = rig.tmp / "modelrig.env"
    env_file.write_text("﻿# appliance\n" + "".join(f"{k}={v}\n" for k, v in rig.env.items()), encoding="utf-8")
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = preflight.main(["--env-file", str(env_file), *extra], probes=rig.probes())
    return code, out.getvalue(), err.getvalue()


def tree(rig: Rig) -> list[tuple[str, int, int]]:
    # modelrig.env is written by run_main itself before each run, so it is left out.
    return sorted((str(p.relative_to(rig.tmp)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in rig.tmp.rglob("*") if p.name != "modelrig.env")


rig = Rig()
code, out, _ = run_main(rig, "--expect-version", "2.0.21", "--expect-sha", SHA, "--planner-model", "qwen3:14b")
check("a ready rig exits 0 and says so", code == 0 and "ingen FAIL" in out and " 0 FAIL" in out, out[-200:])
before = tree(rig)
code, out, _ = run_main(rig, "--json")
after = [entry for entry in tree(rig)]
report = json.loads(out)
check("--json is one object with the schema and every check", report["schema"] == preflight.SCHEMA and len(report["checks"]) > 15)
check("the run wrote nothing next to what it read", before == after)
rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR"] = "0"
code, out, _ = run_main(rig)
check("one FAIL exits 1 and prints its fix on the next line", code == 1 and "\n        -> sæt KALIV_MEDIA_EXECUTOR=1" in out, out[:400])
for extra in ((), ("--json",)):
    for broken in (False, True):
        rig = Rig()
        if broken:
            rig.env["KALIV_MEDIA_EXECUTOR"] = "0"; rig.torch = None; rig.ollama = None
        _, out, err = run_main(rig, *extra)
        check(f"the secret's value is never printed ({'json' if extra else 'text'}, {'failing' if broken else 'passing'})",
              SECRET not in out + err and "z" * 20 not in out + err)
out, err = io.StringIO(), io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    code = preflight.main(["--env-file", str(rig.tmp / "absent.env")], probes=rig.probes())
check("an unreadable env file exits 2", code == 2 and "kan ikke læse" in err.getvalue())
(rig.tmp / "bad.env").write_text("KALIV_TOOLS_ENABLED=1\nnot a pair\n")
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
    code = preflight.main(["--env-file", str(rig.tmp / "bad.env")], probes=rig.probes())
check("an env file the supervisor would refuse exits 2 and says which line", code == 2 and "linje 2" in err.getvalue())
commands = [" ".join(c[:2]) for c in rig.commands]
check("it runs only read-only commands", all(c.startswith(("git -C", "nvidia-smi", str(rig.python))) for c in commands), commands)

# 9b. Review of #2503 (Codex): what the executor refuses must be a FAIL here, in its own words.
rig = Rig()
rig.statuses()
check("the executor's own start check is asked once per configured device", rig.started == ["cuda:1"], rig.started)
rig = Rig()
rig.env["KALIV_MEDIA_EXECUTOR_DEVICES"] = "cuda:0,cuda:1"
for profile_id in ("realvis", "ltx-t2v", "ltx-i2v"):
    document = json.loads((rig.profiles / f"{profile_id}.json").read_text())
    document["resources"]["devices"] = ["cuda:0", "cuda:1"]
    rig.write_profile(document)
rig.statuses()
check("...and for every device when there are two", rig.started == ["cuda:0", "cuda:1"], rig.started)
rig = Rig()
rig.start = ("config", "KALIV_COMFY_DIR/cuda1/input must be an existing folder in the work area (missing)")
item = only_fail(rig, "egen startkontrol")
check("a refusal by the executor (the per-device ComfyUI folders) is a FAIL that quotes it and names exit 78",
      "cuda1/input" in item["detail"] and "78" in item["detail"], item)
rig.start = ("volume", "the media volume is not mounted")
check("a volume that is not there is a FAIL that names exit 75", "75" in only_fail(rig, "egen startkontrol")["detail"])
rig.start = RuntimeError("boom " + SECRET)
item = only_fail(rig, "egen startkontrol")
check("a start check that itself breaks is a FAIL, never OK, and its message is not printed",
      "RuntimeError" in item["detail"] and SECRET not in json.dumps(item), item)
rig = Rig()
rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = ""
fails = rig.statuses()[preflight.FAIL]
check("no enabled profile at all is a FAIL (the loader returns an empty set, the executor refuses to start)",
      any(f["check"] == "profiler" for f in fails) and any("cuda:1: profiler" in f["check"] for f in fails) is False, fails)
rig = Rig()
del rig.env["KALIV_MEDIA_PROFILES_ENABLED"]
check("...and so is a missing KALIV_MEDIA_PROFILES_ENABLED", any(f["check"] == "profiler" for f in rig.statuses()[preflight.FAIL]))
rig = Rig()
rig.env["KALIV_MEDIA_VIDEO"] = "0"
fails = rig.statuses()[preflight.FAIL]
check("video profiles enabled on an executor's GPU with KALIV_MEDIA_VIDEO off stop the whole executor: FAIL, not WARN",
      [f["check"] for f in fails] == ["executor cuda:1: video"] and "billeder" in fails[0]["detail"], fails)
rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "realvis"
rig.env.pop("KALIV_VIDEO_TOOL_PROFILE")
found = rig.statuses()
check("video off with no video profile enabled is still only a WARN", not found[preflight.FAIL] and
      any(w["check"] == "video" for w in found[preflight.WARN]), found[preflight.FAIL])
rig = Rig()
rig.env["KALIV_MEDIA_EXECUTOR_DEVICES"] = "cuda:0,cuda:1"
check("an executor device no enabled profile runs on is a FAIL for that device",
      any(f["check"] == "executor cuda:0: profiler" for f in rig.statuses()[preflight.FAIL]))

# 9c. The real start check, where it refuses before it looks at a disk: the text is the executor's
#     own, and `build_from_env` refuses with the same words (it runs the same function).
from app.media_executor import ExecutorConfigError  # noqa: E402
from app.media_executor_main import build_from_env  # noqa: E402

rig = Rig()
for label, change in (("the executor switch off", {"KALIV_MEDIA_EXECUTOR": "0"}),
                      ("no CUDA_DEVICE_ORDER in the env file", {})):
    env = dict(rig.env, **change)
    refusal = preflight._executor_start(env, "cuda:1")
    try:
        build_from_env("cuda:1", env)
        built = None
    except ExecutorConfigError as exc:
        built = str(exc)
    check(f"real start check, {label}: refused as configuration, in the words build_from_env uses",
          refusal is not None and refusal[0] == "config" and refusal[1] == built, (refusal, built))
check("...and the second one is the CUDA_DEVICE_ORDER rule the supervisor does not add for the executor",
      "CUDA_DEVICE_ORDER" in refusal[1], refusal)

# 9d. A bare Python: no FastAPI, no pydantic, no torch. The tool must still report, not crash.
import subprocess  # noqa: E402

rig = Rig()
env_file = rig.tmp / "bare.env"
env_file.write_text("".join(f"{k}={v}\n" for k, v in rig.env.items()), encoding="utf-8")
blocker = ("import sys, importlib.abc, runpy\n"
           "class B(importlib.abc.MetaPathFinder):\n"
           "    def find_spec(self, name, path, target=None):\n"
           "        if name.split('.')[0] in {'fastapi', 'pydantic', 'starlette', 'torch', 'httpx', 'uvicorn'}:\n"
           "            raise ModuleNotFoundError(name)\n"
           "sys.meta_path.insert(0, B())\n"
           f"sys.argv = ['media_release_preflight.py', '--env-file', {str(env_file)!r}, '--json']\n"
           f"runpy.run_path({str(ROOT / 'scripts' / 'media_release_preflight.py')!r}, run_name='__main__')\n")
done = subprocess.run([sys.executable, "-c", blocker], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
check("without FastAPI/pydantic/torch the tool exits 1 with a report, not a traceback",
      done.returncode == 1 and "Traceback" not in done.stderr, (done.returncode, done.stderr[-400:]))
bare = {item["check"]: item for item in json.loads(done.stdout)["checks"]}
check("...the secret is judged (OK) without the API stack", bare["KALIV_MEDIA_INTERNAL_SECRET"]["status"] == "OK", bare["KALIV_MEDIA_INTERNAL_SECRET"])
check("...the profiles are read by the worker's loader", bare["profiler"]["status"] == "OK", bare["profiler"])
check("...and the executor's own start check ran and answered in its own words",
      bare["executor cuda:1: egen startkontrol"]["status"] == "FAIL" and "CUDA_DEVICE_ORDER" in bare["executor cuda:1: egen startkontrol"]["detail"],
      bare["executor cuda:1: egen startkontrol"])
from app.media_job_api import MIN_SECRET_CHARS, _usable_secret  # noqa: E402  (after 9d: this imports FastAPI)

check("the secret rule restated in the tool is the worker's: same length, same answers",
      preflight.MIN_SECRET_CHARS == MIN_SECRET_CHARS and all(
          preflight._secret_ok(v) == bool(_usable_secret(v))
          for v in ("", "a" * 31, "a" * 32, "a" * 40 + "\n", "a" * 40 + "\r", SECRET, None, 5)))

# 10. The real probes, on whatever machine this is (the Windows gate runs this file too): against
#     the shipped example -- media off, nothing configured -- the tool runs to the end and reports.
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
    code = preflight.main(["--env-file", str(ROOT / "deploy" / "modelrig.env.example"), "--json"])
report = json.loads(out.getvalue())
check("the shipped env example (media off) is reported as not ready, exit 1, with the real probes", code == 1)
check("every finding is one of the four statuses and carries a detail",
      all(item["status"] in ("OK", "WARN", "FAIL", "INFO") and item["detail"] for item in report["checks"]))
ram = preflight._total_ram_gib()
check(f"physical memory is read on this platform ({os.name}): {ram}", isinstance(ram, float) and ram > 0.5)
check("an absolute path of this platform is absolute to the tool", os.path.isabs(str(rig.python)))

print(f"{passed} passed, 0 failed")

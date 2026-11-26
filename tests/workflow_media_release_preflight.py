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
        # Everything but the internal secret; `env` adds it. Kept apart so a case that writes an
        # env file with a filler never handles the stand-in value (CodeQL #2503).
        self.plain_env = {
            "KALIV_TOOLS_ENABLED": "1", "KALIV_MEDIA_JOBS_API": "1", "KALIV_IMAGE_TOOL_ENABLED": "1",
            "KALIV_MEDIA_VIDEO": "1", "KALIV_VIDEO_TOOL_ENABLED": "1",
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
        self.env = dict(self.plain_env, KALIV_MEDIA_INTERNAL_SECRET=SECRET)
        self.head, self.dirty, self.untracked = SHA, "", ""
        self.own_head: str | None = None  # HEAD of the checkout the script itself lies in; None: same as `head`
        self.own_changed = ""  # `git status` of that checkout
        self.process_env: dict[str, str] = {}
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
                elsewhere = str(self.repo) not in cmd
                return 0, (self.own_head if elsewhere and self.own_head else self.head) + "\n"
            if cmd[0] == "git" and "status" in cmd:
                if str(self.repo) not in cmd:
                    return 0, self.own_changed
                return 0, self.untracked if "--untracked-files=all" in cmd else self.dirty
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

        def start(env, device, python, app_dir):
            self.started.append(device)
            self.start_args = (python, app_dir)
            if isinstance(self.start, Exception):
                raise self.start
            return self.start

        return preflight.Probes(run=run, http_json=http, work_area=area, total_ram_gib=lambda: self.ram,
                                secret_ok=lambda value: value == SECRET, executor_start=start,
                                process_env=lambda: self.process_env)

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
                 "video: image_to_video", "profil: skabelon", "KALIV_COMFY_HOST_MEMORY_GIB",
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
warns = rig.statuses()[preflight.WARN]
check("unbound, local changes in the executor's source are a WARN that counts them",
      len(warns) == 1 and warns[0]["detail"].startswith("2 "), warns)
fail = only_fail(rig, "executor-kilde: ændringer", expect_version="2.0.21", expect_sha=SHA)
check("bound to a release, they are a FAIL: HEAD is the release but the files are not (ChatGPT #2503)", fail["detail"].startswith("2 "))
rig = Rig(); rig.untracked = "?? worker/json.py\n M ignored-here\n"
fail = only_fail(rig, "executor-kilde: ændringer", expect_version="2.0.21", expect_sha=SHA)
check("...and so is an untracked file beside the executor's code", "1 ikke-sporede" in fail["detail"], fail)
check("...which is looked for under worker/ with untracked files listed",
      any("--untracked-files=all" in c and c[-2:] == ["--", "worker"] for c in rig.commands), rig.commands)
# The profile, task and work-area rules run from the script's own checkout and decide readiness
# too, so bound to a release that checkout must be the release as well (ChatGPT #2503, re-review).
rig = Rig(); rig.own_head = "e" * 40
warns = rig.statuses()[preflight.WARN]
check("unbound, a script run from a checkout on another commit than the executor's source is a WARN",
      [w["check"] for w in warns] == ["tjekkets eget checkout"], warns)
fail = only_fail(rig, "tjekkets eget checkout", expect_version="2.0.21", expect_sha=SHA)
check("bound to a release it is a FAIL, with the folder to run from", str(rig.repo) in fail["fix"], fail)
rig = Rig(); rig.own_changed = " M worker/app/media_generation_profiles.py\n?? scripts/x.py\n"
check("...and so is the same commit with changed or untracked files under worker/ or scripts/",
      only_fail(rig, "tjekkets eget checkout", expect_version="2.0.21", expect_sha=SHA)["detail"].startswith("2 "))
check("...which unbound is a WARN", [w["check"] for w in rig.statuses()[preflight.WARN]] == ["tjekkets eget checkout"])
check("...and is asked of the script's checkout, under worker/ and scripts/",
      any(c[-3:] == ["--", "worker", "scripts"] and str(ROOT) in c for c in rig.commands), rig.commands)

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
item = only_fail(rig, "profiler")
check("an unknown enabled profile is refused by the worker's own rule, told in this file's words with the key it names",
      "GenerationError" in item["detail"] and "ikke findes i profilmappen" in item["detail"]
      and "KALIV_MEDIA_PROFILES_ENABLED" in item["detail"] and "unknown profiles" not in item["detail"], item)
rig = Rig(); rig.env["KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES"] = "0"
item = only_fail(rig, "profiler")
check("candidate profiles without the allow switch are refused, with the switch named",
      "ikke rig-kvalificeret" in item["detail"] and "KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES" in item["detail"], item)
rig = Rig(); rig.write_profile(image_profile(profile_id="realvis", resources={"min_usable_gib": 8, "reserve_gib": 1, "devices": ["cuda:0"], "cpu_offload": False}))
check("a profile on a card no executor serves is a FAIL", "cuda:0" in only_fail(rig, "profil: enhed")["detail"] and
      only_fail(rig, "profil: enhed")["detail"].startswith("realvis "))
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
check("an edited template no longer matches its profile's pin", "sha256" in only_fail(rig, "profil: skabelon")["detail"] and
      only_fail(rig, "profil: skabelon")["detail"].startswith("ltx-t2v: "))
rig = Rig(); (rig.templates / "ltx-i2v.json").unlink()
check("...the profile is named in the detail, not in the id", only_fail(rig, "profil: skabelon")["detail"].startswith("ltx-i2v: "))
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
item = only_fail(rig, "arbejdsområde: publication_volume")
check("a failed work-area check is named by its id; its free text is not repeated",
      item["detail"] == "ikke opfyldt" and "media_volume_marker_missing" not in json.dumps(item), item)
rig = Rig(); rig.area = {"ok": False, "checks": [{"check": "private:Media Jobs.db\x1b[2J", "ok": False,
                                                    "detail": f"KALIV_MEDIA_JOB_DB is not private ({SECRET})"}]}
item = only_fail(rig, "arbejdsområde: private")
check("...of its name only the component's own word is used, and of its text only the key name",
      item["check"] == "arbejdsområde: private" and item["detail"] == "ikke opfyldt; nævner: KALIV_MEDIA_JOB_DB", item)

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
check("it runs only read-only commands", all(c.startswith(("git --no-optional-locks", "nvidia-smi", str(rig.python))) for c in commands), commands)
rig = Rig()
rig.statuses(expect_version="2.0.21", expect_sha=SHA)
gits = [c for c in rig.commands if c[0] == "git"]
pythons = [c for c in rig.commands if c[0] == str(rig.python)]
check("every git command is run without optional locks (git status would refresh the index)",
      len(gits) >= 3 and all(c[1] == "--no-optional-locks" for c in gits), gits)
check("the media Python is started with -B (it would write __pycache__ beside torch)",
      len(pythons) == 1 and pythons[0][1] == "-B", pythons)
check("the start check is given the supervisor's interpreter and folder, not this script's",
      rig.start_args == (rig.env["KALIV_MEDIA_EXECUTOR_PYTHON"], rig.env["KALIV_MEDIA_EXECUTOR_APP_DIR"]), rig.start_args)

# Check ids are a closed set (ChatGPT #2503, third review): a value can not ride in one.
PLAIN = "zq9" * 12  # a value made only of characters the old identifier filter kept
rig = Rig()
rig.env["KALIV_MEDIA_INTERNAL_SECRET"] = PLAIN
rig.area = {"ok": False, "checks": [{"check": PLAIN, "ok": False, "detail": "x"},
                                    {"check": f"private:{PLAIN}", "ok": False, "detail": "x"},
                                    {"check": f"free_space:{PLAIN}", "ok": False, "detail": PLAIN}]}
for extra in ((), ("--json",)):
    code, out, err = run_main(rig, *extra)
    check(f"a secret in a work-area check name reaches neither id nor text, and the FAILs still exit 1 ({'json' if extra else 'text'})",
          code == 1 and PLAIN[:10] not in out + err, out[-400:])
ids = [f["check"] for f in rig.statuses()[preflight.FAIL] if f["check"].startswith("arbejdsområde")]
check("...the three become fixed ids: andet, private, free_space",
      ids == ["arbejdsområde: andet", "arbejdsområde: private", "arbejdsområde: free_space"], ids)
rig = Rig()
document = json.loads((rig.profiles / "realvis.json").read_text())
document["profile_id"] = "zq9profileidstandin"
(rig.profiles / "realvis.json").unlink()
rig.write_profile(document)
rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "zq9profileidstandin,ltx-t2v,ltx-i2v"
rig.env["KALIV_IMAGE_TOOL_PROFILE"] = "zq9profileidstandin"
rig.env["KALIV_MEDIA_EXECUTOR_DEVICES"] = "cuda:0"
found = rig.evaluate()
check("a profile id is never part of a check id (it is in the detail)",
      not any("zq9profileidstandin" in f["check"] for f in found) and any("zq9profileidstandin" in f["detail"] for f in found),
      [f["check"] for f in found])
seen_ids: set[str] = set()
for scenario in (Rig(), rig):
    for expect in ({}, {"expect_version": "2.0.21", "expect_sha": SHA}):
        seen_ids |= {f["check"] for f in scenario.evaluate(**expect)}
check("every id a report carries is one of the fixed ids", all(preflight.fixed_id(i) for i in seen_ids) and len(seen_ids) > 20, sorted(seen_ids))
real = preflight._evaluate
try:
    preflight._evaluate = lambda env, probes, **kw: [{"status": preflight.FAIL, "check": f"profil {SECRET}: ny", "detail": "d", "fix": ""}]
    found = preflight.evaluate(rig.env, rig.probes())
finally:
    preflight._evaluate = real
check("...and a rule that ever builds an id from a value is reported under a fixed id, still as a FAIL",
      found == [{"status": preflight.FAIL, "check": preflight.UNKNOWN_CHECK, "detail": "d", "fix": ""}], found)
check("the fixed device ids take cuda:N only", preflight.fixed_id("gpu cuda:1") and preflight.fixed_id("executor cuda:12: video")
      and not preflight.fixed_id("gpu cuda:1 " + SECRET) and not preflight.fixed_id("executor cuda:x: video"))

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
check("a refusal by the executor (the per-device ComfyUI folders) is a FAIL with exit 78, this file's reason and the key it names",
      item["detail"] == "afviser start (exit 78): en mappe mangler i arbejdsområdet; nævner: KALIV_COMFY_DIR/cuda1/input"
      and "executor-cuda1.log" in item["fix"], item)
rig.start = ("volume", "the media volume is not mounted")
check("a volume that is not there is a FAIL that names exit 75", "75" in only_fail(rig, "egen startkontrol")["detail"])
# No character of a foreign text reaches the report: not whole, not cut, not transformed.
for kind in ("config", "volume"):
    for label, text in (("whole", f"KALIV_MEDIA_JOB_DB refused: {SECRET} was seen\x1b[31m\nsecond line"),
                        ("across where a cut would fall", "x" * 290 + SECRET + " KALIV_MEDIA_WORK_ROOT"),
                        ("transformed", "token " + SECRET[::-1] + " " + SECRET.upper() + " " + SECRET[:20]),
                        ("dressed as a key name", "KALIV_" + SECRET.upper() + " HF_TOKEN")):
        rig = Rig()
        rig.env["HF_TOKEN"] = "KALIV_PRETEND_KEY"
        rig.start = (kind, text)
        item = only_fail(rig, "egen startkontrol")
        for extra in ((), ("--json",)):
            _, out, err = run_main(rig, *extra)
            shown = out + err
            check(f"a secret {label} in the executor's {kind} refusal is not printed ({'json' if extra else 'text'})",
                  SECRET not in shown and SECRET[:12] not in shown and SECRET[::-1] not in shown and SECRET.upper() not in shown
                  and "second line" not in shown and "refused" not in shown and "\x1b" not in shown, shown[-300:])
rig = Rig()
rig.env["HF_TOKEN"] = "KALIV_PRETEND_KEY"
rig.start = ("config", "KALIV_PRETEND_KEY and KALIV_PRETEND_KEY/cuda1 and KALIV_MEDIA_WORK_ROOT must be an absolute path")
check("a key-name-shaped token that is a value of the env file is dropped; the real key name is kept",
      only_fail(rig, "egen startkontrol")["detail"] == "afviser start (exit 78): en sti er ikke absolut; nævner: KALIV_MEDIA_WORK_ROOT")
rig.start = ("config", " ".join(f"KALIV_KEY_{n}" for n in range(40)))
check("the list of key names is bounded", only_fail(rig, "egen startkontrol")["detail"].count("KALIV_KEY_") == preflight.MAX_NAMES)
rig = Rig()
refusing = rig.probes()


def loader_refuses(env):
    raise ValueError("x" * 190 + SECRET + " in KALIV_MEDIA_PROFILE_DIR")


refusing.profiles = loader_refuses
found = preflight.evaluate(rig.env, refusing)
item = [f for f in found if f["check"] == "profiler"][0]
check("a loader error that quotes a secret (across the old cut) contributes its class and the key name only",
      SECRET[:8] not in json.dumps(found) and item["detail"] ==
      "afvist af profil-loaderen (ValueError): en profilfil eller profilmappen blev afvist; nævner: KALIV_MEDIA_PROFILE_DIR", item)

# The masking is presentation only: it can never change a verdict (ChatGPT #2503, re-review).
for word in ("FAIL", "WARN", "OK  ", "INFO", "profiler", "video"):
    rig = Rig()
    rig.env["KALIV_MEDIA_INTERNAL_SECRET"] = word
    rig.env["KALIV_MEDIA_EXECUTOR"] = "0"
    probes = rig.probes()
    probes.secret_ok = lambda value: False
    found = preflight.evaluate(rig.env, probes)
    check(f"a secret whose value is {word!r}: every status is still one of the four and every check id is unchanged",
          all(f["status"] in (preflight.OK, preflight.WARN, preflight.FAIL, preflight.INFO) for f in found)
          and not any(preflight.HIDDEN in f["check"] for f in found)
          and sum(f["status"] == preflight.FAIL for f in found) >= 2 and preflight.readiness(found)["image"] is False, found[:3])
    code, out, _ = run_main(rig, "--json")
    check(f"...and the command still exits 1 and reports nothing ready ({word!r})",
          code == 1 and json.loads(out)["ready"] == {"image": False, "text_to_video": False, "image_to_video": False})
rig = Rig()
rig.env["KALIV_MEDIA_EXECUTOR_PYTHON"] = str(rig.tmp / ("p" * 700) / SECRET)
item = [f for f in rig.evaluate() if f["check"] == "KALIV_MEDIA_EXECUTOR_PYTHON"][0]
check("a text of this file's own is masked before it is cut: no part of a secret past the limit survives",
      len(item["detail"]) <= preflight.MAX_TEXT and SECRET[:6] not in item["detail"], item["detail"][-80:])
rig = Rig()
rig.start = ("old", "")
check("an executor source without check_start is a FAIL that says it is older than this check",
      "ældre" in only_fail(rig, "egen startkontrol")["detail"])
rig = Rig()
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
    refusal = preflight._executor_start(env, "cuda:1", sys.executable, str(ROOT / "worker"))
    try:
        build_from_env("cuda:1", env)
        built = None
    except ExecutorConfigError as exc:
        built = str(exc)
    check(f"real start check, {label}: refused as configuration, in the words build_from_env uses",
          refusal is not None and refusal[0] == "config" and refusal[1] == built, (refusal, built))
check("...and the second one is the CUDA_DEVICE_ORDER rule the supervisor does not add for the executor",
      "CUDA_DEVICE_ORDER" in refusal[1], refusal)

# The code that answers is the code in KALIV_MEDIA_EXECUTOR_APP_DIR, not this checkout's (ChatGPT
# #2503): three stand-in sources, each run by the real probe.
def source(body: str) -> str:
    folder = Path(tempfile.mkdtemp(prefix="kaliv-preflight-src-"))
    (folder / "app").mkdir()
    (folder / "app" / "__init__.py").write_text("")
    (folder / "app" / "media_executor.py").write_text("class ExecutorConfigError(Exception): pass\n")
    (folder / "app" / "media_generation_contract.py").write_text("class ArtifactSinkUnavailable(Exception): pass\n")
    (folder / "app" / "media_executor_main.py").write_text(body)
    return str(folder)


strict = source("from .media_executor import ExecutorConfigError\n"
                "def check_start(device, env):\n    raise ExecutorConfigError('this source refuses ' + device)\n")
check("the start check runs the source in the executor's folder: its refusal, not this checkout's",
      preflight._executor_start(rig.env, "cuda:1", sys.executable, strict) == ("config", "this source refuses cuda:1"))
gone = source("from .media_generation_contract import ArtifactSinkUnavailable\n"
              "def check_start(device, env):\n    raise ArtifactSinkUnavailable('no volume')\n")
check("...a volume refusal from it is kind volume", preflight._executor_start(rig.env, "cuda:1", sys.executable, gone) == ("volume", "no volume"))
check("...a source that accepts gives None", preflight._executor_start(rig.env, "cuda:1", sys.executable, source("def check_start(device, env):\n    return None\n")) is None)
check("...a source from before check_start is kind old", preflight._executor_start(rig.env, "cuda:1", sys.executable, source("x = 1\n"))[0] == "old")
check("...a source that does not import is kind broken, never a pass",
      preflight._executor_start(rig.env, "cuda:1", sys.executable, source("import nothing_like_this\n"))[0] == "broken")
check("...and no stand-in source got a __pycache__: the child is started with -B",
      not list(Path(strict).rglob("__pycache__")) and not list(Path(gone).rglob("__pycache__")))

# Loopback only: no proxy from the environment, no redirect followed.
import http.server  # noqa: E402
import threading  # noqa: E402

seen: list[str] = []


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        seen.append(f"{self.server.server_port}{self.path}")
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/landed")
            self.end_headers()
            return
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


target = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
proxy = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
for server in (target, proxy):
    threading.Thread(target=server.serve_forever, daemon=True).start()
saved = {key: os.environ.get(key) for key in ("http_proxy", "HTTP_PROXY", "no_proxy", "NO_PROXY")}
try:
    os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = f"http://127.0.0.1:{proxy.server_port}"
    os.environ.pop("no_proxy", None); os.environ.pop("NO_PROXY", None)
    answer = preflight._http_json(f"http://127.0.0.1:{target.server_port}/direct")
    check("a proxy in the environment is not used: the request reaches the loopback port itself",
          answer == (200, {"ok": True}) and seen == [f"{target.server_port}/direct"], (answer, seen))
    answer = preflight._http_json(f"http://127.0.0.1:{target.server_port}/redirect")
    check("a redirect is refused, not followed", answer == (None, None) and not any(s.endswith("/landed") for s in seen), (answer, seen))
finally:
    for key, value in saved.items():
        os.environ.pop(key, None) if value is None else os.environ.__setitem__(key, value)
    target.shutdown(); proxy.shutdown()
check("an address that is not 127.0.0.1 is not asked at all", preflight._http_json("http://example.invalid:80/x") == (None, None))

# What a pass claims: only what is ready (ChatGPT #2503 P3).
rig = Rig()
code, out, _ = run_main(rig)
check("image and both video tasks ready: the last line names them", code == 0 and "første klip (text_to_video, image_to_video)" in out, out[-200:])
rig = Rig(); rig.env["KALIV_VIDEO_TOOL_ENABLED"] = "0"
code, out, _ = run_main(rig)
check("video off: exit 0, but the last line says the clips are NOT ready", code == 0 and "første klip" not in out and
      "IKKE klar: text_to_video, image_to_video" in out, out[-200:])
code, out, _ = run_main(rig, "--json")
check("...and the JSON says the same", json.loads(out)["ready"] == {"image": True, "text_to_video": False, "image_to_video": False})
code, out, _ = run_main(rig, "--require-video")
check("--require-video turns it into a FAIL and exit 1", code == 1 and "ikke klar" in out and "ingen FAIL" not in out, out[-200:])
rig = Rig(); (rig.profiles / "ltx-i2v.json").unlink(); rig.env["KALIV_MEDIA_PROFILES_ENABLED"] = "realvis,ltx-t2v"
rig.env["KALIV_VIDEO_TOOL_PROFILE"] = "ltx-t2v"
code, out, _ = run_main(rig)
check("a video task with no profile is named as not ready", code == 0 and "klip (text_to_video). IKKE klar: image_to_video" in out, out[-200:])
check("...and is a FAIL with --require-video", run_main(rig, "--require-video")[0] == 1)
rig = Rig(); rig.env["KALIV_MEDIA_EXECUTOR"] = "0"
code, out, _ = run_main(rig)
check("with a FAIL nothing is called ready", code == 1 and "klar til" not in out)

# The supervisor's own environment cannot be seen; what this window has beyond the file is named.
rig = Rig(); rig.process_env = {"CUDA_DEVICE_ORDER": "PCI_BUS_ID", "KALIV_TOOLS_ENABLED": "1", "PATH": "x", "HF_TOKEN": SECRET}
infos = [i for i in rig.statuses()[preflight.INFO] if i["check"] == "miljø uden for env-filen"]
check("keys set in this window and absent from the file are listed by name only",
      len(infos) == 1 and "CUDA_DEVICE_ORDER" in infos[0]["detail"] and "HF_TOKEN" in infos[0]["detail"]
      and "KALIV_TOOLS_ENABLED" not in infos[0]["detail"] and SECRET not in json.dumps(infos), infos)

# 9d. A bare Python: no FastAPI, no pydantic, no torch. The tool must still report, not crash.
import subprocess  # noqa: E402

rig = Rig()
env_file = rig.tmp / "bare.env"
# The file gets a throwaway filler where the internal secret goes: the fixture's stand-in value is
# never written to disk (CodeQL #2503: clear-text storage).
bare_env = dict(rig.plain_env, KALIV_MEDIA_EXECUTOR_PYTHON=sys.executable, KALIV_MEDIA_EXECUTOR_APP_DIR=str(ROOT / "worker"))
lines = [f"{k}={v}\n" for k, v in bare_env.items()]
lines.append("KALIV_MEDIA_INTERNAL_" + "SECRET=" + "filler-" * 6 + "\n")
env_file.write_text("".join(lines), encoding="utf-8")
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

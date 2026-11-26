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
(`import torch`), Ollama's tag list and the appliance's /healthz. It writes
nothing, starts nothing, and prints no value of a secret.

Only the env file is read. A child of the supervisor also inherits the
supervisor's own environment, so a key set there and absent from the file is
reported here as missing although the appliance would see it.

Exit 0: no FAIL. Exit 1: at least one FAIL. Exit 2: usage or unreadable env
file. A pass is this machine now -- not a qualification, and not a job: the
first image and the first clip are still the proof.
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


def _run(cmd: list[str], timeout: float = 60.0, cwd: str | None = None) -> tuple[int, str]:
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, type(exc).__name__


def _http_json(url: str, timeout: float = 5.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # loopback only, see callers
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


def _secret_ok(value: str) -> bool:
    from app.media_job_api import _usable_secret
    return bool(_usable_secret(value))


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


@dataclass
class Report:
    checks: list[dict] = field(default_factory=list)

    def add(self, status: str, name: str, detail: str, fix: str = "") -> None:
        self.checks.append({"status": status, "check": name, "detail": detail, "fix": fix})


def evaluate(env: Mapping[str, str], probes: Probes, *, expect_version: str | None = None,
             expect_sha: str | None = None, planner_model: str | None = None) -> list[dict]:
    """The rules. Pure given `probes`; never prints and never raises on a bad configuration."""
    report = Report()
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
        report.add(WARN, "video", "video er slået fra (begge kontakter skal være 1)",
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
        code, head = probes.run(["git", "-C", repo, "rev-parse", "HEAD"], 20.0)
        head = head.strip() if code == 0 else None
        code, dirty = probes.run(["git", "-C", repo, "status", "--porcelain", "--untracked-files=no"], 30.0)
        dirty_count = len([line for line in dirty.splitlines() if line.strip()]) if code == 0 else None
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
        if dirty_count:
            report.add(WARN, "executor-kilde: ændringer", f"{dirty_count} ændrede filer i {repo}",
                       "executoren kører den kode, der ligger der, ikke releasens")

    # --- 4. the media Python can see the GPUs it is told to use ---------------------------------
    highest = max((int(d.split(":")[1]) for d in devices), default=-1)
    if probes.is_file(python) and os.path.isabs(python):
        code, out = probes.run([python, "-c", "import json,torch;print(json.dumps({'torch':torch.__version__,"
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
        report.add(FAIL, "profiler", f"afvist: {str(exc)[:200]}", "ret KALIV_MEDIA_PROFILE_DIR / KALIV_MEDIA_PROFILES_ENABLED / profilfilen")
    if enabled:
        report.add(OK, "profiler", ", ".join(f"{pid} ({p.modality}, {p.qualification})" for pid, p in sorted(enabled.items())))
        for pid, profile in sorted(enabled.items()):
            if devices and not set(profile.resources.devices) & set(devices):
                report.add(FAIL, f"profil {pid}: enhed", f"kører på {','.join(profile.resources.devices)}, men executorerne er {','.join(devices)}",
                           "ingen executor tager dens job: ret profilens devices eller KALIV_MEDIA_EXECUTOR_DEVICES")
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
                    report.add(WARN, f"video: {task}", "ingen slået-til profil laver den opgave", "slå en profil til, der har opgaven, hvis den skal virke")
                elif not chosen and len(serving) > 1:
                    report.add(FAIL, f"video: {task}", f"{len(serving)} profiler kan ({', '.join(sorted(serving))}), og ingen er valgt",
                               "sæt KALIV_VIDEO_TOOL_PROFILE til ét id pr. opgave, adskilt af komma")
                else:
                    report.add(OK, f"video: {task}", (chosen or serving)[0])

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
                report.add(FAIL, f"profil {pid}: skabelon", f"{options.template_name} mangler i {template_dir}", "læg skabelonen dér")
            elif digest != options.template_sha256:
                report.add(FAIL, f"profil {pid}: skabelon", f"{options.template_name} har sha256 {digest[:12]}, profilen pinner {options.template_sha256[:12]}",
                           "skabelon og profil skal stamme fra samme opsætning")
            else:
                report.add(OK, f"profil {pid}: skabelon", options.template_name)
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
                report.add(FAIL, f"arbejdsområde: {item.get('check')}", str(item.get("detail"))[:200], "se docs/MEDIA_WORK_AREA.md og docs/MEDIA_VOLUME.md")
        else:
            report.add(OK, "arbejdsområde, jobdatabase og medievolumen", f"{len(area.get('checks', []))} kontroller bestået")
    except Exception as exc:
        report.add(FAIL, "arbejdsområde", f"kunne ikke kontrolleres: {type(exc).__name__}", "sæt KALIV_MEDIA_WORK_ROOT, _JOB_DB, _VOLUME_ROOT og _VOLUME_ID")

    # --- 8. the GPUs, as the driver reports them now ---------------------------------------------
    code, out = probes.run(["nvidia-smi", "--query-gpu=index,memory.total,memory.used", "--format=csv,noheader,nounits"], 30.0)
    gpus: dict[int, tuple[int, int]] = {}
    if code == 0:
        for line in out.splitlines():
            parts = [part.strip() for part in line.split(",")]
            if len(parts) == 3 and all(part.isdigit() for part in parts):
                gpus[int(parts[0])] = (int(parts[1]), int(parts[2]))
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
    return report.checks


def render(checks: list[dict]) -> str:
    lines = []
    for item in checks:
        lines.append(f"  {item['status']:<5} {item['check']}: {item['detail']}")
        if item["fix"] and item["status"] in (FAIL, WARN):
            lines.append(f"        -> {item['fix']}")
    counts = {status: sum(1 for item in checks if item["status"] == status) for status in (OK, WARN, FAIL, INFO)}
    lines.append("")
    lines.append(f"  {counts[OK]} OK, {counts[WARN]} WARN, {counts[FAIL]} FAIL, {counts[INFO]} INFO"
                 + ("" if counts[FAIL] else "  -- ingen FAIL: klar til første billede og første klip"))
    return "\n".join(lines)


def main(argv: list[str] | None = None, probes: Probes | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", required=True, help="appliancens env-fil, fx C:\\Rig\\ModelRig\\modelrig.env")
    parser.add_argument("--expect-version", help="releasens version, fx 2.0.21")
    parser.add_argument("--expect-sha", help="den fulde commit, tagget peger på")
    parser.add_argument("--planner-model", help="chatmodellen, fx qwen3:14b")
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
                      planner_model=args.planner_model)
    if args.json:
        print(json.dumps({"schema": SCHEMA, "env_file": args.env_file, "checks": checks}, ensure_ascii=False, indent=2))
    else:
        print(render(checks))
    return 1 if any(item["status"] == FAIL for item in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())

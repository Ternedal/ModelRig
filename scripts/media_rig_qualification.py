"""Rig qualification harness for ModelRig media generation (#2296; image #2315, video #2316).

Runbook: #2296 (Claude rig qualification pack). Template: docs/qualification/media/wan21-t2v-1.3b.json.

Qualification only. It runs the real adapters in a separate process; it does not
enable anything in the appliance, opens no route and reaches no network. Every
output and report goes to --out, which must be on the verified media volume.

  image     load the diffusers profile, render one PNG, check the lease from a second
            process while loaded and after close()
  executor  the appliance path (G2b): submit one image job to a job DB on the media
            volume, start the real entry point `python -m app.media_executor_main`,
            and prove: job completed and published job-keyed to the gallery, a second
            executor for the same GPU exits 73, idle unload frees the GPU while the
            executor lives, and the lease is free after the executor is stopped.
            Then prompt retention (#2340) on this volume with this Python's SQLite:
            purged, and the prompt text is in neither the job DB nor its WAL nor
            the executor logs
  chatfirst G4, Anders' decision "chat first, media waits" (#2341), with a real Ollama
            model holding the VRAM: the job is re-queued instead of failing, nothing
            media stays on the GPU while it waits, Ollama keeps its model; then the
            operator unloads Ollama and the same job completes. With --expect-expiry
            nobody unloads Ollama and the job must fail gpu_unavailable after 10 min
  video     start the supervised ComfyUI, render one MP4, report cleanup; --hold keeps
            it loaded until the harness is killed (supervisor-kill test). With
            --expect-error a refusal at load() counts too (G3 pins: hash, lookup,
            version), and ComfyUI must then not be running
  lease     report whether the GPU lease and the resident lock are free right now
  pins      write the pinned Wan profiles (G3): hash the given model files, read
            ComfyUI's version from comfyui_version.py, and write wan21-t2v-qual,
            wan21-t2v-deadline, and the negative wan21-badhash / wan21-badver.
            With --profile-id it writes that one pinned profile instead, for
            --template and --task (e.g. the Wan 2.2 TI2V-5B image_to_video one).
            Every profile is parsed by the real validator before it is written
            video with --task image_to_video: --source-png (a PNG on the media volume) is
            the source image; ComfyUI's input folder must be empty again afterwards

Exit code 0 = every check in the report passed; 1 = a check failed; 2 = usage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path


WORKER_PATH = ""  # set from --repo in main()


def fail_usage(message: str) -> None:
    print(f"usage error: {message}", file=sys.stderr)
    raise SystemExit(2)


def parse_size(text: str) -> tuple[int, int]:
    try:
        width, height = (int(part) for part in text.lower().split("x"))
    except ValueError:
        fail_usage("--size must look like 832x480")
    return width, height


class Report:
    def __init__(self, mode: str, out: Path):
        self.data = {"mode": mode, "started": time.strftime("%Y-%m-%dT%H:%M:%S"), "checks": {}}
        self.out = out

    def check(self, name: str, ok: bool, detail: object = None) -> bool:
        self.data["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'ok  ' if ok else 'FAIL'} {name}" + (f": {detail}" if detail is not None else ""), flush=True)
        return ok

    def finish(self) -> int:
        passed = all(item["ok"] for item in self.data["checks"].values())
        self.data["result"] = "PASS" if passed else "FAIL"
        path = self.out / f"report-{self.data['mode']}-{time.strftime('%Y%m%d-%H%M%S')}.json"
        path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        print(f"{self.data['result']}: report {path}", flush=True)
        return 0 if passed else 1


class QualificationVolume:
    """Qualification-only stand-in for the production VerifiedMediaVolume (ChatGPT's).

    A path is accepted only if it resolves inside --volume-root and lives on the same
    volume as the root, and that volume is not the system volume. This proves the
    supervisor's checks are wired; it does not qualify the production verifier.
    """

    def __init__(self, root: str):
        from app.media_generation_contract import ArtifactSinkUnavailable
        self._unavailable = ArtifactSinkUnavailable
        self.root = Path(root).resolve(strict=True)
        system = (os.environ.get("SystemDrive", "C:") + "\\") if os.name == "nt" else "/"
        self.dev = os.stat(self.root).st_dev
        if self.dev == os.stat(system).st_dev:
            raise self._unavailable(f"{self.root} is on the system volume")

    def require(self, path: str) -> None:
        try:
            resolved = Path(path).resolve(strict=True)
        except OSError:
            raise self._unavailable("path missing") from None
        if resolved != self.root and self.root not in resolved.parents:
            raise self._unavailable("path is outside the media volume root")
        if os.stat(resolved).st_dev != self.dev:
            raise self._unavailable("path is on another volume")


def lease_state(gpu_uuid: str, lease_dir: str) -> str:
    """'busy' or 'free' as seen from ANOTHER process (the lease is per process)."""
    code = ("import sys; from app.gpu_lease import GpuBusy, acquire_gpu_lease\n"
            "try:\n    acquire_gpu_lease(sys.argv[1], lease_dir=sys.argv[2]).release(); print('free')\n"
            "except GpuBusy:\n    print('busy')\n")
    env = dict(os.environ, PYTHONPATH=WORKER_PATH)
    result = subprocess.run([sys.executable, "-c", code, gpu_uuid, lease_dir], capture_output=True, text=True,
                            timeout=60, env=env)
    return result.stdout.strip() or f"error: {result.stderr.strip()[-300:]}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def common(args) -> tuple[dict, str, str]:
    from app.gpu_lease import device_uuid_map, lease_dir_from_env, parse_cuda_device
    from app.media_generation_profiles import enabled_profiles, load_profile_dir
    profiles = enabled_profiles(load_profile_dir(args.profiles))
    if args.profile not in profiles:
        fail_usage(f"profile {args.profile} is not enabled (KALIV_MEDIA_PROFILES_ENABLED)")
    profile = profiles[args.profile]
    lease_dir = lease_dir_from_env()
    gpu_uuid = device_uuid_map().get(parse_cuda_device(args.device))
    if gpu_uuid is None:
        fail_usage(f"no GPU UUID configured for {args.device} (KALIV_GPU_DEVICE_UUIDS)")
    return profile, lease_dir, gpu_uuid


def run_image(args, report: Report) -> None:
    from app.diffusers_image_adapter import DiffusersImageAdapter
    from app.media_generation_contract import GenerationRequest
    profile, lease_dir, gpu_uuid = common(args)
    report.data.update(profile=profile.profile_id, gpu_uuid=gpu_uuid, model_id=profile.model_id,
                       revision=profile.revision)
    adapter = DiffusersImageAdapter(profile, device=args.device, lease_dir=lease_dir)
    started = time.monotonic()
    adapter.load()
    report.data["load_seconds"] = round(time.monotonic() - started, 1)
    report.check("lease busy for other processes while loaded", lease_state(gpu_uuid, lease_dir) == "busy")
    width, height = parse_size(args.size)
    request = GenerationRequest(profile_id=profile.profile_id, task="text_to_image", prompt=args.prompt,
                                width=width, height=height, steps=args.steps, seed=args.seed)
    started = time.monotonic()
    rendered = adapter.render(request)
    report.data["render_seconds"] = round(time.monotonic() - started, 1)
    target = Path(args.out) / f"image-{time.strftime('%Y%m%d-%H%M%S')}.png"
    target.write_bytes(rendered.data)
    report.check("PNG written to the media volume", rendered.data[:8] == b"\x89PNG\r\n\x1a\n",
                 {"path": str(target), "bytes": len(rendered.data), "sha256": sha256(target)})
    closed = adapter.close()
    report.check("close() proved GPU memory free and released the lease", closed is True)
    report.check("lease free for other processes after close", lease_state(gpu_uuid, lease_dir) == "free")


def run_video(args, report: Report) -> None:
    from app.comfy_supervisor import ComfyLaunch, ComfySupervisor
    from app.comfy_video_adapter import ComfyVideoAdapter
    from app.gpu_lease import resident_is_held
    from app.media_generation_contract import GenerationRequest
    profile, lease_dir, gpu_uuid = common(args)
    dirs = {name: str(Path(args.comfy_dirs) / name) for name in ("input", "output", "temp", "user")}
    for path in dirs.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    volume = QualificationVolume(args.volume_root)
    launch = ComfyLaunch(python_executable=args.comfy_python, main_py=args.comfy_main,
                         port=profile.backend_options.port, input_directory=dirs["input"],
                         output_directory=dirs["output"], temp_directory=dirs["temp"], user_directory=dirs["user"],
                         flags=("--disable-auto-launch", "--disable-metadata", "--disable-all-custom-nodes"))
    log = Path(args.out) / f"comfy-{time.strftime('%Y%m%d-%H%M%S')}.log"
    supervisor = ComfySupervisor(gpu_uuid=gpu_uuid, lease_dir=lease_dir, launch=launch, media_volume=volume,
                                 reserve_gib=profile.resources.reserve_gib,
                                 min_usable_gib=profile.resources.min_usable_gib,
                                 ready_timeout_s=args.ready_timeout, log_path=str(log),
                                 host_memory_gib=args.host_memory_gib)
    adapter = ComfyVideoAdapter(profile, supervisor=supervisor, template_dir=args.templates,
                                output_directory=dirs["output"])
    report.data.update(profile=profile.profile_id, gpu_uuid=gpu_uuid, template_sha256=profile.backend_options.template_sha256,
                       comfy_log=str(log), comfyui_version_pin=profile.backend_options.comfyui_version,
                       weight_pins=[pin.path for pin in profile.backend_options.weights])
    started = time.monotonic()
    try:
        adapter.load()
    except Exception as exc:  # G3: a pinned profile may be refused before or right after ComfyUI starts
        error = f"{type(exc).__name__}: {exc}"
        if not args.expect_error:
            raise
        report.check("load() refused with the expected error", args.expect_error in error, error)
        report.check("ComfyUI is not running after the refusal", not supervisor.running)
        report.check("resident lock free after the refusal", not resident_is_held(gpu_uuid, lease_dir=lease_dir))
        report.check("lease free for other processes after the refusal", lease_state(gpu_uuid, lease_dir) == "free")
        return
    report.data["start_seconds"] = round(time.monotonic() - started, 1)
    proc = getattr(supervisor, "_proc", None)
    report.data["pids"] = {"harness": os.getpid(), "comfyui": getattr(proc, "pid", None)}
    report.check("lease busy for other processes while ComfyUI runs", lease_state(gpu_uuid, lease_dir) == "busy")
    report.check("resident lock held by ComfyUI's own process", resident_is_held(gpu_uuid, lease_dir=lease_dir))
    if args.hold:
        report.finish()
        print(f"HOLDING: kill this harness (pid {os.getpid()}) to run the supervisor-kill test", flush=True)
        while True:
            time.sleep(3600)
    width, height = parse_size(args.size)
    source = None
    if args.task == "image_to_video":
        source = Path(args.source_png).read_bytes()
        report.data["source_png"] = {"path": args.source_png, "bytes": len(source), "sha256": hashlib.sha256(source).hexdigest()}
    request = GenerationRequest(profile_id=profile.profile_id, task=args.task, prompt=args.prompt,
                                width=width, height=height, steps=args.steps, seed=args.seed, frames=args.frames,
                                input_asset_id=hashlib.sha256(source).hexdigest()[:32] if source else None)
    target = Path(args.out) / f"video-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    started = time.monotonic()
    error = None
    try:
        with open(target, "wb") as sink:
            mime = adapter.render_to(request, sink, source_png=source) if source else adapter.render_to(request, sink)
    except Exception as exc:  # recorded by type and our own message; ComfyUI's text is never propagated
        error = f"{type(exc).__name__}: {exc}"
        mime = None
    report.data["render_seconds"] = round(time.monotonic() - started, 1)
    report.data["cleanup"] = adapter.last_cleanup
    if args.expect_error:
        report.check("render failed with the expected error", error is not None and args.expect_error in error, error)
        if target.exists() and target.stat().st_size == 0:
            target.unlink()
    else:
        report.check("render succeeded", error is None and mime == "video/mp4", error)
        if error is None:
            report.check("MP4 written to the media volume", target.stat().st_size > 0,
                         {"path": str(target), "bytes": target.stat().st_size, "sha256": sha256(target)})
    report.check("cleanup removed only this job's file and kept nothing it cannot prove",
                 not adapter.last_cleanup.get("failed") and not adapter.last_cleanup.get("kept_replaced"),
                 adapter.last_cleanup)
    if source is not None:
        staged = sorted(os.listdir(dirs["input"]))
        report.check("ComfyUI input folder is empty again (the staged source image was removed)", staged == [], staged)
    left = sorted(os.listdir(dirs["output"]))
    if args.expect_error:  # a write that lands after a timeout interrupt is a stated limit: recorded, not failed
        report.check("ComfyUI output root after the failed job (late writes are reported as untracked)", True, left)
    else:
        report.check("ComfyUI output root is empty after the job", left == [], left)
    closed = adapter.close()
    report.check("close(): ComfyUI exited and the lease was released", closed is True)
    report.check("resident lock free after close", not resident_is_held(gpu_uuid, lease_dir=lease_dir))
    report.check("lease free for other processes after close", lease_state(gpu_uuid, lease_dir) == "free")


def run_executor(args, report: Report) -> None:
    """R5b: the real entry point, as modelrig-supervisor starts it (one executor, one GPU)."""
    from app.image_job_store import ImageJobStore
    from app.media_gallery_catalog import list_gallery
    from app.media_gallery_store import ExternalMediaSink
    profile, lease_dir, gpu_uuid = common(args)
    if profile.modality != "image":
        fail_usage("executor mode qualifies the image path (video waits for the staged sink)")
    sink = ExternalMediaSink(args.media_root, args.volume_root)
    try:
        sink._root()  # the entry point checks the same thing first and would exit 75
    except Exception as exc:
        report.check("media volume and gallery root verified (ExternalMediaSink)", False, f"{type(exc).__name__}: {exc}")
        return
    report.check("media volume and gallery root verified (ExternalMediaSink)", True,
                 {"volume_root": args.volume_root, "media_root": args.media_root})
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = Path(args.out) / f"jobs-{stamp}.sqlite3"  # prompts stay on the media volume, removed with $Out
    env = dict(os.environ, PYTHONPATH=WORKER_PATH, PYTHONDONTWRITEBYTECODE="1", KALIV_MEDIA_EXECUTOR="1",
               KALIV_MEDIA_JOB_DB=str(db), KALIV_MEDIA_ROOT=args.media_root,
               KALIV_MEDIA_VOLUME_ROOT=args.volume_root, KALIV_MEDIA_PROFILE_DIR=args.profiles,
               KALIV_MEDIA_IDLE_UNLOAD_S=str(int(args.idle_unload)))
    command = [sys.executable, "-u", "-m", "app.media_executor_main", "--device", args.device]
    report.data.update(profile=profile.profile_id, gpu_uuid=gpu_uuid, job_db=str(db), command=command[1:])

    def start(name: str):
        log = open(Path(args.out) / f"executor-{name}-{stamp}.log", "wb")
        return subprocess.Popen(command, cwd=WORKER_PATH, env=env, stdout=log, stderr=subprocess.STDOUT), log

    store = ImageJobStore(str(db))
    width, height = parse_size(args.size)
    job = store.submit("qual", args.prompt, profile_id=profile.profile_id,
                       params={"width": width, "height": height, "steps": args.steps, "seed": args.seed})["job_id"]
    report.data["job_id"] = job
    first, first_log = start("first")
    report.data["pids"] = {"harness": os.getpid(), "executor": first.pid}
    try:
        deadline, row, saw_busy = time.monotonic() + args.timeout, None, False
        while time.monotonic() < deadline and first.poll() is None:
            row = store.get(job, "qual")
            if row["state"] in ("completed", "failed", "cancelled"):
                break
            saw_busy = saw_busy or lease_state(gpu_uuid, lease_dir) == "busy"
            time.sleep(2)
        row = store.get(job, "qual")
        resident = lease_state(gpu_uuid, lease_dir)  # within the idle window the model stays loaded
        report.check("the executor is still running after the job", first.poll() is None, first.poll())
        report.check("job completed through the real entry point", row["state"] == "completed",
                     {"state": row["state"], "error": row.get("error")})
        report.check("GPU lease busy for other processes while the model is resident", resident == "busy",
                     {"right_after_the_job": resident, "seen_busy_while_polling": saw_busy})
        expected = sink.job_asset_id(job)
        report.check("asset is job-keyed", row.get("asset_id") == expected, {"asset_id": row.get("asset_id"), "expected": expected})
        evidence = sink.inspect_job_asset(job)
        report.check("asset is a PNG on the media volume and indexed",
                     bool(evidence) and evidence["extension"] == ".png" and evidence["indexed"], evidence)
        listed = [item["id"] for item in list_gallery(args.media_root, verified_volume_root=args.volume_root)["items"]]
        report.check("the gallery lists it", expected in listed)
        second, second_log = start("second")
        try:
            code = second.wait(timeout=120)
        except subprocess.TimeoutExpired:
            second.kill()
            code = "still running after 120 s"
        second_log.close()
        report.check("a second executor for the same GPU exits 73 and touches nothing", code == 73, code)
        time.sleep(args.idle_unload + 20)
        report.check("idle unload freed the GPU while the executor lives",
                     first.poll() is None and lease_state(gpu_uuid, lease_dir) == "free",
                     {"executor_exit": first.poll(), "idle_unload_s": args.idle_unload})
    finally:
        stop(first)
        first_log.close()
    report.check("lease free for other processes after the executor stopped", lease_state(gpu_uuid, lease_dir) == "free")
    check_retention(store, db, args.prompt, Path(args.out).glob(f"executor-*-{stamp}.log"), report)


def stop(proc) -> None:
    if proc.poll() is None:
        proc.terminate()  # as the supervisor does on stop; Windows: TerminateProcess
        try:
            proc.wait(timeout=60)
        except subprocess.TimeoutExpired:
            proc.kill()


def check_retention(store, db: Path, prompt: str, logs, report: Report) -> None:
    """#2340 on the rig: this Python's SQLite on this volume. A window of 0 purges every finished job
    now; the 30-day default is the same code path with another cutoff."""
    import sqlite3
    needle = prompt.encode("utf-8")
    files = lambda: [p for p in (db, Path(str(db) + "-wal")) if p.exists()]
    report.data["sqlite_version"] = sqlite3.sqlite_version
    before = any(needle in p.read_bytes() for p in files())
    try:
        purged = store.purge_prompts(older_than_s=0)
    except Exception as exc:
        report.check("retention: purge_prompts ran (secure_delete supported, scrub paid)", False,
                     f"{type(exc).__name__}: {exc}")
        return
    report.check("retention: purge_prompts ran (secure_delete supported, scrub paid)", purged >= 1,
                 {"purged": purged, "prompt_was_in_the_file_before": before})
    left = [str(p) for p in files() if needle in p.read_bytes()]
    report.check("retention: the prompt text is in neither the job DB nor its WAL", left == [], left)
    in_logs = [str(p) for p in logs if needle in p.read_bytes()]
    report.check("the prompt text is in no executor log", in_logs == [], in_logs)


def free_vram_mib(gpu_uuid: str):
    """Evidence only: nvidia-smi's free memory for this GPU, or None if it cannot be read."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=uuid,memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in out.splitlines():
        uuid, _, free = line.partition(",")
        if uuid.strip() == gpu_uuid:
            try:
                return int(free.strip())
            except ValueError:
                return None
    return None


def ollama_ps():
    """Evidence only: `ollama ps` output, or None if Ollama's CLI is not there."""
    try:
        return subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_chatfirst(args, report: Report) -> None:
    """R12: G4 with a real Ollama model holding the VRAM (the operator loads it before the run)."""
    from app.image_job_store import ImageJobStore
    from app.media_gallery_store import ExternalMediaSink
    profile, lease_dir, gpu_uuid = common(args)
    if profile.modality != "image":
        fail_usage("chatfirst qualifies the image path")
    sink = ExternalMediaSink(args.media_root, args.volume_root)
    sink._root()
    need_mib = int((profile.resources.min_usable_gib + profile.resources.reserve_gib) * 1024)
    free = free_vram_mib(gpu_uuid)
    ps = ollama_ps()
    report.data.update(profile=profile.profile_id, gpu_uuid=gpu_uuid, free_vram_mib_before=free,
                       profile_needs_mib=need_mib, ollama_ps_before=ps)
    report.check("precondition: free VRAM is below what the profile needs (Ollama holds it)",
                 free is None or free < need_mib, {"free_mib": free, "needs_mib": need_mib})
    if args.ollama_model:
        report.check("precondition: Ollama has the model loaded", ps is not None and args.ollama_model in ps, ps)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    db = Path(args.out) / f"jobs-chatfirst-{stamp}.sqlite3"
    env = dict(os.environ, PYTHONPATH=WORKER_PATH, PYTHONDONTWRITEBYTECODE="1", KALIV_MEDIA_EXECUTOR="1",
               KALIV_MEDIA_JOB_DB=str(db), KALIV_MEDIA_ROOT=args.media_root,
               KALIV_MEDIA_VOLUME_ROOT=args.volume_root, KALIV_MEDIA_PROFILE_DIR=args.profiles,
               KALIV_MEDIA_IDLE_UNLOAD_S=str(int(args.idle_unload)))
    store = ImageJobStore(str(db))
    width, height = parse_size(args.size)
    job = store.submit("qual", args.prompt, profile_id=profile.profile_id,
                       params={"width": width, "height": height, "steps": args.steps, "seed": args.seed})["job_id"]
    report.data["job_id"] = job
    log = open(Path(args.out) / f"executor-chatfirst-{stamp}.log", "wb")
    executor = subprocess.Popen([sys.executable, "-u", "-m", "app.media_executor_main", "--device", args.device],
                                cwd=WORKER_PATH, env=env, stdout=log, stderr=subprocess.STDOUT)
    report.data["pids"] = {"harness": os.getpid(), "executor": executor.pid}
    try:
        deadline, row = time.monotonic() + 180, None
        while time.monotonic() < deadline and executor.poll() is None:
            row = store.get(job, "qual")
            if row.get("deferred_since") is not None or row["state"] in ("completed", "failed", "cancelled"):
                break
            time.sleep(1)
        row = store.get(job, "qual")
        report.check("the job was put back in the queue, not failed",
                     row["state"] in ("queued", "running") and row.get("deferred_since") is not None
                     and row.get("error") is None,
                     {"state": row["state"], "error": row.get("error"), "deferred_since": row.get("deferred_since")})
        report.check("the executor keeps running while the job waits", executor.poll() is None, executor.poll())
        report.check("nothing media holds the GPU while the job waits", lease_state(gpu_uuid, lease_dir) == "free")
        if args.ollama_model:
            ps = ollama_ps()
            report.check("Ollama still has its model (media never touched it)",
                         ps is not None and args.ollama_model in ps, ps)
        if args.expect_expiry:
            limit = time.monotonic() + 600 + 120
            while time.monotonic() < limit and store.get(job, "qual")["state"] != "failed":
                time.sleep(5)
            row = store.get(job, "qual")
            report.check("after 10 minutes of waiting the job failed gpu_unavailable",
                         (row["state"], row.get("error")) == ("failed", "gpu_unavailable"),
                         {"state": row["state"], "error": row.get("error")})
        else:
            unload = f"ollama stop {args.ollama_model}" if args.ollama_model else "unload the Ollama model"
            print(f"ACTION: within {int(args.wait_timeout)} s, in another window: {unload}", flush=True)
            limit = time.monotonic() + args.wait_timeout
            while time.monotonic() < limit and store.get(job, "qual")["state"] not in ("completed", "failed", "cancelled"):
                time.sleep(2)
            row = store.get(job, "qual")
            report.check("once VRAM was free the same job completed",
                         row["state"] == "completed" and row.get("asset_id") == sink.job_asset_id(job),
                         {"state": row["state"], "error": row.get("error"), "asset_id": row.get("asset_id"),
                          "free_vram_mib_after": free_vram_mib(gpu_uuid)})
    finally:
        stop(executor)
        log.close()
    report.check("lease free for other processes after the executor stopped", lease_state(gpu_uuid, lease_dir) == "free")


def run_pins(args, report: Report) -> None:
    import re
    from app.media_generation_profiles import parse_profile
    main_py = Path(args.comfy_main)
    models = main_py.parent / "models"  # where ComfyUI reads them (ComfyLaunch.resolved_models_directory)
    text = (main_py.parent / "comfyui_version.py").read_text(encoding="utf-8")
    found = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not found:
        report.check("ComfyUI version read from comfyui_version.py", False)
        return
    version = found.group(1)
    report.check("ComfyUI version read from comfyui_version.py", True, version)
    pins = []
    for rel in args.pin:
        path = models / rel
        pins.append({"path": rel, "sha256": sha256(path), "bytes": path.stat().st_size})
    report.check("pinned files hashed", True, pins)
    template = Path(args.templates) / (args.template or "wan21-t2v-1.3b.json")
    template_sha = sha256(template)
    if args.profile_id:  # one pinned profile for --template / --task
        width, height = parse_size(args.size)
        data = {"schema": "kaliv-media-profile/v1", "profile_id": args.profile_id, "modality": "video",
                "tasks": [args.task], "backend": "comfyui", "pipeline": None,
                "model_id": args.model_id, "revision": args.revision,
                "limits": {"max_prompt_chars": 500, "sizes": [[width, height]], "max_steps": 30,
                           "max_frames": args.max_frames},
                "outputs": ["video/mp4"],
                "resources": {"min_usable_gib": 8, "reserve_gib": 1.5, "devices": [args.device], "cpu_offload": False},
                "qualification": "candidate", "license": "apache-2.0",
                "backend_options": {"template_name": template.name, "template_sha256": template_sha, "fps": args.fps,
                                    "max_render_seconds": 3600, "max_output_bytes": 536870912, "port": 18190,
                                    "comfyui_version": version, "weights": pins}}
        parse_profile(data)  # the real validator, including the pinned template binding at load time
        (Path(args.profiles) / f"{args.profile_id}.json").write_text(json.dumps(data, indent=1), encoding="ascii")
        report.check("profile written and accepted by parse_profile", True, args.profile_id)
        report.data.update(comfyui_version=version, template_sha256=template_sha, revision=args.revision,
                           task=args.task)
        return

    def profile(profile_id: str, *, seconds: int, port: int, version_pin: str, weights: list) -> dict:
        return {"schema": "kaliv-media-profile/v1", "profile_id": profile_id, "modality": "video",
                "tasks": ["text_to_video"], "backend": "comfyui", "pipeline": None,
                "model_id": "Comfy-Org/Wan_2.1_ComfyUI_repackaged", "revision": args.revision,
                "limits": {"max_prompt_chars": 500, "sizes": [[832, 480]], "max_steps": 30, "max_frames": 81},
                "outputs": ["video/mp4"],
                "resources": {"min_usable_gib": 8, "reserve_gib": 1.5, "devices": [args.device], "cpu_offload": False},
                "qualification": "candidate", "license": "apache-2.0",
                "backend_options": {"template_name": template.name, "template_sha256": template_sha, "fps": 16,
                                    "max_render_seconds": seconds, "max_output_bytes": 536870912, "port": port,
                                    "comfyui_version": version_pin, "weights": weights}}
    flipped = [dict(pins[0], sha256=("1" if pins[0]["sha256"][0] == "0" else "0") + pins[0]["sha256"][1:])] + pins[1:]
    profiles = {"wan21-t2v-qual": profile("wan21-t2v-qual", seconds=1800, port=18188, version_pin=version, weights=pins),
                "wan21-t2v-deadline": profile("wan21-t2v-deadline", seconds=10, port=18189, version_pin=version, weights=pins),
                "wan21-badhash": profile("wan21-badhash", seconds=1800, port=18188, version_pin=version, weights=flipped),
                "wan21-badver": profile("wan21-badver", seconds=1800, port=18188, version_pin="0.0.0-not-this", weights=pins)}
    for profile_id, data in profiles.items():
        parse_profile(data)  # the real validator; raises before anything is written
        (Path(args.profiles) / f"{profile_id}.json").write_text(json.dumps(data, indent=1), encoding="ascii")
    report.check("profiles written and accepted by parse_profile", True, sorted(profiles))
    report.data.update(comfyui_version=version, template_sha256=template_sha, revision=args.revision)


def run_lease(args, report: Report) -> None:
    from app.gpu_lease import lease_dir_from_env, normalize_gpu_uuid, resident_is_held
    gpu_uuid = normalize_gpu_uuid(args.gpu_uuid)
    lease_dir = lease_dir_from_env()
    report.data["gpu_uuid"] = gpu_uuid
    report.check("resident lock free", not resident_is_held(gpu_uuid, lease_dir=lease_dir))
    report.check("main lease free", lease_state(gpu_uuid, lease_dir) == "free")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("image", "executor", "chatfirst", "video", "lease", "pins"))
    parser.add_argument("--repo", required=True, help="ModelRig worktree at the qualified head")
    parser.add_argument("--out", required=True, help="report/output folder on the media volume")
    parser.add_argument("--profiles", help="operator profile folder")
    parser.add_argument("--profile", help="profile id")
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--prompt", default="a red bicycle leaning against a brick wall, overcast daylight")
    parser.add_argument("--size", default="1024x1024")
    parser.add_argument("--steps", type=int, default=20)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--frames", type=int, default=33)
    parser.add_argument("--task", default="text_to_video", choices=("text_to_video", "image_to_video"),
                        help="video/pins: the task (image_to_video needs --source-png for video)")
    parser.add_argument("--source-png", help="video: the source PNG for image_to_video (on the media volume)")
    parser.add_argument("--template", help="pins: template file name in --templates (default wan21-t2v-1.3b.json)")
    parser.add_argument("--profile-id", help="pins: write only this one pinned profile")
    parser.add_argument("--model-id", default="Comfy-Org/Wan_2.1_ComfyUI_repackaged", help="pins: Hugging Face repo")
    parser.add_argument("--fps", type=int, default=16, help="pins --profile-id: frames per second")
    parser.add_argument("--max-frames", type=int, default=81, help="pins --profile-id: limit")
    parser.add_argument("--comfy-python")
    parser.add_argument("--comfy-main")
    parser.add_argument("--comfy-dirs", help="folder on the media volume for ComfyUI input/output/temp/user")
    parser.add_argument("--templates", help="folder with the pinned workflow template")
    parser.add_argument("--volume-root", help="root of the media volume (qualification verifier)")
    parser.add_argument("--ready-timeout", type=float, default=300.0)
    parser.add_argument("--host-memory-gib", type=float, default=32.0)
    parser.add_argument("--hold", action="store_true")
    parser.add_argument("--expect-error", help="the run must fail with an error containing this text")
    parser.add_argument("--gpu-uuid")
    parser.add_argument("--media-root", help="executor: gallery folder on the media volume (KALIV_MEDIA_ROOT)")
    parser.add_argument("--idle-unload", type=float, default=30.0, help="executor: KALIV_MEDIA_IDLE_UNLOAD_S")
    parser.add_argument("--timeout", type=float, default=900.0, help="executor: seconds to wait for the job")
    parser.add_argument("--pin", action="append", default=[], help="pins: a model file relative to models/ (repeat)")
    parser.add_argument("--revision", help="pins: the Hugging Face revision of the repackaged weights")
    parser.add_argument("--ollama-model", help="chatfirst: the Ollama model holding the VRAM (checked with `ollama ps`)")
    parser.add_argument("--wait-timeout", type=float, default=540.0,
                        help="chatfirst: seconds to wait for the operator to unload Ollama (below the 600 s expiry)")
    parser.add_argument("--expect-expiry", action="store_true", help="chatfirst: nobody unloads Ollama; expect gpu_unavailable")
    args = parser.parse_args(argv)
    global WORKER_PATH
    WORKER_PATH = str(Path(args.repo, "worker").resolve())
    sys.path.insert(0, WORKER_PATH)
    out = Path(args.out)
    if not out.is_dir():
        fail_usage("--out must be an existing folder on the media volume")
    if args.mode in ("image", "executor", "chatfirst", "video") and not (args.profiles and args.profile):
        fail_usage("--profiles and --profile are required")
    if args.mode == "video" and not all((args.comfy_python, args.comfy_main, args.comfy_dirs, args.templates,
                                         args.volume_root)):
        fail_usage("video needs --comfy-python --comfy-main --comfy-dirs --templates --volume-root")
    if args.mode in ("executor", "chatfirst") and not (args.volume_root and args.media_root):
        fail_usage(f"{args.mode} needs --volume-root (the mounted volume, e.g. E:\\) and --media-root")
    if args.mode == "pins" and not (args.comfy_main and args.templates and args.profiles and args.pin
                                    and args.revision):
        fail_usage("pins needs --comfy-main --templates --profiles --pin (repeat) --revision")
    if args.mode == "video" and args.task == "image_to_video" and not args.source_png:
        fail_usage("video --task image_to_video needs --source-png")
    if args.mode == "lease" and not args.gpu_uuid:
        fail_usage("lease needs --gpu-uuid")
    from app.media_generation_contract import ArtifactSinkUnavailable
    try:  # never write outputs or reports to the internal disk
        QualificationVolume(args.volume_root or args.out).require(str(out))
    except ArtifactSinkUnavailable as exc:
        print(f"REFUSED: {exc}; nothing was written", file=sys.stderr)
        return 1
    report = Report(args.mode, out)
    head = subprocess.run(["git", "-C", args.repo, "rev-parse", "HEAD"], capture_output=True, text=True)
    report.data["head"] = head.stdout.strip() or None
    try:
        {"image": run_image, "executor": run_executor, "chatfirst": run_chatfirst, "video": run_video,
         "lease": run_lease, "pins": run_pins}[args.mode](args, report)
    except SystemExit:
        raise
    except Exception as exc:
        report.check("harness ran to completion", False, f"{type(exc).__name__}: {exc}")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

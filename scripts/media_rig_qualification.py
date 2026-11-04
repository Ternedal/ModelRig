"""Rig qualification harness for ModelRig media generation (#2296; image #2315, video #2316).

Runbook: #2296 (Claude rig qualification pack). Template: docs/qualification/media/wan21-t2v-1.3b.json.

Qualification only. It runs the real adapters in a separate process; it does not
enable anything in the appliance, opens no route and reaches no network. Every
output and report goes to --out, which must be on the verified media volume.

  image  load the diffusers profile, render one PNG, check the lease from a second
         process while loaded and after close()
  video  start the supervised ComfyUI, render one MP4, report cleanup; --hold keeps
         it loaded until the harness is killed (supervisor-kill test)
  lease  report whether the GPU lease and the resident lock are free right now

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
                       comfy_log=str(log))
    started = time.monotonic()
    adapter.load()
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
    request = GenerationRequest(profile_id=profile.profile_id, task="text_to_video", prompt=args.prompt,
                                width=width, height=height, steps=args.steps, seed=args.seed, frames=args.frames)
    target = Path(args.out) / f"video-{time.strftime('%Y%m%d-%H%M%S')}.mp4"
    started = time.monotonic()
    error = None
    try:
        with open(target, "wb") as sink:
            mime = adapter.render_to(request, sink)
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
    left = sorted(os.listdir(dirs["output"]))
    if args.expect_error:  # a write that lands after a timeout interrupt is a stated limit: recorded, not failed
        report.check("ComfyUI output root after the failed job (late writes are reported as untracked)", True, left)
    else:
        report.check("ComfyUI output root is empty after the job", left == [], left)
    closed = adapter.close()
    report.check("close(): ComfyUI exited and the lease was released", closed is True)
    report.check("resident lock free after close", not resident_is_held(gpu_uuid, lease_dir=lease_dir))
    report.check("lease free for other processes after close", lease_state(gpu_uuid, lease_dir) == "free")


def run_lease(args, report: Report) -> None:
    from app.gpu_lease import lease_dir_from_env, normalize_gpu_uuid, resident_is_held
    gpu_uuid = normalize_gpu_uuid(args.gpu_uuid)
    lease_dir = lease_dir_from_env()
    report.data["gpu_uuid"] = gpu_uuid
    report.check("resident lock free", not resident_is_held(gpu_uuid, lease_dir=lease_dir))
    report.check("main lease free", lease_state(gpu_uuid, lease_dir) == "free")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", choices=("image", "video", "lease"))
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
    args = parser.parse_args(argv)
    global WORKER_PATH
    WORKER_PATH = str(Path(args.repo, "worker").resolve())
    sys.path.insert(0, WORKER_PATH)
    out = Path(args.out)
    if not out.is_dir():
        fail_usage("--out must be an existing folder on the media volume")
    if args.mode in ("image", "video") and not (args.profiles and args.profile):
        fail_usage("--profiles and --profile are required")
    if args.mode == "video" and not all((args.comfy_python, args.comfy_main, args.comfy_dirs, args.templates,
                                         args.volume_root)):
        fail_usage("video needs --comfy-python --comfy-main --comfy-dirs --templates --volume-root")
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
        {"image": run_image, "video": run_video, "lease": run_lease}[args.mode](args, report)
    except SystemExit:
        raise
    except Exception as exc:
        report.check("harness ran to completion", False, f"{type(exc).__name__}: {exc}")
    return report.finish()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

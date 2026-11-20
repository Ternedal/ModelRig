#!/usr/bin/env python3
"""The chat-to-picture chain in one piece (#2419), without a GPU or a model.

Every link has its own suite; this one proves they fit: what ``image_generate``
stores is what the *real* executor accepts and renders, the finished job is the
installation owner's (the owner the gateway reads status and media for), and
"animate the latest picture" then names exactly that asset.

1. tool -> store: one queued job for OWNER, params the executor's own request
   builder accepts (it refuses unknown keys).
2. store -> executor (real MediaExecutor, fake adapter, real GPU lease): the
   job completes; the adapter got the tool's prompt and size.
3. status as the device sees it (job_view): completed with the asset; the
   asset is owned by OWNER, which is the gateway's mediaInstallationOwner.
4. next turn: ``video_generate(source_image_job_id="latest")`` queues
   image_to_video with that asset as input, and the executor's request builder
   accepts those params too.

Run: PYTHONPATH=worker python3 tests/worker_media_chat_chain.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("KALIV_TOOLS_DIR", tempfile.mkdtemp())
os.environ.setdefault("KALIV_AUDIT_DB", os.path.join(tempfile.mkdtemp(), "audit.db"))

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT / "worker", ROOT / "tests", ROOT / "tests" / "support"):
    sys.path.insert(0, str(extra))

from app import image_generate_tool as igt  # noqa: E402
from app import video_generate_tool as vgt  # noqa: E402
from app.image_generate_tool import parse_job_reference  # noqa: E402
from app.image_job_store import ImageJobStore  # noqa: E402
from app.media_executor import MediaExecutor  # noqa: E402
from app.media_generation_profiles import parse_profile  # noqa: E402
from app.media_job_api import OWNER, MediaJobService, job_view  # noqa: E402
from source_code import code_of  # noqa: E402
from worker_media_executor import GPU_A, Clock, FakeImageAdapter, MemorySink  # noqa: E402
from worker_media_generation_profiles import image_profile, video_profile  # noqa: E402

passed = failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


tmp = tempfile.mkdtemp(prefix="kaliv-chain-")
lease_dir = os.path.join(tmp, "lease")
os.mkdir(lease_dir, 0o700)
store = ImageJobStore(os.path.join(tmp, "jobs.sqlite3"))
# Lists image_to_image too, as a real SDXL profile may: alphabetically it comes before text_to_image.
IMG = parse_profile(image_profile(profile_id="sdxl-a", tasks=["text_to_image", "image_to_image"], resources={"min_usable_gib": 8, "reserve_gib": 2,
                                                                   "devices": ["cuda:0"], "cpu_offload": False}))
I2V = parse_profile(video_profile(profile_id="wan-i2v", tasks=["image_to_video"]))
service = MediaJobService(store, {p.profile_id: p for p in (IMG, I2V)}, "s" * 40, video_enabled=True)
sink = MemorySink()
FakeImageAdapter.rendered.clear()
executor = MediaExecutor(store, gpu_uuid=GPU_A, profiles={IMG.profile_id: IMG},
                         adapter_factory=lambda p: FakeImageAdapter(p, lease_dir=lease_dir, gpu_uuid=GPU_A),
                         lease_dir=lease_dir, image_sink=sink, idle_unload_s=60, clock=Clock())
PROMPT = "a red bicycle by a lake, photo, 35mm"
try:
    print("== 1. tool -> store ==")
    text = igt._run_image_generate({"prompt": PROMPT, "width": 1024, "height": 1024, "seed": 7},
                                   service_getter=lambda: service, env={})
    ref = parse_job_reference(text)
    check(ref is not None and ref["kind"] == "image" and ref["profile_id"] == "sdxl-a", "the tool queued one image job")
    row = store.get(ref["job_id"], OWNER) if ref else None
    check(row is not None and row["state"] == "queued" and row["prompt"] == PROMPT, "it is the installation owner's, queued")
    params = json.loads(row["params"])
    check(params.get("width") == 1024 and params.get("seed") == 7, f"the size and seed are stored: {sorted(params)}")
    check(params.get("task") == "text_to_image",
          "and the resolved task: without it the executor would take the profile's alphabetically first task")
    request = executor._request(row, IMG)
    check(request.task == "text_to_image" and request.prompt == PROMPT and request.width == 1024,
          "the executor's own request builder accepts what the tool stored")

    print("== 2. store -> executor ==")
    executor.start()
    check(executor.step() == "completed", "the real executor renders the tool's job")
    check(FakeImageAdapter.rendered == [PROMPT], "the adapter got the tool's prompt, once")

    print("== 3. as the device sees it ==")
    done = store.get(ref["job_id"], OWNER)
    view = job_view(done)
    check(view["state"] == "completed" and view["asset_id"] in sink.assets, "status says completed and names the published asset")
    check(view.get("asset_url") == "/api/v1/media/" + view["asset_id"], "with the gallery path the clients compare against")
    check("prompt" not in view, "and without the prompt")
    check(store.owns_completed_asset(OWNER, view["asset_id"]), "the asset is the installation owner's")
    gateway = code_of(ROOT / "backend" / "internal" / "httpapi" / "media_contract.go")
    check(f'mediaInstallationOwner = "{OWNER}"' in gateway,
          "which is the owner the gateway reads job status and media for")

    print("== 4. the next turn animates it ==")
    text = vgt._run_video_generate({"prompt": "the bicycle rolls slowly forward", "source_image_job_id": "latest"},
                                   service_getter=lambda: service, env={})
    clip = parse_job_reference(text)
    check(clip is not None and clip["kind"] == "video" and clip["profile_id"] == "wan-i2v", "'latest' queued a clip on the i2v profile")
    clip_row = store.get(clip["job_id"], OWNER) if clip else None
    clip_params = json.loads(clip_row["params"]) if clip_row else {}
    check(clip_params.get("task") == "image_to_video" and clip_params.get("input_asset_id") == view["asset_id"],
          "its source is exactly the picture the executor just published")
    video_executor = MediaExecutor.__new__(MediaExecutor)  # only the request builder: no GPU, no ComfyUI
    request = MediaExecutor._request(video_executor, clip_row, I2V)
    check(request.task == "image_to_video" and request.input_asset_id == view["asset_id"],
          "and the executor's request builder accepts the clip's params too")
finally:
    if executor.adapter is not None:
        try:
            executor.adapter.close()
        except Exception:  # noqa: BLE001
            pass
    executor.release_lock()
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n===== MEDIA CHAT CHAIN: {passed} passed, {failed} failed =====")
sys.exit(1 if failed else 0)

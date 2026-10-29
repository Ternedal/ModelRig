# Video generation (ComfyUI) — slice 2 of #2296

**Status:** default-off and not wired into the worker. Nothing has been proven on the rig.
**Ownership (6490545753):**
- Claude owns the supervisor, the adapter, the template binding and the profiles.
- ChatGPT owns the storage side (`StagedFileArtifactSink`), the gallery and the routes.

Design: #2296 6493077060. Prototype findings: 6493971744. Resident lock: 6495721654 and 6496114257. Seam: 6494148463.

## Flow

```
profile (kaliv-media-profile/v1, backend=comfyui, backend_options pin template SHA-256)
  └─ ComfyVideoAdapter.load()
       ├─ read the template once, check SHA-256, parse the same bytes
       └─ ComfySupervisor.start()
            ├─ validate argv (allowlisted flags, absolute non-symlink dirs, port 1024..65535)
            ├─ media_volume.require(dir) for input/output/temp/user: all on the verified external volume
            ├─ acquire_gpu_lease(UUID)          main lease; refuses while a resident lock is held
            ├─ refuse if the port already answers
            ├─ spawn: comfy_resident_launcher -> runpy(main.py) in ComfyUI's own process
            │     env: CUDA_VISIBLE_DEVICES=<UUID>, offline vars, a fresh token; nothing else from the caller
            │     POSIX: pass_fds(main lease); Windows: Job Object (KILL_ON_JOB_CLOSE, host-memory limit)
            └─ ready = child alive ∧ resident lock held ∧ proof{token,pid} matches ∧ /system_stats VRAM budget
  └─ per job: with sink.staged(".mp4") as out:
       ├─ adapter.render_to(request, out)
       │     job slot (one job per ComfyUI; a concurrent second job is refused, never queued)
       │     -> media volume re-check -> validate_request -> VRAM re-check -> empty queue -> bind slots -> /prompt
       │     -> /history until the profile deadline (interrupt on timeout)
       │     -> media volume re-check -> exactly one new .mp4: not a symlink, settled, unchanged while copied, ftyp, size cap
       │     -> written into `out` (the adapter never sees a path) -> ComfyUI's copy removed
       └─ asset_id = sink.adopt(out, "video/mp4")       storage side (ChatGPT)
  └─ close(): interrupt -> terminate -> kill; the lease is released only after ComfyUI has exited
```

## What keeps the GPU from being shared by mistake

| Mechanism | Covers | Does not cover |
|---|---|---|
| Main lease (`<UUID>.lock`) | Cooperating generators in other processes | Ollama, WSL2 and anything else that does not take it |
| Resident lock (`<UUID>.resident.lock`), held by ComfyUI's own process | A crashed or killed supervisor; an orphaned ComfyUI, on POSIX and Windows | The short window inside ComfyUI's own process teardown on Windows (lock handle closed before the driver frees VRAM) |
| Proof `{token, pid}` written after the lock | A stray ComfyUI or another executor pretending to be ours | Hostile code running as the same OS user (it can read the child's environment) |
| `CUDA_VISIBLE_DEVICES=<UUID>` | ComfyUI seeing other GPUs | Whether the pinned ComfyUI version leaves it alone (rig check) |
| VRAM admission (`/system_stats`), before start and before every job | Memory taken by processes outside the lease | Proof of exclusive ownership; it is only a budget check |
| Job slot (non-blocking lock in the supervisor, held from admission to cleanup) | Two jobs racing past the empty-queue check in one process | Other processes; those are blocked by the leases |

## Media never on the internal disk

ComfyUI writes the full MP4 into its own `output_directory` before the adapter copies it into the sink's handle. So the supervisor requires a `VerifiedMediaVolume` (ChatGPT's external-mount verifier; there is no default) and calls `require()` on ComfyUI's input/output/temp/user directories:
- before ComfyUI starts;
- before every submit;
- again before the copy.

A missing, unmounted or replaced volume raises `ArtifactSinkUnavailable`. That is fatal, with no fallback, and nothing is handed to the sink.

`pass_fds` (POSIX) and the resident lock each keep the GPU busy after a supervisor SIGKILL on their own. Both are kept as defence in depth.

## Template rules

- The template is operator-installed API-format JSON, and the profile pins its SHA-256.
- Seven value slots: `__KALIV_VIDEO_{PROMPT,WIDTH,HEIGHT,FPS,FRAMES,STEPS,SEED}__`.
  - Each must appear exactly once, as a whole input value, under allowlisted input names.
  - A marker anywhere else refuses the template: inside a longer string, in a list, as an input name, as a class or in `_meta`.
- A prompt can never become graph structure.

## Launch flags

- Always: `--listen 127.0.0.1`.
- Allowed: `--disable-auto-launch`, `--disable-metadata` and `--disable-all-custom-nodes`. `--disable-metadata` keeps the prompt and workflow out of MP4s that the gallery later shares.
- Refused: everything else (`--enable-cors-header`, `--enable-manager`, another `--listen`, …).

## Must be proven on the rig before any activation

1. The pinned ComfyUI runs under `runpy`: argv, `sys.path` and `__file__` as if started directly.
2. It leaves `CUDA_VISIBLE_DEVICES=<UUID>` alone when `--cuda-device` is omitted.
3. Core nodes produce MP4 with `--disable-all-custom-nodes`. If not, use an allowlist of custom nodes with pinned commits.
4. `/system_stats` fields on the pinned version.
5. Windows: Job Object kill-on-close and the resident lock's lifetime. `tests/support/windows_resident_lock_contract.py` runs on the Windows runner; the rig is separate.
6. Wan VRAM fit and render time on the 3060s, and GPU UUID mapping on the dual-GPU rig.
7. Outbound network from the ComfyUI backend. `--offline` restricts only the frontend, so this needs a firewall rule. That is §2 (external data transfer), Anders' decision.
8. WSL/native mixed topology stays **disabled**. Lock interoperability across that boundary is unproven.

## Tests (no GPU, no ComfyUI)

A fake ComfyUI (`tests/support/fake_comfyui/main.py`) runs as a real child process under the real launcher and supervisor. Suites:

- `worker_comfy_supervisor.py`
- `worker_comfy_resident_launcher.py` (also runs the Windows contract on POSIX)
- `worker_comfy_video_adapter.py`
- `worker_staged_sink_conformance.py`: the storage seam, as a mixin that ChatGPT's sink can be run against
- `workflow_media_generation_boundary.py`:
  - only the supervisor may use `subprocess` + `http.client`;
  - only the launcher may use `runpy`, and only once, on the validated `main.py`;
  - the launcher imports nothing from ModelRig;
  - no module-level torch.

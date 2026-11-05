# Video generation (ComfyUI) — slice 2 of #2296

**Status:** default-off and not wired into the worker. Nothing has been proven on the rig.
**Ownership (6490545753):**
- Claude owns the supervisor, the adapter, the template binding and the profiles.
- ChatGPT owns the storage side (`ExternalMediaSink`, the gallery index), the gallery and the routes.
- The staged video sink (`ExternalStagedVideoSink`) is Claude's by Anders' work order 6667100037. It composes ChatGPT's storage code without changing it (6667142387).

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
            │     env: CUDA_VISIBLE_DEVICES=<UUID>, offline vars, a fresh token, TEMP/TMP/TMPDIR = ComfyUI's temp
            │          dir on the verified volume (never the caller's temp, which is on the internal disk); PATH,
            │          SYSTEMROOT, HOME, USERPROFILE, LANG, LC_ALL from the caller; nothing else
            │     POSIX: pass_fds(main lease); Windows: Job Object (KILL_ON_JOB_CLOSE, host-memory limit)
            └─ ready = child alive ∧ resident lock held ∧ proof{token,pid} matches ∧ /system_stats VRAM budget
  └─ per job: with sink.staged(".mp4") as out:
       ├─ adapter.render_to(request, out)
       │     job slot (one job per ComfyUI; a concurrent second job is refused, never queued)
       │     -> media volume re-check -> validate_request -> VRAM re-check -> empty queue -> bind slots -> /prompt
       │     -> /history until the profile deadline (interrupt on timeout)
       │     -> media volume re-check -> exactly one new .mp4: not a symlink, settled, unchanged while copied, ftyp, size cap
       │     -> written into `out` (the adapter never sees a path)
       │     finally: remove exactly the files ComfyUI's history names for THIS prompt (output root, new since
       │              the snapshot, same (st_dev, st_ino) as recorded); see "Output cleanup" below.
       │              Cleanup never raises, so it cannot mask the render's own result or error
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

## Output cleanup

Neither POSIX nor Windows can "unlink this name only if it is still inode X" atomically. A plain stat followed by an unlink always leaves a window where a different file could take the name. Cleanup therefore never unlinks by name. For each file the job owns:

1. **Capture.** Rename it to a random `.kaliv-cleanup-<hex>` name in the same directory. This is atomic, so it captures exactly the file that carried the name at that instant.
2. **Check.** Stat the captured file. If its `(st_dev, st_ino)` matches what was recorded when the history arrived, delete it.
3. **Restore.** Anything else is put back under its name without overwriting (POSIX: `link` plus unlink of the quarantine name; Windows: `rename`). Both refuse an existing target. If the name has been taken again meanwhile, the file stays under its quarantine name and is reported there.

A replaced file is therefore never deleted, on either code path:
- POSIX uses one directory fd.
- Windows has no `dir_fd` and works by path.

Other rules:
- **Unprovable identity.** A file whose filesystem reports no file id (`st_ino == 0`) is never owned; it is kept and reported.
- **Volume not verified.** If the volume cannot be verified at cleanup time, nothing is touched.
- **Files left in place.** A file still open on Windows (sharing violation) is left in place. So is a captured file whose delete fails; it is reported under its quarantine name.
- **Reporting.** Every outcome lands in `last_cleanup` (`removed`, `kept_replaced`, `untracked`, `failed`) and is logged. File names only, never a prompt.

Stated limits (outside the threat model):
- An actor who learns the random quarantine name within the microseconds between capture and check.
- An actor who deletes the job's file and creates another under the same generated name that gets the same inode number.

An actor with write access to the volume could delete files directly anyway.

`tests/support/windows_cleanup_identity_contract.py` runs on the Windows runner (NTFS) and on POSIX. It proves that:
- a rename keeps the file id;
- a swapped-in file survives;
- the restore never overwrites;
- an open file is not captured.

## Staged video sink (`ExternalStagedVideoSink`, not wired)

`worker/app/media_staged_video_sink.py` implements the seam (`StagedFileArtifactSink` + `JobKeyedStagedSink`) on the verified external volume. **Nothing constructs it yet.** The executor entry point still refuses video profiles (exit 78) until G1 (the production `VerifiedMediaVolume`), #2339 and a physical rig test are in.

- **Reuses ChatGPT's code unchanged:** `ExternalMediaSink._root()` (volume and root), `job_asset_id()` (the same id an image of the same job would get) and `register_asset()` (the gallery index).
- **Staging.** `staged(".mp4")` verifies the root, then creates `.kaliv-<16 hex>.tmp` in the media root (`O_EXCL`, `O_NOFOLLOW`, `0600`). That is the sink's own temporary naming, so its read-only temp inventory lists a crash leftover. The handle has `write`/`flush` only, and bytes past `max_bytes` are not written.
- **Adoption.** `adopt_for_job` / `adopt` take one attempt per live handle: `video/mp4` only, 12 bytes to `max_bytes`, `ftyp` at bytes 4–8. Then:
  - fsync, a root re-check, and the staged name must still be this sink's file at the written size;
  - a sibling `.png` is a conflict;
  - an existing destination with identical bytes is an idempotent retry; anything else at that name, including a symlink, is a conflict;
  - otherwise `os.link` (atomic, never overwrites), and the new name must be our file;
  - then `register_asset`. If it raises, the index decides:
    - our exact row means the writer failed after committing, so the asset is published;
    - otherwise nothing is reported as published, and the asset is **kept** unindexed, never unlinked. `register_asset` validates the file before it takes its lock, so an identical adoption may be about to index it (#2347 reviews 4485232710, 4485290339).
    - The kept asset is listed by `inspect_unindexed_assets` for reconciliation, and an identical retry adopts it. This matches what `publish_and_register_for_job` does with an image.
  - This module never unlinks anything except its own staged name.
  - On success the descriptor is closed at once (the published file shares its inode) and the staged name is removed.
- **Leaving the context** removes the staged name if it is still ours. With the volume no longer verified, it touches nothing.
- **No logging.**
- **Stated limit:** the identity checks and the unlink are separate calls, so an actor with write access to the media root could race them. The media root is operator-only (R1's ACL).

## Template rules

- The template is operator-installed API-format JSON, and the profile pins its SHA-256.
- Seven value slots: `__KALIV_VIDEO_{PROMPT,WIDTH,HEIGHT,FPS,FRAMES,STEPS,SEED}__`.
  - Each must appear exactly once, as a whole input value, under allowlisted input names.
  - A marker anywhere else refuses the template: inside a longer string, in a list, as an input name, as a class or in `_meta`.
- A prompt can never become graph structure.

## Version and weight pins (G3)

Design: #2296 6634996133. A `comfyui` profile may pin two things in `backend_options`:
- `comfyui_version`: the exact `system.comfyui_version` from `/system_stats`;
- `weights`: up to 16 entries `{path, sha256, bytes}`, relative to ComfyUI's models directory.

A `rig-qualified` profile must pin both. Candidates may omit them.

When pins are set:
1. **Template binding.** `load_template` refuses a graph in which any input value, including one inside a list, names a model file that is not pinned. A model file is any string ending in an extension ComfyUI lists in a model folder, plus `.gguf`. The check is keyed on the value, not the input name, because `DualCLIPLoader` uses `clip_name1`/`clip_name2` (#2328 review 4472123690). The value is compared exactly as ComfyUI receives it, with the pin's path minus its model folder: pin `loras/sub/x.safetensors` is loaded as `sub/x.safetensors`. So ` wan.safetensors` (leading space) does not satisfy the pin for `wan.safetensors` (#2328 review 4472405235). A backslash never matches, because it is a separator on Windows but a file-name character on POSIX (4472675602).
   - **Embeddings.** ComfyUI's tokenizer loads `models/embeddings/<name>` for `embedding:<name>` in any text it encodes, extension or not (4472675615). Under pins this is refused three ways:
     - a template string containing `embedding:` (case-insensitive) is refused;
     - `bind()` refuses a prompt containing it, before anything is submitted;
     - the lookup check refuses any unpinned file in `models/embeddings/`, independent of prompt parsing.
2. **Weights.** `verify_weights` (`comfy_weights.py`) runs before the lease and before ComfyUI starts. Every pinned file must be a regular file, not a link, inside the models directory, of the pinned size, with the pinned SHA-256.
   - Files are opened non-blocking, so a FIFO is refused instead of hanging the executor, even one swapped in after the path check (#2328 review 4472123700). The cache is read the same way and written only to a new, exclusive temporary file.
   - **Where it looks.** The models directory is always `<main.py dir>/models`: the one ComfyUI reads, since no flag that moves it is allowlisted.
   - **Caching is an opt-in** (`weights_cache`) for a trusted local filesystem, keyed by `(real path, st_dev, st_ino, size, mtime_ns)`. The default re-hashes on every start.
3. **Lookup is unambiguous** (#2296 6636684138). A hash only proves which file loads if ComfyUI cannot find another one, so the start is refused if any of these is present:
   - `extra_model_paths.yaml`/`.yml` in ComfyUI's root;
   - any link in the models tree;
   - a second file anywhere under `models/` with a pinned name. This includes alias folders such as `unet/` for `diffusion_models/`.
   - Names are compared case-insensitively, because on Windows a lookup of `wan.safetensors` also opens `WAN.safetensors`. Pins whose names differ only in case are refused.
4. **Before every job** (ComfyUI reads weights when a job runs, not when it starts), and before anything is submitted:
   - each pinned path must still be the file that was hashed: same inode, size and mtime (`check_weights_unchanged`);
   - the lookup check runs again, so an embedding or same-named file added since start is caught.

   A failure refuses the job and marks ComfyUI for a restart, which re-verifies from scratch. Stated limit: a change between this check and ComfyUI's read needs write access to the models directory, which only the operator may have.
5. **Version.** The version is compared when ComfyUI is ready and before every job. A mismatch at start stops ComfyUI, so the lease is released. A mismatch before a job refuses that job before anything is submitted.

**Stated limit:** an actor who rewrites a file and restores its size, inode and mtime defeats the cache. Such an actor can also edit the profile.

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
9. The media volume and ComfyUI's output root (#2316 5705457473):
   - The output root is private to the supervised ComfyUI/worker account. Check with `icacls <output root>`: only that account, SYSTEM and Administrators; no Users, Everyone or Authenticated Users. Rename-capture does not protect against a hostile process that renames concurrently inside the output root.
   - Same-directory rename is atomic on the volume, and the filesystem has stable file ids (NTFS, ReFS, ext4, xfs, btrfs). Run `tests/support/windows_cleanup_identity_contract.py` against a temp folder on the volume itself (rig run).
   - FAT32/exFAT derive the id from the directory-entry position. It can change on rename, and a later file can reuse it.
   - On those filesystems, cleanup may fail to remove its own output. Worse, it cannot rule out a reused id.
   - Proposal for the `VerifiedMediaVolume` owner: refuse such volumes.

## Tests (no GPU, no ComfyUI)

A fake ComfyUI (`tests/support/fake_comfyui/main.py`) runs as a real child process under the real launcher and supervisor. Suites:

- `worker_comfy_supervisor.py`
- `worker_comfy_resident_launcher.py` (also runs the Windows contract on POSIX)
- `worker_comfy_video_adapter.py`: also runs the Windows cleanup contract on POSIX
- `worker_staged_sink_conformance.py`: the storage seam, as a mixin that ChatGPT's sink can be run against
- `workflow_media_generation_boundary.py`:
  - only the supervisor may use `subprocess` + `http.client`;
  - only the launcher may use `runpy`, and only once, on the validated `main.py`;
  - the launcher imports nothing from ModelRig;
  - no module-level torch.

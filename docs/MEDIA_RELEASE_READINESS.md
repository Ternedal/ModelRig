# Media generation: release and migration readiness (C9)

Image and video generation on the rig, #2296. This page separates three questions that are easy to blur: what is merged, what is switched on, and what may be released. **A merge is not a release:** every media capability below is default-off, and turning one on is a decision Anders takes per §2. This page records the gates; it does not authorize anything.

**This is a snapshot,** verified against main `cc2b28a6` (after #2282) and the open PRs and branches named below. It must be refreshed after the current merge sequence (#2325, then #2345–#2349). When a row says "open", the PR's own exact-head evidence decides; this page does not replace it.

**Two different "off"s.** Most media modules are **merged but inert**: present in the code, with nothing that starts or calls them. The reachability gate is separate. There are **no media HTTP routes on main**, so no client can submit, list or fetch media.

## 1. What exists, and what is on

| Part | Where | State on main | Switch | Default |
|---|---|---|---|---|
| Profiles (`kaliv-media-profile/v1`), validator, candidate gate | `media_generation_profiles.py` | merged | `KALIV_MEDIA_PROFILES_ENABLED`, `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES` | nothing enabled; only `rig-qualified` profiles run |
| GPU lease (OS lock per GPU UUID), executor lock, resident lock | `gpu_lease.py` | merged | `KALIV_GPU_LEASE_DIR`, `KALIV_GPU_DEVICE_UUIDS`, `CUDA_DEVICE_ORDER=PCI_BUS_ID` | none |
| Job store (SQLite) with executor protocol, prompt retention (30 d), chat-first wait (G4) | `image_job_store.py` | merged (G4 = #2341) | `KALIV_MEDIA_JOB_DB` (in the work area once the wiring lands) | none |
| Media executor process | `python -m app.media_executor_main --device cuda:N` | merged, **not started by anything** | `KALIV_MEDIA_EXECUTOR=1` | off: exit 78 |
| Image generation (diffusers) | `diffusers_image_adapter.py` | merged | via profile | off |
| Supervised ComfyUI (video), pins (G3) | `comfy_supervisor.py`, `comfy_video_adapter.py`, `comfy_weights.py` | merged | via profile | off |
| Video in the executor | `media_executor_main` | **refused: exit 78 for any video profile** | none yet | off |
| Gallery catalog, store, index writer, asset streaming | `media_gallery_*.py` | merged (ChatGPT) | none (no route) | not reachable |
| Owner-gated source image (#2339) | `media_source_image.py` | merged | none (no route) | not reachable |
| Gallery HTTP routes, submit/get/cancel API | ChatGPT | **not on main: this is the reachability gate** | not on main | nothing is reachable |
| Android gallery client (#2301, #2302) | `android/` | merged, fixture-driven | needs the routes | inert |

Open PRs and branches on the path to video:
- **#2345** G5: lease directory ACL on Windows.
- **#2346** image-to-video adapter.
- **#2347** staged video sink.
- **#2349** G1: production `VerifiedMediaVolume`.
- `feat/media-i2v-executor`, the executor's image-to-video path.
- **G1 wiring and the work area**, branch `feat/media-volume-wiring`. It is prepared, not merged and not enabled. It implements Anders' 6 Nov decision: media is generated in a private work area on the internal disk (C:), with the job database there, and published on the external volume (Z:) (`docs/MEDIA_WORK_AREA.md`).
- `fix/gallery-index-os-lock`, the index lock (C8 findings).
- C6 repair tool (`feat/media-volume-repair`), stacked on the wiring: it also reports and removes work-area residue.

## 2. Data and migrations

Every change to stored data so far is **additive**. Nothing is rewritten, renamed or dropped.

| Store | Change | Introduced | Downgrade |
|---|---|---|---|
| `image_jobs` (SQLite) | `CREATE TABLE IF NOT EXISTS`, then `ADD COLUMN claimed_by`, `cancel_requested`, `deferred_since` | G2, G2b, G4 | Older code ignores extra columns. The executor protocol columns are only read by the executor. |
| `image_jobs` | index `image_jobs_state`, index `image_jobs_owner_asset_state` | G2, #2339 | Harmless to older code |
| `image_jobs_scrub` | one-row table: a VACUUM is owed once after `secure_delete` was enabled | #2340 | Older code never reads it |
| Gallery index `gallery-index.json` (`kaliv-media-gallery/v1` items) | none since v1. The writer strips presentation-only fields before writing. | #2313 | — |
| `.gallery-index.lock` | with the lock fix: a persistent, never-unlinked lock file instead of an `O_EXCL` marker | `fix/gallery-index-os-lock` | **One-way:** the old writer treats a leftover file as held. Once the new writer has run, do not downgrade without deleting the file, with no writer running. |
| `.kaliv-media-volume` marker | new file at the volume root | G1 (#2349) | Older code ignores it |
| Job database location | moves into the work area on the internal disk (`KALIV_MEDIA_WORK_ROOT`) | wiring (Anders, 6 Nov) | **An operator copy, never automatic:** stop the executor, copy the file and its `-wal`/`-shm` into `<work area>\state`, start, check the queue, then delete the old copy (`docs/MEDIA_WORK_AREA.md`). To go back, copy it back the same way |

**Before any migration on the rig:** copy the job database while no executor runs (the executor lock is free). SQLite's migration is one transaction (`BEGIN IMMEDIATE` spans creation and every `ALTER`), so an interrupted start leaves the old schema.

## 3. Rollback

| To undo | Do | What remains |
|---|---|---|
| Media generation entirely | Unset `KALIV_MEDIA_EXECUTOR` (or stop the supervisor's executor) | Jobs stay in the DB. Queued ones are never claimed; running ones are recorded as `failed: interrupted by restart` at the next start. Assets stay on the volume. |
| One profile | Remove it from `KALIV_MEDIA_PROFILES_ENABLED` | Its queued jobs stay queued and are never claimed by a profile that is no longer enabled |
| The media volume | Stop the executor, then unmount | The executor refuses to start without it (exit 75) and never claims a job while it is gone; nothing is published anywhere else |
| The work area | Stop the executor | Prompts stay in the job database there until retention blanks them; crash leftovers stay until an operator removes them (C6 `remove-work-file`) |
| A bad index or residue | `scripts/media_volume_repair.py report` (C6), then one named repair at a time | Nothing is deleted automatically |

Prompts are blanked 30 days after a job finishes (#2340). A rollback does not change that.

## 4. Release gates (all required; none is met by a merge)

| Gate | Evidence | Owner | Status |
|---|---|---|---|
| G1 and the work area wired: `MountedMediaVolume` for the publication volume and the sink; `PrivateWorkArea` for the job database and ComfyUI's directories (Anders, 6 Nov) | wiring PR plus rig R1, R5, R14 | Claude | G1 open (#2349); wiring branch prepared, not merged, not enabled |
| Staged video sink and image-to-video in the executor | #2347, #2346, the i2v executor PR | Claude | open |
| Gallery routes and Android gallery against real routes | ChatGPT's route PR, R11 | ChatGPT | not on main |
| Rig qualification pack at the qualified SHA, with the evidence manifest | runbook #2296 6642831318, R0–R16 | Anders runs it | waiting for A1–A3 (and A2b for Wan 2.2) |
| Profiles promoted to `rig-qualified` with the measured limits (C4 R16) | a profile PR citing the manifest | Claude + ChatGPT | after the rig run |
| ComfyUI backend outbound network blocked (firewall rule) | rig item 7 | **Anders (§2)** | open |
| Cloud: media never reaches the cloud; chat cloud payload is current-message only (D5); no fallback after Stop (F1) | `CloudCurrentMessageOnlyTest`; #2348 | Claude (F1), ChatGPT (review); Anders approved F1 | D5 implemented and tested; #2348 pending exact-head qualification |
| Index lock survives a killed writer (C8 findings 2–3) | `fix/gallery-index-os-lock` | Claude | branch |
| Production signing / release | — | **Anders (§2)** | not requested |

## 5. Upgrade and compatibility matrix

| Component | Requires | Compatible with |
|---|---|---|
| Worker (API) | nothing media | Runs with media off; the boundary test forbids the API entry point to import the generation layer |
| Media executor | Python 3.12 with its bundled SQLite (the rig's `sqlite_version` is recorded by R5b; the retention scrub needs `secure_delete` and `VACUUM`), CUDA driver as qualified | one executor per GPU UUID (exit 73 for a second) |
| ComfyUI | the version pinned in the profile (G3) and `--disable-all-custom-nodes` | pinned weights by SHA-256 |
| Media volume | NTFS, ReFS, ext4, xfs or btrfs; external, mounted, with the marker (G1) | FAT and exFAT refused; network shares refused |
| Work area | NTFS, ReFS, ext4, xfs or btrfs on a local disk; private to the executor's account (Windows DACL, POSIX `0700`); not on the media volume | network drives, FAT, exFAT and tmpfs refused. The gallery routes read the job database there, so they run as the same account |
| Mixed WSL / native on one GPU or volume | — | **not supported**: OS locks do not cross that boundary |
| Android app | `kaliv-media-gallery/v1` | older apps ignore the gallery |

## 6. Known limits carried into a release

- Checks, not handles: a process running as the same OS user can race a path check. The private work area is the mitigation (rig item 9).
- Prompts and partial media sit on the internal disk while kept or rendered; the work area's ACL keeps other users out, and retention blanks prompts after 30 days.
- A crash can leave leftovers in the work area. C6 reports them; an operator removes them one at a time.
- Publish first, then delete: a finished video stays in the work area until it is published. If publication fails (the volume went away, the sink refused it), it is kept there for recovery and C6 lists it; there is no automatic republish, and the owner resubmits.
- ComfyUI's error text is never propagated, so an out-of-memory error is visible only in ComfyUI's own log.
- An interrupted render is failed, not re-queued; the owner resubmits.
- A volume lost mid-render leaves an unindexed `.kaliv-*.tmp`; C6 reports it, and an operator removes it.
- Windows releases a dead process's byte-range lock "after a delay"; the index lock waits up to 5 s before refusing.

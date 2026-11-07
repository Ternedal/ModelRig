# Media generation: release and migration readiness (C9)

Image and video generation on the rig, #2296. This page separates three questions that are easy to blur: what is merged, what is switched on, and what may be released. **A merge is not a release:** every media capability below is default-off, and turning one on is a decision Anders takes per §2. This page records the gates; it does not authorize anything.

**This is a snapshot,** verified against main `4d6e8bb3` and the open PRs and branches named below. It must be refreshed after the current merge sequence (#2325, then #2345–#2349). When a row says "open", the PR's own exact-head evidence decides; this page does not replace it.

**Two different "off"s.** Most media modules are **merged but inert**: present in the code, with nothing that starts or calls them. The reachability gate is separate. There are **no media HTTP routes on main**, so no client can submit, list or fetch media.

## 1. What exists, and what is on

| Part | Where | State on main | Switch | Default |
|---|---|---|---|---|
| Profiles (`kaliv-media-profile/v1`), validator, candidate gate | `media_generation_profiles.py` | merged | `KALIV_MEDIA_PROFILES_ENABLED`, `KALIV_MEDIA_ALLOW_CANDIDATE_PROFILES` | nothing enabled; only `rig-qualified` profiles run |
| GPU lease (OS lock per GPU UUID), executor lock, resident lock | `gpu_lease.py` | merged | `KALIV_GPU_LEASE_DIR`, `KALIV_GPU_DEVICE_UUIDS`, `CUDA_DEVICE_ORDER=PCI_BUS_ID` | none |
| Job store (SQLite) with executor protocol, prompt retention (30 d), chat-first wait (G4) | `image_job_store.py` | merged (G4 = #2341) | `KALIV_MEDIA_JOB_DB` (in the work area once the wiring lands) | none |
| Queued-job expiry: unclaimed for 24 h → terminal `expired`, error `expired_unclaimed` (Anders, 6 Nov) | `image_job_store.py`, `media_executor.py` | wiring branch | none: always on once merged | 24 h |
| Hand-off receipts (`image_jobs_handoff`) and executor diagnostics (`kaliv-media-event` lines on stderr) | `image_job_store.py`, `media_executor*.py` | wiring branch | none | on with the executor |
| Recovery inventory (read-only; no republish) | `media_recovery_inventory.py`, `scripts/media_volume_repair.py inventory` | C6 branch | operator runs it | never automatic |
| Media executor process | `python -m app.media_executor_main --device cuda:N` | merged, **not started by anything** | `KALIV_MEDIA_EXECUTOR=1` | off: exit 78 |
| Image generation (diffusers) | `diffusers_image_adapter.py` | merged | via profile | off |
| Supervised ComfyUI (video), pins (G3) | `comfy_supervisor.py`, `comfy_video_adapter.py`, `comfy_weights.py` | merged | via profile | off |
| Video in the executor | `media_executor_main` | **refused: exit 78 for any video profile** | none yet | off |
| Image-to-video: ComfyUI adapter (`render_to(source_png=...)`) | `comfy_video_adapter.py` | merged 7 Nov (#2346, `f20a6c2a`) | via profile | off |
| Image-to-video through the executor, via the owner-gated source reader | `media_executor.py` | PR #2353, qualifying | via profile | off (video still exit 78) |
| Gallery catalog, store, index writer, asset streaming | `media_gallery_*.py` | merged (ChatGPT) | none (no route) | not reachable |
| Owner-scoped gallery reads (list, open, stream) | `media_gallery_owner.py` on ChatGPT's `feat/media-owner-gallery-filter` | branch; open findings (#2275 6702693683): descriptor bound to the verified volume, ungated legacy helpers, one DB connection per entry | none (no route) | not reachable |
| Descriptor check for readers: `MountedMediaVolume.require_descriptor(fd, path)` | `media_volume.py` | wiring branch; Windows contract cases mandatory, not yet run | none | used by nothing yet |
| Owner-gated source image (#2339) | `media_source_image.py` | merged | none (no route) | not reachable |
| Gallery HTTP routes, submit/get/cancel API | ChatGPT | **not on main: this is the reachability gate** | not on main | nothing is reachable |
| Android gallery client (#2301, #2302) | `android/` | merged, fixture-driven | needs the routes | inert |
| Android job model: proposed `kaliv-media-job/v1` parser, Danish texts, polling, drift test against the store | `feat/android-media-job-readiness` (`docs/MEDIA_ANDROID_READINESS.md`) | branch; contract not yet agreed | needs the routes | no UI |

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
| `image_jobs.state` | new value `expired` (no schema change) | wiring | Older code never claims or counts an expired job, but its retention does not know the state: **prompts of expired jobs are not blanked while older code runs.** They are blanked once the newer code runs again. |
| `image_jobs_handoff` | new table: one copy receipt per video job | wiring | Older code never reads it; C6 then has no receipt to classify by |
| `image_jobs.error` after a restart | the codes `interrupted_by_restart` and `interrupted_during_publication` instead of sentences; existing rows are **not** rewritten | wiring | Older code writes the sentences again. `public_error()` maps both forms, so the route and Android show the same thing either way |
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
| Staged video sink and image-to-video in the executor | #2347, #2346, #2353 | Claude | #2346 merged 7 Nov; #2347 (three durability fixes on 7 Nov) and #2353 qualifying |
| Gallery reads bound to the verified volume: index and asset descriptors on the pinned device and the walked path (`require_descriptor`), proven on Windows/NTFS | ChatGPT's gallery branch + wiring; the Windows volume contract | ChatGPT (gallery), Claude (`require_descriptor`) | open; required before any route |
| Gallery routes and Android gallery against real routes | ChatGPT's route PR, R11 | ChatGPT | not on main |
| Rig qualification pack at the qualified SHA, with the evidence manifest | runbook #2296 6642831318, R0–R16 | Anders runs it | waiting for A1–A3 (and A2b for Wan 2.2) |
| Profiles promoted to `rig-qualified` with the measured limits (C4 R16) | a profile PR citing the manifest | Claude + ChatGPT | after the rig run |
| ComfyUI backend outbound network blocked (firewall rule) | rig item 7 | **Anders (§2)** | open |
| Cloud: media never reaches the cloud; chat cloud payload is current-message only (D5); no fallback after Stop (F1) | `CloudCurrentMessageOnlyTest`; #2348 | Claude (F1), ChatGPT (review); Anders approved F1 | D5 implemented and tested. #2348: a consent regression (opt-in read before the rig call) was fixed on 7 Nov, so it is now read when the rig fails; qualifying |
| Index lock survives a killed writer (C8 findings 2–3) | `fix/gallery-index-os-lock` | Claude | branch |
| C:/Z: layout proven on the rig: private work area, one account for every process, separate disks, low space visible, residue baseline, rollback (R17) | `docs/MEDIA_R17_DEPLOYMENT_PROOF.md` (R17.1–R17.13; R17.10–R17.13 added 7 Nov: lease ACL, moved DB, junction root, unplug, other disk) | Anders runs it; ChatGPT reviews | pending: needs the wiring merged and a new `$QualSha` |
| Job routes expose `expired` and Android shows it | ChatGPT's route PR; Android branch above | ChatGPT (routes), Claude (Android) | contract proposed (#2275), not agreed |
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
| Android app | `kaliv-media-gallery/v1`; jobs: `kaliv-media-job/v1` once agreed | older apps ignore the gallery and jobs. A newer app refuses a job state it does not know rather than guessing |

## 6. Known limits carried into a release

- Checks, not handles: a process running as the same OS user can race a path check. The private work area is the mitigation (rig item 9).
- Prompts and partial media sit on the internal disk while kept or rendered; the work area's ACL keeps other users out, and retention blanks prompts after 30 days.
- A crash can leave leftovers in the work area. C6 reports them; an operator removes them one at a time.
- Publish first, then delete: a finished video stays in the work area until it is published. If publication fails (the volume went away, the sink refused it), it is kept there for recovery and C6 lists it; there is no automatic republish, and the owner resubmits.
- ComfyUI's error text is never propagated, so an out-of-memory error is visible only in ComfyUI's own log.
- An interrupted render is failed, not re-queued; the owner resubmits.
- A queued job nobody claims for 24 hours expires; the owner resubmits. Running and publishing jobs never expire.
- A volume lost mid-render leaves an unindexed `.kaliv-*.tmp`; C6 reports it, and an operator removes it.
- Windows releases a dead process's byte-range lock "after a delay"; the index lock waits up to 5 s before refusing.

# Media gallery: how a paired device lists and plays generated media

**Default off.** `/api/v1/media` and `/api/v1/media/{id}` are always behind the paired-device Bearer check (`authMW`). They answer 503 unless `KALIV_MEDIA_JOBS_API=1` is set with a usable `KALIV_MEDIA_INTERNAL_SECRET` (32 or more characters) and a loopback worker. The same switch turns on the job routes (`docs/MEDIA_EXECUTOR.md`).

```
Android --Bearer--> Go (authMW, Range, headers) --loopback + internal secret--> worker /internal/media/assets
                                                                                  |
                                       job database (ownership)  +  MountedMediaVolume (Z:)
```

## Who decides what

| Question | Decided by | Where |
|---|---|---|
| Is this device paired? | Go `authMW` | `backend/internal/httpapi` |
| Is this asset the installation's? | the worker, from the job database: only assets of **completed** jobs | `worker/app/media_gallery_api.py` (`completed_assets_for`, `owns_completed_asset`) |
| Are these bytes from the verified volume? | the worker: marker and id, pinned identity, no network or `subst` drive, not the system disk, the file opened without following a link and checked with `require_descriptor` | `worker/app/media_volume.py` |
| Which byte range, which headers? | Go, with one explicit range per worker request | `media_routes.go`, `media_range*.go`, `media_worker_catalog.go` |

**Go never opens the media volume.** The worker never gives Go a path, only items and bytes.

## Three states, never more

| The worker answers | The device sees | Why |
|---|---|---|
| owned and verified | 200/206 (416 past the end) | |
| not owned (failed, running, publishing, expired), or unknown | **404**, the same body for both | No existence oracle. It is decided from the job database **before** the volume is touched. |
| cannot decide: database error, more than 10,000 assets, volume missing or changed, index invalid, an owned asset missing or of another size | **503** with a code | Never an empty 200, never a 404 |
| a wrong internal secret (401), a redirect, worker down or timing out | **503** | It is never a pairing error for the device |

**A lost volume stays lost** for the worker process, as for the executor: 503 until the worker restarts. A replugged disk is not trusted again on its own.

## The list
- **Newest first.** The sink appends to the index, so the worker lists in reverse order, and a new result is on the first page.
- The gallery index is filtered by the installation's completed assets **before** pagination, so a cursor always lies inside what the device may see.
- An unknown cursor is 400.
- A thumbnail whose asset is not owned is dropped (`thumbnail_id` and `thumbnail_url` are `null`) rather than linked to a 404.
- Items have exactly the `kaliv-media-gallery/v1` shape of the shared fixture (`contracts/kaliv-media-gallery-v1-fixtures.json`). Go refuses any other shape, or a link to another place, with 503.

## Tests
- `tests/worker_media_gallery_api.py`, on the shared fixture with the real job store and volume:
  - only completed assets are listed;
  - pagination stays inside them;
  - not owned is the same 404;
  - ownership is checked before the volume;
  - Range, HEAD and 416;
  - a database error and too many assets are 503;
  - a lost volume stays lost;
  - a changed marker, a missing, resized, linked or unindexed asset and a bad index are all 503;
  - secret and loopback;
  - the configuration codes.
- `backend/internal/httpapi/media_worker_catalog_test.go`, cross-platform, with a fake worker that follows the same contract:
  - the device page equals the fixture page;
  - cursor pagination, and 400 for an unknown cursor;
  - full, ranged, suffix and multi-range requests, HEAD, 416;
  - the three-state mapping (404, and 503 for 401, 403, 500, 502, 503 and 302);
  - worker down, and a wrong secret;
  - a contract-breaking list (another location, an extra or missing field, a foreign thumbnail, an unserved type, a bad cursor, too many items, another schema, not JSON);
  - a range answer that is not exactly the one asked;
  - a short body is an error;
  - HEAD reads no body;
  - 32 concurrent requests (`-race`);
  - the catalog is off without the switch, the secret or a loopback worker.

## Limits
- **A same-size swap is not detected.** The index carries no content hash, so a file replaced on Z: by another file of the **same size**, under the same name, is served. Only the Z: ACL prevents it. Writing a SHA-256 into the index at publication would close it.
- **The physical proof is still open.** Z: identity on the rig is R17. Playback on the phone is C5 P5 and P7.

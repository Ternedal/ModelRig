# BodyRig M1.1 local video ingest

Status: implementation slice for #718. This does **not** complete physical MP4/H.264 qualification or activate body cloning.

## Boundary

`bodyrig.video_ingest.VideoDecoder` is the local media boundary. It emits BodyRig-owned `DecodedVideoFrame` values containing:

- presentation timestamp in microseconds;
- width and height;
- tightly packed RGB24 bytes.

No PyAV/FFmpeg frame, stream, packet or codec type is allowed to cross that boundary. The existing `bodyrig.tracking/v1` schema remains unchanged.

## Why timestamps come from PTS

BodyRig uses decoded presentation timestamps (`PTS × time_base`) instead of reconstructing time from frame number / nominal FPS. This preserves variable-frame-rate timing and keeps later pose, hand and face observations aligned to the source presentation timeline. The first decoded frame is normalized to `0 us`; subsequent spacing comes from source PTS.

A missing, duplicate or decreasing presentation timestamp fails closed. The decoder does not invent timing.

## Current decoder adapter

The first adapter is `PyAVVideoDecoder`, pinned to PyAV `18.0.0` in `worker/requirements-bodyrig-video.txt`.

The dependency is optional and lazy-loaded. Normal ModelRig CI and the base worker do not install it. This is deliberate for two reasons:

1. BodyRig extraction is an optional heavy/local capability, not a base ModelRig dependency.
2. Existing ModelRig notes record that bundled PyAV/FFmpeg DLLs may be rejected by Windows Application Control on some hosts. The `VideoDecoder` boundary therefore stays replaceable; a policy-compatible decoder must be qualified before production activation on such a host.

The adapter converts decoded frames to RGB24 without NumPy by repacking the single RGB plane row-by-row when FFmpeg adds stride padding.

## Contract qualification

`python3 tests/bodyrig_video_ingest.py`

The repository test uses a tiny PyAV-shaped fake. It proves:

- exact PyAV runtime pin enforcement;
- H.264 media facts mapping;
- PTS/time-base timestamp conversion without float drift;
- first-frame zero normalization;
- deterministic RGB24 stride removal;
- rejection of missing/duplicate PTS;
- rejection of non-video input;
- no implicit MediaPipe/model dependency.

This test intentionally does not pretend that a native H.264 decoder ran in CI.

## Physical qualification still required

Before #718 can claim MP4/H.264 ingest acceptance, run an opt-in host qualification with the pinned decoder against a small permitted H.264/MP4 fixture and verify:

- PyAV imports under the host's Windows policy;
- stream codec is reported as H.264;
- decoded frame count is non-zero;
- timestamps remain strictly increasing;
- RGB frame geometry matches the source;
- the last emitted timestamp remains within the inspected media duration.

If PyAV is blocked, implement and qualify another `VideoDecoder` adapter rather than weakening host policy.

## Next slice

Add a MediaPipe Holistic tracking backend behind the existing `TrackingBackend` protocol. It should consume `DecodedVideoFrame`, create MediaPipe VIDEO-mode inputs at the decoded timestamps, map only canonical BodyRig landmark/expression ids, retain independent body/hands/face loss, pin the local model asset by hash/revision, and never download a model implicitly.

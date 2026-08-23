# BodyRig bootstrap

Executable V1 foundation for the separate BodyRig product.

This bootstrap deliberately implements the stable product boundary before the heavy video-recovery stack:

- strict `.mrbody` build/validation;
- atomic profile installation;
- loopback-only FastAPI service on `127.0.0.1:8775`;
- semantic `BodyCue` runtime contract from ModelRig;
- speech timing/viseme side-channel from VoiceRig keyed by `utterance_id`;
- in-memory runtime state ready for a future WebSocket renderer transport;
- a model-neutral recovery contract for video/3D engines;
- deterministic extraction of observed body proportions and motion style from recovered joints.

## Recovery boundary

Heavy human-mesh recovery is intentionally isolated from the BodyRig service environment.

`JsonCommandRecoveryAdapter` launches a separately installed recovery engine and exchanges bounded JSON over stdin/stdout. An HMR2/4D-Humans environment can therefore provide person tracks without making its Python/Torch/body-model dependency stack part of the stable BodyRig runtime.

The canonical recovery result contains timestamped 3D joints plus confidence. BodyRig itself converts that into a `bodyprint` with observed values such as:

- shoulder/hip/arm/leg proportions relative to recovered body height;
- movement energy;
- gesture amplitude and frequency;
- head motion;
- turn speed.

Values that cannot actually be observed are omitted instead of invented. For example, V1 does not infer an absolute `height_scale` from monocular video unless a future calibrated adapter supplies trustworthy scale.

The remaining heavy pipeline is:

```text
video → person tracking / 3D recovery adapter → canonical joints/tracks
      → BodyRig bodyprint extraction → avatar fitting/VRM export → .mrbody
```

## Run

```bash
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e ".[test]"
pytest -q
bodyrig
```

## Safety defaults

- package paths are allow-listed before extraction;
- duplicate/encrypted/traversal entries are rejected;
- per-file and total expanded-size limits are enforced;
- checksums must match exactly all payload files;
- VRM/VRMA assets must at least be valid GLB v2 containers;
- bodyprint and recovery numbers must be finite and range-valid;
- recovery adapter identity/revision is pinned and checked;
- stale VoiceRig timing for a different utterance is rejected;
- imports are validated before atomic replacement;
- non-loopback binds are refused unless explicitly overridden.

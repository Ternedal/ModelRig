# BodyRig bootstrap

Executable V1 foundation for the separate BodyRig product.

This bootstrap deliberately implements the stable product boundary before the heavy video-recovery stack:

- strict `.mrbody` build/validation;
- atomic profile installation;
- loopback-only FastAPI service on `127.0.0.1:8775`;
- semantic `BodyCue` runtime contract from ModelRig;
- speech timing/viseme side-channel from VoiceRig keyed by `utterance_id`;
- in-memory runtime state ready for a future WebSocket renderer transport.

The video → person tracking → 3D recovery → VRM generation pipeline plugs in behind this contract and must not leak its model-specific tensors/checkpoints into `.mrbody`.

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
- bodyprint numbers must be finite and range-valid;
- imports are validated before atomic replacement;
- non-loopback binds are refused unless explicitly overridden.

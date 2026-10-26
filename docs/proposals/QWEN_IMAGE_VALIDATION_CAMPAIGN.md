# Qwen-Image isolated validation campaign

This branch is **not a production release**. The image API router is a factory
and is deliberately not mounted in `worker/app/entrypoint.py`.

## CI versus decoder coverage

The default worker deliberately does not depend on Pillow. Tests using
`pytest.importorskip("PIL.Image")` are **skipped** unless the isolated
decoder is installed. A green default CI result does not prove image decoding
or ComfyUI GPU generation works.

In an isolated Python environment with a reviewed, pinned Pillow version,
run from `worker/`:

```bash
python -m pytest -q tests/test_image_generation_real_decoder_integration.py tests/test_image_generation_sanitize.py tests/test_image_generation_ingest.py tests/test_image_generation_decompression.py
python -m pytest -q tests/test_image_generation_api_pipeline.py tests/test_image_generation_api.py tests/test_image_generation_artifact_api.py
```

Record the Pillow version, test result, machine and GPU driver in the
qualification report. Never install the decoder into the V1 worker just to
make these tests pass.

## Activation blockers

- Review and pin the exact Qwen-Image ComfyUI workflow and model files.
- Supply a trusted, existing ModelRig authentication dependency. Do **not**
  use client-controlled identity headers.
- Require an explicitly configured **external media drive** for image output;
  do not default to the system drive or silently fall back when it is missing.
- Implement a durable multi-process job and ingestion ledger, including
  recovery after restart and retention limits.
- Perform real ComfyUI GPU and mobile/VR client qualification.
- Review resource, cancellation and shutdown behavior before mounting any API.

The current API and artifact store are single-process building blocks. The
in-memory ingestion ledger and locks are not sufficient for multi-process
production. No existing V1 release or main branch is modified by this plan.

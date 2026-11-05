"""Operator checklist for the experimental image API.

This feature is intentionally not production-enabled. These checks must be
completed before replacing the fail-closed worker entrypoint guard.
"""

# Deployment prerequisites (no automatic actions performed)
#
# 1. Authenticate callers through the existing trusted server-side identity
#    mechanism. Never accept an owner id from headers, query strings or body.
# 2. Configure an operator-reviewed ComfyUI workflow and bounded local adapter.
#    A workflow path or node graph must never come from an untrusted client.
# 3. Verify the target storage is physically external at the OS/deployment
#    layer. The .modelrig-volume-id marker only checks configured identity;
#    it is not proof of removable media or a real mounted filesystem.
# 4. Construct the store with external_image_artifact_store(...), and validate
#    that the volume remains mounted during reads, writes and ingestion.
# 5. Ensure multi-process workers cannot duplicate ingestion; the current
#    ledger is process-local. Do not enable multi-worker deployment until
#    persistent coordination and cleanup are implemented.
# 6. Ensure the image decoder dependency is present for sanitization and
#    thumbnails; otherwise generation/preview must fail closed.
# 7. Run physical unplug/replug, app authentication, Android and Quest client
#    acceptance tests before enabling the production feature flag.
# 8. Keep V1 release/main unchanged; deploy only after a separately approved
#    integration and successful exact-head qualification.

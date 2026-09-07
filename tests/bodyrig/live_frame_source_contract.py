"""Regression contract for the Unity live BodyRig frame source.

This is intentionally static: CI cannot compile or run the Unity player, but it
can pin the stream/reconnect and evidence semantics that the physical gate later
exercises.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "support"))
from source_code import code_of  # noqa: E402

root = Path(__file__).resolve().parents[2]
source = code_of(
    root
    / "renderers"
    / "bodyrig-unity"
    / "Assets"
    / "BodyRig"
    / "Runtime"
    / "BodyRigFrameSource.cs"
)

reset_marker = "lastTimestampMs = -1;"
send_marker = "yield return request.SendWebRequest();"
strict_guard = "if (frame.timestamp_ms <= lastTimestampMs)"
apply_marker = "renderer.Apply(frame);"
receipt_marker = "WriteLiveReceiptIfRequested(frame);"
redirect_marker = "request.redirectLimit = 0;"

assert source.count(reset_marker) >= 2, (
    "timestamp authority must be reset for each new HTTP/SSE stream, not only "
    "when the component is constructed"
)
stream_reset = source.find(reset_marker, source.find("while (enabled)"))
assert stream_reset >= 0 and stream_reset < source.index(send_marker), (
    "the per-stream timestamp reset must happen before the request starts"
)
assert redirect_marker in source and source.index(redirect_marker) < source.index(send_marker), (
    "Bearer-authenticated Unity requests must refuse redirects before the request starts"
)
assert strict_guard in source and source.index(strict_guard) < source.index(apply_marker), (
    "non-increasing timestamps must be rejected before renderer.Apply"
)
assert "lastTimestampMs - frame.timestamp_ms" not in source, (
    "do not infer reconnects from the size of a timestamp rewind; reconnect is "
    "an HTTP-stream boundary"
)
assert receipt_marker in source and source.index(apply_marker) < source.index(receipt_marker), (
    "live evidence may only be committed after a validated frame was actually applied"
)
for required in (
    '"bodyrig.unity_live_stream/v0.1"',
    'GetEnvironmentVariable("BODYRIG_LIVE_RECEIPT")',
    'RequireEnvironment("BODYRIG_CANDIDATE_SHA")',
    'RequireEnvironment("BODYRIG_BODY_ID")',
    'RequireEnvironment("BODYRIG_PACKAGE_SHA256")',
    "bearer_auth_used = !string.IsNullOrWhiteSpace(token)",
    "renderer_bound = renderer != null && renderer.IsBound",
    "frame_applied = true",
):
    assert required in source, f"live receipt contract missing: {required}"
assert "token =" not in source[source.index("var receipt = new LiveReceipt"):source.index("var raw =")], (
    "the live receipt must never serialize the bearer token"
)

print("LIVE FRAME SOURCE CONTRACT: PASS")

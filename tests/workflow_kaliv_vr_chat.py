#!/usr/bin/env python3
"""Static contract for Kaliv VR streaming chat."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests" / "support"))
from source_code import code_of  # noqa: E402

CLIENT = code_of(ROOT / "vr/Assets/Scripts/ModelRigVrClient.cs")
APP = code_of(ROOT / "vr/Assets/Scripts/KalivVrApp.cs")
PANEL = code_of(ROOT / "vr/Assets/Scripts/KalivVrPanel.cs")
README = (ROOT / "vr/README.md").read_text(encoding="utf-8")

passed = 0
failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS: {message}")
    else:
        failed += 1
        print(f"  FAIL: {message}")


check(
    "stream = true" in CLIENT and '"/api/v1/chat"' in CLIENT,
    "VR chat uses the backend's streaming chat contract",
)
check(
    "DownloadHandlerScript" in CLIENT
    and "Encoding.UTF8.GetDecoder()" in CLIENT
    and "_decoder.GetChars(" in CLIENT,
    "stream parser preserves UTF-8 across UnityWebRequest chunk boundaries",
)
check(
    "ChatStreamEnvelope" in CLIENT
    and "envelope.message?.content" in CLIENT
    and "envelope.done" in CLIENT,
    "NDJSON deltas and terminal done are parsed explicitly",
)
check(
    "SawDone" in CLIENT
    and "Chat-streamen blev afbrudt undervejs" in CLIENT
    and "Chat-streamen lukkede før et svar begyndte" in CLIENT,
    "stream EOF fails closed instead of masquerading as success",
)
check(
    "public bool CancelChat()" in CLIENT
    and "_activeChatRequest.Abort();" in CLIENT,
    "active chat can be explicitly cancelled",
)
check(
    "_client.ChatStream(" in APP
    and "_panel.AppendAssistantDelta(delta)" in APP
    and "CompleteStreamingTurn(generation)" in APP,
    "Kaliv VR renders chat deltas incrementally",
)
check(
    "_history.Add(new ModelRigVrClient.ChatMessage(\"assistant\", clean));" in APP
    and APP.index("_history.Add(new ModelRigVrClient.ChatMessage(\"assistant\", clean));")
        > APP.index("private void CompleteStreamingTurn"),
    "only a terminally complete answer is committed to conversation history",
)
check(
    "_history.RemoveAt(_history.Count - 1);" in APP
    and "private void FailStreamingTurn" in APP,
    "failed/cancelled turns do not poison the next backend history",
)
check(
    '"STOP"' in PANEL
    and "_app.StopChat" in PANEL
    and "_stopButton.interactable = busy" in PANEL,
    "world-space conversation UI exposes a stop control only while generating",
)
check(
    "token-for-token NDJSON streaming" in README
    and "Streaming chat, voice, RAG" not in README,
    "VR documentation records streaming parity without claiming the remaining slices",
)

print(f"\nkaliv vr chat contract: {passed} passed, {failed} failed")
if failed:
    raise SystemExit(1)

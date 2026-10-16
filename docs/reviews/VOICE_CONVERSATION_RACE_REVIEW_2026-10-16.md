# Voice conversation-switch race review — 2026-10-16

Scope: review of PR #2211 on top of PR #2210. This document is an analysis, **not** physical acceptance or a passing test receipt.

## Observed code

- ChatScreen snapshots `convId`, `voiceConversationRevision`, and prior completed messages at the start of `runVoiceTurn`.
- On a conversation switch, the revision is incremented, the voice cancellation object is stopped, the job cancelled, and the shared messages list cleared.
- After the network turn, the persistence path checks the revision before selecting/creating a conversation and again before assigning a new ID. It also mutates Compose state from `withContext(Dispatchers.IO)`.
- The worker accepts per-request history, filters non-user/assistant roles, and bounds context to 20 messages and 24,000 characters.

## Review findings (require verification)

1. **Potential check-then-write race:** checking `voiceConversationRevision` and then writing messages to SQLite is not an atomic operation. A conversation switch may occur after the check but before either write. Test with controlled dispatchers and a blocking fake DB, and ensure a stale turn cannot persist into a switched conversation.
2. **Thread confinement:** `convId = cid`, `onConvChanged(cid)`, and reads of Compose-backed `voiceConversationRevision` currently occur inside an IO context. Move UI-state reads/writes to the main dispatcher or pass immutable state into IO and revalidate on Main before UI mutation.
3. **Callback isolation:** verify every transcript, chunk, completion, error and cleanup callback rejects an obsolete revision, not only the final streaming-bubble cleanup. A cancelled request can still deliver a late callback.
4. **Conversation creation:** when the first voice turn has no ID, test navigation during request and during DB creation. Prevent orphan conversations and incorrect navigation.
5. **Context security:** the mocked test fixes the model reply to “blå elefant”; that checks forwarding but does not establish real model recall. Run physical two-turn recall, isolation between conversations, text-to-voice continuity and cloud opt-in boundary checks.

## Acceptance matrix

| Scenario | Expected | Evidence |
| --- | --- | --- |
| Switch before transcript | No stale bubble or DB write in new conversation | NOT_RUN |
| Switch during first voice-only conversation creation | No wrong navigation or persisted turn | NOT_RUN |
| Switch between revision check and DB write | No stale persisted answer | NOT_RUN |
| Cancel and receive late audio chunk | No playback or UI mutation in new conversation | NOT_RUN |
| Two-turn `blå elefant` voice recall | Second response recalls phrase without scripted answer | NOT_RUN |
| Fresh conversation after recall | Secret phrase absent unless reintroduced | NOT_RUN |
| Text → voice and voice → text | Prior completed turns preserved | NOT_RUN |
| Cloud off | History does not leave local rig | NOT_RUN |

## Merge ordering

Keep #2210 as the release-source reconciliation candidate and #2211 stacked on it. Do not merge either on the basis of this review. Exact-head checks, independent review, signing governance, and isolated physical Windows/Android evidence remain mandatory. Do not touch production worker 8099 or published APK.

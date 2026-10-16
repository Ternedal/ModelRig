# Kaliv voice v2.0.15 — isolated physical proof candidate (16 October 2026)

This branch snapshots the exact integration source from draft PR #2216 and
exists **only to trigger the existing** `.github/workflows/candidate-apk.yml`
and `a425f-apk.yml` on `physical-proof/**` pushes.

**NOT a release. Do not promote, tag, merge to main, or replace the installed
ModelRig backend/worker. Production activation: false.**

## Why two coordinated components are necessary

The stream-terminal fix (#2214) is **Android-only** and can be evaluated with
an unchanged v2.0.15 rig. It ends the client's NDJSON read on `done`/`error`
rather than waiting for TCP/HTTP body EOF.

The same-conversation recall fix (#2215) **requires both**:
1. Android sends `context_messages` with a bounded 12-message current-chat suffix.
2. The Python worker accepts and forwards these messages into the voice LLM call.

**Installing only this APK on an unchanged v2.0.15 worker does not enable
"blå elefant" recall.** Pydantic on the older worker may ignore the extra
request field. Full proof requires a separately approved/matched worker candidate.

The TTS text normalization fix is **worker-only**; the APK alone cannot change
symbol pronunciation either.

## Candidate gating

- Verify GitHub CI on the integration PR head SHA and the exact branch build SHA.
- Inspect and download the signed APK from the workflow artifact; never assume
  that building an APK publishes it through the app's normal update channel.
- Do not install a test APK until the operator explicitly chooses to test it.
- No Android SDK, USB or ADB required on the Windows rig to build the APK.
- If testing on the phone manually, read the artifact's SHA/build identity first.
  Never mislabel this candidate as a v2.0.16 release.

## Physical acceptance tests (not yet executed)

1. Rig running v2.0.15 and Android-only candidate: say a short question; tap
   **Tryk for at sende**; confirm the voice round-trip reaches an ending state
   rather than staying at **Tænker…**.
2. Say a longer passage; verify **Lytter…** means microphone capture, not
   processing. Explicitly tap **Tryk for at sende**, then confirm termination.
3. On a **matched approved worker+Android candidate**, in one conversation:
   say "Husk at mit testord er blå elefant", send, then ask
   "Hvad er mit testord?" and check the response cites **blå elefant**.
4. Start a fresh separate conversation and confirm history from the other chat
   is not implicitly injected (Memory 4 cross-conversation persistence is
   independently default-off).
5. With the matched worker, ask for an answer containing a Markdown link,
   bold/emphasis and a bare URL; check text stays legible but TTS does not
   spell Markdown markers or the URL.
6. Interrupt playback, repeat a voice turn, and verify no stuck UI state,
   hidden pending network call or duplicated assistant message.

Record pass/fail, exact source SHAs, APK SHA-256, phone app version, installed
backend/worker versions and relevant logs. Do not claim phone validation
until a real device has actually been tested.

# BodyRig ↔ VoiceRig compatibility

## Verified upstream snapshot

This note records the VoiceRig contract inspected while implementing BodyRig M0.2.

- repository: `Ternedal/VoiceRig`
- branch: `agent/voicerig-mvp`
- inspected candidate: `587e6cced8bde599a0f62d8bd181d9d9a45f5469` (RC25 at inspection time)
- endpoint: `POST /api/tts/synthesize`

At that candidate the synthesis endpoint returns a complete `audio/wav` response. Useful response headers include:

- `X-VoiceRig-Voice`
- `X-VoiceRig-Voice-ID`
- `X-VoiceRig-Package`
- `X-VoiceRig-Engine`
- `X-VoiceRig-Model`
- `X-VoiceRig-Revision`
- `X-VoiceRig-Sample-Rate`
- `X-VoiceRig-Duration`
- `X-VoiceRig-Device`

The inspected endpoint does **not** expose phoneme timestamps, viseme timestamps or a streaming speech-timing timeline.

This is a statement about the pinned inspected candidate, not a permanent claim about VoiceRig.

## BodyRig fidelity modes

BodyRig therefore defines two distinct timing modes.

### `audio_envelope`

Current compatibility mode for VoiceRig RC25.

BodyRig reads the returned PCM16 WAV locally and derives a short-window RMS energy envelope. The envelope can drive approximate mouth opening while the audio plays.

Properties:

- no text-to-phoneme guessing;
- no invented viseme identity;
- no network or ML dependency in the adapter;
- sample-rate and duration headers are checked against the actual WAV payload when supplied;
- header/payload disagreement fails closed;
- the resulting track is explicitly labelled `audio_envelope`.

This mode is **not phoneme-accurate lipsync**.

### `timed`

Higher-fidelity mode reserved for explicit upstream timing data.

A timed track may contain timestamped canonical viseme identifiers and weights. BodyRig accepts this mode only when timing data is explicitly supplied by an upstream component. It does not synthesize precise timing from text and then label that result as authoritative.

This keeps the protocol forward-compatible if VoiceRig later adds alignment or viseme output.

## Runtime flow today

```text
VoiceRig /api/tts/synthesize
        │
        ├── WAV payload
        ├── sample-rate header
        └── duration header
                │
                ▼
      BodyRig wav_envelope_track
                │
                ▼
      SpeechTrack(audio_envelope)
                │
                ▼
      EmbodimentScheduler
                │
        mouth energy + procedural
        state/gaze/expression hints
                │
                ▼
          renderer adapter
```

## Future upgrade path

If VoiceRig later supplies explicit speech timing, the integration becomes:

```text
VoiceRig audio + timed visemes
             │
             ▼
     BodyRig timed_track
             │
             ▼
     EmbodimentScheduler
```

The renderer and ModelRig semantic contracts do not need to change.

## Cancellation

Speech timing fidelity does not change interruption semantics.

On utterance cancellation:

1. `BodyRigRuntime` marks the utterance cancelled and leaves `speaking`;
2. `EmbodimentScheduler` removes the attached speech track;
3. subsequent render frames emit neutral mouth output;
4. the same utterance id cannot be reattached/restarted;
5. stale queued frames cannot reactivate it.

This property is more important to conversational presence than pretending approximate audio energy is precise lipsync.

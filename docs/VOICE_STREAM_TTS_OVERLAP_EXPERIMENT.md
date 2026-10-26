# Experimental VoiceRig/ModelRig voice-stream overlap (V1 unchanged)

**Draft; not physical qualification, not V1 release.**
This proposes one narrowly bounded runtime latency improvement in the Kaliv
voice pipeline. The qualified `main` SHA is not changed.

## Exact old versus proposed behavior

`converse()` currently streams LLM tokens, splits sentences, then calls
`await _synth(sentence)` **inside the LLM read loop**. Each Piper sentence
synthesis pauses consumption of model tokens until audio is finished.
The first sentence is spoken promptly, but sentence 2/3 generation and
synthesis become serialized unnecessarily.

The experiment schedules `asyncio.create_task(_synth(sentence))` with at
most **one** outstanding task; the next LLM token may be consumed while the
previous sentence's TTS runs through `asyncio.to_thread`. On the next
complete sentence, `_queue_sentence` must `await` that task before
starting another TTS. Thus TTS remains serial, callbacks remain ordered,
no unbounded queue or TTS fanout is created, and no model text is dropped.

- The original ASR/LLM/TTS models, configuration, output artifacts and APIs
  stay identical; cloud egress, tool authorization, model security,
  transcript privacy and file handling are **not** changed.
- The existing `_ASR_LOCK` and `_TTS_LOCK` remain authoritative. Same
  `on_transcript` and `on_chunk` callbacks, audio file naming, BodyRig
  speaker notes, chunk indexing and synthesis error behavior.
- No buffering entire replies before playing. Completion of the final
  synth is `await`ed in `finally`, even if the model stream fails.
- A failed TTS or model stream still raises; it never silently returns a
  success, fabricated WAV, release proof or production activation.

## Fail-closed offline proof

`tests/workflow_voice_tts_overlap.py` uses stubbed ASR, LLM and Piper with
no GPU, model server or network. A blocking fake Piper worker requires
the next LLM token to be consumed *before* the first synthesis completes.
The old sequential implementation fails this test; the new bounded
overlap implementation must pass. Additional tests verify ordered chunks,
max one simultaneous TTS, normal buffered API, joined synthesis on model
failure and no swallowed Piper errors. Existing `tests/worker_voice_stream.py`
must also remain green.

## What this does and does not prove

One-stage latency is expected to shrink only when LLM token generation
and CPU/GPU TTS are both substantial and can overlap without resource
contention. The two RTX 3060 GPUs might compete for VRAM/compute; benefits
may vanish or regress. This branch **does not contain a rig-side
benchmark** and cannot claim any measured millisecond speedup.

Before a software re-freeze: run full exact-head and CI/CodeQL on this exact
SHA; test real 20-clip Danish voice baseline, first-audio p50/p95, full turn
latency p50/p95, audio correctness, cancellation/barge-in, two simultaneous
turns, ASR/TTS device contention and all physical gates. Do not merge or
weaken any required gate without explicit user decision and independent
V1 software qualification.

# BodyCue v1 runtime boundary

ModelRig #704 requires the production integration to send **semantic BodyCue v1**, never bone/joint transforms.

The executable boundary is now:

```text
VoiceRig sentence
  -> exact utterance_id + track duration
  -> worker/app/body_cues.py policy (default off)
  -> modelrig-body-cue / version 1
  -> bodyrig.body_cue.validate_body_cue()
  -> same-body + exact utterance + optional duration binding
  -> semantic cue -> renderer-neutral expression plan
  -> BodyRigRuntime
  -> RenderFrame v0.1
```

## Authority rules

- `type` is exactly `modelrig-body-cue` and `version` is exactly `1`.
- `utterance_id` is mandatory and is copied from the actual VoiceRig speech chunk for speech cues.
- Applying a cue always requires caller-supplied utterance authority; there is no unbound public apply path.
- A speech cue is applied only when its `utterance_id` equals both caller authority and the runtime's active utterance.
- If a cue carries `duration_ms`, it must equal the VoiceRig track duration supplied by the caller; otherwise it fails closed.
- A cue naming another `body_id` is rejected.
- Unknown fields and unknown versions fail closed.
- The wire has no bone, joint, rotation, transform or engine-animation fields.
- `posture` is valid in the public v1 schema but the current runtime cannot realize it yet, so it fails closed rather than being silently ignored.
- Optional state emotion/energy cues are emitted only when the caller already has a real utterance id. The state hook does **not** invent one.
- `KALIV_BODY_CUES` remains default-off; only exact `1` enables the optional semantic policy.

## Current small policy

When enabled:

- long spoken sentences: semantic `gesture=explain`, `energy=0.5`;
- short spoken sentences: neutral semantic baseline, `energy=0.5`;
- state embellishments, when supplied a real utterance authority: `thinking -> curious`, `error -> concerned`, and idle/listening/interrupted -> neutral reset.

No sentiment or emotion is inferred from the sentence text.

## Deliberate separation

Body state (`thinking`, `speaking`, `interrupted`, etc.) and speech timing are separate runtime inputs. BodyCue carries optional semantic intent only. `duration_ms`, when present, is a consistency-bound timing hint; actual speech scheduling remains owned by VoiceRig timing/audio. Kaliv/Unity consumes BodyRig RenderFrame output; it does not receive raw BodyCue and does not decide semantic meaning.

This is software proof only. It does not activate BodyRig and does not replace #704/#846 physical Windows/Android/Quest acceptance.

`production_activation=false`.

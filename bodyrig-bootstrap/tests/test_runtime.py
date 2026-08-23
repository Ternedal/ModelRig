import pytest
from pydantic import ValidationError

from bodyrig.models import BodyCue, SpeechTiming
from bodyrig.runtime import BodyRuntime


def test_bodycue_fails_closed_on_unknown_field():
    with pytest.raises(ValidationError):
        BodyCue.model_validate({
            "type": "modelrig-body-cue",
            "version": 1,
            "utterance_id": "u-1",
            "emotion": "thoughtful",
            "raw_bone_rotation": 42,
        })


def test_runtime_rejects_stale_voice_timing():
    runtime = BodyRuntime()
    runtime.apply_cue(BodyCue(utterance_id="u-new", emotion="thoughtful"))
    with pytest.raises(ValueError, match="does not match"):
        runtime.apply_speech(SpeechTiming(utterance_id="u-old", state="start"))


def test_runtime_keeps_semantic_cue():
    runtime = BodyRuntime()
    state = runtime.apply_cue(BodyCue(
        utterance_id="u-1",
        emotion="amused",
        intensity=0.4,
        gesture="small_shrug",
        gaze="user",
    ))
    assert state.cue["gesture"] == "small_shrug"
    assert state.utterance_id == "u-1"

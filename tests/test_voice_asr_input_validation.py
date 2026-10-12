"""Regression tests for Kaliv Voice audio input validation (no model/GPU needed)."""
import sys
import types
from unittest.mock import Mock

import numpy as np
import pytest

from worker.app import voice_asr


@pytest.mark.parametrize("samples,rate", [
    (np.array([], dtype=np.float32), 16000),
    (np.array([0.0], dtype=np.float32), 0),
    (np.array([np.nan], dtype=np.float32), 16000),
    (np.array([np.inf], dtype=np.float32), 16000),
])
def test_invalid_audio_rejected_before_transcription(monkeypatch, samples, rate):
    model = Mock()
    monkeypatch.setattr(voice_asr, "_get_model", lambda: model)
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=lambda *a, **kw: (samples, rate)))
    with pytest.raises(ValueError, match="Unable to decode audio"):
        voice_asr.transcribe_wav("bad.wav")
    model.transcribe.assert_not_called()


def test_valid_audio_disables_previous_text_conditioning(monkeypatch):
    model = Mock()
    model.transcribe.return_value = (iter([]), types.SimpleNamespace(language="da", duration=1.0))
    monkeypatch.setattr(voice_asr, "_get_model", lambda: model)
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=lambda *a, **kw: (np.zeros(16000, dtype=np.float32), 16000)))
    result = voice_asr.transcribe_wav("valid.wav")
    assert result["text"] == ""
    assert model.transcribe.call_args.kwargs["condition_on_previous_text"] is False


def test_stereo_audio_downmixed_to_mono(monkeypatch):
    model = Mock()
    model.transcribe.return_value = (iter([]), types.SimpleNamespace(language="da", duration=0.5))
    monkeypatch.setattr(voice_asr, "_get_model", lambda: model)
    stereo = np.column_stack((np.ones(8000, dtype=np.float32), np.zeros(8000, dtype=np.float32)))
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=lambda *a, **kw: (stereo, 16000)))
    voice_asr.transcribe_wav("stereo.wav")
    mono = model.transcribe.call_args.args[0]
    assert mono.shape == (8000,)
    np.testing.assert_allclose(mono, 0.5)


def test_48khz_audio_resampled_to_16khz(monkeypatch):
    model = Mock()
    model.transcribe.return_value = (iter([]), types.SimpleNamespace(language="da", duration=1.0))
    monkeypatch.setattr(voice_asr, "_get_model", lambda: model)
    monkeypatch.setitem(sys.modules, "soundfile", types.SimpleNamespace(read=lambda *a, **kw: (np.zeros(48000, dtype=np.float32), 48000)))
    voice_asr.transcribe_wav("48k.wav")
    audio = model.transcribe.call_args.args[0]
    assert audio.shape == (16000,)
    assert audio.dtype == np.float32

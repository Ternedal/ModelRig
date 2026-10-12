"""GPU-free Kaliv Voice input regressions, runnable by CI's Python glob runner."""
import sys
import types
import unittest
from unittest.mock import Mock, patch

import numpy as np
from worker.app import voice_asr


class VoiceAudioInputTests(unittest.TestCase):
    def _run(self, samples, rate):
        model = Mock()
        model.transcribe.return_value = (iter([]), types.SimpleNamespace(language="da", duration=1.0))
        sf = types.SimpleNamespace(read=lambda *args, **kwargs: (samples, rate))
        with patch.object(voice_asr, "_get_model", return_value=model), patch.dict(sys.modules, {"soundfile": sf}):
            result = voice_asr.transcribe_wav("fixture.wav")
        return model, result

    def test_invalid_samples(self):
        for samples, rate in ((np.array([], dtype=np.float32), 16000),
                              (np.zeros(1, dtype=np.float32), 0),
                              (np.array([np.nan], dtype=np.float32), 16000),
                              (np.array([np.inf], dtype=np.float32), 16000)):
            with self.subTest(rate=rate, samples=str(samples)):
                model = Mock()
                sf = types.SimpleNamespace(read=lambda *a, **kw: (samples, rate))
                with patch.object(voice_asr, "_get_model", return_value=model), patch.dict(sys.modules, {"soundfile": sf}):
                    with self.assertRaisesRegex(ValueError, "Unable to decode audio"):
                        voice_asr.transcribe_wav("bad.wav")
                model.transcribe.assert_not_called()

    def test_conditioning_disabled(self):
        model, result = self._run(np.zeros(16000, dtype=np.float32), 16000)
        self.assertEqual(result["text"], "")
        self.assertIs(model.transcribe.call_args.kwargs["condition_on_previous_text"], False)

    def test_stereo_downmix(self):
        stereo = np.column_stack((np.ones(8000, dtype=np.float32), np.zeros(8000, dtype=np.float32)))
        model, _ = self._run(stereo, 16000)
        audio = model.transcribe.call_args.args[0]
        self.assertEqual(audio.shape, (8000,))
        np.testing.assert_allclose(audio, 0.5)

    def test_48khz_resampling(self):
        model, _ = self._run(np.zeros(48000, dtype=np.float32), 48000)
        audio = model.transcribe.call_args.args[0]
        self.assertEqual(audio.shape, (16000,))
        self.assertEqual(audio.dtype, np.float32)


if __name__ == "__main__":
    unittest.main()

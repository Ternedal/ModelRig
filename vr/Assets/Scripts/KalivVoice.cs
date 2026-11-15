using System;
using System.Collections.Generic;
using UnityEngine;
#if UNITY_ANDROID && !UNITY_EDITOR
using UnityEngine.Android;
#endif

namespace Kaliv.VR
{
    /// <summary>
    /// Microphone in, Kaliv's voice out.
    ///
    /// In: tap to talk, tap again to send. A hold-to-talk button is natural on a phone but
    /// awkward with a VR controller ray that drifts off the button while you speak, so the
    /// headset gets a toggle. The capture is bounded (60 s) and resampled to the rig's
    /// 16 kHz mono in KalivWav, never trusting the device's own rate.
    ///
    /// Out: sentences play in order as they arrive, from an AudioSource placed on Kaliv's
    /// body — in a headset her voice should come from where she stands, not from inside
    /// your head. Each sentence reports started/ended so the rig's mouth follows the audio
    /// actually playing.
    /// </summary>
    public sealed class KalivVoice : MonoBehaviour
    {
        public const int MaxRecordSeconds = 60;
        /// <summary>Below this peak the recording is treated as silence and not sent.</summary>
        public const float SilencePeak = 0.02f;

        private AudioSource _source;
        private string _device;
        private AudioClip _recording;
        private int _recordRate;
        private float _level;

        private readonly SortedDictionary<int, (AudioClip clip, string utterance)> _pending =
            new SortedDictionary<int, (AudioClip, string)>();
        private int _nextIndex;
        private string _playingUtterance;
        private bool _speaking;

        public bool IsRecording => _recording != null && Microphone.IsRecording(_device);
        public bool IsSpeaking => _speaking || _pending.Count > 0;
        /// <summary>0..1 peak of the last ~100 ms, for the "Kaliv hears you" indicator.</summary>
        public float Level => _level;
        public float RecordedSeconds { get; private set; }

        /// <summary>(utteranceId, "started" | "ended") — wired to the body speech reporter.</summary>
        public event Action<string, string> SpeechEvent;
        public event Action SpeakingFinished;

        public void Initialize(Transform voiceAnchor)
        {
            var go = new GameObject("KalivVoice.Source");
            go.transform.SetParent(voiceAnchor != null ? voiceAnchor : transform, false);
            // Roughly mouth height on a standing avatar whose root is at the floor.
            go.transform.localPosition = voiceAnchor != null ? new Vector3(0f, 1.55f, 0f) : Vector3.zero;
            _source = go.AddComponent<AudioSource>();
            _source.playOnAwake = false;
            _source.loop = false;
            _source.spatialBlend = voiceAnchor != null ? 1f : 0f;
            _source.rolloffMode = AudioRolloffMode.Linear;
            _source.minDistance = 1.5f;
            _source.maxDistance = 12f;
            _source.dopplerLevel = 0f;
        }

        // ---- microphone ---------------------------------------------------------------------

        public bool HasMicrophone => Microphone.devices != null && Microphone.devices.Length > 0;

        public bool HasPermission
        {
            get
            {
#if UNITY_ANDROID && !UNITY_EDITOR
                return Permission.HasUserAuthorizedPermission(Permission.Microphone);
#else
                return true;
#endif
            }
        }

        public void RequestPermission()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!Permission.HasUserAuthorizedPermission(Permission.Microphone))
                Permission.RequestUserPermission(Permission.Microphone);
#endif
        }

        /// <summary>Start recording. Returns an error text, or null on success.</summary>
        public string StartRecording()
        {
            if (!HasPermission) { RequestPermission(); return "Giv Kaliv VR adgang til mikrofonen, og tryk igen."; }
            if (!HasMicrophone) return "Ingen mikrofon fundet i headsettet.";
            StopSpeaking();   // barge-in: talking over Kaliv stops her, as on Android

            _device = Microphone.devices[0];
            Microphone.GetDeviceCaps(_device, out int minRate, out int maxRate);
            // 0/0 means "any rate". Prefer the rig's own 16 kHz when the device offers it.
            _recordRate = (minRate == 0 && maxRate == 0) ? KalivWav.RigSampleRate
                : Mathf.Clamp(KalivWav.RigSampleRate, minRate, maxRate);
            _recording = Microphone.Start(_device, false, MaxRecordSeconds, _recordRate);
            if (_recording == null) return "Mikrofonen kunne ikke startes.";
            _recordRate = _recording.frequency;
            RecordedSeconds = 0f;
            return null;
        }

        /// <summary>Stop and return a rig-ready WAV, or null with a reason.</summary>
        public byte[] StopRecording(out string reason)
        {
            reason = null;
            if (_recording == null) { reason = "Der blev ikke optaget noget."; return null; }

            int length = Microphone.GetPosition(_device);
            bool wrapped = !Microphone.IsRecording(_device);   // hit the 60 s cap
            Microphone.End(_device);
            if (wrapped || length <= 0) length = _recording.samples;

            var raw = new float[length * _recording.channels];
            _recording.GetData(raw, 0);
            float[] mono = ToMono(raw, _recording.channels);
            int rate = _recordRate;
            Destroy(_recording);
            _recording = null;
            _level = 0f;

            if (mono.Length < rate / 4) { reason = "Optagelsen var for kort."; return null; }
            if (KalivWav.Peak(mono) < SilencePeak) { reason = "Der kom ingen lyd igennem — tal tættere på headsettet."; return null; }
            return KalivWav.EncodeForRig(mono, rate);
        }

        public void CancelRecording()
        {
            if (_recording == null) return;
            Microphone.End(_device);
            Destroy(_recording);
            _recording = null;
            _level = 0f;
        }

        private static float[] ToMono(float[] interleaved, int channels)
        {
            if (channels <= 1) return interleaved;
            var mono = new float[interleaved.Length / channels];
            for (int i = 0; i < mono.Length; i++)
            {
                float sum = 0f;
                for (int c = 0; c < channels; c++) sum += interleaved[i * channels + c];
                mono[i] = sum / channels;
            }
            return mono;
        }

        // ---- playback -----------------------------------------------------------------------

        /// <summary>Start a new spoken reply: chunk indices restart at 0.</summary>
        public void BeginReply()
        {
            StopSpeaking();
            _nextIndex = 0;
        }

        /// <summary>
        /// Queue one sentence. Decoding failures drop the sentence's audio but keep the order
        /// moving: one bad chunk must not silence everything after it.
        /// </summary>
        public bool EnqueueChunk(int index, string audioB64, string utteranceId, out string error)
        {
            error = null;
            if (index < _nextIndex || _pending.ContainsKey(index)) return false;   // late or duplicate; never replay

            AudioClip clip = null;
            try
            {
                var pcm = KalivWav.Decode(Convert.FromBase64String(audioB64 ?? ""));
                int frames = pcm.Samples.Length / pcm.Channels;
                if (frames > 0)
                {
                    clip = AudioClip.Create("kaliv-" + index, frames, pcm.Channels, pcm.SampleRate, false);
                    clip.SetData(pcm.Samples, 0);
                }
            }
            catch (FormatException e) { error = e.Message; }

            _pending[index] = (clip, utteranceId);
            return error == null;
        }

        public void StopSpeaking()
        {
            if (_source != null && _source.isPlaying) _source.Stop();
            if (_playingUtterance != null) SpeechEvent?.Invoke(_playingUtterance, "ended");
            _playingUtterance = null;
            foreach (var kv in _pending) if (kv.Value.clip != null) Destroy(kv.Value.clip);
            _pending.Clear();
            bool was = _speaking;
            _speaking = false;
            if (was) SpeakingFinished?.Invoke();
        }

        private void Update()
        {
            UpdateLevel();

            if (_source == null) return;
            if (_source.isPlaying) return;

            // The previous sentence ended.
            if (_playingUtterance != null)
            {
                SpeechEvent?.Invoke(_playingUtterance, "ended");
                _playingUtterance = null;
            }
            if (_source.clip != null)
            {
                Destroy(_source.clip);
                _source.clip = null;
            }

            // Play strictly in index order; wait for a missing index rather than skip it.
            if (_pending.TryGetValue(_nextIndex, out var next))
            {
                _pending.Remove(_nextIndex);
                _nextIndex++;
                _speaking = true;
                if (next.clip != null)
                {
                    _source.clip = next.clip;
                    _source.Play();
                    _playingUtterance = next.utterance;
                    if (_playingUtterance != null) SpeechEvent?.Invoke(_playingUtterance, "started");
                }
                return;
            }

            if (_speaking && _pending.Count == 0)
            {
                _speaking = false;
                SpeakingFinished?.Invoke();
            }
        }

        private void UpdateLevel()
        {
            if (_recording == null || !Microphone.IsRecording(_device)) return;
            int pos = Microphone.GetPosition(_device);
            RecordedSeconds = (float)pos / Mathf.Max(1, _recording.frequency);
            int window = Mathf.Max(1, _recording.frequency / 10);
            int start = pos - window;
            if (start < 0) { _level = Mathf.Lerp(_level, 0f, 0.2f); return; }
            var buf = new float[window * _recording.channels];
            _recording.GetData(buf, start);
            _level = Mathf.Lerp(_level, KalivWav.Peak(buf), 0.5f);
        }

        private void OnDestroy()
        {
            CancelRecording();
            StopSpeaking();
        }
    }
}

using System;
using SkyPlayer.Engine;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Kaliv-owned media presentation facade over SkyPlayer-Engine.
    ///
    /// SkyPlayer-Engine owns decoding/projection mechanics; Kaliv owns where the
    /// generated geometry lives in the product scenegraph and how origin shifts
    /// are propagated into immersive projection orientation.
    /// </summary>
    public sealed class KalivVrMediaRenderer : MonoBehaviour
    {
        private VrPlayer _player;

        public bool IsPrepared => _player != null && _player.IsPrepared;
        public bool IsPlaying => _player != null && _player.IsPlaying;
        public double Length => _player?.Length ?? 0;
        public double Time => _player?.Time ?? 0;
        public string FormatLabel => _player?.FormatLabel ?? "";

        public event Action<string> StateChanged;
        public event Action<GameObject> DisplayChanged;
        public event Action Ended;

        public void Initialize(Camera camera, Transform mediaRoot, int mediaLayer)
        {
            if (camera == null) throw new ArgumentNullException(nameof(camera));
            if (mediaRoot == null) throw new ArgumentNullException(nameof(mediaRoot));

            _player = gameObject.GetComponent<VrPlayer>();
            if (_player == null) _player = gameObject.AddComponent<VrPlayer>();

            _player.SetPresentationRoot(mediaRoot, mediaLayer);
            _player.StateChanged += OnPlayerStateChanged;
            _player.DisplayChanged += OnPlayerDisplayChanged;
            _player.Ended += OnPlayerEnded;
            _player.Initialize(camera);
        }

        public void Open(string url, string formatHint = "FLAT", double resumeSeconds = 0)
        {
            if (_player == null)
                throw new InvalidOperationException("Kaliv VR media renderer is not initialized.");

            _player.Open(
                new MediaSource(url, resumeSeconds),
                Projection.FromHint(formatHint));
        }

        public void SetFormat(string formatHint) => _player?.SetFormatHint(formatHint);
        public void TogglePlayPause() => _player?.TogglePlayPause();
        public void Play() => _player?.Play();
        public void Pause() => _player?.Pause();
        public void Stop() => _player?.Stop();
        public void Seek(float fraction01) => _player?.Seek(fraction01);
        public void SeekRelative(double seconds) => _player?.SeekRelative(seconds);
        public void Recenter() => _player?.Recenter();
        public void AdjustZoom(float delta) => _player?.AdjustZoom(delta);
        public void Pan(float yawDegrees, float pitchDegrees) => _player?.Pan(yawDegrees, pitchDegrees);

        public void ApplyOriginShift(Quaternion rotationDelta)
        {
            if (_player == null || _player.Projection.Geometry != Geometry.Sphere)
                return;

            _player.ApplyOriginShift(rotationDelta);
        }

        private void OnPlayerStateChanged(string state) => StateChanged?.Invoke(state);
        private void OnPlayerDisplayChanged(GameObject display) => DisplayChanged?.Invoke(display);
        private void OnPlayerEnded() => Ended?.Invoke();

        private void OnDestroy()
        {
            if (_player == null) return;
            _player.StateChanged -= OnPlayerStateChanged;
            _player.DisplayChanged -= OnPlayerDisplayChanged;
            _player.Ended -= OnPlayerEnded;
        }
    }
}

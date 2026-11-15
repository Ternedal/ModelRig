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
            // Start fully zoomed out — the widest span, most pixels per degree. Anders' own
            // SkyPlayer setting on the headset is defaultZoom 0 (read 15 Nov); Kaliv VR started
            // at 0.4, i.e. magnified, which is why the same video looked grainier here.
            _player.SetDefaultZoom(0f);
        }

        /// <summary>Zoom each new video starts at (0 = widest). The app remembers the user's last one.</summary>
        public float StartZoom { get; set; }

        /// <summary>Current zoom of an immersive video, 0..1 (0 = widest).</summary>
        public float Zoom01 => _player != null ? _player.Zoom01 : 0f;

        public void Open(string url, string formatHint = "FLAT", double resumeSeconds = 0)
        {
            if (_player == null)
                throw new InvalidOperationException("Kaliv VR media renderer is not initialized.");

            _player.SetDefaultZoom(Mathf.Clamp01(StartZoom));
            SetDisplayVisible(true);
            _player.Open(
                new MediaSource(url, resumeSeconds),
                Projection.FromHint(formatHint));
        }

        public void SetFormat(string formatHint) => _player?.SetFormatHint(formatHint);
        public void TogglePlayPause() => _player?.TogglePlayPause();
        public void Play() => _player?.Play();
        public void Pause() => _player?.Pause();

        /// <summary>
        /// Stop AND take the picture away. The engine's Stop only pauses, leaving the last frame
        /// on the sphere — behind the menu after LUK, which is what Anders saw. The next Open
        /// builds a fresh display, so hiding the renderers here is enough.
        /// </summary>
        public void Stop()
        {
            _player?.Stop();
            SetDisplayVisible(false);
        }

        private void SetDisplayVisible(bool visible)
        {
            foreach (var r in GetComponentsInChildren<Renderer>(true)) r.enabled = visible;
            if (_player == null) return;
            // The display may be parented elsewhere (the engine's presentation root).
            foreach (var r in _player.GetComponentsInChildren<Renderer>(true)) r.enabled = visible;
        }
        public void Seek(float fraction01) => _player?.Seek(fraction01);
        public void SeekRelative(double seconds) => _player?.SeekRelative(seconds);
        public void Recenter() => _player?.Recenter();
        public void AdjustZoom(float delta) => _player?.AdjustZoom(delta);
        public void Pan(float yawDegrees, float pitchDegrees) => _player?.Pan(yawDegrees, pitchDegrees);

        /// <summary>
        /// The engine's AR background key (RUM): removes the video's backdrop so the people in
        /// it stand in the real room through passthrough. Only acts on 180°/360° video — the
        /// engine itself ignores it for flat.
        /// </summary>
        public void ApplyBackgroundKey(BackgroundKeySettings settings) => _player?.ApplyBackgroundKey(settings);

        /// <summary>PIPET: read the video's colour where the user looks, so that colour can be keyed.</summary>
        public bool TrySampleKeyColorAtGaze(out Color color)
        {
            color = Color.clear;
            return _player != null && _player.TrySampleKeyColorAtGaze(out color);
        }

        public bool IsImmersive => _player != null && _player.Projection.Geometry == Geometry.Sphere;

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

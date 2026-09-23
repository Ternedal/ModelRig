using System;
using SkyPlayer.Engine;
using UniVRM10;
using UnityEngine;
using UnityEngine.Rendering;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Kaliv VR's product rendering engine.
    ///
    /// Owns spatial presence, avatar lifecycle, scene lighting and the bridge from
    /// authenticated ModelRig/BodyRig state into a local VRM render target.
    /// It does not own body intelligence or motion semantics: those remain BodyRig authority.
    /// </summary>
    public sealed class KalivVrRenderEngine : MonoBehaviour
    {
        private Camera _camera;
        private KalivVrComposition _composition;
        private KalivTrackingOriginCompensator _trackingOrigin;
        private KalivSpatialTargetRegistry _spatialTargets;
        private KalivVrMediaRenderer _mediaRenderer;
        private GameObject _bodyRoot;
        private KalivVrmRenderer _renderer;
        private KalivVrmAvatarLoader _loader;
        private KalivBodyFrameStream _frames;
        private KalivBodyRevisionWatcher _revisionWatcher;
        private KalivVrmaMotionController _motionController;
        private Light _keyLight;
        private string _baseUrl;
        private string _token;

        public bool AvatarReady => _loader != null && _loader.Current != null;
        public bool LiveFrames => _frames != null && _frames.IsConnected;
        public bool MediaPrepared => _mediaRenderer != null && _mediaRenderer.IsPrepared;
        public bool MediaPlaying => _mediaRenderer != null && _mediaRenderer.IsPlaying;
        public string ActiveBodyId => _loader?.BodyId;
        public string ActiveBodyName => _loader?.BodyName;
        public Transform BodyRoot => _composition?.BodyRoot;
        public Transform MediaRoot => _composition?.MediaRoot;
        public Transform UiRoot => _composition?.UiRoot;
        public Transform DebugRoot => _composition?.DebugRoot;

        public event Action<string, bool> StatusChanged;

        public void Initialize(Camera camera)
        {
            _camera = camera != null ? camera : throw new ArgumentNullException(nameof(camera));

            _composition = gameObject.GetComponent<KalivVrComposition>();
            if (_composition == null)
                _composition = gameObject.AddComponent<KalivVrComposition>();
            _composition.Initialize();

            _trackingOrigin = gameObject.GetComponent<KalivTrackingOriginCompensator>();
            if (_trackingOrigin == null)
                _trackingOrigin = gameObject.AddComponent<KalivTrackingOriginCompensator>();
            _trackingOrigin.Initialize(_camera, transform);

            _bodyRoot = _composition.BodyRoot.gameObject;
            _spatialTargets = gameObject.GetComponent<KalivSpatialTargetRegistry>();
            if (_spatialTargets == null)
                _spatialTargets = gameObject.AddComponent<KalivSpatialTargetRegistry>();

            _renderer = _bodyRoot.AddComponent<KalivVrmRenderer>();
            _loader = _bodyRoot.AddComponent<KalivVrmAvatarLoader>();
            _frames = _bodyRoot.AddComponent<KalivBodyFrameStream>();
            _revisionWatcher = _bodyRoot.AddComponent<KalivBodyRevisionWatcher>();
            _motionController = _bodyRoot.AddComponent<KalivVrmaMotionController>();
            _renderer.SetSpatialTargetRegistry(_spatialTargets);

            _mediaRenderer = _composition.MediaRoot.gameObject.AddComponent<KalivVrMediaRenderer>();
            _mediaRenderer.Initialize(_camera, _composition.MediaRoot, _composition.MediaLayer);
            _mediaRenderer.DisplayChanged += OnMediaDisplayChanged;
            _trackingOrigin.OriginShifted += OnOriginShifted;

            _loader.Initialize(_renderer, _camera.transform);
            _loader.AvatarLoaded += OnAvatarLoaded;
            _loader.LoadFailed += message => StatusChanged?.Invoke(message, true);
            _frames.StreamWarning += message => StatusChanged?.Invoke(message, true);
            _frames.FrameApplied += OnFrameApplied;
            _revisionWatcher.RevisionChanged += OnBodyRevisionChanged;
            _revisionWatcher.WatchWarning += message => Debug.LogWarning("[KalivVR.Render] " + message);
            _motionController.MotionStatus += message => Debug.Log("[KalivVR.Motion] " + message);
            _motionController.MotionWarning += message => Debug.LogWarning("[KalivVR.Motion] " + message);

            ConfigureScene();
            PassthroughFeature.SetEnabled(true);
            StatusChanged?.Invoke("Renderer klar · ingen aktiv krop endnu", false);
        }

        public void Connect(string baseUrl, string token)
        {
            _baseUrl = (baseUrl ?? "").Trim().TrimEnd('/');
            _token = token ?? "";

            if (string.IsNullOrWhiteSpace(_baseUrl) || string.IsNullOrWhiteSpace(_token))
            {
                Disconnect();
                return;
            }

            _revisionWatcher.StopWatching();
            _frames.StopStreaming();
            _motionController.ResetRevision();
            _loader.Unload();
            StatusChanged?.Invoke("Henter aktiv BodyRig-krop …", false);
            StartCoroutine(_loader.LoadActiveFromRig(_baseUrl, _token));
        }

        public void AttachUi(GameObject root)
        {
            if (root == null || _composition == null) return;
            root.transform.SetParent(_composition.UiRoot, true);
            _composition.ApplyUi(root);
        }

        public void AttachMedia(GameObject root)
        {
            if (root == null || _composition == null) return;
            root.transform.SetParent(_composition.MediaRoot, true);
            _composition.ApplyMedia(root);
        }

        public void AttachDebug(GameObject root)
        {
            if (root == null || _composition == null) return;
            root.transform.SetParent(_composition.DebugRoot, true);
            _composition.ApplyDebug(root);
        }

        public void OpenMedia(string url, string formatHint = "FLAT", double resumeSeconds = 0) =>
            _mediaRenderer?.Open(url, formatHint, resumeSeconds);

        public void StopMedia() => _mediaRenderer?.Stop();
        public void ToggleMediaPlayback() => _mediaRenderer?.TogglePlayPause();
        public void SeekMedia(float fraction01) => _mediaRenderer?.Seek(fraction01);
        public void SeekMediaRelative(double seconds) => _mediaRenderer?.SeekRelative(seconds);
        public void SetMediaFormat(string formatHint) => _mediaRenderer?.SetFormat(formatHint);
        public void RecenterMedia() => _mediaRenderer?.Recenter();
        public void AdjustMediaZoom(float delta) => _mediaRenderer?.AdjustZoom(delta);
        public void PanMedia(float yawDegrees, float pitchDegrees) =>
            _mediaRenderer?.Pan(yawDegrees, pitchDegrees);

        public void RegisterObjectTarget(string id, Transform target) =>
            _spatialTargets?.RegisterObject(id, target);

        public void RegisterWorldTarget(string id, Transform target) =>
            _spatialTargets?.RegisterWorld(id, target);

        public bool UnregisterSpatialTarget(string semanticTarget) =>
            _spatialTargets != null && _spatialTargets.Unregister(semanticTarget);

        public void RefreshBody()
        {
            if (!string.IsNullOrWhiteSpace(_baseUrl) && !string.IsNullOrWhiteSpace(_token))
                Connect(_baseUrl, _token);
        }

        public void Disconnect()
        {
            _revisionWatcher?.StopWatching();
            _frames?.StopStreaming();
            _motionController?.ResetRevision();
            _loader?.Unload();
            _mediaRenderer?.Stop();
            _baseUrl = "";
            _token = "";
            StatusChanged?.Invoke("Renderer afkoblet", false);
        }

        public void RecenterPresence()
        {
            if (_camera == null || _bodyRoot == null) return;

            Vector3 forward = _camera.transform.forward;
            forward.y = 0f;
            if (forward.sqrMagnitude < 0.001f) forward = Vector3.forward;
            forward.Normalize();

            // XR Origin is floor-based. Keep feet at floor level and place Kaliv
            // at conversational distance in front of the user.
            Vector3 cameraPos = _camera.transform.position;
            _bodyRoot.transform.position = new Vector3(
                cameraPos.x + forward.x * 1.85f,
                0f,
                cameraPos.z + forward.z * 1.85f);

            Vector3 towardUser = _camera.transform.position - _bodyRoot.transform.position;
            towardUser.y = 0f;
            if (towardUser.sqrMagnitude > 0.001f)
                _bodyRoot.transform.rotation = Quaternion.LookRotation(towardUser.normalized, Vector3.up);
        }

        private void OnAvatarLoaded(Vrm10Instance instance)
        {
            _composition?.ApplyBody(instance.gameObject);
            KalivQuestRenderBudget.Log(instance.gameObject);
            KalivQuestRenderBudget.LogScene(gameObject, "avatar-loaded");
            RecenterPresence();
            _motionController.BindRevision(
                instance,
                _renderer,
                _baseUrl,
                _token,
                _loader.BodyId,
                _loader.PackageSha256,
                _loader.MotionNames);

            _frames.Configure(_renderer, _baseUrl, _token);
            _frames.StartStreaming();

            _revisionWatcher.Configure(_baseUrl, _token);
            _revisionWatcher.SetCurrent(_loader.BodyId, _loader.PackageSha256);
            _revisionWatcher.StartWatching();

            string name = string.IsNullOrWhiteSpace(_loader.BodyName) ? "Krop" : _loader.BodyName;
            StatusChanged?.Invoke(
                $"{name} · {_loader.HeightScale:0.00}× · live BodyRig-frames",
                false);
        }

        private void OnBodyRevisionChanged(string bodyId, string packageSha)
        {
            StatusChanged?.Invoke("BodyRig skiftede krop/revision · genindlæser …", false);
            Connect(_baseUrl, _token);
        }

        private void OnOriginShifted(Quaternion rotationDelta, Vector3 translationDelta)
        {
            _mediaRenderer?.ApplyOriginShift(rotationDelta);
        }

        private void OnMediaDisplayChanged(GameObject display)
        {
            KalivQuestRenderBudget.LogScene(
                gameObject,
                display == null ? "media-cleared" : "media-display-changed");
        }

        private void OnFrameApplied(KalivBodyRenderFrame frame)
        {
            if (frame == null) return;
            _motionController?.ApplyFrame(frame);
            // Deliberately presentation-only. BodyRig remains state authority.
            if (frame.state == "error")
                StatusChanged?.Invoke("BodyRig rapporterer fejltilstand", true);
        }

        private void Update()
        {
            PassthroughFeature.LogDiagOnce();
        }

        private void ConfigureScene()
        {
            RenderSettings.ambientMode = AmbientMode.Flat;
            RenderSettings.ambientLight = new Color(0.31f, 0.29f, 0.26f, 1f);

            var lightGo = new GameObject("KalivVR.RenderEngine.KeyLight");
            lightGo.transform.SetParent(transform, false);
            lightGo.transform.rotation = Quaternion.Euler(42f, -28f, 0f);
            _keyLight = lightGo.AddComponent<Light>();
            _keyLight.type = LightType.Directional;
            _keyLight.intensity = 1.05f;
            _keyLight.color = new Color(1.0f, 0.94f, 0.82f, 1f);
            _keyLight.shadows = LightShadows.Soft;
        }

        private void OnDestroy()
        {
            if (_loader != null)
                _loader.AvatarLoaded -= OnAvatarLoaded;
            if (_frames != null)
                _frames.FrameApplied -= OnFrameApplied;
            if (_revisionWatcher != null)
                _revisionWatcher.RevisionChanged -= OnBodyRevisionChanged;
            if (_mediaRenderer != null)
                _mediaRenderer.DisplayChanged -= OnMediaDisplayChanged;
            if (_trackingOrigin != null)
                _trackingOrigin.OriginShifted -= OnOriginShifted;
        }
    }
}

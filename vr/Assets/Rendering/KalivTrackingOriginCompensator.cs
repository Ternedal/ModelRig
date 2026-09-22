using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.XR;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Keeps world-locked Kaliv presentation visually stable when Quest changes
    /// its tracking origin (system recenter, tracking recovery, guardian changes).
    ///
    /// The HMD is never moved. Instead the whole Kaliv composition receives the
    /// same rigid pose delta that the camera reported across the origin change.
    /// </summary>
    [DefaultExecutionOrder(12000)]
    public sealed class KalivTrackingOriginCompensator : MonoBehaviour
    {
        private readonly List<XRInputSubsystem> _subsystems = new List<XRInputSubsystem>();

        private Camera _camera;
        private Transform _presentationRoot;
        private bool _hooked;
        private bool _dirty;
        private int _dirtyFrame = -1;
        private bool _havePose;
        private float _retryAt;
        private Vector3 _previousPosition;
        private Quaternion _previousRotation = Quaternion.identity;

        public event Action<Quaternion, Vector3> OriginShifted;

        public void Initialize(Camera camera, Transform presentationRoot)
        {
            _camera = camera;
            _presentationRoot = presentationRoot;
            CapturePose();
        }

        private void Update()
        {
            EnsureHooked();
        }

        private void LateUpdate()
        {
            if (_camera == null || _presentationRoot == null) return;

            Vector3 currentPosition = _camera.transform.position;
            Quaternion currentRotation = _camera.transform.rotation;

            if (_dirty && _havePose)
            {
                // Preserve the last pre-event HMD pose. Updating _previous* in the
                // event frame would erase the very delta we need to compensate.
                if (Time.frameCount <= _dirtyFrame)
                    return;

                Quaternion rotationDelta =
                    currentRotation * Quaternion.Inverse(_previousRotation);
                float angle = Quaternion.Angle(rotationDelta, Quaternion.identity);
                float translation = Vector3.Distance(currentPosition, _previousPosition);

                // Some runtimes announce an origin update one frame before the
                // tracked camera pose settles. Hold the old authority briefly
                // rather than consuming a false identity delta.
                bool settledDelta = angle > 0.001f || translation > 0.0001f;
                if (!settledDelta && Time.frameCount <= _dirtyFrame + 3)
                    return;

                Vector3 oldRelative =
                    _presentationRoot.position - _previousPosition;
                _presentationRoot.position =
                    currentPosition + rotationDelta * oldRelative;
                _presentationRoot.rotation =
                    rotationDelta * _presentationRoot.rotation;

                Vector3 translationDelta = currentPosition - _previousPosition;
                _dirty = false;
                _dirtyFrame = -1;

                OriginShifted?.Invoke(rotationDelta, translationDelta);

                Debug.Log(
                    $"[KalivVR.XR] tracking origin shifted: " +
                    $"{angle:0.0}° / {translation:0.000} m · composition compensated");
            }

            _previousPosition = currentPosition;
            _previousRotation = currentRotation;
            _havePose = true;
        }

        private void EnsureHooked()
        {
            if (_hooked || Time.unscaledTime < _retryAt) return;
            _retryAt = Time.unscaledTime + 2f;

            _subsystems.Clear();
            SubsystemManager.GetSubsystems(_subsystems);
            if (_subsystems.Count == 0) return;

            foreach (var subsystem in _subsystems)
            {
                if (subsystem != null)
                    subsystem.trackingOriginUpdated += OnTrackingOriginUpdated;
            }

            _hooked = true;
            Debug.Log(
                $"[KalivVR.XR] tracking-origin compensation active " +
                $"({_subsystems.Count} subsystem(s))");
        }

        private void OnTrackingOriginUpdated(XRInputSubsystem subsystem)
        {
            _dirty = true;
            _dirtyFrame = Time.frameCount;
        }

        private void CapturePose()
        {
            if (_camera == null) return;
            _previousPosition = _camera.transform.position;
            _previousRotation = _camera.transform.rotation;
            _havePose = true;
        }

        private void OnDestroy()
        {
            foreach (var subsystem in _subsystems)
            {
                if (subsystem != null)
                    subsystem.trackingOriginUpdated -= OnTrackingOriginUpdated;
            }
            _subsystems.Clear();
            _hooked = false;
        }
    }
}

#if BODYRIG_AR
using UnityEngine;
using UnityEngine.XR.ARCore;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.Management;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Emits one non-secret marker only after the Android AR stack is genuinely
    /// live. It grants no placement, release or production authority.
    /// </summary>
    public sealed class BodyRigArRuntimeProbe : MonoBehaviour
    {
        public ARCameraManager CameraManager { get; set; }
        public ARCameraBackground CameraBackground { get; set; }
        public ARPlaneManager PlaneManager { get; set; }
        public ARRaycastManager RaycastManager { get; set; }

        public bool Qualified { get; private set; }

        private void Update()
        {
            if (Qualified)
            {
                return;
            }

            var general = XRGeneralSettings.Instance;
            var manager = general != null ? general.Manager : null;
            if (manager == null || !(manager.activeLoader is ARCoreLoader))
            {
                return;
            }
            if (ARSession.state != ARSessionState.SessionTracking)
            {
                return;
            }
            if (CameraManager == null
                || CameraManager.subsystem == null
                || !CameraManager.subsystem.running)
            {
                return;
            }
            if (PlaneManager == null
                || PlaneManager.subsystem == null
                || !PlaneManager.subsystem.running)
            {
                return;
            }
            if (RaycastManager == null
                || RaycastManager.subsystem == null
                || !RaycastManager.subsystem.running)
            {
                return;
            }
            if (CameraBackground == null || !CameraBackground.backgroundRenderingEnabled)
            {
                return;
            }

            Qualified = true;
            Debug.Log(
                "BodyRig: ARCore runtime qualified "
                + "(loader+session-tracking+camera-background+planes+raycast).");
        }
    }
}
#endif

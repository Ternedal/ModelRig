using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.UI;
using UnityEngine.InputSystem.XR;
using Unity.XR.CoreUtils;

namespace Kaliv.VR
{
    /// <summary>
    /// Code-driven Quest entrypoint. Kaliv VR deliberately has no authored scene dependency.
    /// </summary>
    public sealed class KalivVrBootstrap : MonoBehaviour
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.BeforeSceneLoad)]
        private static void Boot()
        {
            UnityEngine.XR.XRSettings.eyeTextureResolutionScale = 1.2f;

            var go = new GameObject("KalivVR");
            DontDestroyOnLoad(go);
            go.AddComponent<KalivVrBootstrap>();
        }

        private void Awake()
        {
            Camera camera = BuildRig();
            BuildEventSystem();

            var pointer = gameObject.AddComponent<KalivVrPointer>();
            pointer.Initialize(camera);

            var app = gameObject.AddComponent<KalivVrApp>();
            app.Initialize(camera);
        }

        private static Camera BuildRig()
        {
            var originGo = new GameObject("XR Origin");
            DontDestroyOnLoad(originGo);
            var origin = originGo.AddComponent<XROrigin>();

            var offset = new GameObject("Camera Offset");
            offset.transform.SetParent(originGo.transform, false);

            var cameraGo = new GameObject("Main Camera");
            cameraGo.transform.SetParent(offset.transform, false);
            cameraGo.tag = "MainCamera";

            var camera = cameraGo.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.black;
            camera.nearClipPlane = 0.05f;
            camera.farClipPlane = 1000f;
            cameraGo.AddComponent<AudioListener>();

            var driver = cameraGo.AddComponent<TrackedPoseDriver>();
            driver.trackingType = TrackedPoseDriver.TrackingType.RotationAndPosition;
            driver.updateType = TrackedPoseDriver.UpdateType.UpdateAndBeforeRender;

            var position = new InputAction(
                "HMDPosition",
                InputActionType.Value,
                "<XRHMD>/centerEyePosition",
                expectedControlType: "Vector3");
            var rotation = new InputAction(
                "HMDRotation",
                InputActionType.Value,
                "<XRHMD>/centerEyeRotation",
                expectedControlType: "Quaternion");

            driver.positionInput = new InputActionProperty(position);
            driver.rotationInput = new InputActionProperty(rotation);
            position.Enable();
            rotation.Enable();

            origin.Camera = camera;
            origin.CameraFloorOffsetObject = offset;
            origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Floor;
            origin.CameraYOffset = 1.6f;
            return camera;
        }

        private static void BuildEventSystem()
        {
            if (EventSystem.current != null) return;

            var go = new GameObject("EventSystem");
            go.AddComponent<EventSystem>();

            // InputField implements IUpdateSelectedHandler. A bare EventSystem can
            // receive our manually synthesized pointer clicks, but it cannot drive
            // selected-field keyboard/navigation updates without a BaseInputModule.
            // InputSystemUIInputModule supports runtime creation; AssignDefaultActions
            // installs the package's UI action map without an authored .inputactions asset.
            var uiInput = go.AddComponent<InputSystemUIInputModule>();
            uiInput.AssignDefaultActions();

            UnityEngine.Object.DontDestroyOnLoad(go);
        }
    }
}

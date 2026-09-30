using System;
using UnityEngine;
#if BODYRIG_AR
using Unity.XR.CoreUtils;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
#endif

namespace ModelRig.BodyRig.UnityRenderer
{
    public static class BodyRigDemoBootstrap
    {
        [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
        private static void StartDemo()
        {
            if (UnityEngine.Object.FindFirstObjectByType<BodyRigVrmRenderer>() != null)
            {
                return;
            }

            var root = new GameObject("BodyRig Renderer Proof");
#if BODYRIG_AR
            var camera = EnsureArRuntime(out var raycastManager);
#else
            var camera = EnsureCamera();
#endif
            EnsureLight();

            var renderer = root.AddComponent<BodyRigVrmRenderer>();
            renderer.SetDefaultGazeTarget(camera.transform);

            var loader = root.AddComponent<BodyRigVrmLoader>();
            loader.Renderer = renderer;
            loader.GazeTarget = camera.transform;
            loader.VrmPath = Environment.GetEnvironmentVariable("BODYRIG_VRM_PATH");
            loader.LoadOnStart = Application.platform != RuntimePlatform.Android;

#if BODYRIG_AR
            var placement = root.AddComponent<BodyRigArPlacement>();
            placement.Loader = loader;
            placement.RaycastManager = raycastManager;

            var runtimeProbe = root.AddComponent<BodyRigArRuntimeProbe>();
            runtimeProbe.CameraManager = camera.GetComponent<ARCameraManager>();
            runtimeProbe.CameraBackground = camera.GetComponent<ARCameraBackground>();
            runtimeProbe.PlaneManager =
                UnityEngine.Object.FindFirstObjectByType<ARPlaneManager>();
            runtimeProbe.RaycastManager = raycastManager;
#endif

            // Desktop keeps the deterministic fixture unless environment
            // authority is explicitly mentioned. Android always resolves through
            // BodyRigRigLink because Kaliv supplies the rig via package-pinned
            // intent extras. Partial environment authority is still explicit and
            // therefore fails closed instead of falling back to intent/fixture.
            var rigUrl = Environment.GetEnvironmentVariable("BODYRIG_RIG_URL");
            var rigToken = Environment.GetEnvironmentVariable("BODYRIG_RIG_TOKEN");
            var environmentMentioned =
                !string.IsNullOrWhiteSpace(rigUrl) || !string.IsNullOrWhiteSpace(rigToken);
            var liveRequested = environmentMentioned
                || Application.platform == RuntimePlatform.Android;
            if (liveRequested)
            {
                var link = root.AddComponent<BodyRigRigLink>();
                link.Resolved += (url, token) =>
                {
                    if (root.GetComponent<BodyRigRemoteAvatarSource>() == null)
                    {
                        var avatarSource =
                            root.AddComponent<BodyRigRemoteAvatarSource>();
                        avatarSource.Loader = loader;
                        avatarSource.BaseUrl = url;
                        avatarSource.Token = token;
                        avatarSource.Begin();
                    }

                    if (root.GetComponent<BodyRigFrameSource>() == null)
                    {
                        var source = root.AddComponent<BodyRigFrameSource>();
                        source.Renderer = renderer;
                        source.BaseUrl = url;
                        source.Token = token;
                    }
                };
                return;
            }

            var player = root.AddComponent<BodyRigFixturePlayer>();
            player.Renderer = renderer;
            player.ResourceName = "bodyrig-demo";
        }

#if BODYRIG_AR
        private static Camera EnsureArRuntime(out ARRaycastManager raycastManager)
        {
            var session = UnityEngine.Object.FindFirstObjectByType<ARSession>();
            if (session == null)
            {
                var sessionObject = new GameObject("AR Session");
                session = sessionObject.AddComponent<ARSession>();
                sessionObject.AddComponent<ARInputManager>();
            }
            else if (UnityEngine.Object.FindFirstObjectByType<ARInputManager>() == null)
            {
                session.gameObject.AddComponent<ARInputManager>();
            }

            var origin = UnityEngine.Object.FindFirstObjectByType<XROrigin>();
            Camera camera;
            if (origin == null)
            {
                var originObject = new GameObject("XR Origin (AR)");
                var cameraObject = new GameObject("AR Camera");
                cameraObject.tag = "MainCamera";
                cameraObject.transform.SetParent(originObject.transform, false);

                camera = cameraObject.AddComponent<Camera>();
                EnsureArCameraComponents(cameraObject);

                origin = originObject.AddComponent<XROrigin>();
                origin.Camera = camera;
                origin.Origin = originObject;
                origin.CameraFloorOffsetObject = originObject;
                origin.CameraYOffset = 0.0f;
                origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Device;
            }
            else
            {
                camera = origin.Camera != null ? origin.Camera : Camera.main;
                if (camera == null)
                {
                    var cameraObject = new GameObject("AR Camera");
                    cameraObject.tag = "MainCamera";
                    cameraObject.transform.SetParent(origin.transform, false);
                    camera = cameraObject.AddComponent<Camera>();
                }
                else if (!camera.transform.IsChildOf(origin.transform))
                {
                    camera.transform.SetParent(origin.transform, false);
                    camera.transform.localPosition = Vector3.zero;
                    camera.transform.localRotation = Quaternion.identity;
                }

                EnsureArCameraComponents(camera.gameObject);
                origin.Camera = camera;
                origin.CameraFloorOffsetObject = origin.gameObject;
                origin.CameraYOffset = 0.0f;
                origin.RequestedTrackingOriginMode = XROrigin.TrackingOriginMode.Device;
            }

            var planeManager = origin.GetComponent<ARPlaneManager>();
            if (planeManager == null)
            {
                planeManager = origin.gameObject.AddComponent<ARPlaneManager>();
            }
            planeManager.requestedDetectionMode =
                PlaneDetectionMode.Horizontal | PlaneDetectionMode.Vertical;

            raycastManager = origin.GetComponent<ARRaycastManager>();
            if (raycastManager == null)
            {
                raycastManager = origin.gameObject.AddComponent<ARRaycastManager>();
            }

            Debug.Log(
                "BodyRig: AR runtime bootstrap ready (session+xr-origin+camera+planes+raycast).");
            return camera;
        }

        private static void EnsureArCameraComponents(GameObject cameraObject)
        {
            if (cameraObject.GetComponent<ARCameraManager>() == null)
            {
                cameraObject.AddComponent<ARCameraManager>();
            }
            if (cameraObject.GetComponent<ARCameraBackground>() == null)
            {
                cameraObject.AddComponent<ARCameraBackground>();
            }

            var poseDriver = cameraObject.GetComponent<TrackedPoseDriver>();
            if (poseDriver == null)
            {
                poseDriver = cameraObject.AddComponent<TrackedPoseDriver>();
                poseDriver.positionInput = new InputActionProperty(
                    new InputAction(
                        "BodyRig AR Camera Position",
                        InputActionType.Value,
                        "<XRHMD>/centerEyePosition"));
                poseDriver.rotationInput = new InputActionProperty(
                    new InputAction(
                        "BodyRig AR Camera Rotation",
                        InputActionType.Value,
                        "<XRHMD>/centerEyeRotation"));
                poseDriver.trackingStateInput = new InputActionProperty(
                    new InputAction(
                        "BodyRig AR Camera Tracking State",
                        InputActionType.Value,
                        "<XRHMD>/trackingState"));
            }
        }
#endif

        private static Camera EnsureCamera()
        {
            if (Camera.main != null)
            {
                return Camera.main;
            }

            var cameraObject = new GameObject("Main Camera");
            cameraObject.tag = "MainCamera";
            cameraObject.transform.position = new Vector3(0.0f, 1.55f, 2.8f);
            cameraObject.transform.rotation = Quaternion.Euler(0.0f, 180.0f, 0.0f);
            var camera = cameraObject.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0.07f, 0.07f, 0.08f, 1.0f);
            return camera;
        }

        private static void EnsureLight()
        {
            if (UnityEngine.Object.FindFirstObjectByType<Light>() != null)
            {
                return;
            }

            var lightObject = new GameObject("Key Light");
            lightObject.transform.rotation = Quaternion.Euler(35.0f, -30.0f, 0.0f);
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Directional;
            light.intensity = 1.2f;
        }
    }
}

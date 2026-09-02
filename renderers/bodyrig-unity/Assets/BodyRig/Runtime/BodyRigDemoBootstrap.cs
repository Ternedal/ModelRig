using System;
using UnityEngine;

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
            var camera = EnsureCamera();
            EnsureLight();

            var renderer = root.AddComponent<BodyRigVrmRenderer>();
            renderer.SetDefaultGazeTarget(camera.transform);

            var loader = root.AddComponent<BodyRigVrmLoader>();
            loader.Renderer = renderer;
            loader.GazeTarget = camera.transform;
            loader.VrmPath = Environment.GetEnvironmentVariable("BODYRIG_VRM_PATH");
            loader.LoadOnStart = true;

            var player = root.AddComponent<BodyRigFixturePlayer>();
            player.Renderer = renderer;
            player.ResourceName = "bodyrig-demo";
        }

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

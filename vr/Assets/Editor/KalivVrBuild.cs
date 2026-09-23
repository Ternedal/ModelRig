using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.SceneManagement;
using Kaliv.VR.Rendering;

namespace Kaliv.VR.EditorTools
{
    public static class KalivVrBuild
    {
        private const string AppId = "dk.ternedal.kalivvr";
        private const string GeneratedScenePath = "Assets/__KalivVrBuild/Main.unity";
        private const string OutputDirectory = "release/output";
        private const string ApkName = "KalivVR-dev.apk";

        [MenuItem("Kaliv VR/Build Android APK")]
        public static void BuildAndroid()
        {
            bool ok = false;
            string apk = null;
            try
            {
                ValidateCompositionLayers();
                ValidateOpenXrAuthority();
                ValidatePackageLockAuthority();
                ValidatePlayerSettingsAuthority();
                string[] scenes = CreateTemporaryBootScene();

                string root = Directory.GetParent(Application.dataPath)!.FullName;
                string outDir = Path.Combine(root, OutputDirectory);
                Directory.CreateDirectory(outDir);
                apk = Path.Combine(outDir, ApkName);
                if (File.Exists(apk)) File.Delete(apk);

                if (EditorUserBuildSettings.activeBuildTarget != BuildTarget.Android)
                    EditorUserBuildSettings.SwitchActiveBuildTarget(
                        BuildTargetGroup.Android, BuildTarget.Android);

                var report = BuildPipeline.BuildPlayer(new BuildPlayerOptions
                {
                    scenes = scenes,
                    locationPathName = apk,
                    target = BuildTarget.Android,
                    options = BuildOptions.None
                });

                ok = report.summary.result == UnityEditor.Build.Reporting.BuildResult.Succeeded
                     && File.Exists(apk);

                if (ok)
                    Debug.Log($"[KalivVR] BUILD OK — {apk}");
                else
                    Debug.LogError(
                        $"[KalivVR] BUILD FAILED — result={report.summary.result}, " +
                        $"errors={report.summary.totalErrors}, apkExists={File.Exists(apk)}");
            }
            catch (System.Exception exc)
            {
                Debug.LogException(exc);
                ok = false;
            }
            finally
            {
                CleanupTemporaryBootScene();
            }

            if (Application.isBatchMode)
                EditorApplication.Exit(ok ? 0 : 1);
        }

        private static void ValidateCompositionLayers()
        {
            foreach (string layer in new[]
            {
                KalivVrComposition.BodyLayerName,
                KalivVrComposition.MediaLayerName,
                KalivVrComposition.UiLayerName,
                KalivVrComposition.DebugLayerName,
            })
            {
                if (LayerMask.NameToLayer(layer) < 0)
                    throw new System.InvalidOperationException(
                        "[KalivVR] Missing committed render composition layer: " + layer);
            }
            Debug.Log("[KalivVR] Render composition layers verified.");
        }

        private static void ValidateOpenXrAuthority()
        {
            string packageSettingsPath = Path.Combine(
                Application.dataPath, "XR", "Settings", "OpenXR Package Settings.asset");
            string generalSettingsPath = Path.Combine(
                Application.dataPath, "XR", "XRGeneralSettingsPerBuildTarget.asset");

            if (!File.Exists(packageSettingsPath) || !File.Exists(generalSettingsPath))
                throw new System.InvalidOperationException(
                    "[KalivVR] Committed OpenXR project settings are missing.");

            string packageSettings = File.ReadAllText(packageSettingsPath);
            string generalSettings = File.ReadAllText(generalSettingsPath);

            RequireEnabledOpenXrFeature(
                packageSettings,
                "com.unity.openxr.feature.metaquest",
                "Meta Quest Support");
            RequireEnabledOpenXrFeature(
                packageSettings,
                "com.unity.openxr.feature.input.oculustouch",
                "Oculus Touch Controller Profile");
            RequireEnabledOpenXrFeature(
                packageSettings,
                "dk.ternedal.skyplayer.engine.passthrough",
                "SkyPlayer Engine Passthrough (FB)");

            if (packageSettings.Contains("com.stashskyplayer.passthrough") ||
                packageSettings.Contains("StashSkyPlayer.PassthroughFeature"))
            {
                throw new System.InvalidOperationException(
                    "[KalivVR] Legacy Skyplayer-local passthrough feature leaked into Kaliv VR.");
            }

            const string loaderGuid = "4c092d04a4d74f443aa067b76eef5b9d";
            int androidProviders = generalSettings.IndexOf(
                "m_Name: Android Providers",
                System.StringComparison.Ordinal);
            if (androidProviders < 0)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android XR provider settings are missing.");
            int providerEnd = generalSettings.IndexOf(
                "--- !u!114",
                androidProviders + 1,
                System.StringComparison.Ordinal);
            string providerBlock = providerEnd < 0
                ? generalSettings.Substring(androidProviders)
                : generalSettings.Substring(androidProviders, providerEnd - androidProviders);
            if (!providerBlock.Contains(loaderGuid))
                throw new System.InvalidOperationException(
                    "[KalivVR] Android XR provider does not reference the committed OpenXR loader.");

            int androidSettings = generalSettings.IndexOf(
                "m_Name: Android Settings",
                System.StringComparison.Ordinal);
            if (androidSettings < 0)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android XR general settings are missing.");
            int settingsEnd = generalSettings.IndexOf(
                "--- !u!114",
                androidSettings + 1,
                System.StringComparison.Ordinal);
            string settingsBlock = settingsEnd < 0
                ? generalSettings.Substring(androidSettings)
                : generalSettings.Substring(androidSettings, settingsEnd - androidSettings);
            if (!settingsBlock.Contains("m_InitManagerOnStart: 1"))
                throw new System.InvalidOperationException(
                    "[KalivVR] Android XR must initialize on startup.");

            Debug.Log(
                "[KalivVR] OpenXR authority verified " +
                "(startup + Meta Quest + Touch + engine passthrough).");
        }

        private static void RequireEnabledOpenXrFeature(
            string settings,
            string featureId,
            string label)
        {
            int feature = settings.IndexOf(
                "featureIdInternal: " + featureId,
                System.StringComparison.Ordinal);
            if (feature < 0)
                throw new System.InvalidOperationException(
                    "[KalivVR] Missing OpenXR feature: " + label);

            int start = settings.LastIndexOf("--- !u!114", feature, System.StringComparison.Ordinal);
            int end = settings.IndexOf("--- !u!114", feature, System.StringComparison.Ordinal);
            string block = settings.Substring(
                start >= 0 ? start : 0,
                (end < 0 ? settings.Length : end) - (start >= 0 ? start : 0));
            if (!block.Contains("m_enabled: 1"))
                throw new System.InvalidOperationException(
                    "[KalivVR] OpenXR feature is present but disabled: " + label);
        }

        private static void ValidatePackageLockAuthority()
        {
            string root = Directory.GetParent(Application.dataPath)!.FullName;
            string lockPath = Path.Combine(root, "Packages", "packages-lock.json");
            if (!File.Exists(lockPath))
                throw new System.InvalidOperationException(
                    "[KalivVR] Packages/packages-lock.json is missing after package restore.");

            string lockText = File.ReadAllText(lockPath);
            RequireLockedGitPackage(
                lockText,
                "com.vrmc.gltf",
                "a4711bbf8c4d10659d3e5568c2e3d7d595005e51");
            RequireLockedGitPackage(
                lockText,
                "com.vrmc.vrm",
                "a4711bbf8c4d10659d3e5568c2e3d7d595005e51");
            RequireLockedGitPackage(
                lockText,
                "dk.ternedal.skyplayer.engine",
                "a6c0087624fff26472a8804e7efd4e8e7347c3d7");

            foreach (var required in new[]
            {
                "\"com.unity.xr.openxr\"",
                "\"version\": \"1.16.1\"",
                "\"com.unity.xr.management\"",
                "\"version\": \"4.5.2\"",
                "\"com.unity.inputsystem\"",
                "\"version\": \"1.19.0\"",
            })
            {
                if (!lockText.Contains(required))
                    throw new System.InvalidOperationException(
                        "[KalivVR] Package lock is missing required resolution token: " + required);
            }

            Debug.Log("[KalivVR] Package lock authority verified.");
        }

        private static void RequireLockedGitPackage(
            string lockText,
            string packageName,
            string expectedHash)
        {
            string marker = "\"" + packageName + "\": {";
            int start = lockText.IndexOf(marker, System.StringComparison.Ordinal);
            if (start < 0)
                throw new System.InvalidOperationException(
                    "[KalivVR] Package lock is missing " + packageName + ".");

            int next = lockText.IndexOf(
                "\n    \"",
                start + marker.Length,
                System.StringComparison.Ordinal);
            string block = next < 0
                ? lockText.Substring(start)
                : lockText.Substring(start, next - start);

            if (!block.Contains("\"source\": \"git\"") ||
                !block.Contains("\"hash\": \"" + expectedHash + "\""))
            {
                throw new System.InvalidOperationException(
                    "[KalivVR] " + packageName +
                    " did not resolve to expected Git hash " + expectedHash + ".");
            }
        }

        private static void ValidatePlayerSettingsAuthority()
        {
            if (PlayerSettings.companyName != "Ternedal")
                throw new System.InvalidOperationException(
                    "[KalivVR] PlayerSettings.companyName must be Ternedal.");
            if (PlayerSettings.productName != "Kaliv VR")
                throw new System.InvalidOperationException(
                    "[KalivVR] PlayerSettings.productName must be Kaliv VR.");
            if (PlayerSettings.GetApplicationIdentifier(BuildTargetGroup.Android) != AppId)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android application identifier must be " + AppId + ".");
            if (PlayerSettings.bundleVersion != "0.1.0")
                throw new System.InvalidOperationException(
                    "[KalivVR] bundleVersion must be 0.1.0 for this bootstrap candidate.");
            if (PlayerSettings.Android.bundleVersionCode != 1)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android bundleVersionCode must be 1.");

            if (PlayerSettings.GetScriptingBackend(BuildTargetGroup.Android) !=
                ScriptingImplementation.IL2CPP)
            {
                throw new System.InvalidOperationException(
                    "[KalivVR] Android scripting backend must be IL2CPP.");
            }
            if (PlayerSettings.Android.targetArchitectures != AndroidArchitecture.ARM64)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android target architecture must be ARM64 only.");
            if (PlayerSettings.Android.minSdkVersion != AndroidSdkVersions.AndroidApiLevel29)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android minSdk must be API 29.");
            if (PlayerSettings.colorSpace != ColorSpace.Linear)
                throw new System.InvalidOperationException(
                    "[KalivVR] Player color space must be Linear.");
            if (PlayerSettings.GetUseDefaultGraphicsAPIs(BuildTarget.Android))
                throw new System.InvalidOperationException(
                    "[KalivVR] Android graphics APIs must be explicitly pinned.");

            var graphicsApis = PlayerSettings.GetGraphicsAPIs(BuildTarget.Android);
            if (graphicsApis == null || graphicsApis.Length != 1 ||
                graphicsApis[0] != GraphicsDeviceType.OpenGLES3)
            {
                throw new System.InvalidOperationException(
                    "[KalivVR] Android graphics API must be OpenGLES3 only.");
            }
            if (PlayerSettings.defaultInterfaceOrientation != UIOrientation.LandscapeLeft)
                throw new System.InvalidOperationException(
                    "[KalivVR] Default orientation must be LandscapeLeft.");
            if (PlayerSettings.insecureHttpOption != InsecureHttpOption.AlwaysAllowed)
                throw new System.InvalidOperationException(
                    "[KalivVR] Cleartext LAN/Tailscale HTTP must be explicitly allowed for bootstrap.");
            if (!PlayerSettings.Android.forceInternetPermission)
                throw new System.InvalidOperationException(
                    "[KalivVR] Android INTERNET permission must be explicitly required.");

            int activeQuality = QualitySettings.GetQualityLevel();
            if (QualitySettings.antiAliasing != 4)
                throw new System.InvalidOperationException(
                    "[KalivVR] Active Android quality level must use 4x MSAA.");

            Debug.Log(
                $"[KalivVR] Committed player authority verified " +
                $"(IL2CPP/ARM64/GLES3/Linear/API29/4xMSAA, quality={activeQuality}).");
        }

        private static string[] CreateTemporaryBootScene()
        {
            CleanupTemporaryBootScene();

            string directory = Path.GetDirectoryName(GeneratedScenePath)!.Replace('\\', '/');
            if (!AssetDatabase.IsValidFolder(directory))
                AssetDatabase.CreateFolder("Assets", "__KalivVrBuild");

            EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            if (!EditorSceneManager.SaveScene(SceneManager.GetActiveScene(), GeneratedScenePath))
                throw new System.InvalidOperationException(
                    "[KalivVR] Could not create temporary boot scene.");

            Debug.Log("[KalivVR] Temporary code-driven boot scene created.");
            return new[] { GeneratedScenePath };
        }

        private static void CleanupTemporaryBootScene()
        {
            if (AssetDatabase.LoadAssetAtPath<SceneAsset>(GeneratedScenePath) != null)
                AssetDatabase.DeleteAsset(GeneratedScenePath);

            const string folder = "Assets/__KalivVrBuild";
            if (AssetDatabase.IsValidFolder(folder))
            {
                string[] remaining = AssetDatabase.FindAssets("", new[] { folder });
                if (remaining.Length == 0)
                    AssetDatabase.DeleteAsset(folder);
            }

            AssetDatabase.Refresh();
        }
    }
}

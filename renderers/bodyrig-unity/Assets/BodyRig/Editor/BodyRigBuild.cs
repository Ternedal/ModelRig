#if UNITY_EDITOR
using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine.SceneManagement;

namespace ModelRig.BodyRig.UnityRenderer.Editor
{
    public static class BodyRigBuild
    {
        private const string SceneDirectory = "Assets/BodyRig/Scenes";
        private const string ScenePath = SceneDirectory + "/BodyRigDemo.unity";

        // UniVRM resolves these shaders by name at load time. In the editor that
        // works; in a player build a shader nothing references is stripped, and
        // the import dies with "ArgumentNullException: Parameter name: Shader"
        // inside MaterialFactory. They are permanent project requirements, so
        // GraphicsSettings.asset must pin them before a physical proof starts.
        private static readonly string[] RequiredShaderNames =
        {
            "VRM10/MToon10",
            "UniGLTF/UniUnlit",
            "Standard",
        };

        public static void BuildWindows()
        {
            var sceneDirectoryExisted = AssetDatabase.IsValidFolder(SceneDirectory);
            var restoreShaders = IncludeRequiredShaders();
            if (restoreShaders != null)
            {
                throw new InvalidOperationException(
                    "BodyRig: shader validation unexpectedly returned a mutation callback.");
            }
            try
            {
                Directory.CreateDirectory(SceneDirectory);
                var scene = EditorSceneManager.NewScene(
                    NewSceneSetup.EmptyScene,
                    NewSceneMode.Single);
                EditorSceneManager.SaveScene(scene, ScenePath);
                AssetDatabase.Refresh();

                var configured = Environment.GetEnvironmentVariable("BODYRIG_BUILD_DIR");
                var buildDirectory = string.IsNullOrWhiteSpace(configured)
                    ? Path.GetFullPath("Build/Windows")
                    : Path.GetFullPath(configured);
                Directory.CreateDirectory(buildDirectory);

                var output = Path.Combine(buildDirectory, "BodyRigRendererProof.exe");
                var options = new BuildPlayerOptions
                {
                    scenes = new[] { ScenePath },
                    locationPathName = output,
                    target = BuildTarget.StandaloneWindows64,
                    options = BuildOptions.StrictMode,
                };

                var report = BuildPipeline.BuildPlayer(options);
                if (report.summary.result != UnityEditor.Build.Reporting.BuildResult.Succeeded)
                {
                    throw new InvalidOperationException(
                        "BodyRig Windows renderer build failed: " + report.summary.result);
                }
            }
            finally
            {
                // The proof scene is generated build input, not repository state.
                // Remove it even on failure so later evidence cannot inherit an
                // untracked scene or folder .meta from an earlier physical run.
                EditorSceneManager.NewScene(
                    NewSceneSetup.EmptyScene,
                    NewSceneMode.Single);
                if (AssetDatabase.LoadAssetAtPath<UnityEngine.Object>(ScenePath) != null)
                {
                    AssetDatabase.DeleteAsset(ScenePath);
                }
                if (!sceneDirectoryExisted && AssetDatabase.IsValidFolder(SceneDirectory))
                {
                    AssetDatabase.DeleteAsset(SceneDirectory);
                }
                AssetDatabase.Refresh();
            }
        }

        /// <summary>
        /// Compatibility wrapper retained for the existing renderer contract.
        /// Shader inclusion is committed project authority now: validate only,
        /// never mutate or serialize GraphicsSettings during physical proof.
        /// </summary>
        private static Action IncludeRequiredShaders()
        {
            ValidateRequiredShadersPinned();
            return null;
        }

        private static void ValidateRequiredShadersPinned()
        {
            var assets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset");
            if (assets == null || assets.Length == 0)
            {
                throw new InvalidOperationException(
                    "BodyRig: GraphicsSettings.asset is not readable; cannot validate shader pins.");
            }

            var serialized = new SerializedObject(assets[0]);
            var list = serialized.FindProperty("m_AlwaysIncludedShaders");
            if (list == null)
            {
                throw new InvalidOperationException(
                    "BodyRig: m_AlwaysIncludedShaders is missing; cannot validate shader pins.");
            }

            foreach (var name in RequiredShaderNames)
            {
                var shader = UnityEngine.Shader.Find(name);
                if (shader == null)
                {
                    throw new InvalidOperationException(
                        "BodyRig: required physical-proof shader is unavailable: " + name);
                }

                var pinned = false;
                for (var i = 0; i < list.arraySize; i++)
                {
                    if (list.GetArrayElementAtIndex(i).objectReferenceValue == shader)
                    {
                        pinned = true;
                        break;
                    }
                }

                if (!pinned)
                {
                    throw new InvalidOperationException(
                        "BodyRig: required physical-proof shader is not committed to Always Included Shaders: "
                        + name);
                }
            }
        }
    }
}
#endif

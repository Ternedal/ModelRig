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

        // UniVRM resolves its shaders by name at load time. In the editor that
        // works; in a player build a shader nothing references is stripped, and
        // the import dies with "ArgumentNullException: Parameter name: Shader"
        // inside MaterialFactory. Measured on the rig 6/9: the build succeeded,
        // the player started, the VRM parsed, and it fell over exactly there.
        private static readonly string[] RequiredShaderNames =
        {
            "VRM10/MToon10",
            "VRM10/MToon10Outline",
            "UniGLTF/UniUnlit",
            "Standard",
        };

        public static void BuildWindows()
        {
            var sceneDirectoryExisted = AssetDatabase.IsValidFolder(SceneDirectory);
            var restoreShaders = IncludeRequiredShaders();
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
                // Graphics settings are repository state: the build needed the
                // shaders included, the repository must not keep the change or
                // the next proof starts with a dirty tree.
                if (restoreShaders != null)
                {
                    restoreShaders();
                }

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
        /// Add the shaders UniVRM loads by name to Always Included Shaders and
        /// return an action that restores the list exactly as it was.
        /// </summary>
        private static Action IncludeRequiredShaders()
        {
            var assets = AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset");
            if (assets == null || assets.Length == 0)
            {
                UnityEngine.Debug.LogWarning("BodyRig: GraphicsSettings.asset not readable; shaders not pinned.");
                return null;
            }

            var settings = assets[0];
            var serialized = new SerializedObject(settings);
            var list = serialized.FindProperty("m_AlwaysIncludedShaders");
            if (list == null)
            {
                UnityEngine.Debug.LogWarning("BodyRig: m_AlwaysIncludedShaders not found; shaders not pinned.");
                return null;
            }

            var original = new UnityEngine.Object[list.arraySize];
            for (var i = 0; i < list.arraySize; i++)
            {
                original[i] = list.GetArrayElementAtIndex(i).objectReferenceValue;
            }

            foreach (var name in RequiredShaderNames)
            {
                var shader = UnityEngine.Shader.Find(name);
                if (shader == null)
                {
                    UnityEngine.Debug.LogWarning("BodyRig: shader not found, skipping: " + name);
                    continue;
                }

                var already = false;
                for (var i = 0; i < list.arraySize; i++)
                {
                    if (list.GetArrayElementAtIndex(i).objectReferenceValue == shader)
                    {
                        already = true;
                        break;
                    }
                }

                if (already)
                {
                    continue;
                }

                list.InsertArrayElementAtIndex(list.arraySize);
                list.GetArrayElementAtIndex(list.arraySize - 1).objectReferenceValue = shader;
            }

            serialized.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.SaveAssets();

            return () =>
            {
                var restore = new SerializedObject(settings);
                var property = restore.FindProperty("m_AlwaysIncludedShaders");
                property.ClearArray();
                for (var i = 0; i < original.Length; i++)
                {
                    property.InsertArrayElementAtIndex(i);
                    property.GetArrayElementAtIndex(i).objectReferenceValue = original[i];
                }
                restore.ApplyModifiedPropertiesWithoutUndo();
                AssetDatabase.SaveAssets();
            };
        }
    }
}
#endif

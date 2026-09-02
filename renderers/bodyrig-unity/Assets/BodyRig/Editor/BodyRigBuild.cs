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

        public static void BuildWindows()
        {
            var sceneDirectoryExisted = AssetDatabase.IsValidFolder(SceneDirectory);
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
    }
}
#endif

using System;
using System.Collections.Generic;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Cheap one-shot Quest 2 sanity check for the accepted avatar.
    ///
    /// Meta's 2026 device-specific guidance recommends keeping the whole Quest 2
    /// scene below roughly 100 draw calls and 750k triangles. These numbers are
    /// therefore used only as hard-to-ignore SOFT warnings when the avatar ALONE
    /// consumes that entire scene budget. They are not a performance qualification:
    /// only on-device CPU/GPU frame timing can prove the 72 Hz target.
    /// </summary>
    public static class KalivQuestRenderBudget
    {
        public const int Quest2RecommendedSceneDrawCalls = 100;
        public const long Quest2RecommendedSceneTriangles = 750_000;

        public sealed class Snapshot
        {
            public int RendererCount { get; internal set; }
            public int SkinnedRendererCount { get; internal set; }
            public int MaterialSlots { get; internal set; }
            public int EstimatedDrawCalls { get; internal set; }
            public long Triangles { get; internal set; }
            public bool ExceedsSceneDrawCallGuidance =>
                EstimatedDrawCalls > Quest2RecommendedSceneDrawCalls;
            public bool ExceedsSceneTriangleGuidance =>
                Triangles > Quest2RecommendedSceneTriangles;
            public bool AvatarExceedsSceneDrawCallGuidance => ExceedsSceneDrawCallGuidance;
            public bool AvatarExceedsSceneTriangleGuidance => ExceedsSceneTriangleGuidance;

            public override string ToString() =>
                $"renderers={RendererCount}, skinned={SkinnedRendererCount}, " +
                $"materials={MaterialSlots}, estDrawCalls={EstimatedDrawCalls}, " +
                $"triangles={Triangles}";
        }

        public static Snapshot Analyze(GameObject avatarRoot)
        {
            if (avatarRoot == null) throw new ArgumentNullException(nameof(avatarRoot));

            var result = new Snapshot();
            var renderers = avatarRoot.GetComponentsInChildren<Renderer>(true);
            foreach (var renderer in renderers)
            {
                if (renderer == null || !renderer.enabled || !renderer.gameObject.activeInHierarchy)
                    continue;

                result.RendererCount++;
                if (renderer is SkinnedMeshRenderer) result.SkinnedRendererCount++;

                int materialSlots = renderer.sharedMaterials?.Length ?? 0;
                result.MaterialSlots += materialSlots;

                Mesh mesh = ResolveMesh(renderer);
                int subMeshes = mesh != null ? mesh.subMeshCount : 0;
                result.EstimatedDrawCalls += Math.Max(1, Math.Max(materialSlots, subMeshes));

                if (mesh == null) continue;
                for (int sub = 0; sub < mesh.subMeshCount; sub++)
                {
                    // Triangles are expected for VRM/MToon geometry. If a future
                    // asset uses a different topology, don't fake a triangle count.
                    if (mesh.GetTopology(sub) != MeshTopology.Triangles) continue;
                    result.Triangles += (long)mesh.GetIndexCount(sub) / 3L;
                }
            }

            return result;
        }

        public static void Log(GameObject avatarRoot)
        {
            Snapshot snapshot = Analyze(avatarRoot);
            string prefix = "[KalivVR.Perf] avatar " + snapshot;

            if (snapshot.AvatarExceedsSceneDrawCallGuidance ||
                snapshot.AvatarExceedsSceneTriangleGuidance)
            {
                Debug.LogWarning(
                    prefix +
                    " — avatar alone exceeds current Quest 2 whole-scene guidance; " +
                    "this is a soft guard, not a measured GPU failure.");
            }
            else
            {
                Debug.Log(prefix + " — within avatar-only soft guard; device profiling still required.");
            }
        }

        public static void LogScene(GameObject sceneRoot, string reason)
        {
            Snapshot snapshot = Analyze(sceneRoot);
            string suffix = string.IsNullOrWhiteSpace(reason) ? "" : " · " + reason;
            string prefix = "[KalivVR.Perf] renderer-scene " + snapshot + suffix;

            if (snapshot.ExceedsSceneDrawCallGuidance ||
                snapshot.ExceedsSceneTriangleGuidance)
            {
                Debug.LogWarning(
                    prefix +
                    " — visible Unity renderers exceed current Quest 2 scene guidance; " +
                    "UI/compositor/passthrough cost is not included and device profiling remains mandatory.");
            }
            else
            {
                Debug.Log(
                    prefix +
                    " — renderer snapshot is inside the static soft guard; " +
                    "UI/compositor/passthrough cost is not included and device profiling remains mandatory.");
            }
        }

        private static Mesh ResolveMesh(Renderer renderer)
        {
            if (renderer is SkinnedMeshRenderer skinned) return skinned.sharedMesh;
            var filter = renderer.GetComponent<MeshFilter>();
            return filter != null ? filter.sharedMesh : null;
        }
    }
}

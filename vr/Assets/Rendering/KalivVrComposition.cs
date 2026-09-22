using System;
using UnityEngine;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Stable scenegraph contract for the Kaliv VR product.
    /// Body, media, UI and diagnostics have separate roots/layers so future
    /// composition rules can change without coupling product code to object names.
    /// </summary>
    public sealed class KalivVrComposition : MonoBehaviour
    {
        public const string BodyLayerName = "KalivBody";
        public const string MediaLayerName = "KalivMedia";
        public const string UiLayerName = "KalivUI";
        public const string DebugLayerName = "KalivDebug";

        public Transform BodyRoot { get; private set; }
        public Transform MediaRoot { get; private set; }
        public Transform UiRoot { get; private set; }
        public Transform DebugRoot { get; private set; }

        public int BodyLayer { get; private set; }
        public int MediaLayer { get; private set; }
        public int UiLayer { get; private set; }
        public int DebugLayer { get; private set; }

        public void Initialize()
        {
            if (BodyRoot != null && MediaRoot != null && UiRoot != null && DebugRoot != null)
                return;

            BodyLayer = RequireLayer(BodyLayerName);
            MediaLayer = RequireLayer(MediaLayerName);
            UiLayer = RequireLayer(UiLayerName);
            DebugLayer = RequireLayer(DebugLayerName);

            BodyRoot = CreateRoot("Body", BodyLayer);
            MediaRoot = CreateRoot("Media", MediaLayer);
            UiRoot = CreateRoot("UI", UiLayer);
            DebugRoot = CreateRoot("Debug", DebugLayer);
        }

        public void ApplyBody(GameObject target) => SetLayerRecursive(target, BodyLayer);
        public void ApplyMedia(GameObject target) => SetLayerRecursive(target, MediaLayer);
        public void ApplyUi(GameObject target) => SetLayerRecursive(target, UiLayer);
        public void ApplyDebug(GameObject target) => SetLayerRecursive(target, DebugLayer);

        public void SetBodyVisible(bool visible)
        {
            if (BodyRoot != null) BodyRoot.gameObject.SetActive(visible);
        }

        public void SetMediaVisible(bool visible)
        {
            if (MediaRoot != null) MediaRoot.gameObject.SetActive(visible);
        }

        public void SetUiVisible(bool visible)
        {
            if (UiRoot != null) UiRoot.gameObject.SetActive(visible);
        }

        public void SetDebugVisible(bool visible)
        {
            if (DebugRoot != null) DebugRoot.gameObject.SetActive(visible);
        }

        private Transform CreateRoot(string name, int layer)
        {
            var go = new GameObject("KalivVR." + name + "Root");
            go.layer = layer;
            go.transform.SetParent(transform, false);
            return go.transform;
        }

        private static int RequireLayer(string name)
        {
            int layer = LayerMask.NameToLayer(name);
            if (layer < 0)
                throw new InvalidOperationException("Kaliv VR project is missing Unity layer: " + name);
            return layer;
        }

        private static void SetLayerRecursive(GameObject target, int layer)
        {
            if (target == null) return;
            target.layer = layer;
            foreach (Transform child in target.transform)
                SetLayerRecursive(child.gameObject, layer);
        }
    }
}

using UnityEngine;
using UnityEngine.UI;

namespace Kaliv.VR
{
    /// <summary>
    /// Shows a still image from the rig's gallery on a floating plane in front of the user.
    ///
    /// A UI RawImage rather than a textured quad on purpose: the UI shader is always in the
    /// build, while Shader.Find("Unlit/Texture") only works if something else happens to
    /// reference that shader — on a headset build it can quietly return null and draw pink.
    ///
    /// 180°/360° photos are shown flat, one eye's view. A sphere would need the video
    /// engine's projection path, which takes a video source, not a texture.
    /// </summary>
    public sealed class KalivImageViewer : MonoBehaviour
    {
        private Canvas _canvas;
        private RawImage _image;
        private Texture2D _texture;

        public bool Visible => _canvas != null && _canvas.gameObject.activeSelf;

        public static KalivImageViewer Create(Transform parent)
        {
            var go = new GameObject("KalivImageViewer");
            if (parent != null) go.transform.SetParent(parent, false);
            var viewer = go.AddComponent<KalivImageViewer>();
            viewer.Build();
            return viewer;
        }

        private void Build()
        {
            var canvasGo = new GameObject("KalivImage.Canvas", typeof(Canvas));
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            var imgGo = new GameObject("Image", typeof(RawImage));
            imgGo.transform.SetParent(canvasGo.transform, false);
            _image = imgGo.GetComponent<RawImage>();
            _image.raycastTarget = false;
            canvasGo.SetActive(false);
        }

        /// <summary>Takes ownership of <paramref name="texture"/> and destroys it on Hide.</summary>
        public void Show(Texture2D texture, string stereo, Camera camera)
        {
            Hide();
            _texture = texture;
            Rect uv = KalivMediaGallery.ImageUvRect(stereo);
            _image.texture = texture;
            _image.uvRect = uv;

            // Size by the VISIBLE part's aspect, 2.4 m wide at 3 m — about the panel's footprint.
            float aspect = (texture.width * uv.width) / Mathf.Max(1f, texture.height * uv.height);
            const float width = 2.4f;
            float height = width / Mathf.Max(0.1f, aspect);
            if (height > 1.8f) { height = 1.8f; }
            float w = height * aspect;

            var rt = (RectTransform)_canvas.transform;
            rt.sizeDelta = new Vector2(1000f, 1000f / Mathf.Max(0.1f, aspect));
            rt.localScale = Vector3.one * (w / 1000f);
            _image.rectTransform.sizeDelta = rt.sizeDelta;

            Vector3 fwd = camera.transform.forward;
            fwd.y = 0f;
            if (fwd.sqrMagnitude < 0.001f) fwd = Vector3.forward;
            fwd.Normalize();
            rt.position = camera.transform.position + fwd * 3f;
            rt.rotation = Quaternion.LookRotation(fwd, Vector3.up);
            _canvas.gameObject.SetActive(true);
        }

        public void Hide()
        {
            if (_canvas != null) _canvas.gameObject.SetActive(false);
            if (_image != null) _image.texture = null;
            if (_texture != null) { Destroy(_texture); _texture = null; }
        }

        private void OnDestroy() => Hide();
    }
}

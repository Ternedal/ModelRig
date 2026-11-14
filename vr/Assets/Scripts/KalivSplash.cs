using System.Collections;
using UnityEngine;
using UnityEngine.UI;

namespace Kaliv.VR
{
    /// <summary>
    /// Kaliv VR's own splash, shown once at startup — the same approach as SkyPlayer's.
    /// Unity's built-in VR splash is drawn on a small fixed quad that cannot be sized, so it
    /// always reads small and grainy. This one is drawn large, at a comfortable distance,
    /// from the full-resolution texture, then fades out and removes itself.
    ///
    /// The art: put the image at <c>Assets/Resources/Branding/kaliv_splash.png</c>
    /// (Texture Type: Default, Non-Power-of-2: None, Max Size 4096, Compression: None or
    /// High Quality). No image bundled → no splash, nothing else changes.
    /// </summary>
    public class KalivSplash : MonoBehaviour
    {
        public const string ResourcePath = "Branding/kaliv_splash";

        // SkyPlayer's 3.4 m at 2.6 m, brought in to 1.9 m so it sits in FRONT of the panel
        // (2 m) — same apparent size.
        private const float MetersWide = 2.5f;
        private const float Distance = 1.9f;
        private const float HoldSeconds = 1.8f;
        private const float FadeSeconds = 0.7f;
        private const float TrackingWait = 3f;

        private Camera _camera;
        private Texture2D _texture;
        private Canvas _canvas;
        private Image _image;

        /// <summary>Starts the splash if the art is bundled. Returns false when there is none.</summary>
        public static bool Show(Camera camera, Transform parent)
        {
            var tex = Resources.Load<Texture2D>(ResourcePath);
            if (tex == null || camera == null) return false;
            var go = new GameObject("KalivSplash");
            go.transform.SetParent(parent, false);
            var splash = go.AddComponent<KalivSplash>();
            splash._camera = camera;
            splash._texture = tex;
            splash.StartCoroutine(splash.Run());
            return true;
        }

        private IEnumerator Run()
        {
            // Wait for a real head pose, or the splash lands low and tilted — the same lesson
            // as the panel's placement.
            float waited = 0f;
            while (waited < TrackingWait && _camera.transform.position.y < 0.5f)
            {
                waited += Time.unscaledDeltaTime;
                yield return null;
            }
            yield return null;
            Build();

            yield return new WaitForSecondsRealtime(HoldSeconds);
            float t = 0f;
            while (t < FadeSeconds)
            {
                t += Time.unscaledDeltaTime;
                if (_image != null) _image.color = new Color(1, 1, 1, 1f - Mathf.Clamp01(t / FadeSeconds));
                yield return null;
            }
            Destroy(gameObject);
        }

        private void Build()
        {
            var canvasGo = new GameObject("SplashCanvas", typeof(Canvas), typeof(CanvasScaler));
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = _camera;
            _canvas.sortingOrder = 500;   // in front of the panel

            var rt = (RectTransform)_canvas.transform;
            rt.sizeDelta = new Vector2(_texture.width, _texture.height);
            rt.localScale = Vector3.one * (MetersWide / Mathf.Max(1, _texture.width));

            // Yaw only: upright and facing the user, at eye height.
            var head = _camera.transform;
            Vector3 fwd = head.forward;
            fwd.y = 0f;
            if (fwd.sqrMagnitude < 0.001f) fwd = Vector3.forward;
            fwd.Normalize();
            rt.position = head.position + fwd * Distance;
            rt.rotation = Quaternion.LookRotation(fwd, Vector3.up);

            var imgGo = new GameObject("Hero", typeof(RectTransform), typeof(Image));
            imgGo.transform.SetParent(_canvas.transform, false);
            _image = imgGo.GetComponent<Image>();
            _image.sprite = Sprite.Create(_texture, new Rect(0, 0, _texture.width, _texture.height), new Vector2(.5f, .5f));
            _image.raycastTarget = false;
            _image.preserveAspect = true;
            var irt = _image.rectTransform;
            irt.anchorMin = irt.anchorMax = new Vector2(.5f, .5f);
            irt.sizeDelta = new Vector2(_texture.width, _texture.height);
            irt.anchoredPosition = Vector2.zero;
        }
    }
}

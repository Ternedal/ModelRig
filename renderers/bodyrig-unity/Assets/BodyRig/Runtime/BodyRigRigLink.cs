using System;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Resolves the rig origin and paired device token for the renderer.
    /// Authority order is intentionally small: process environment first,
    /// then Kaliv's package-pinned Android launch-intent extras. Kaliv owns
    /// pairing; the Unity body app never persists or issues credentials itself.
    /// A present but incomplete/malformed higher-priority source fails closed.
    /// </summary>
    public sealed class BodyRigRigLink : MonoBehaviour
    {
        private enum SourceState
        {
            Absent,
            Resolved,
            Invalid,
        }

        public event Action<string, string> Resolved;

        public string BaseUrl { get; private set; } = "";
        public string Token { get; private set; } = "";
        public string LastError { get; private set; } = "";
        public bool IsResolved =>
            !string.IsNullOrWhiteSpace(BaseUrl) && !string.IsNullOrWhiteSpace(Token);

        private void Start()
        {
            var url = Environment.GetEnvironmentVariable("BODYRIG_RIG_URL");
            var token = Environment.GetEnvironmentVariable("BODYRIG_RIG_TOKEN");
            var state = TryUseSource(url, token, "environment");
            if (state != SourceState.Absent)
            {
                return;
            }

            ReadIntentExtras(out url, out token);
            state = TryUseSource(url, token, "intent");
            if (state != SourceState.Absent)
            {
                return;
            }

            LastError = Application.platform == RuntimePlatform.Android
                ? "BodyRig: Kaliv Body was launched without rig authority. Start it from Kaliv."
                : "BodyRig: no rig authority configured.";
            Debug.LogWarning(LastError);
        }

        private SourceState TryUseSource(string url, string token, string source)
        {
            var any = !string.IsNullOrWhiteSpace(url) || !string.IsNullOrWhiteSpace(token);
            if (!any)
            {
                return SourceState.Absent;
            }
            if (string.IsNullOrWhiteSpace(url) || string.IsNullOrWhiteSpace(token))
            {
                LastError = "BodyRig: incomplete rig link from " + source + "; not falling back.";
                Debug.LogWarning(LastError);
                return SourceState.Invalid;
            }
            if (!TryNormalizeBaseUrl(url, out var normalized))
            {
                LastError = "BodyRig: invalid rig URL from " + source + "; not falling back.";
                Debug.LogWarning(LastError);
                return SourceState.Invalid;
            }

            BaseUrl = normalized;
            Token = token.Trim();
            LastError = "";
            Debug.Log("BodyRig: rig link resolved from " + source + " (" + BaseUrl + ")");
            Resolved?.Invoke(BaseUrl, Token);
            return SourceState.Resolved;
        }

        private static bool TryNormalizeBaseUrl(string raw, out string normalized)
        {
            normalized = "";
            if (string.IsNullOrWhiteSpace(raw)
                || !Uri.TryCreate(raw.Trim(), UriKind.Absolute, out var uri)
                || (uri.Scheme != Uri.UriSchemeHttp && uri.Scheme != Uri.UriSchemeHttps)
                || string.IsNullOrWhiteSpace(uri.Host)
                || !string.IsNullOrEmpty(uri.UserInfo)
                || (!string.IsNullOrEmpty(uri.AbsolutePath) && uri.AbsolutePath != "/")
                || !string.IsNullOrEmpty(uri.Query)
                || !string.IsNullOrEmpty(uri.Fragment))
            {
                return false;
            }

            normalized = uri.GetLeftPart(UriPartial.Authority).TrimEnd('/');
            return true;
        }

        private static void ReadIntentExtras(out string url, out string token)
        {
            url = null;
            token = null;
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                using (var player = new AndroidJavaClass("com.unity3d.player.UnityPlayer"))
                using (var activity = player.GetStatic<AndroidJavaObject>("currentActivity"))
                using (var intent = activity.Call<AndroidJavaObject>("getIntent"))
                {
                    url = intent.Call<string>("getStringExtra", "bodyrig_rig_url");
                    token = intent.Call<string>("getStringExtra", "bodyrig_rig_token");
                }
            }
            catch (Exception)
            {
                Debug.LogWarning("BodyRig: could not read Android rig-link intent; not falling back.");
            }
#endif
        }
    }
}

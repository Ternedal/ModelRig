using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Where the renderer gets the rig's address and device token -- the one
    /// piece of slice D that is the same for both host choices.
    ///
    /// Sources, first match wins:
    ///   1. environment (Windows proof and manual runs): BODYRIG_RIG_URL / _TOKEN;
    ///   2. Android intent extras "bodyrig_rig_url" / "bodyrig_rig_token", the
    ///      way an embedding host (Unity as a Library inside Kaliv) hands them
    ///      over -- Kaliv already holds a paired token, so no second pairing;
    ///   3. PlayerPrefs, from an earlier pairing done here;
    ///   4. otherwise a minimal on-screen form: rig URL + the pairing code the
    ///      rig shows in Control Center -> POST /api/v1/pair/claim -> token,
    ///      stored in PlayerPrefs. Same exchange Kaliv's own pairing card makes.
    ///
    /// Nothing here renders a body; it only resolves (url, token) and hands
    /// them to whoever asks. The token never leaves PlayerPrefs except in the
    /// Authorization header of requests to the rig it was issued for.
    /// </summary>
    public sealed class BodyRigRigLink : MonoBehaviour
    {
        private const string PrefUrl = "bodyrig.rig.url";
        private const string PrefToken = "bodyrig.rig.token";
        private const string DeviceName = "kaliv-body";

        public event Action<string, string> Resolved;

        public string BaseUrl { get; private set; } = "";
        public string Token { get; private set; } = "";
        public bool IsResolved => !string.IsNullOrWhiteSpace(BaseUrl) && !string.IsNullOrWhiteSpace(Token);

        private string formUrl = "http://192.168.1.33:8080";
        private string formCode = "";
        private string formStatus = "";
        private bool claiming;

        private void Start()
        {
            var url = Environment.GetEnvironmentVariable("BODYRIG_RIG_URL");
            var token = Environment.GetEnvironmentVariable("BODYRIG_RIG_TOKEN");
            if (Use(url, token, "environment"))
            {
                return;
            }
            ReadIntentExtras(out url, out token);
            if (Use(url, token, "intent"))
            {
                return;
            }
            if (Use(PlayerPrefs.GetString(PrefUrl, ""), PlayerPrefs.GetString(PrefToken, ""), "playerprefs"))
            {
                return;
            }
            // Fall through to the on-screen form (OnGUI).
        }

        private bool Use(string url, string token, string source)
        {
            if (string.IsNullOrWhiteSpace(url) || string.IsNullOrWhiteSpace(token))
            {
                return false;
            }
            BaseUrl = url.Trim().TrimEnd('/');
            Token = token.Trim();
            Debug.Log("BodyRig: rig link resolved from " + source + " (" + BaseUrl + ")");
            Resolved?.Invoke(BaseUrl, Token);
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
            catch (Exception exc)
            {
                Debug.LogWarning("BodyRig: no intent extras: " + exc.Message);
            }
#endif
        }

        private void OnGUI()
        {
            if (IsResolved)
            {
                return;
            }
            var scale = Mathf.Max(1.0f, Screen.dpi / 160.0f);
            GUI.matrix = Matrix4x4.Scale(new Vector3(scale, scale, 1.0f));
            var area = new Rect(16, 16, Screen.width / scale - 32, 220);
            GUILayout.BeginArea(area, GUI.skin.box);
            GUILayout.Label("Kaliv Body - forbind til riggen");
            GUILayout.Label("Rig-adresse");
            formUrl = GUILayout.TextField(formUrl);
            GUILayout.Label("Parringskode (fra Control Center paa riggen)");
            formCode = GUILayout.TextField(formCode);
            GUI.enabled = !claiming && formUrl.Trim().Length > 0 && formCode.Trim().Length > 0;
            if (GUILayout.Button(claiming ? "Forbinder..." : "Forbind"))
            {
                StartCoroutine(Claim(formUrl.Trim().TrimEnd('/'), formCode.Trim()));
            }
            GUI.enabled = true;
            if (!string.IsNullOrEmpty(formStatus))
            {
                GUILayout.Label(formStatus);
            }
            GUILayout.EndArea();
        }

        [Serializable]
        private sealed class ClaimRequest
        {
            public string device_name;
            public string code;
        }

        [Serializable]
        private sealed class ClaimResponse
        {
            public string token;
            public string device_id;
        }

        private IEnumerator Claim(string url, string code)
        {
            claiming = true;
            formStatus = "";
            var body = JsonUtility.ToJson(new ClaimRequest { device_name = DeviceName, code = code });
            using (var request = new UnityWebRequest(url + "/api/v1/pair/claim", UnityWebRequest.kHttpVerbPOST))
            {
                request.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(body));
                request.downloadHandler = new DownloadHandlerBuffer();
                request.SetRequestHeader("Content-Type", "application/json");
                request.timeout = 10;
                yield return request.SendWebRequest();
                claiming = false;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    formStatus = "Parring fejlede (HTTP " + request.responseCode + "): " + request.error;
                    yield break;
                }
                ClaimResponse response = null;
                try
                {
                    response = JsonUtility.FromJson<ClaimResponse>(request.downloadHandler.text);
                }
                catch (Exception)
                {
                    response = null;
                }
                if (response == null || string.IsNullOrWhiteSpace(response.token))
                {
                    formStatus = "Parring fejlede: svaret manglede et token.";
                    yield break;
                }
                PlayerPrefs.SetString(PrefUrl, url);
                PlayerPrefs.SetString(PrefToken, response.token);
                PlayerPrefs.Save();
                Use(url, response.token, "pairing");
            }
        }

        /// <summary>Forget the stored pairing (the rig's Control Center revokes the device).</summary>
        public void Forget()
        {
            PlayerPrefs.DeleteKey(PrefUrl);
            PlayerPrefs.DeleteKey(PrefToken);
            PlayerPrefs.Save();
            BaseUrl = "";
            Token = "";
        }
    }
}

using System;
using System.Collections;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Polls only the tiny active-body manifest. A changed body id or package digest
    /// means the render asset authority moved and the engine must reload atomically.
    /// </summary>
    public sealed class KalivBodyRevisionWatcher : MonoBehaviour
    {
        [Serializable]
        private sealed class ActiveBodyManifest
        {
            public string schema;
            public string body_id;
            public string package_sha256;
        }

        private string _baseUrl;
        private string _token;
        private string _bodyId;
        private string _packageSha;
        private Coroutine _loop;
        private int _generation;

        public float PollSeconds { get; set; } = 3f;

        public event Action<string, string> RevisionChanged;
        public event Action<string> WatchWarning;

        public void Configure(string baseUrl, string token)
        {
            _baseUrl = (baseUrl ?? "").Trim().TrimEnd('/');
            _token = token ?? "";
        }

        public void SetCurrent(string bodyId, string packageSha)
        {
            _bodyId = bodyId ?? "";
            _packageSha = packageSha ?? "";
        }

        public void StartWatching()
        {
            StopWatching();
            if (string.IsNullOrWhiteSpace(_baseUrl) || string.IsNullOrWhiteSpace(_token))
                return;

            int generation = ++_generation;
            _loop = StartCoroutine(Loop(generation));
        }

        public void StopWatching()
        {
            ++_generation;
            if (_loop != null)
            {
                StopCoroutine(_loop);
                _loop = null;
            }
        }

        private IEnumerator Loop(int generation)
        {
            while (enabled && generation == _generation)
            {
                yield return new WaitForSecondsRealtime(Mathf.Max(1f, PollSeconds));
                if (generation != _generation) yield break;

                using var request = UnityWebRequest.Get(_baseUrl + "/api/v1/body/active");
                request.redirectLimit = 0;
                request.timeout = 10;
                request.SetRequestHeader("Authorization", "Bearer " + _token.Trim());
                request.SetRequestHeader("Cache-Control", "no-store");
                yield return request.SendWebRequest();

                if (generation != _generation) yield break;

                if (request.result != UnityWebRequest.Result.Success)
                {
                    // 404/409/503 may be temporary during person/body activation.
                    // Keep the current avatar rather than disappearing on a transient.
                    WatchWarning?.Invoke(
                        $"BodyRig revisionskontrol fejlede (HTTP {request.responseCode}); beholder nuværende krop.");
                    continue;
                }

                ActiveBodyManifest manifest;
                try
                {
                    manifest = JsonUtility.FromJson<ActiveBodyManifest>(request.downloadHandler.text);
                }
                catch (Exception exc)
                {
                    WatchWarning?.Invoke("Ugyldigt aktiv-krop manifest: " + exc.Message);
                    continue;
                }

                if (manifest == null ||
                    manifest.schema != "modelrig-body-assets/v1" ||
                    string.IsNullOrWhiteSpace(manifest.body_id) ||
                    string.IsNullOrWhiteSpace(manifest.package_sha256))
                {
                    WatchWarning?.Invoke("Aktiv-krop manifest mangler BodyRig revision authority.");
                    continue;
                }

                if (manifest.body_id != _bodyId ||
                    !string.Equals(manifest.package_sha256, _packageSha, StringComparison.OrdinalIgnoreCase))
                {
                    // Retire this generation before announcing, but do not StopCoroutine
                    // ourselves: Unity may abort execution before the event is delivered.
                    ++_generation;
                    _loop = null;
                    RevisionChanged?.Invoke(manifest.body_id, manifest.package_sha256);
                    yield break;
                }
            }
        }

        private void OnDisable() => StopWatching();
    }
}

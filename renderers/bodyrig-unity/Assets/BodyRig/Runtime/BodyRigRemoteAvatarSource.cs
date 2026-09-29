using System;
using System.Collections;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UnityEngine;
using UnityEngine.Networking;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Fetches the active digest-bound BodyRig avatar from the paired rig.
    /// Transport/cache only: BodyRigVrmLoader remains the sole VRM parser,
    /// renderer binder and AR-placement handoff authority.
    /// </summary>
    public sealed class BodyRigRemoteAvatarSource : MonoBehaviour
    {
        private const int MaxAvatarBytes = 192 * 1024 * 1024;
        private const int MaxBodyprintBytes = 1024 * 1024;

        [Serializable]
        private sealed class ActiveBodyManifest
        {
            public string schema;
            public string body_id;
            public string name;
            public string package_sha256;
        }

        [Serializable]
        private sealed class BodyprintShape
        {
            public float height_scale;
        }

        [Serializable]
        private sealed class BodyprintDocument
        {
            public string format;
            public int version;
            public BodyprintShape shape;
        }

        [SerializeField] private BodyRigVrmLoader loader;
        [SerializeField] private string baseUrl = "";
        [SerializeField] private string token = "";

        private bool started;

        public BodyRigVrmLoader Loader
        {
            get => loader;
            set => loader = value;
        }

        public string BaseUrl
        {
            get => baseUrl;
            set => baseUrl = value;
        }

        public string Token
        {
            get => token;
            set => token = value;
        }

        public void Begin()
        {
            if (started)
            {
                return;
            }
            started = true;

            if (loader == null
                || string.IsNullOrWhiteSpace(baseUrl)
                || string.IsNullOrWhiteSpace(token))
            {
                Debug.LogWarning(
                    "BodyRig: remote avatar source needs loader, rig URL and device token.");
                enabled = false;
                return;
            }

            StartCoroutine(LoadActive());
        }

        private IEnumerator LoadActive()
        {
            var origin = baseUrl.Trim().TrimEnd('/');
            ActiveBodyManifest manifest;

            using (var request = AuthorizedGet(origin + "/api/v1/body/active"))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail("active body manifest HTTP " + request.responseCode);
                    yield break;
                }

                try
                {
                    manifest =
                        JsonUtility.FromJson<ActiveBodyManifest>(request.downloadHandler.text);
                }
                catch (Exception exc)
                {
                    Fail("active body manifest parse failed: " + exc.Message);
                    yield break;
                }
            }

            if (manifest == null
                || manifest.schema != "modelrig-body-assets/v1"
                || !IsCanonicalBodyId(manifest.body_id)
                || !IsLowerHex(manifest.package_sha256, 64))
            {
                Fail("active body manifest failed schema/identity validation");
                yield break;
            }

            var heightScale = 1.0f;
            using (var request =
                AuthorizedGet(origin + "/api/v1/body/active/bodyprint.json"))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail("bodyprint HTTP " + request.responseCode);
                    yield break;
                }

                var responseBodyId =
                    (request.GetResponseHeader("X-BodyRig-Body-ID") ?? "").Trim();
                var responsePackage =
                    (request.GetResponseHeader("X-BodyRig-Package-SHA256") ?? "")
                    .Trim().ToLowerInvariant();
                var bodyprintSha =
                    (request.GetResponseHeader("X-BodyRig-Member-SHA256") ?? "")
                    .Trim().ToLowerInvariant();
                var bodyprintBytes = request.downloadHandler.data;

                if (responseBodyId != manifest.body_id
                    || responsePackage != manifest.package_sha256
                    || !IsLowerHex(bodyprintSha, 64)
                    || bodyprintBytes == null
                    || bodyprintBytes.Length == 0
                    || bodyprintBytes.Length > MaxBodyprintBytes
                    || !string.Equals(
                        Sha256(bodyprintBytes),
                        bodyprintSha,
                        StringComparison.Ordinal))
                {
                    Fail("bodyprint identity/digest validation failed");
                    yield break;
                }

                try
                {
                    var json = Encoding.UTF8.GetString(bodyprintBytes);
                    var bodyprint = JsonUtility.FromJson<BodyprintDocument>(json);
                    if (bodyprint == null
                        || bodyprint.format != "modelrig-bodyprint"
                        || bodyprint.version != 1)
                    {
                        throw new FormatException("unknown bodyprint format");
                    }
                    if (bodyprint.shape != null && bodyprint.shape.height_scale > 0.0f)
                    {
                        var value = bodyprint.shape.height_scale;
                        if (float.IsNaN(value)
                            || float.IsInfinity(value)
                            || value > 4.0f)
                        {
                            throw new FormatException("height_scale is outside contract");
                        }
                        heightScale = value;
                    }
                }
                catch (Exception exc)
                {
                    Fail("bodyprint parse failed: " + exc.Message);
                    yield break;
                }
            }

            byte[] avatarBytes;
            string memberSha;
            using (var request =
                AuthorizedGet(origin + "/api/v1/body/active/avatar.vrm"))
            {
                yield return request.SendWebRequest();
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail("avatar HTTP " + request.responseCode);
                    yield break;
                }

                var responseBodyId =
                    (request.GetResponseHeader("X-BodyRig-Body-ID") ?? "").Trim();
                var responsePackage =
                    (request.GetResponseHeader("X-BodyRig-Package-SHA256") ?? "")
                    .Trim().ToLowerInvariant();
                memberSha =
                    (request.GetResponseHeader("X-BodyRig-Member-SHA256") ?? "")
                    .Trim().ToLowerInvariant();

                if (responseBodyId != manifest.body_id
                    || responsePackage != manifest.package_sha256
                    || !IsLowerHex(memberSha, 64))
                {
                    Fail("avatar response identity headers changed or are missing");
                    yield break;
                }

                avatarBytes = request.downloadHandler.data;
            }

            if (avatarBytes == null
                || avatarBytes.Length < 20
                || avatarBytes.Length > MaxAvatarBytes)
            {
                Fail("avatar byte size is outside the allowed range");
                yield break;
            }

            var actualSha = Sha256(avatarBytes);
            if (!string.Equals(actualSha, memberSha, StringComparison.Ordinal))
            {
                Fail("avatar SHA-256 does not match the rig member receipt");
                yield break;
            }

            string path;
            try
            {
                path = CommitCache(
                    manifest.body_id,
                    manifest.package_sha256,
                    actualSha,
                    avatarBytes);
            }
            catch (Exception exc)
            {
                Fail("avatar cache commit failed: " + exc.Message);
                yield break;
            }

            LoadAndReportAsync(
                path,
                manifest.body_id,
                manifest.package_sha256,
                actualSha,
                heightScale);
        }

        private async void LoadAndReportAsync(
            string path,
            string bodyId,
            string packageSha,
            string avatarSha,
            float heightScale)
        {
            try
            {
                var instance = await loader.LoadAsync(path);
                instance.transform.localScale = Vector3.one * heightScale;
                Debug.Log(
                    "BodyRig: active avatar loaded from rig "
                    + "(body=" + bodyId
                    + ", package=" + packageSha
                    + ", avatar_sha256=" + avatarSha
                    + ", height_scale=" + heightScale.ToString("0.###") + ").");
            }
            catch (Exception exc)
            {
                Fail("cached avatar failed VRM load/bind: " + exc.Message);
            }
        }

        private string CommitCache(
            string bodyId,
            string packageSha,
            string avatarSha,
            byte[] bytes)
        {
            var directory =
                Path.Combine(Application.persistentDataPath, "BodyRig", "Bodies");
            Directory.CreateDirectory(directory);

            var packagePrefix = packageSha.Substring(0, 20);
            var path = Path.Combine(
                directory,
                bodyId + "-" + packagePrefix + "-" + avatarSha.Substring(0, 20) + ".vrm");

            if (File.Exists(path))
            {
                if (Sha256File(path) == avatarSha)
                {
                    return path;
                }
                File.Delete(path);
            }

            var temporary = path + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                File.WriteAllBytes(temporary, bytes);
                if (Sha256File(temporary) != avatarSha)
                {
                    throw new IOException("temporary avatar cache digest mismatch");
                }
                File.Move(temporary, path);
                temporary = null;
            }
            finally
            {
                if (!string.IsNullOrEmpty(temporary) && File.Exists(temporary))
                {
                    try
                    {
                        File.Delete(temporary);
                    }
                    catch (IOException)
                    {
                    }
                    catch (UnauthorizedAccessException)
                    {
                    }
                }
            }

            return path;
        }

        private UnityWebRequest AuthorizedGet(string url)
        {
            var request = UnityWebRequest.Get(url);
            request.redirectLimit = 0;
            request.timeout = 30;
            request.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            request.SetRequestHeader("Cache-Control", "no-store");
            return request;
        }

        private static bool IsCanonicalBodyId(string value)
        {
            const string prefix = "bodyid-";
            return value != null
                && value.Length == prefix.Length + 24
                && value.StartsWith(prefix, StringComparison.Ordinal)
                && IsLowerHex(value.Substring(prefix.Length), 24);
        }

        private static bool IsLowerHex(string value, int length)
        {
            if (value == null || value.Length != length)
            {
                return false;
            }
            foreach (var c in value)
            {
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                {
                    return false;
                }
            }
            return true;
        }

        private static string Sha256(byte[] bytes)
        {
            using (var sha = SHA256.Create())
            {
                return BitConverter.ToString(sha.ComputeHash(bytes))
                    .Replace("-", string.Empty)
                    .ToLowerInvariant();
            }
        }

        private static string Sha256File(string path)
        {
            using (var sha = SHA256.Create())
            using (var stream = File.OpenRead(path))
            {
                return BitConverter.ToString(sha.ComputeHash(stream))
                    .Replace("-", string.Empty)
                    .ToLowerInvariant();
            }
        }

        private static void Fail(string message)
        {
            Debug.LogWarning("BodyRig: remote avatar source failed: " + message);
        }
    }
}

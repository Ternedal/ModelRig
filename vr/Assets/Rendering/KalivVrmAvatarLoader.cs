using System;
using System.Collections;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR.Rendering
{
    public sealed class KalivVrmAvatarLoader : MonoBehaviour
    {
        [Serializable]
        private sealed class ActiveBodyManifest
        {
            public string schema;
            public string body_id;
            public string name;
            public string package_sha256;
            public string source;
            public string[] motion_names;
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

        private KalivVrmRenderer _renderer;
        private Transform _gazeTarget;
        private Vrm10Instance _current;
        private int _loadGeneration;

        public Vrm10Instance Current => _current;
        public string BodyId { get; private set; }
        public string BodyName { get; private set; }
        public string PackageSha256 { get; private set; }
        public float HeightScale { get; private set; } = 1f;
        public string[] MotionNames { get; private set; } = Array.Empty<string>();

        public event Action<Vrm10Instance> AvatarLoaded;
        public event Action<string> LoadFailed;

        public void Initialize(KalivVrmRenderer renderer, Transform gazeTarget)
        {
            _renderer = renderer ?? throw new ArgumentNullException(nameof(renderer));
            _gazeTarget = gazeTarget;
        }

        public IEnumerator LoadActiveFromRig(string baseUrl, string token)
        {
            int generation = ++_loadGeneration;
            string origin = Normalize(baseUrl);
            if (string.IsNullOrWhiteSpace(origin) || string.IsNullOrWhiteSpace(token))
            {
                Fail("Kaliv VR renderer mangler rig-adresse eller device-token.");
                yield break;
            }

            ActiveBodyManifest manifest = null;
            using (var request = AuthorizedGet(origin + "/api/v1/body/active", token))
            {
                yield return request.SendWebRequest();
                if (generation != _loadGeneration) yield break;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail($"Kunne ikke hente aktiv krop (HTTP {request.responseCode}).");
                    yield break;
                }

                try
                {
                    manifest = JsonUtility.FromJson<ActiveBodyManifest>(request.downloadHandler.text);
                }
                catch (Exception exc)
                {
                    Fail("BodyRig-manifestet kunne ikke læses: " + exc.Message);
                    yield break;
                }
            }

            if (manifest == null ||
                manifest.schema != "modelrig-body-assets/v1" ||
                !IsCanonicalBodyId(manifest.body_id) ||
                !IsLowerHex(manifest.package_sha256, 64))
            {
                Fail("Riggen returnerede et ugyldigt BodyRig asset-manifest.");
                yield break;
            }

            float pendingHeightScale = 1f;
            using (var request = AuthorizedGet(origin + "/api/v1/body/active/bodyprint.json", token))
            {
                yield return request.SendWebRequest();
                if (generation != _loadGeneration) yield break;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail($"Kunne ikke hente bodyprint.json (HTTP {request.responseCode}).");
                    yield break;
                }

                string bodyprintBodyId = (request.GetResponseHeader("X-BodyRig-Body-ID") ?? "").Trim();
                string bodyprintPackage = (request.GetResponseHeader("X-BodyRig-Package-SHA256") ?? "").Trim();
                string expectedBodyprintSha = (request.GetResponseHeader("X-BodyRig-Member-SHA256") ?? "")
                    .Trim().ToLowerInvariant();

                if (!string.IsNullOrEmpty(bodyprintBodyId) && bodyprintBodyId != manifest.body_id)
                {
                    Fail("BodyRig body-id ændrede sig under bodyprint-download.");
                    yield break;
                }
                if (!string.IsNullOrEmpty(bodyprintPackage) &&
                    !string.Equals(bodyprintPackage, manifest.package_sha256, StringComparison.OrdinalIgnoreCase))
                {
                    Fail("BodyRig package-revision ændrede sig under bodyprint-download.");
                    yield break;
                }

                byte[] bodyprintBytes = request.downloadHandler.data;
                if (bodyprintBytes == null || bodyprintBytes.Length == 0)
                {
                    Fail("Riggen returnerede en tom bodyprint.json.");
                    yield break;
                }

                string bodyprintSha = Sha256(bodyprintBytes);
                if (!string.IsNullOrEmpty(expectedBodyprintSha) &&
                    !string.Equals(expectedBodyprintSha, bodyprintSha, StringComparison.Ordinal))
                {
                    Fail("bodyprint.json fejlede SHA-256-verifikation.");
                    yield break;
                }

                try
                {
                    string json = System.Text.Encoding.UTF8.GetString(bodyprintBytes);
                    var bodyprint = JsonUtility.FromJson<BodyprintDocument>(json);
                    if (bodyprint == null || bodyprint.format != "modelrig-bodyprint" || bodyprint.version != 1)
                    {
                        Fail("Riggen returnerede et ukendt BodyRig bodyprint-format.");
                        yield break;
                    }

                    if (bodyprint.shape != null && bodyprint.shape.height_scale > 0f)
                    {
                        if (float.IsNaN(bodyprint.shape.height_scale) ||
                            float.IsInfinity(bodyprint.shape.height_scale) ||
                            bodyprint.shape.height_scale > 4f)
                        {
                            Fail("BodyRig height_scale er uden for den tilladte kontrakt.");
                            yield break;
                        }
                        pendingHeightScale = bodyprint.shape.height_scale;
                    }
                }
                catch (Exception exc)
                {
                    Fail("bodyprint.json kunne ikke læses: " + exc.Message);
                    yield break;
                }
            }

            byte[] avatarBytes;
            string expectedMemberSha;
            using (var request = AuthorizedGet(origin + "/api/v1/body/active/avatar.vrm", token))
            {
                yield return request.SendWebRequest();
                if (generation != _loadGeneration) yield break;
                if (request.result != UnityWebRequest.Result.Success)
                {
                    Fail($"Kunne ikke hente avatar.vrm (HTTP {request.responseCode}).");
                    yield break;
                }

                avatarBytes = request.downloadHandler.data;
                expectedMemberSha = (request.GetResponseHeader("X-BodyRig-Member-SHA256") ?? "")
                    .Trim().ToLowerInvariant();

                string responseBodyId = (request.GetResponseHeader("X-BodyRig-Body-ID") ?? "").Trim();
                string responsePackage = (request.GetResponseHeader("X-BodyRig-Package-SHA256") ?? "").Trim();

                if (!string.IsNullOrEmpty(responseBodyId) && responseBodyId != manifest.body_id)
                {
                    Fail("BodyRig body-id ændrede sig under avatar-download; prøver ikke at blande revisioner.");
                    yield break;
                }
                if (!string.IsNullOrEmpty(responsePackage) &&
                    !string.Equals(responsePackage, manifest.package_sha256, StringComparison.OrdinalIgnoreCase))
                {
                    Fail("BodyRig package-revision ændrede sig under avatar-download.");
                    yield break;
                }
            }

            if (avatarBytes == null || avatarBytes.Length < 20)
            {
                Fail("Riggen returnerede en tom eller ugyldig avatar.");
                yield break;
            }

            string actualSha = Sha256(avatarBytes);
            if (!string.IsNullOrEmpty(expectedMemberSha) &&
                !string.Equals(expectedMemberSha, actualSha, StringComparison.Ordinal))
            {
                Fail("avatar.vrm fejlede SHA-256-verifikation.");
                yield break;
            }

            string bodyId = manifest.body_id;
            string bodyName = manifest.name;
            string packageSha = manifest.package_sha256;
            float heightScale = pendingHeightScale;
            string[] motionNames;
            try
            {
                motionNames = ValidateMotionNames(manifest.motion_names);
            }
            catch (Exception exc)
            {
                Fail("BodyRig motion-inventory er ugyldigt: " + exc.Message);
                yield break;
            }

            string folder = Path.Combine(Application.persistentDataPath, "KalivVR", "Bodies");
            Directory.CreateDirectory(folder);
            string safePackage = manifest.package_sha256.Length > 20
                ? manifest.package_sha256.Substring(0, 20)
                : manifest.package_sha256;
            string path = Path.Combine(folder, bodyId + "-" + safePackage + ".vrm");

            bool write = true;
            if (File.Exists(path))
            {
                try { write = !string.Equals(Sha256(File.ReadAllBytes(path)), actualSha, StringComparison.Ordinal); }
                catch { write = true; }
            }
            if (write) File.WriteAllBytes(path, avatarBytes);

            if (generation != _loadGeneration) yield break;
            _ = LoadPathAsync(path, generation, bodyId, bodyName, packageSha, heightScale, motionNames);
        }

        private async Task LoadPathAsync(
            string path,
            int generation,
            string bodyId,
            string bodyName,
            string packageSha,
            float heightScale,
            string[] motionNames)
        {
            try
            {
                var awaitCaller = new RuntimeOnlyAwaitCaller();
                var instance = await Vrm10.LoadPathAsync(
                    path,
                    canLoadVrm0X: false,
                    showMeshes: false,
                    awaitCaller: awaitCaller);
                if (instance == null)
                    throw new InvalidOperationException("UniVRM returnerede ingen VRM 1.0-instans.");

                if (generation != _loadGeneration)
                {
                    Destroy(instance.gameObject);
                    return;
                }

                await instance.Vrm.FirstPerson.SetupAsync(instance.gameObject, awaitCaller);
                if (generation != _loadGeneration)
                {
                    Destroy(instance.gameObject);
                    return;
                }

                instance.GetComponent<RuntimeGltfInstance>()?.ShowMeshes();
                instance.transform.SetParent(transform, false);
                instance.transform.localScale = Vector3.one * heightScale;
                AlignFeetToParentFloor(instance);

                _renderer.Bind(instance, _gazeTarget);
                if (generation != _loadGeneration)
                {
                    Destroy(instance.gameObject);
                    return;
                }
                if (!_renderer.IsBound)
                    throw new InvalidOperationException("Kaliv VR renderer kunne ikke binde VRM-avatarens humanoid rig.");

                var previous = _current;
                _current = instance;
                BodyId = bodyId;
                BodyName = bodyName;
                PackageSha256 = packageSha;
                HeightScale = heightScale;
                MotionNames = motionNames;
                if (previous != null) Destroy(previous.gameObject);

                AvatarLoaded?.Invoke(instance);
            }
            catch (Exception exc)
            {
                Fail("VRM-load fejlede: " + exc.Message);
            }
        }

        private static void AlignFeetToParentFloor(Vrm10Instance instance)
        {
            if (instance == null || instance.transform.parent == null) return;

            var animator = instance.GetComponent<Animator>();
            if (animator == null || !animator.isHuman) return;

            Transform left = animator.GetBoneTransform(HumanBodyBones.LeftFoot);
            Transform right = animator.GetBoneTransform(HumanBodyBones.RightFoot);

            bool have = false;
            float floorY = float.PositiveInfinity;
            var parent = instance.transform.parent;

            if (left != null)
            {
                floorY = Mathf.Min(floorY, parent.InverseTransformPoint(left.position).y);
                have = true;
            }
            if (right != null)
            {
                floorY = Mathf.Min(floorY, parent.InverseTransformPoint(right.position).y);
                have = true;
            }

            if (!have || float.IsNaN(floorY) || float.IsInfinity(floorY))
            {
                Debug.LogWarning(
                    "[KalivVR.Render] humanoid feet unavailable; keeping authored VRM root height.");
                return;
            }

            instance.transform.localPosition += Vector3.up * -floorY;
            Debug.Log($"[KalivVR.Render] avatar floor aligned by {-floorY:0.000} m.");
        }

        public void Unload()
        {
            ++_loadGeneration;
            if (_current != null)
            {
                Destroy(_current.gameObject);
                _current = null;
            }
            BodyId = null;
            BodyName = null;
            PackageSha256 = null;
            HeightScale = 1f;
            MotionNames = Array.Empty<string>();
        }

        private static bool IsCanonicalBodyId(string value)
        {
            const string prefix = "bodyid-";
            if (value == null || value.Length != prefix.Length + 24 ||
                !value.StartsWith(prefix, StringComparison.Ordinal))
                return false;

            return IsLowerHex(value.Substring(prefix.Length), 24);
        }

        private static bool IsLowerHex(string value, int length)
        {
            if (value == null || value.Length != length) return false;
            foreach (char c in value)
            {
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f')))
                    return false;
            }
            return true;
        }

        private static string[] ValidateMotionNames(string[] names)
        {
            if (names == null || names.Length == 0) return Array.Empty<string>();
            var output = new System.Collections.Generic.List<string>(names.Length);
            foreach (string raw in names)
            {
                string name = (raw ?? "").Trim();
                if (name != "idle" && name != "walk" && name != "talk" &&
                    name != "gesture_01" && name != "gesture_02" && name != "gesture_03")
                {
                    throw new FormatException("BodyRig manifest contains an unsupported motion name.");
                }
                if (!output.Contains(name)) output.Add(name);
            }
            return output.ToArray();
        }

        private static UnityWebRequest AuthorizedGet(string url, string token)
        {
            var request = UnityWebRequest.Get(url);
            request.redirectLimit = 0;
            request.timeout = 30;
            request.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            request.SetRequestHeader("Cache-Control", "no-store");
            return request;
        }

        private void Fail(string message)
        {
            Debug.LogWarning("[KalivVR.Render] " + message);
            LoadFailed?.Invoke(message);
        }

        private static string Normalize(string value)
        {
            value = (value ?? "").Trim();
            while (value.EndsWith("/")) value = value.Substring(0, value.Length - 1);
            return value;
        }

        private static string Sha256(byte[] bytes)
        {
            using var sha = SHA256.Create();
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }
    }
}

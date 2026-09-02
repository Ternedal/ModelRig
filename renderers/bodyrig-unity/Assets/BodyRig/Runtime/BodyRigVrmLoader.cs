using System;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;

namespace ModelRig.BodyRig.UnityRenderer
{
    public sealed class BodyRigVrmLoader : MonoBehaviour
    {
        private const string RuntimeReceiptSchema = "bodyrig.unity_runtime_load/v0.1";

        [Serializable]
        private sealed class RuntimeReceipt
        {
            public string schema;
            public string created_at;
            public bool production_activation;
            public bool visual_acceptance;
            public bool vrm_loaded;
            public bool renderer_bound;
            public string candidate_git_sha;
            public string body_id;
            public string package_sha256;
            public string avatar_sha256;
            public string unity_version;
            public string vrm_path;
        }

        [SerializeField] private string vrmPath;
        [SerializeField] private BodyRigVrmRenderer renderer;
        [SerializeField] private Transform gazeTarget;
        [SerializeField] private bool loadOnStart = true;

        private Vrm10Instance current;

        public string VrmPath
        {
            get => vrmPath;
            set => vrmPath = value;
        }

        public BodyRigVrmRenderer Renderer
        {
            get => renderer;
            set => renderer = value;
        }

        public Transform GazeTarget
        {
            get => gazeTarget;
            set => gazeTarget = value;
        }

        public bool LoadOnStart
        {
            get => loadOnStart;
            set => loadOnStart = value;
        }

        private async void Start()
        {
            if (!loadOnStart)
            {
                return;
            }

            var path = ResolvePath();
            if (string.IsNullOrEmpty(path))
            {
                Debug.LogWarning("BodyRig: no VRM path configured. Set BODYRIG_VRM_PATH or VrmPath.");
                return;
            }

            try
            {
                await LoadAsync(path);
            }
            catch (Exception exc)
            {
                Debug.LogError("BodyRig: VRM load failed: " + exc);
            }
        }

        public async Task<Vrm10Instance> LoadAsync(string path)
        {
            if (string.IsNullOrWhiteSpace(path))
            {
                throw new ArgumentException("VRM path is required.", nameof(path));
            }

            var fullPath = Path.GetFullPath(path);
            if (!File.Exists(fullPath))
            {
                throw new FileNotFoundException("BodyRig VRM file does not exist.", fullPath);
            }

            var awaitCaller = new RuntimeOnlyAwaitCaller();
            var instance = await Vrm10.LoadPathAsync(
                fullPath,
                canLoadVrm0X: false,
                showMeshes: false,
                awaitCaller: awaitCaller);
            if (instance == null)
            {
                throw new InvalidOperationException("UniVRM returned no VRM 1.0 instance.");
            }

            await instance.Vrm.FirstPerson.SetupAsync(instance.gameObject, awaitCaller);
            var runtimeGltf = instance.GetComponent<RuntimeGltfInstance>();
            runtimeGltf?.ShowMeshes();

            instance.transform.SetParent(transform, false);
            if (current != null)
            {
                Destroy(current.gameObject);
            }
            current = instance;

            if (renderer == null)
            {
                renderer = GetComponent<BodyRigVrmRenderer>();
            }
            if (renderer == null)
            {
                renderer = gameObject.AddComponent<BodyRigVrmRenderer>();
            }

            renderer.Bind(instance, gazeTarget);
            if (!renderer.IsBound)
            {
                throw new InvalidOperationException("BodyRig renderer did not bind the loaded VRM instance.");
            }

            WriteRuntimeReceiptIfRequested(fullPath);
            return instance;
        }

        private string ResolvePath()
        {
            if (!string.IsNullOrWhiteSpace(vrmPath))
            {
                return vrmPath;
            }
            return Environment.GetEnvironmentVariable("BODYRIG_VRM_PATH");
        }

        private static void WriteRuntimeReceiptIfRequested(string fullPath)
        {
            var receiptPathRaw = Environment.GetEnvironmentVariable("BODYRIG_RUNTIME_RECEIPT");
            if (string.IsNullOrWhiteSpace(receiptPathRaw))
            {
                return;
            }

            var candidateSha = RequireEnvironment("BODYRIG_CANDIDATE_SHA");
            var bodyId = RequireEnvironment("BODYRIG_BODY_ID");
            var packageSha = RequireEnvironment("BODYRIG_PACKAGE_SHA256");
            var expectedAvatarSha = RequireEnvironment("BODYRIG_AVATAR_SHA256").ToLowerInvariant();
            var actualAvatarSha = Sha256File(fullPath);
            if (!string.Equals(expectedAvatarSha, actualAvatarSha, StringComparison.Ordinal))
            {
                throw new InvalidOperationException(
                    "BodyRig runtime avatar SHA-256 differs from the selected renderer handoff.");
            }

            var receiptPath = Path.GetFullPath(receiptPathRaw);
            if (File.Exists(receiptPath) || Directory.Exists(receiptPath))
            {
                throw new IOException("BodyRig runtime receipt destination already exists.");
            }
            var directory = Path.GetDirectoryName(receiptPath);
            if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
            {
                throw new DirectoryNotFoundException("BodyRig runtime receipt directory does not exist.");
            }

            var receipt = new RuntimeReceipt
            {
                schema = RuntimeReceiptSchema,
                created_at = DateTimeOffset.UtcNow.ToString("o"),
                production_activation = false,
                visual_acceptance = false,
                vrm_loaded = true,
                renderer_bound = true,
                candidate_git_sha = candidateSha,
                body_id = bodyId,
                package_sha256 = packageSha,
                avatar_sha256 = actualAvatarSha,
                unity_version = Application.unityVersion,
                vrm_path = fullPath,
            };
            var raw = Encoding.UTF8.GetBytes(JsonUtility.ToJson(receipt, false));
            var temporary = receiptPath + ".tmp-" + Guid.NewGuid().ToString("N");
            try
            {
                using (var stream = new FileStream(
                    temporary,
                    FileMode.CreateNew,
                    FileAccess.Write,
                    FileShare.None))
                {
                    stream.Write(raw, 0, raw.Length);
                    stream.Flush(true);
                }
                if (File.Exists(receiptPath) || Directory.Exists(receiptPath))
                {
                    throw new IOException("BodyRig runtime receipt destination appeared before commit.");
                }
                File.Move(temporary, receiptPath);
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

            Debug.Log("BodyRig: VRM loaded, renderer bound, runtime receipt committed: " + receiptPath);
        }

        private static string RequireEnvironment(string name)
        {
            var value = Environment.GetEnvironmentVariable(name);
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new InvalidOperationException("BodyRig runtime proof environment is missing " + name + ".");
            }
            return value;
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
    }
}

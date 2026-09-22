using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Security.Cryptography;
using System.Threading.Tasks;
using UniGLTF;
using UniVRM10;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR.Rendering
{
    /// <summary>
    /// Loads the active .mrbody revision's authored VRM Animation state clips.
    ///
    /// Only semantically unambiguous state mappings are used:
    ///   idle -> motions/idle.vrma
    ///   speaking -> motions/talk.vrma (fallback: idle)
    ///
    /// gesture_01..03 are deliberately not guessed into semantic gestures.
    /// BodyRig remains the semantic authority until an explicit mapping exists.
    /// </summary>
    public sealed class KalivVrmaMotionController : MonoBehaviour
    {
        private sealed class BodyOnlyAnimation : IVrm10Animation
        {
            private static readonly IReadOnlyDictionary<ExpressionKey, Func<float>> EmptyExpressions =
                new Dictionary<ExpressionKey, Func<float>>();

            private readonly Vrm10AnimationInstance _source;

            public BodyOnlyAnimation(Vrm10AnimationInstance source)
            {
                _source = source ?? throw new ArgumentNullException(nameof(source));
            }

            public (INormalizedPoseProvider, ITPoseProvider) ControlRig => _source.ControlRig;
            public IReadOnlyDictionary<ExpressionKey, Func<float>> ExpressionMap => EmptyExpressions;
            public LookAtInput? LookAt => null;

            public void ShowBoxMan(bool enable) => _source.ShowBoxMan(enable);
            public void SetBoxManMaterial(Material material) => _source.SetBoxManMaterial(material);

            // Lifetime belongs to KalivVrmaMotionController. Vrm10Runtime does not
            // own or dispose the source when VrmAnimation is replaced.
            public void Dispose() { }
        }

        private sealed class LoadedMotion
        {
            public string Name;
            public Vrm10AnimationInstance Instance;
            public BodyOnlyAnimation BodyOnly;
        }

        private readonly Dictionary<string, LoadedMotion> _motions =
            new Dictionary<string, LoadedMotion>(StringComparer.Ordinal);

        private Vrm10Instance _avatar;
        private KalivVrmRenderer _renderer;
        private string _baseUrl;
        private string _token;
        private string _bodyId;
        private string _packageSha;
        private string _state = "idle";
        private int _generation;
        private Coroutine _loadLoop;

        public bool IsAuthoredMotionActive =>
            _avatar != null && _motions.ContainsKey("idle");

        public event Action<string> MotionStatus;
        public event Action<string> MotionWarning;

        public void BindRevision(
            Vrm10Instance avatar,
            KalivVrmRenderer renderer,
            string baseUrl,
            string token,
            string bodyId,
            string packageSha,
            string[] motionNames)
        {
            ResetRevision();

            _avatar = avatar ?? throw new ArgumentNullException(nameof(avatar));
            _renderer = renderer ?? throw new ArgumentNullException(nameof(renderer));
            _baseUrl = (baseUrl ?? "").Trim().TrimEnd('/');
            _token = token ?? "";
            _bodyId = bodyId ?? "";
            _packageSha = packageSha ?? "";

            if (string.IsNullOrWhiteSpace(_baseUrl) ||
                string.IsNullOrWhiteSpace(_token) ||
                string.IsNullOrWhiteSpace(_bodyId) ||
                string.IsNullOrWhiteSpace(_packageSha))
            {
                MotionWarning?.Invoke("VRMA state-motion mangler BodyRig revision authority.");
                return;
            }

            bool hasIdle = Contains(motionNames, "idle");
            if (!hasIdle)
            {
                // Without a neutral authored baseline, enabling only talk risks
                // freezing the avatar in the last talking pose when speech ends.
                MotionStatus?.Invoke("Ingen idle.vrma · bruger procedural body motion.");
                return;
            }

            var wanted = new List<string> { "idle" };
            if (Contains(motionNames, "talk")) wanted.Add("talk");

            int generation = ++_generation;
            _loadLoop = StartCoroutine(LoadMotions(generation, wanted));
        }

        public void ApplyFrame(KalivBodyRenderFrame frame)
        {
            if (frame == null) return;
            _state = frame.state ?? "idle";
            ApplyStateMotion();
        }

        public void ResetRevision()
        {
            ++_generation;
            if (_loadLoop != null)
            {
                StopCoroutine(_loadLoop);
                _loadLoop = null;
            }

            if (_avatar != null && _avatar.Runtime != null)
                _avatar.Runtime.VrmAnimation = null;

            _renderer?.SetAuthoredMotionActive(false);

            foreach (var motion in _motions.Values)
            {
                if (motion?.Instance != null) Destroy(motion.Instance.gameObject);
            }
            _motions.Clear();

            _avatar = null;
            _renderer = null;
            _baseUrl = "";
            _token = "";
            _bodyId = "";
            _packageSha = "";
            _state = "idle";
        }

        private IEnumerator LoadMotions(int generation, List<string> names)
        {
            foreach (string name in names)
            {
                if (generation != _generation) yield break;

                byte[] bytes = null;
                string memberSha = "";
                string url = _baseUrl + "/api/v1/body/active/motions/" + name + ".vrma";

                using (var request = UnityWebRequest.Get(url))
                {
                    request.redirectLimit = 0;
                    request.timeout = 30;
                    request.SetRequestHeader("Authorization", "Bearer " + _token.Trim());
                    request.SetRequestHeader("Cache-Control", "no-store");

                    yield return request.SendWebRequest();
                    if (generation != _generation) yield break;

                    if (request.result != UnityWebRequest.Result.Success)
                    {
                        if (name == "idle")
                        {
                            MotionWarning?.Invoke(
                                $"idle.vrma kunne ikke hentes (HTTP {request.responseCode}); bruger procedural motion.");
                            yield break;
                        }

                        MotionWarning?.Invoke(
                            $"{name}.vrma kunne ikke hentes (HTTP {request.responseCode}); bruger idle.");
                        continue;
                    }

                    string responseBodyId =
                        (request.GetResponseHeader("X-BodyRig-Body-ID") ?? "").Trim();
                    string responsePackage =
                        (request.GetResponseHeader("X-BodyRig-Package-SHA256") ?? "").Trim();
                    memberSha =
                        (request.GetResponseHeader("X-BodyRig-Member-SHA256") ?? "").Trim().ToLowerInvariant();

                    if ((!string.IsNullOrEmpty(responseBodyId) && responseBodyId != _bodyId) ||
                        (!string.IsNullOrEmpty(responsePackage) &&
                         !string.Equals(responsePackage, _packageSha, StringComparison.OrdinalIgnoreCase)))
                    {
                        MotionWarning?.Invoke(
                            "BodyRig revision ændrede sig under VRMA-download; motion droppes.");
                        yield break;
                    }

                    bytes = request.downloadHandler.data;
                }

                if (bytes == null || bytes.Length < 20)
                {
                    MotionWarning?.Invoke(name + ".vrma var tom eller ugyldig.");
                    if (name == "idle") yield break;
                    continue;
                }

                string actualSha = Sha256(bytes);
                if (!string.IsNullOrEmpty(memberSha) &&
                    !string.Equals(memberSha, actualSha, StringComparison.Ordinal))
                {
                    MotionWarning?.Invoke(name + ".vrma fejlede SHA-256-verifikation.");
                    if (name == "idle") yield break;
                    continue;
                }

                string directory = Path.Combine(
                    Application.persistentDataPath,
                    "KalivVR",
                    "Bodies",
                    Safe(_bodyId),
                    Safe(_packageSha));
                Directory.CreateDirectory(directory);
                string path = Path.Combine(directory, name + ".vrma");

                bool write = true;
                if (File.Exists(path))
                {
                    try
                    {
                        write = !string.Equals(
                            Sha256(File.ReadAllBytes(path)),
                            actualSha,
                            StringComparison.Ordinal);
                    }
                    catch
                    {
                        write = true;
                    }
                }
                if (write) File.WriteAllBytes(path, bytes);

                Task<LoadedMotion> task = LoadVrmaAsync(path, name, generation);
                while (!task.IsCompleted)
                {
                    if (generation != _generation) yield break;
                    yield return null;
                }

                if (generation != _generation) yield break;

                if (task.IsCanceled)
                {
                    MotionWarning?.Invoke(name + ".vrma load blev annulleret.");
                    if (name == "idle") yield break;
                    continue;
                }

                if (task.IsFaulted || task.Result == null || task.Result.Instance == null || task.Result.BodyOnly == null)
                {
                    string detail = task.Exception?.GetBaseException().Message ?? "ukendt VRMA-loadfejl";
                    MotionWarning?.Invoke(name + ".vrma kunne ikke bindes: " + detail);
                    if (name == "idle") yield break;
                    continue;
                }

                _motions[name] = task.Result;
            }

            _loadLoop = null;

            if (!_motions.ContainsKey("idle"))
            {
                _renderer?.SetAuthoredMotionActive(false);
                yield break;
            }

            ApplyStateMotion();
            MotionStatus?.Invoke(
                _motions.ContainsKey("talk")
                    ? "Authored motion · idle + talk"
                    : "Authored motion · idle");
        }

        private async Task<LoadedMotion> LoadVrmaAsync(string path, string name, int generation)
        {
            using GltfData data = new AutoGltfFileParser(path).Parse();
            var vrmaData = new VrmAnimationData(data);
            using var loader = new VrmAnimationImporter(vrmaData);
            var gltfInstance = await loader.LoadAsync(new RuntimeOnlyAwaitCaller());

            if (generation != _generation)
            {
                if (gltfInstance != null) Destroy(gltfInstance.gameObject);
                return null;
            }

            var motion = gltfInstance != null
                ? gltfInstance.GetComponent<Vrm10AnimationInstance>()
                : null;
            if (motion == null)
            {
                if (gltfInstance != null) Destroy(gltfInstance.gameObject);
                throw new InvalidOperationException("UniVRM returnerede ingen Vrm10AnimationInstance.");
            }

            if (motion.BoxMan != null) motion.BoxMan.enabled = false;

            var animation = motion.GetComponent<Animation>();
            if (animation == null)
            {
                Destroy(motion.gameObject);
                throw new InvalidOperationException("VRMA-instansen mangler Unity Animation-komponenten.");
            }

            animation.wrapMode = WrapMode.Loop;
            foreach (AnimationState state in animation)
            {
                state.wrapMode = WrapMode.Loop;
                state.speed = 1f;
            }
            animation.Play();

            motion.transform.SetParent(transform, false);
            return new LoadedMotion
            {
                Name = name,
                Instance = motion,
                BodyOnly = new BodyOnlyAnimation(motion),
            };
        }

        private void ApplyStateMotion()
        {
            if (_avatar == null || _avatar.Runtime == null || !_motions.TryGetValue("idle", out var idle))
            {
                _renderer?.SetAuthoredMotionActive(false);
                return;
            }

            LoadedMotion selected = idle;
            if (_state == "speaking" && _motions.TryGetValue("talk", out var talk))
                selected = talk;

            if (_avatar.Runtime.VrmAnimation != selected.BodyOnly)
                _avatar.Runtime.VrmAnimation = selected.BodyOnly;

            _renderer?.SetAuthoredMotionActive(true);
        }

        private static bool Contains(string[] values, string target)
        {
            if (values == null) return false;
            foreach (string value in values)
                if (string.Equals(value, target, StringComparison.Ordinal)) return true;
            return false;
        }

        private static string Safe(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "unknown";
            foreach (char c in Path.GetInvalidFileNameChars())
                value = value.Replace(c, '_');
            return value.Length <= 96 ? value : value.Substring(0, 96);
        }

        private static string Sha256(byte[] bytes)
        {
            using var sha = SHA256.Create();
            return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        private void OnDisable() => ResetRevision();
        private void OnDestroy() => ResetRevision();
    }
}

using System;
using System.Collections;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace ModelRig.BodyRig.UnityRenderer
{
    /// <summary>
    /// Live frame source: reads the rig's render-frame stream
    /// (GET /api/v1/body/frames, server-sent events, one v0.1 frame per
    /// "data:" line) and applies each frame to the renderer -- the same
    /// contract the fixture player uses, so the renderer cannot tell them
    /// apart. Every frame is validated before it is applied, no frame is
    /// applied before the VRM is bound, timestamps must advance within each
    /// stream, and a dropped connection reconnects with a delay instead of
    /// throwing.
    ///
    /// The fixture player remains the deterministic proof path; this is the
    /// product path. Both feed BodyRigVrmRenderer.Apply and nothing else.
    /// </summary>
    public sealed class BodyRigFrameSource : MonoBehaviour
    {
        private const string LiveReceiptSchema = "bodyrig.unity_live_stream/v0.1";

        /// <summary>
        /// Emitted only after a frame has passed validation, timestamp ordering,
        /// renderer binding and renderer.Apply(). Machine evidence may observe
        /// this event; it must never be used as an alternate render path.
        /// </summary>
        public static event Action<BodyRigRenderFrame> FrameApplied;

        [Serializable]
        private sealed class LiveReceipt
        {
            public string schema;
            public string created_at;
            public bool production_activation;
            public string candidate_git_sha;
            public string body_id;
            public string package_sha256;
            public string source_url;
            public bool bearer_auth_used;
            public bool renderer_bound;
            public bool frame_applied;
            public long first_frame_timestamp_ms;
            public string first_frame_state;
        }

        [SerializeField] private BodyRigVrmRenderer renderer;
        [SerializeField] private string baseUrl = "";
        [SerializeField] private string token = "";
        [SerializeField] private float reconnectDelaySeconds = 2.0f;

        private long lastTimestampMs = -1;
        private bool connected;
        private bool liveReceiptAttempted;

        public BodyRigVrmRenderer Renderer
        {
            get => renderer;
            set => renderer = value;
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

        public bool IsConnected => connected;

        private void Start()
        {
            if (renderer == null || string.IsNullOrWhiteSpace(baseUrl) || string.IsNullOrWhiteSpace(token))
            {
                Debug.LogWarning("BodyRig: frame source needs a renderer, a base URL and a device token.");
                enabled = false;
                return;
            }
            StartCoroutine(StreamForever());
        }

        private IEnumerator StreamForever()
        {
            var url = baseUrl.TrimEnd('/') + "/api/v1/body/frames";
            while (enabled)
            {
                using (var request = UnityWebRequest.Get(url))
                {
                    // The paired device token is origin-bound proof material.
                    // A rig endpoint that redirects is a configuration error;
                    // do not let Unity replay Bearer credentials to a redirect.
                    request.redirectLimit = 0;
                    request.SetRequestHeader("Authorization", "Bearer " + token);
                    request.SetRequestHeader("Accept", "text/event-stream");
                    request.downloadHandler = new SseFrameHandler(this);
                    request.timeout = 0;
                    connected = false;
                    // Monotonicity is scoped to one HTTP/SSE stream. A reconnect
                    // starts a new stream and may legitimately follow a rig reboot
                    // whose monotonic clock has restarted.
                    lastTimestampMs = -1;
                    yield return request.SendWebRequest();
                    connected = false;
                    if (request.result != UnityWebRequest.Result.Success)
                    {
                        Debug.LogWarning("BodyRig: frame stream ended: " + request.error + " (HTTP " + request.responseCode + ")");
                    }
                }
                // Any exit -- rig restarted, network dropped, 404 while no body
                // is active -- is a pause, not a failure. The avatar keeps its
                // last frame; the renderer's own idle motion carries on.
                yield return new WaitForSecondsRealtime(reconnectDelaySeconds);
            }
        }

        /// <summary>
        /// One decoded SSE payload. Runs on the main thread (DownloadHandlerScript
        /// callbacks do), so applying directly is safe.
        /// </summary>
        internal void OnFramePayload(string json)
        {
            BodyRigRenderFrame frame;
            try
            {
                frame = JsonUtility.FromJson<BodyRigRenderFrame>(json);
                if (frame == null)
                {
                    throw new FormatException("BodyRig frame payload is empty.");
                }
                frame.Validate();
            }
            catch (Exception exc)
            {
                // A malformed frame is dropped, never applied and never fatal:
                // the stream continues with the next one.
                Debug.LogWarning("BodyRig: dropped invalid frame: " + exc.Message);
                return;
            }
            connected = true;
            if (renderer == null || !renderer.IsBound)
            {
                // Same rule as the fixture player: nothing reaches an avatar
                // that is not there yet.
                return;
            }
            if (frame.timestamp_ms <= lastTimestampMs)
            {
                return;
            }
            lastTimestampMs = frame.timestamp_ms;
            renderer.Apply(frame);
            FrameApplied?.Invoke(frame);
            WriteLiveReceiptIfRequested(frame);
        }

        private void WriteLiveReceiptIfRequested(BodyRigRenderFrame frame)
        {
            if (liveReceiptAttempted)
            {
                return;
            }
            var receiptPathRaw = Environment.GetEnvironmentVariable("BODYRIG_LIVE_RECEIPT");
            if (string.IsNullOrWhiteSpace(receiptPathRaw))
            {
                return;
            }
            liveReceiptAttempted = true;
            try
            {
                var receiptPath = Path.GetFullPath(receiptPathRaw);
                if (File.Exists(receiptPath) || Directory.Exists(receiptPath))
                {
                    throw new IOException("BodyRig live receipt destination already exists.");
                }
                var directory = Path.GetDirectoryName(receiptPath);
                if (string.IsNullOrWhiteSpace(directory) || !Directory.Exists(directory))
                {
                    throw new DirectoryNotFoundException("BodyRig live receipt directory does not exist.");
                }

                var receipt = new LiveReceipt
                {
                    schema = LiveReceiptSchema,
                    created_at = DateTimeOffset.UtcNow.ToString("o"),
                    production_activation = false,
                    candidate_git_sha = RequireEnvironment("BODYRIG_CANDIDATE_SHA"),
                    body_id = RequireEnvironment("BODYRIG_BODY_ID"),
                    package_sha256 = RequireEnvironment("BODYRIG_PACKAGE_SHA256"),
                    source_url = baseUrl.TrimEnd('/'),
                    bearer_auth_used = !string.IsNullOrWhiteSpace(token),
                    renderer_bound = renderer != null && renderer.IsBound,
                    frame_applied = true,
                    first_frame_timestamp_ms = frame.timestamp_ms,
                    first_frame_state = frame.state,
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
                        throw new IOException("BodyRig live receipt destination appeared before commit.");
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
                Debug.Log("BodyRig: first authenticated live frame applied; receipt committed: " + receiptPath);
            }
            catch (Exception exc)
            {
                Debug.LogError("BodyRig: could not commit live-frame receipt: " + exc.Message);
            }
        }

        private static string RequireEnvironment(string name)
        {
            var value = Environment.GetEnvironmentVariable(name);
            if (string.IsNullOrWhiteSpace(value))
            {
                throw new InvalidOperationException("BodyRig live proof environment is missing " + name + ".");
            }
            return value;
        }

        private sealed class SseFrameHandler : DownloadHandlerScript
        {
            private readonly BodyRigFrameSource owner;
            private readonly StringBuilder buffer = new StringBuilder();

            public SseFrameHandler(BodyRigFrameSource owner) : base(new byte[16 * 1024])
            {
                this.owner = owner;
            }

            protected override bool ReceiveData(byte[] data, int dataLength)
            {
                if (data == null || dataLength <= 0)
                {
                    return false;
                }
                buffer.Append(Encoding.UTF8.GetString(data, 0, dataLength));
                var text = buffer.ToString();
                int boundary;
                while ((boundary = text.IndexOf("\n\n", StringComparison.Ordinal)) >= 0)
                {
                    var eventText = text.Substring(0, boundary);
                    text = text.Substring(boundary + 2);
                    foreach (var line in eventText.Split('\n'))
                    {
                        if (line.StartsWith("data: ", StringComparison.Ordinal))
                        {
                            owner.OnFramePayload(line.Substring(6).Trim('\r'));
                        }
                    }
                }
                buffer.Clear();
                buffer.Append(text);
                return true;
            }

            protected override void CompleteContent()
            {
                buffer.Clear();
            }
        }
    }
}

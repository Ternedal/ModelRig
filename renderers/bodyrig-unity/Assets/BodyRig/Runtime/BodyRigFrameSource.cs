using System;
using System.Collections;
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
    /// applied before the VRM is bound, timestamps must advance, and a
    /// dropped connection reconnects with a delay instead of throwing.
    ///
    /// The fixture player remains the deterministic proof path; this is the
    /// product path. Both feed BodyRigVrmRenderer.Apply and nothing else.
    /// </summary>
    public sealed class BodyRigFrameSource : MonoBehaviour
    {
        [SerializeField] private BodyRigVrmRenderer renderer;
        [SerializeField] private string baseUrl = "";
        [SerializeField] private string token = "";
        [SerializeField] private float reconnectDelaySeconds = 2.0f;

        private long lastTimestampMs = -1;
        private bool connected;

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
                    request.SetRequestHeader("Authorization", "Bearer " + token);
                    request.SetRequestHeader("Accept", "text/event-stream");
                    request.downloadHandler = new SseFrameHandler(this);
                    request.timeout = 0;
                    connected = false;
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
            connected = true;
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
            if (renderer == null || !renderer.IsBound)
            {
                // Same rule as the fixture player: nothing reaches an avatar
                // that is not there yet.
                return;
            }
            if (frame.timestamp_ms <= lastTimestampMs)
            {
                // A reconnect restarts the rig's clock; accept the rewind once
                // by treating a large drop as a new stream, never apply stale
                // frames within one.
                if (lastTimestampMs - frame.timestamp_ms < 1000)
                {
                    return;
                }
            }
            lastTimestampMs = frame.timestamp_ms;
            renderer.Apply(frame);
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

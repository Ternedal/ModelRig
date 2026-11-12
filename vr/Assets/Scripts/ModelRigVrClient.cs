using System;
using System.Collections;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR
{
    /// <summary>
    /// Minimal ModelRig backend client for the Kaliv VR bootstrap.
    /// Uses the exact public client contracts already used by Android/Desktop:
    /// pair/claim, models and chat with bearer auth.
    /// </summary>
    public sealed class ModelRigVrClient : MonoBehaviour
    {
        [Serializable] private sealed class PairClaimRequest
        {
            public string device_name;
            public string code;
        }

        [Serializable] public sealed class PairingResponse
        {
            public string token;
            public string device_id;
        }

        [Serializable] public sealed class ModelInfo
        {
            public string name;
            public string model;
        }

        [Serializable] private sealed class ModelsResponse
        {
            public ModelInfo[] models;
            public ModelInfo[] data;
        }

        [Serializable] public sealed class ChatMessage
        {
            public string role;
            public string content;

            public ChatMessage(string role, string content)
            {
                this.role = role;
                this.content = content;
            }
        }

        [Serializable] private sealed class ChatRequest
        {
            public string model;
            public ChatMessage[] messages;
            public bool stream;
        }

        [Serializable] private sealed class ChatResponse
        {
            public ChatMessage message;
        }

        public IEnumerator ClaimPairing(
            string baseUrl,
            string code,
            Action<PairingResponse> ok,
            Action<string> fail)
        {
            var payload = new PairClaimRequest
            {
                device_name = "kaliv-vr",
                code = (code ?? "").Trim()
            };

            yield return JsonRequest(
                "POST",
                Normalize(baseUrl) + "/api/v1/pair/claim",
                JsonUtility.ToJson(payload),
                null,
                text =>
                {
                    var response = JsonUtility.FromJson<PairingResponse>(text);
                    if (response == null || string.IsNullOrWhiteSpace(response.token))
                    {
                        fail?.Invoke("Parringen svarede uden et device-token.");
                        return;
                    }
                    ok?.Invoke(response);
                },
                fail);
        }

        public IEnumerator ListModels(
            string baseUrl,
            string token,
            Action<List<string>> ok,
            Action<string> fail)
        {
            yield return JsonRequest(
                "GET",
                Normalize(baseUrl) + "/api/v1/models",
                null,
                token,
                text =>
                {
                    var root = JsonUtility.FromJson<ModelsResponse>(text);
                    var rows = root?.models ?? root?.data ?? Array.Empty<ModelInfo>();
                    var names = new List<string>();
                    foreach (var row in rows)
                    {
                        if (row == null) continue;
                        string name = !string.IsNullOrWhiteSpace(row.name) ? row.name : row.model;
                        if (!string.IsNullOrWhiteSpace(name) && !names.Contains(name))
                            names.Add(name);
                    }
                    ok?.Invoke(names);
                },
                fail);
        }

        public IEnumerator Chat(
            string baseUrl,
            string token,
            string model,
            IReadOnlyList<ChatMessage> history,
            Action<string> ok,
            Action<string> fail)
        {
            var messages = new ChatMessage[history.Count];
            for (int i = 0; i < history.Count; i++) messages[i] = history[i];

            var payload = new ChatRequest
            {
                model = model,
                messages = messages,
                stream = false
            };

            yield return JsonRequest(
                "POST",
                Normalize(baseUrl) + "/api/v1/chat",
                JsonUtility.ToJson(payload),
                token,
                text =>
                {
                    var response = JsonUtility.FromJson<ChatResponse>(text);
                    ok?.Invoke(response?.message?.content ?? "");
                },
                fail);
        }

        /// <summary>
        /// Streaming chat. Calls <paramref name="onDelta"/> per NDJSON chunk as it arrives,
        /// so the answer appears word by word instead of after the whole generation.
        ///
        /// The transport is a DownloadHandlerScript, because UnityWebRequest's buffered
        /// handler only hands over the body when the request completes — which is exactly
        /// the latency this slice removes. Lines are split here; meaning lives in
        /// KalivStreamContract, shared with the Android reader.
        ///
        /// <paramref name="registerCancel"/> hands back a cancel delegate so the UI can
        /// stop an in-flight generation. Stopping is reported through <paramref name="onStopped"/>,
        /// never as an error: the user ending a generation is a normal outcome, and an
        /// aborted UnityWebRequest is indistinguishable from a dropped link unless we say so.
        /// </summary>
        public IEnumerator ChatStream(
            string baseUrl,
            string token,
            string model,
            IReadOnlyList<ChatMessage> history,
            Action<string> onDelta,
            Action<string> onPhase,
            Action onDone,
            Action onStopped,
            Action<string> fail,
            Action<Action> registerCancel = null)
        {
            var messages = new ChatMessage[history.Count];
            for (int i = 0; i < history.Count; i++) messages[i] = history[i];

            var payload = new ChatRequest
            {
                model = model,
                messages = messages,
                stream = true
            };

            string url = Normalize(baseUrl) + "/api/v1/chat";
            using var req = new UnityWebRequest(url, "POST");

            bool sawTerminal = false;
            bool sawContent = false;
            string inBandFailure = null;

            var handler = new NdjsonDownloadHandler(line =>
            {
                var ev = KalivStreamContract.Parse(line);
                switch (ev.Kind)
                {
                    case KalivStreamEventKind.Delta:
                        sawContent = true;
                        onDelta?.Invoke(ev.Text);
                        break;
                    case KalivStreamEventKind.Done:
                        if (ev.Text.Length > 0) { sawContent = true; onDelta?.Invoke(ev.Text); }
                        sawTerminal = true;
                        break;
                    case KalivStreamEventKind.Failure:
                        inBandFailure = ev.Info;
                        sawTerminal = true;
                        break;
                    case KalivStreamEventKind.Phase:
                        onPhase?.Invoke(ev.Info);
                        break;
                }
            });

            req.downloadHandler = handler;
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload)));
            req.SetRequestHeader("Content-Type", "application/json");
            if (!string.IsNullOrWhiteSpace(token))
                req.SetRequestHeader("Authorization", "Bearer " + token.Trim());

            // No timeout on a stream: a long local generation is not a hung request, and
            // UnityWebRequest.timeout measures the whole transfer, not silence.
            req.timeout = 0;

            var liveReq = req;
            var liveHandler = handler;
            registerCancel?.Invoke(() =>
            {
                // Stop can land in the same frame the stream finishes, after `using` has
                // disposed the request. Aborting a disposed request throws, and the user
                // pressing Stop on an answer that just completed is not an error.
                try
                {
                    liveHandler.MarkAborted();
                    liveReq.Abort();
                }
                catch (Exception) { }
            });

            yield return req.SendWebRequest();

            // The user pressing Stop aborts the request; that is an outcome, not a failure.
            if (handler.Aborted)
            {
                onStopped?.Invoke();
                yield break;
            }

            if (req.result != UnityWebRequest.Result.Success)
            {
                string detail = string.IsNullOrWhiteSpace(handler.RawTail) ? req.error : handler.RawTail;
                fail?.Invoke($"POST {url} fejlede ({req.responseCode}): {detail}");
                yield break;
            }

            handler.FlushTail();

            if (inBandFailure != null) { fail?.Invoke("chat: " + inBandFailure); yield break; }

            string terminal = KalivStreamContract.TerminalFailure(sawTerminal, sawContent);
            if (terminal != null) { fail?.Invoke(terminal); yield break; }

            onDone?.Invoke();
        }

        /// <summary>
        /// Splits the incoming byte stream into NDJSON lines on Unity's main thread.
        /// ReceiveData is called as data arrives, which is what makes word-by-word possible.
        /// A chunk can split a line anywhere, including mid-UTF8, so bytes are decoded with
        /// a stateful decoder and the partial tail is carried to the next chunk.
        /// </summary>
        private sealed class NdjsonDownloadHandler : DownloadHandlerScript
        {
            private readonly Action<string> _onLine;
            private readonly StringBuilder _pending = new StringBuilder();
            private readonly System.Text.Decoder _decoder = Encoding.UTF8.GetDecoder();
            private char[] _chars = new char[4096];

            public bool Aborted { get; private set; }

            /// <summary>Last partial text, for error reporting when the body was not NDJSON.</summary>
            public string RawTail => _pending.ToString();

            public NdjsonDownloadHandler(Action<string> onLine) : base(new byte[16 * 1024])
            {
                _onLine = onLine;
            }

            public void MarkAborted() => Aborted = true;

            protected override bool ReceiveData(byte[] data, int dataLength)
            {
                if (data == null || dataLength <= 0) return true;

                int needed = _decoder.GetCharCount(data, 0, dataLength, false);
                if (needed > _chars.Length) _chars = new char[needed];
                int produced = _decoder.GetChars(data, 0, dataLength, _chars, 0, false);
                _pending.Append(_chars, 0, produced);

                while (true)
                {
                    int nl = -1;
                    for (int i = 0; i < _pending.Length; i++)
                        if (_pending[i] == '\n') { nl = i; break; }
                    if (nl < 0) break;

                    string line = _pending.ToString(0, nl);
                    _pending.Remove(0, nl + 1);
                    _onLine?.Invoke(line);
                }
                return true;
            }

            /// <summary>A last line without a trailing newline is still a line.</summary>
            public void FlushTail()
            {
                if (_pending.Length == 0) return;
                string line = _pending.ToString();
                _pending.Length = 0;
                _onLine?.Invoke(line);
            }
        }

        private static IEnumerator JsonRequest(
            string method,
            string url,
            string json,
            string bearer,
            Action<string> ok,
            Action<string> fail)
        {
            using var req = new UnityWebRequest(url, method);
            req.downloadHandler = new DownloadHandlerBuffer();

            if (json != null)
            {
                byte[] bytes = Encoding.UTF8.GetBytes(json);
                req.uploadHandler = new UploadHandlerRaw(bytes);
                req.SetRequestHeader("Content-Type", "application/json");
            }

            if (!string.IsNullOrWhiteSpace(bearer))
                req.SetRequestHeader("Authorization", "Bearer " + bearer.Trim());

            req.timeout = 120;
            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
            {
                string body = req.downloadHandler?.text;
                string detail = string.IsNullOrWhiteSpace(body) ? req.error : body;
                fail?.Invoke($"{method} {url} fejlede ({req.responseCode}): {detail}");
                yield break;
            }

            ok?.Invoke(req.downloadHandler?.text ?? "");
        }

        private static string Normalize(string baseUrl)
        {
            string value = (baseUrl ?? "").Trim();
            while (value.EndsWith("/")) value = value.Substring(0, value.Length - 1);
            return value;
        }
    }
}

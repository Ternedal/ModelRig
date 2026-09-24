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
        private UnityWebRequest _activeChatRequest;
        private bool _chatCancelRequested;

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

        [Serializable] private sealed class ChatStreamEnvelope
        {
            public ChatMessage message;
            public bool done;
            public string error;
        }

        private sealed class ChatStreamDownloadHandler : DownloadHandlerScript
        {
            private readonly Decoder _decoder = Encoding.UTF8.GetDecoder();
            private readonly StringBuilder _pending = new();
            private readonly Action<string> _delta;

            public bool SawDone { get; private set; }
            public bool SawContent { get; private set; }
            public string StreamError { get; private set; }

            public ChatStreamDownloadHandler(Action<string> delta)
            {
                _delta = delta;
            }

            protected override bool ReceiveData(byte[] data, int dataLength)
            {
                if (data == null || dataLength <= 0) return true;

                try
                {
                    int charCount = _decoder.GetCharCount(data, 0, dataLength, false);
                    if (charCount > 0)
                    {
                        var chars = new char[charCount];
                        int written = _decoder.GetChars(data, 0, dataLength, chars, 0, false);
                        _pending.Append(chars, 0, written);
                    }

                    DrainLines(false);
                    return string.IsNullOrWhiteSpace(StreamError);
                }
                catch (Exception ex)
                {
                    StreamError = "Chat-streamen kunne ikke afkodes: " + ex.Message;
                    return false;
                }
            }

            protected override void CompleteContent()
            {
                try
                {
                    var flush = new char[4];
                    int written = _decoder.GetChars(Array.Empty<byte>(), 0, 0, flush, 0, true);
                    if (written > 0) _pending.Append(flush, 0, written);
                    DrainLines(true);
                }
                catch (Exception ex)
                {
                    StreamError = "Chat-streamen sluttede med ugyldig UTF-8: " + ex.Message;
                }
            }

            private void DrainLines(bool final)
            {
                while (true)
                {
                    string current = _pending.ToString();
                    int newline = current.IndexOf('\n');
                    if (newline < 0) break;

                    string line = current.Substring(0, newline).TrimEnd('\r');
                    _pending.Remove(0, newline + 1);
                    ParseLine(line);
                    if (!string.IsNullOrWhiteSpace(StreamError)) return;
                }

                if (final && _pending.Length > 0)
                {
                    string line = _pending.ToString().TrimEnd('\r');
                    _pending.Clear();
                    ParseLine(line);
                }
            }

            private void ParseLine(string line)
            {
                if (string.IsNullOrWhiteSpace(line) || SawDone || !string.IsNullOrWhiteSpace(StreamError))
                    return;

                try
                {
                    var envelope = JsonUtility.FromJson<ChatStreamEnvelope>(line);
                    if (envelope == null)
                    {
                        StreamError = "Chat-streamen indeholdt en tom NDJSON-hændelse.";
                        return;
                    }

                    if (!string.IsNullOrWhiteSpace(envelope.error))
                    {
                        StreamError = envelope.error.Trim();
                        return;
                    }

                    string text = envelope.message?.content ?? "";
                    if (!string.IsNullOrEmpty(text))
                    {
                        SawContent = true;
                        _delta?.Invoke(text);
                    }

                    if (envelope.done) SawDone = true;
                }
                catch (Exception ex)
                {
                    StreamError = "Chat-streamen indeholdt ugyldig NDJSON: " + ex.Message;
                }
            }
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

        public IEnumerator ChatStream(
            string baseUrl,
            string token,
            string model,
            IReadOnlyList<ChatMessage> history,
            Action<string> delta,
            Action done,
            Action<string> fail)
        {
            if (_activeChatRequest != null)
            {
                fail?.Invoke("Der kører allerede et Kaliv-svar.");
                yield break;
            }

            var messages = new ChatMessage[history.Count];
            for (int i = 0; i < history.Count; i++) messages[i] = history[i];

            var payload = new ChatRequest
            {
                model = model,
                messages = messages,
                stream = true
            };

            var handler = new ChatStreamDownloadHandler(delta);
            using var req = new UnityWebRequest(Normalize(baseUrl) + "/api/v1/chat", "POST");
            byte[] bytes = Encoding.UTF8.GetBytes(JsonUtility.ToJson(payload));
            req.uploadHandler = new UploadHandlerRaw(bytes);
            req.downloadHandler = handler;
            req.SetRequestHeader("Content-Type", "application/json");
            if (!string.IsNullOrWhiteSpace(token))
                req.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            req.timeout = 120;

            _chatCancelRequested = false;
            _activeChatRequest = req;
            yield return req.SendWebRequest();

            bool cancelled = _chatCancelRequested;
            if (ReferenceEquals(_activeChatRequest, req)) _activeChatRequest = null;
            _chatCancelRequested = false;

            if (cancelled)
            {
                fail?.Invoke("Chat stoppet.");
                yield break;
            }

            if (!string.IsNullOrWhiteSpace(handler.StreamError))
            {
                fail?.Invoke("Chat-stream fejlede: " + handler.StreamError);
                yield break;
            }

            if (req.result != UnityWebRequest.Result.Success)
            {
                string body = req.downloadHandler?.text;
                string detail = string.IsNullOrWhiteSpace(body) ? req.error : body;
                fail?.Invoke($"POST {Normalize(baseUrl)}/api/v1/chat fejlede ({req.responseCode}): {detail}");
                yield break;
            }

            if (!handler.SawDone)
            {
                fail?.Invoke(handler.SawContent
                    ? "Chat-streamen blev afbrudt undervejs — svaret er ikke komplet."
                    : "Chat-streamen lukkede før et svar begyndte.");
                yield break;
            }

            done?.Invoke();
        }

        public bool CancelChat()
        {
            if (_activeChatRequest == null) return false;
            _chatCancelRequested = true;
            _activeChatRequest.Abort();
            return true;
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

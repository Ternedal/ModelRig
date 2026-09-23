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

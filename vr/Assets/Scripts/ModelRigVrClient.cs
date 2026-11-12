using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

namespace Kaliv.VR
{
    /// <summary>
    /// ModelRig backend client for Kaliv VR. Speaks the exact public contracts the Android
    /// and Desktop clients use — same endpoints, same payloads, same stream rules — so a
    /// turn means the same thing on every surface.
    ///
    /// Every streaming endpoint goes through one transport (<see cref="NdjsonPost"/>) and
    /// every line's meaning comes from KalivStreamContract / KalivToolStream. The transport
    /// splits bytes into lines; it never decides what a line means.
    /// </summary>
    public sealed class ModelRigVrClient : MonoBehaviour
    {
        [Serializable] public sealed class PairingResponse
        {
            public string token;
            public string device_id;
        }

        // ---- pairing & models ---------------------------------------------------------------

        public IEnumerator ClaimPairing(string baseUrl, string code,
                                        Action<PairingResponse> ok, Action<string> fail)
        {
            string body = KalivJson.Serialize(new Dictionary<string, object>
            {
                ["device_name"] = "kaliv-vr",
                ["code"] = (code ?? "").Trim(),
            });
            yield return JsonRequest("POST", Normalize(baseUrl) + "/api/v1/pair/claim", body, null,
                text =>
                {
                    var o = KalivJson.TryParseObject(text);
                    string token = KalivJson.Str(o, "token");
                    if (string.IsNullOrWhiteSpace(token))
                    {
                        fail?.Invoke("Parringen svarede uden et device-token.");
                        return;
                    }
                    ok?.Invoke(new PairingResponse { token = token, device_id = KalivJson.Str(o, "device_id") });
                },
                (status, msg) => fail?.Invoke(msg));
        }

        public IEnumerator ListModels(string baseUrl, string token, Action<List<string>> ok, Action<string> fail)
        {
            yield return JsonRequest("GET", Normalize(baseUrl) + "/api/v1/models", null, token,
                text =>
                {
                    var o = KalivJson.TryParseObject(text);
                    var rows = KalivJson.Arr(o, "models") ?? KalivJson.Arr(o, "data") ?? new List<object>();
                    var names = new List<string>();
                    foreach (var r in rows)
                    {
                        var row = r as Dictionary<string, object>;
                        string name = KalivJson.Str(row, "name");
                        if (string.IsNullOrWhiteSpace(name)) name = KalivJson.Str(row, "model");
                        if (!string.IsNullOrWhiteSpace(name) && !names.Contains(name)) names.Add(name);
                    }
                    ok?.Invoke(names);
                },
                (status, msg) => fail?.Invoke(msg));
        }

        // ---- chat ---------------------------------------------------------------------------

        /// <summary>
        /// Streaming plain chat: POST /api/v1/chat with stream=true. Deltas arrive word by word.
        /// </summary>
        public IEnumerator ChatStream(string baseUrl, string token, string model,
                                      List<(string role, string content)> history,
                                      Action<string> onDelta, Action<string> onPhase,
                                      Action onDone, Action onStopped, Action<string> fail,
                                      Action<Action> registerCancel = null)
        {
            var messages = new List<object>();
            foreach (var (role, content) in history)
                messages.Add(new Dictionary<string, object> { ["role"] = role, ["content"] = content });
            string body = KalivJson.Serialize(new Dictionary<string, object>
            {
                ["model"] = model,
                ["messages"] = messages,
                ["stream"] = true,
            });

            yield return ContractStream(Normalize(baseUrl) + "/api/v1/chat", token, body, "chat",
                null, onDelta, onPhase, onDone, onStopped, fail, registerCancel);
        }

        /// <summary>
        /// Document-grounded chat: POST /api/v1/rag/chat. The sources header arrives before
        /// any content and is recognised by shape. Like Android, the request carries only the
        /// query — the rig's RAG path is single-turn by design.
        /// </summary>
        public IEnumerator RagChatStream(string baseUrl, string token, string query, string model,
                                         string sourceFilter,
                                         Action<IReadOnlyList<string>> onSources,
                                         Action<string> onDelta, Action<string> onPhase,
                                         Action onDone, Action onStopped, Action<string> fail,
                                         Action<Action> registerCancel = null)
        {
            var payload = new Dictionary<string, object> { ["query"] = query, ["top_k"] = 4L };
            if (!string.IsNullOrWhiteSpace(model)) payload["model"] = model;
            if (!string.IsNullOrWhiteSpace(sourceFilter)) payload["source"] = sourceFilter;

            yield return ContractStream(Normalize(baseUrl) + "/api/v1/rag/chat", token,
                KalivJson.Serialize(payload), "rag chat",
                onSources, onDelta, onPhase, onDone, onStopped, fail, registerCancel);
        }

        /// <summary>
        /// One shared reader for /chat and /rag/chat: the contract's events, the terminal
        /// rule, and the stop-versus-failure distinction, in one place.
        /// </summary>
        private IEnumerator ContractStream(string url, string token, string body, string label,
                                           Action<IReadOnlyList<string>> onSources,
                                           Action<string> onDelta, Action<string> onPhase,
                                           Action onDone, Action onStopped, Action<string> fail,
                                           Action<Action> registerCancel)
        {
            bool sawTerminal = false, sawContent = false;
            string inBandFailure = null;

            void OnLine(string line)
            {
                if (inBandFailure != null) return;
                var ev = KalivStreamContract.Parse(line);
                switch (ev.Kind)
                {
                    case KalivStreamEventKind.Sources: onSources?.Invoke(ev.Names); break;
                    case KalivStreamEventKind.Phase: onPhase?.Invoke(ev.Info); break;
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
                }
            }

            yield return NdjsonPost(url, token, body, OnLine,
                onStopped: onStopped,
                onHttpFail: (status, msg) => fail?.Invoke(msg),
                onComplete: () =>
                {
                    if (inBandFailure != null) { fail?.Invoke(label + ": " + inBandFailure); return; }
                    string terminal = KalivStreamContract.TerminalFailure(sawTerminal, sawContent);
                    if (terminal != null) { fail?.Invoke(terminal); return; }
                    onDone?.Invoke();
                },
                registerCancel: registerCancel);
        }

        // ---- tools --------------------------------------------------------------------------

        /// <summary>
        /// A turn in which the model may propose a tool: POST /api/v1/tools/chat/stream.
        /// The stream carries phases and ONE `result` line. The result is either an answer or
        /// a proposal that has executed nothing and waits for a human.
        ///
        /// History goes in its own field and the current message separately — Android found
        /// that without history, turning Tools on made Kaliv amnesiac ("write down what we
        /// just discussed" had nothing to write).
        /// </summary>
        public IEnumerator ToolsChatStream(string baseUrl, string token, string message, string model,
                                           string conversationId,
                                           List<(string role, string content)> history, bool rag,
                                           Action<string> onPhase, Action<KalivToolTurn> onResult,
                                           Action onStopped, Action<string> fail,
                                           Action<Action> registerCancel = null)
        {
            var payload = new Dictionary<string, object> { ["message"] = message };
            if (history != null && history.Count > 0)
            {
                var arr = new List<object>();
                foreach (var (role, content) in history)
                    arr.Add(new Dictionary<string, object> { ["role"] = role, ["content"] = content });
                payload["history"] = arr;
            }
            if (rag) payload["rag"] = true;
            if (!string.IsNullOrWhiteSpace(model)) payload["model"] = model;
            if (!string.IsNullOrWhiteSpace(conversationId)) payload["conversation_id"] = conversationId;

            KalivToolTurn turn = null;
            string failure = null;

            void OnLine(string line)
            {
                if (turn != null || failure != null) return;
                switch (KalivToolStream.Parse(line, out string info, out KalivToolTurn result))
                {
                    case KalivToolStream.LineKind.Phase: onPhase?.Invoke(info); break;
                    case KalivToolStream.LineKind.Result: turn = result; break;
                    case KalivToolStream.LineKind.Failure: failure = info; break;
                }
            }

            yield return NdjsonPost(Normalize(baseUrl) + "/api/v1/tools/chat/stream", token,
                KalivJson.Serialize(payload), OnLine,
                onStopped: onStopped,
                onHttpFail: (status, msg) => fail?.Invoke(status == 403
                    ? "Værktøjslaget er slået fra på riggen."
                    : msg),
                onComplete: () =>
                {
                    if (failure != null) { fail?.Invoke("værktøj: " + failure); return; }
                    if (turn == null) { fail?.Invoke(KalivToolStream.Truncated); return; }
                    onResult?.Invoke(turn);
                },
                registerCancel: registerCancel);
        }

        /// <summary>
        /// Approve or deny a parked proposal. The rig executes exactly the arguments it showed
        /// on the card. 409 = already used, 410 = expired; both are refusals, and a timeout is
        /// never an acceptance.
        /// </summary>
        public IEnumerator ToolsConfirm(string baseUrl, string token, string confirmationId, bool approve,
                                        Action<KalivToolTurn> ok, Action<string> fail)
        {
            string body = KalivJson.Serialize(new Dictionary<string, object>
            {
                ["confirmation_id"] = confirmationId,
                ["decision"] = approve ? "approve" : "deny",
            });
            // An approved write can run the model again afterwards; give it room.
            yield return JsonRequest("POST", Normalize(baseUrl) + "/api/v1/tools/confirm", body, token,
                text =>
                {
                    var o = KalivJson.TryParseObject(text);
                    if (o == null) { fail?.Invoke("Riggen svarede ikke med en gyldig bekræftelse."); return; }
                    ok?.Invoke(KalivToolTurn.Parse(o));
                },
                (status, msg) => fail?.Invoke(
                    status == 410 ? "Forslaget er udløbet — intet blev udført. Bed Kaliv igen." :
                    status == 409 ? "Forslaget er allerede brugt — intet blev udført igen." :
                    msg),
                timeoutSeconds: 300);
        }

        // ---- voice --------------------------------------------------------------------------

        /// <summary>Whether ASR/TTS are installed on the rig, so the UI can say so before recording.</summary>
        public IEnumerator VoiceStatus(string baseUrl, string token,
                                       Action<Dictionary<string, object>> ok, Action<string> fail)
        {
            yield return JsonRequest("GET", Normalize(baseUrl) + "/api/v1/voice/status", null, token,
                text => ok?.Invoke(KalivJson.TryParseObject(text) ?? new Dictionary<string, object>()),
                (status, msg) => fail?.Invoke(msg));
        }

        /// <summary>
        /// A spoken turn: POST /api/v1/voice/converse/stream with a 16 kHz mono WAV. The rig
        /// runs ASR → LLM → TTS and streams the transcript, then one chunk per spoken
        /// sentence with its audio, so Kaliv starts talking while the rest still generates.
        ///
        /// History: last 12 turns, each capped at 4000 characters — Android's bound, sent only
        /// because VR has no cloud path (voice cloud consent covers the turn, not the context).
        /// </summary>
        public IEnumerator VoiceConverseStream(string baseUrl, string token, byte[] wav, string model,
                                               List<(string role, string content)> history,
                                               Action<string> onTranscript,
                                               Action<KalivStreamEvent> onChunk,
                                               Action<string> onPhase,
                                               Action<string, string> onDone,
                                               Action onStopped, Action<string> fail,
                                               Action<Action> registerCancel = null)
        {
            var payload = new Dictionary<string, object>
            {
                ["audio_base64"] = Convert.ToBase64String(wav),
                ["language"] = "da",
            };
            if (history != null && history.Count > 0)
            {
                var arr = new List<object>();
                int start = Math.Max(0, history.Count - 12);
                for (int i = start; i < history.Count; i++)
                {
                    var (role, content) = history[i];
                    if ((role != "user" && role != "assistant") || string.IsNullOrWhiteSpace(content)) continue;
                    arr.Add(new Dictionary<string, object>
                    {
                        ["role"] = role,
                        ["content"] = content.Length > 4000 ? content.Substring(0, 4000) : content,
                    });
                }
                payload["history"] = arr;
            }
            if (!string.IsNullOrWhiteSpace(model)) payload["model"] = model;

            bool finished = false;
            string failure = null;
            string reply = "", replyModel = null;

            void OnLine(string line)
            {
                if (finished || failure != null) return;
                var ev = KalivStreamContract.Parse(line);
                switch (ev.Kind)
                {
                    case KalivStreamEventKind.Transcript: onTranscript?.Invoke(ev.Text); break;
                    case KalivStreamEventKind.Chunk: onChunk?.Invoke(ev); break;
                    case KalivStreamEventKind.Phase: onPhase?.Invoke(ev.Info); break;
                    case KalivStreamEventKind.Done:
                        finished = true;
                        reply = ev.Reply;
                        replyModel = ev.Model;
                        break;
                    case KalivStreamEventKind.Failure:
                        failure = ev.Status == 501 || ev.Status == 503
                            ? "Stemme er ikke installeret eller klar på riggen (" + ev.Info + ")."
                            : ev.Info;
                        break;
                }
            }

            yield return NdjsonPost(Normalize(baseUrl) + "/api/v1/voice/converse/stream", token,
                KalivJson.Serialize(payload), OnLine,
                onStopped: onStopped,
                onHttpFail: (status, msg) => fail?.Invoke(msg),
                onComplete: () =>
                {
                    if (failure != null) { fail?.Invoke("stemme: " + failure); return; }
                    // HTTP 200 with EOF but no terminal event is truncated — Android's rule.
                    if (!finished)
                    {
                        fail?.Invoke("stemmesvaret blev afbrudt — forbindelsen lukkede før riggen var færdig; prøv igen");
                        return;
                    }
                    onDone?.Invoke(reply, replyModel);
                },
                registerCancel: registerCancel,
                bodyIsLarge: true);
        }

        /// <summary>
        /// Tell the rig's body which sentence is actually playing, so the mouth follows the
        /// audio the user hears rather than the moment the rig finished synthesizing it.
        /// POST /api/v1/body/speech/{utterance}/started|ended — Android's BodyPlaybackReporter.
        ///
        /// Fire-and-forget. A rig without an active body answers 404; the caller then stops
        /// reporting for the session instead of paying two calls per sentence for nothing.
        /// </summary>
        public IEnumerator ReportBodySpeech(string baseUrl, string token, string utteranceId, string ev,
                                            Action<bool> onResult)
        {
            if (string.IsNullOrWhiteSpace(utteranceId)) yield break;
            string url = Normalize(baseUrl) + "/api/v1/body/speech/" +
                         UnityWebRequest.EscapeURL(utteranceId) + "/" + ev;
            using var req = new UnityWebRequest(url, "POST");
            req.uploadHandler = new UploadHandlerRaw(new byte[0]);
            req.downloadHandler = new DownloadHandlerBuffer();
            if (!string.IsNullOrWhiteSpace(token)) req.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            req.timeout = 3;
            yield return req.SendWebRequest();
            onResult?.Invoke(req.responseCode != 404);
        }

        // ---- media gallery ------------------------------------------------------------------

        public IEnumerator MediaPage(string baseUrl, string token, string cursor,
                                     Action<KalivMediaPage> ok, Action<int, string> fail)
        {
            string url = Normalize(baseUrl) + "/api/v1/media?limit=" + KalivMediaGallery.DefaultLimit;
            if (cursor != null)
            {
                if (!KalivMediaGallery.IsValidCursor(cursor)) { fail?.Invoke(0, "Ugyldig cursor"); yield break; }
                url += "&cursor=" + UnityWebRequest.EscapeURL(cursor);
            }
            yield return JsonRequest("GET", url, null, token,
                text =>
                {
                    KalivMediaPage page;
                    try { page = KalivMediaGallery.ParsePage(text); }
                    catch (FormatException e) { fail?.Invoke(0, e.Message); return; }
                    ok?.Invoke(page);
                },
                (status, msg) => fail?.Invoke(status, msg));
        }

        /// <summary>Thumbnail as a texture. Auth goes in the header, never in the URL.</summary>
        public IEnumerator MediaThumbnail(string baseUrl, string token, KalivMediaItem item,
                                          Action<Texture2D> ok, Action<string> fail)
        {
            if (item?.ThumbnailPath == null) yield break;
            // Bytes + ImageConversion rather than UnityWebRequestTexture: that one lives in a
            // module this project does not include, and adding it would mean changing the
            // pinned package set for one thumbnail.
            using var req = new UnityWebRequest(Normalize(baseUrl) + item.ThumbnailPath, "GET");
            req.downloadHandler = new DownloadHandlerBuffer();
            if (!string.IsNullOrWhiteSpace(token)) req.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            req.timeout = 30;
            yield return req.SendWebRequest();
            if (req.result != UnityWebRequest.Result.Success) { fail?.Invoke(req.error); yield break; }
            byte[] bytes = req.downloadHandler.data;
            // Bounded like Android's thumbnail reader: a "thumbnail" is not allowed to be huge.
            if (bytes == null || bytes.Length == 0 || bytes.Length > 4 * 1024 * 1024)
            {
                fail?.Invoke("ugyldig thumbnail");
                yield break;
            }
            var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
            if (!tex.LoadImage(bytes, true)) { Destroy(tex); fail?.Invoke("thumbnail kunne ikke afkodes"); yield break; }
            ok?.Invoke(tex);
        }

        /// <summary>
        /// Fetch a video to local cache so the engine can play it.
        ///
        /// SkyPlayer-Engine opens media with MediaItem.fromUri — it has no way to attach the
        /// Bearer header the rig requires. Putting the token in the URL is not an option (it
        /// lands in logs and proxies). So the client downloads with the header and hands the
        /// engine a file:// path. The file is reused when the size matches, so reopening the
        /// same item is instant.
        /// </summary>
        public IEnumerator MediaDownload(string baseUrl, string token, KalivMediaItem item,
                                         Action<float> onProgress, Action<string> ok, Action<string> fail,
                                         Action<Action> registerCancel = null)
        {
            string dir = Path.Combine(Application.temporaryCachePath, "kaliv-media");
            Directory.CreateDirectory(dir);
            string ext = item.MimeType == "video/mp4" ? ".mp4" : "";
            string path = Path.Combine(dir, item.Id + ext);

            if (File.Exists(path) && new FileInfo(path).Length == item.SizeBytes)
            {
                ok?.Invoke(path);
                yield break;
            }

            string partial = path + ".part";
            using var req = new UnityWebRequest(Normalize(baseUrl) + item.MediaPath, "GET");
            req.downloadHandler = new DownloadHandlerFile(partial) { removeFileOnAbort = true };
            if (!string.IsNullOrWhiteSpace(token)) req.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            req.timeout = 0;
            bool aborted = false;
            var live = req;
            registerCancel?.Invoke(() => { aborted = true; try { live.Abort(); } catch (Exception) { } });

            var op = req.SendWebRequest();
            while (!op.isDone)
            {
                onProgress?.Invoke(req.downloadProgress < 0 ? 0f : req.downloadProgress);
                yield return null;
            }

            if (aborted) { fail?.Invoke("Hentningen blev stoppet."); yield break; }
            if (req.result != UnityWebRequest.Result.Success)
            {
                fail?.Invoke($"Hentning fejlede ({req.responseCode}): {req.error}");
                yield break;
            }
            if (File.Exists(path)) File.Delete(path);
            File.Move(partial, path);
            ok?.Invoke(path);
        }

        // ---- transport ----------------------------------------------------------------------

        /// <summary>
        /// POST a JSON body and feed the NDJSON response to <paramref name="onLine"/> as it
        /// arrives. Exactly one of onStopped / onHttpFail / onComplete runs.
        ///
        /// No timeout: UnityWebRequest.timeout measures the whole transfer, not silence, so any
        /// value cuts off a long local generation that is working fine.
        /// </summary>
        private IEnumerator NdjsonPost(string url, string token, string jsonBody,
                                       Action<string> onLine, Action onStopped,
                                       Action<long, string> onHttpFail, Action onComplete,
                                       Action<Action> registerCancel, bool bodyIsLarge = false)
        {
            using var req = new UnityWebRequest(url, "POST");
            var handler = new NdjsonDownloadHandler(onLine);
            req.downloadHandler = handler;
            req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(jsonBody));
            req.SetRequestHeader("Content-Type", "application/json");
            if (!string.IsNullOrWhiteSpace(token))
                req.SetRequestHeader("Authorization", "Bearer " + token.Trim());
            req.timeout = 0;

            var liveReq = req;
            registerCancel?.Invoke(() =>
            {
                // Stop can land in the same frame the stream finishes, after `using` has
                // disposed the request. Aborting a disposed request throws, and pressing Stop
                // on an answer that just completed is not an error.
                try
                {
                    handler.MarkAborted();
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
                // The error body was parsed as stream lines and probably ignored; the handler
                // keeps a bounded raw copy precisely so the reason is not lost here.
                string raw = handler.RawHead;
                string reason = ErrorReason(raw);
                string detail = string.IsNullOrWhiteSpace(reason) ? req.error : reason;
                onHttpFail?.Invoke(req.responseCode, $"POST {ShortPath(url)} fejlede ({req.responseCode}): {detail}");
                yield break;
            }

            handler.FlushTail();
            onComplete?.Invoke();
        }

        /// <summary>
        /// Splits the incoming byte stream into NDJSON lines on Unity's main thread.
        /// A chunk can split a line anywhere, including mid-UTF8, so bytes are decoded with a
        /// stateful decoder and the partial tail is carried to the next chunk.
        /// </summary>
        private sealed class NdjsonDownloadHandler : DownloadHandlerScript
        {
            private const int RawHeadLimit = 2048;
            private readonly Action<string> _onLine;
            private readonly StringBuilder _pending = new StringBuilder();
            private readonly StringBuilder _rawHead = new StringBuilder();
            private readonly Decoder _decoder = Encoding.UTF8.GetDecoder();
            private char[] _chars = new char[4096];

            public bool Aborted { get; private set; }

            /// <summary>The first 2 KB of the body, for error reporting when it was not NDJSON.</summary>
            public string RawHead => _rawHead.ToString();

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
                if (_rawHead.Length < RawHeadLimit)
                    _rawHead.Append(_chars, 0, Math.Min(produced, RawHeadLimit - _rawHead.Length));

                int lineStart = 0;
                for (int i = 0; i < _pending.Length; i++)
                {
                    if (_pending[i] != '\n') continue;
                    string line = _pending.ToString(lineStart, i - lineStart);
                    lineStart = i + 1;
                    _onLine?.Invoke(line);
                }
                if (lineStart > 0) _pending.Remove(0, lineStart);
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

        private static IEnumerator JsonRequest(string method, string url, string json, string bearer,
                                               Action<string> ok, Action<int, string> fail,
                                               int timeoutSeconds = 120)
        {
            using var req = new UnityWebRequest(url, method);
            req.downloadHandler = new DownloadHandlerBuffer();
            if (json != null)
            {
                req.uploadHandler = new UploadHandlerRaw(Encoding.UTF8.GetBytes(json));
                req.SetRequestHeader("Content-Type", "application/json");
            }
            if (!string.IsNullOrWhiteSpace(bearer))
                req.SetRequestHeader("Authorization", "Bearer " + bearer.Trim());

            req.timeout = timeoutSeconds;
            yield return req.SendWebRequest();

            if (req.result != UnityWebRequest.Result.Success)
            {
                string reason = ErrorReason(req.downloadHandler?.text);
                string detail = string.IsNullOrWhiteSpace(reason) ? req.error : reason;
                fail?.Invoke((int)req.responseCode, $"{method} {ShortPath(url)} fejlede ({req.responseCode}): {detail}");
                yield break;
            }

            ok?.Invoke(req.downloadHandler?.text ?? "");
        }

        /// <summary>
        /// The reason inside an error body: FastAPI's {"detail": …}, the backend's {"error": …},
        /// or the raw text if neither. Shown to the user, so never longer than a line or two.
        /// </summary>
        private static string ErrorReason(string body)
        {
            if (string.IsNullOrWhiteSpace(body)) return null;
            string firstLine = body.Split('\n')[0];
            var o = KalivJson.TryParseObject(firstLine) ?? KalivJson.TryParseObject(body);
            string reason = KalivJson.Str(o, "detail");
            if (reason.Length == 0) reason = KalivJson.Str(o, "error");
            if (reason.Length == 0) reason = body.Trim();
            return reason.Length > 240 ? reason.Substring(0, 240) + " …" : reason;
        }

        /// <summary>The path only — the rig's address stays out of the status line.</summary>
        private static string ShortPath(string url)
        {
            int scheme = url.IndexOf("://", StringComparison.Ordinal);
            int slash = scheme < 0 ? -1 : url.IndexOf('/', scheme + 3);
            string path = slash < 0 ? url : url.Substring(slash);
            int q = path.IndexOf('?');
            return q < 0 ? path : path.Substring(0, q);
        }

        private static string Normalize(string baseUrl)
        {
            string value = (baseUrl ?? "").Trim();
            while (value.EndsWith("/")) value = value.Substring(0, value.Length - 1);
            return value;
        }
    }
}

using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;
using Kaliv.VR.Rendering;

namespace Kaliv.VR
{
    /// <summary>
    /// Product-level state for the VR client. Backend semantics stay here; reusable XR/media
    /// mechanics stay in SkyPlayer-Engine; what is on screen is the panel's business.
    ///
    /// Every way a turn can start — typed, spoken, retried — goes through one router
    /// (KalivTurnPlan) and ends through one exit (FinishTurn), so the composer, the stop
    /// button, the history and the body can never be left half-finished.
    /// </summary>
    public sealed partial class KalivVrApp : MonoBehaviour
    {
        private const string BaseUrlKey = "kaliv.vr.rig_url";
        private const string TokenKey = "kaliv.vr.rig_token";
        private const string ModelKey = "kaliv.vr.model";
        private const string RagKey = "kaliv.vr.mode.rag";
        private const string ToolsKey = "kaliv.vr.mode.tools";
        private const string RagSourceKey = "kaliv.vr.mode.rag_source";
        private const string DeviceIdKey = "kaliv.vr.device_id";
        private const string ConversationFile = "kaliv-vr-conversation.json";

        private ModelRigVrClient _client;
        private KalivVrPanel _panel;
        private KalivVrRenderEngine _renderEngine;
        private KalivVoice _voice;
        private readonly KalivConversation _conversation = new KalivConversation();

        // The one in-flight turn.
        private bool _busy;
        private Action _cancel;
        private KalivMessage _live;              // the assistant message being written
        private KalivToolTurn _pendingConfirmation;
        private bool _bodySpeechReporting = true;
        private KalivCapabilities _caps = KalivCapabilities.Unknown;

        // Media
        private string _mediaCursor;
        private readonly List<KalivMediaItem> _mediaItems = new List<KalivMediaItem>();
        private int _mediaFormatIndex;
        private Action _cancelDownload;
        private bool _mediaOpen;

        public string BaseUrl { get; private set; }
        public string Token { get; private set; }
        public string Model { get; private set; }
        /// <summary>This headset's id on the rig, from pairing. Null for pairings made before it was kept.</summary>
        public string DeviceId { get; private set; }
        public bool RagMode { get; private set; }
        public bool ToolsMode { get; private set; }
        /// <summary>Narrow VIDEN to one source; null searches all. Android's ragSourceFilter.</summary>
        public string RagSource { get; private set; }

        public bool Paired => !string.IsNullOrWhiteSpace(BaseUrl) && !string.IsNullOrWhiteSpace(Token);

        private string ConversationPath => Path.Combine(Application.persistentDataPath, ConversationFile);

        // =====================================================================================
        // Startup & pairing
        // =====================================================================================

        private Camera _camera;

        public void Initialize(Camera camera)
        {
            _camera = camera;
            _client = gameObject.AddComponent<ModelRigVrClient>();
            BaseUrl = PlayerPrefs.GetString(BaseUrlKey, "http://192.168.1.10:8080");
            Token = PlayerPrefs.GetString(TokenKey, "");
            Model = PlayerPrefs.GetString(ModelKey, "");
            DeviceId = PlayerPrefs.GetString(DeviceIdKey, "");
            if (string.IsNullOrWhiteSpace(DeviceId)) DeviceId = null;
            RagMode = PlayerPrefs.GetInt(RagKey, 0) == 1;
            ToolsMode = PlayerPrefs.GetInt(ToolsKey, 0) == 1;
            RagSource = PlayerPrefs.GetString(RagSourceKey, "");
            if (string.IsNullOrWhiteSpace(RagSource)) RagSource = null;

            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0f, 0f, 0f, 0f);

            _renderEngine = gameObject.AddComponent<KalivVrRenderEngine>();
            _renderEngine.Initialize(camera);

            _panel = KalivVrPanel.Create(camera, this, _renderEngine.UiRoot);
            _renderEngine.AttachUi(_panel.gameObject);
            _renderEngine.StatusChanged += (status, error) => _panel.SetBodyStatus(status, error);
            _renderEngine.MediaEnded += OnMediaEnded;

            // The panel is a "screen" the avatar can be asked to look at, and a named object.
            _renderEngine.SetScreenTarget(_panel.PanelTransform);
            _renderEngine.RegisterObjectTarget("panel", _panel.PanelTransform);

            _voice = gameObject.AddComponent<KalivVoice>();
            _voice.Initialize(_renderEngine.BodyRoot);
            _voice.SpeechEvent += ReportBodySpeech;

            _panel.SetConnectionDefaults(BaseUrl, "");
            _panel.SetModes(RagMode, ToolsMode, RagSource);
            _panel.BindConversation(_conversation);
            _panel.SetPaired(Paired);
            _panel.SetBodyStatus("Renderer klar", false);

            // History survives a restart. A file that will not parse is ignored, never fatal.
            _conversation.Load(ConversationPath);
            UpdateRetry();

            if (Paired)
            {
                _renderEngine.Connect(BaseUrl, Token);
                RefreshModels();
            }
        }

        public void Pair(string baseUrl, string code)
        {
            if (string.IsNullOrWhiteSpace(baseUrl) || string.IsNullOrWhiteSpace(code))
            {
                _panel.SetStatus("Indtast rig-adresse og parringskode.", true);
                return;
            }

            _panel.SetBusy(true);
            _panel.SetStatus("Forbinder til din rig …", false);

            StartCoroutine(_client.ClaimPairing(baseUrl, code,
                response =>
                {
                    BaseUrl = baseUrl.Trim().TrimEnd('/');
                    Token = response.token.Trim();
                    DeviceId = string.IsNullOrWhiteSpace(response.device_id) ? null : response.device_id.Trim();
                    PlayerPrefs.SetString(BaseUrlKey, BaseUrl);
                    PlayerPrefs.SetString(TokenKey, Token);
                    PlayerPrefs.SetString(DeviceIdKey, DeviceId ?? "");
                    PlayerPrefs.Save();

                    _panel.SetBusy(false);
                    _panel.SetPaired(true);
                    _panel.SetStatus("Forbundet til din rig.", false);
                    _renderEngine.Connect(BaseUrl, Token);
                    RefreshModels();
                },
                error =>
                {
                    _panel.SetBusy(false);
                    _panel.SetStatus(Friendly(error), true);
                }));
        }

        /// <summary>Ask the rig what it can do, so buttons do not promise what it cannot.</summary>
        private void RefreshCapabilities()
        {
            if (!Paired) return;
            StartCoroutine(_client.Capabilities(BaseUrl, Token, caps => _caps = caps));
        }

        public void RefreshModels()
        {
            if (!Paired) return;
            RefreshCapabilities();
            _panel.SetStatus("Henter modeller …", false);
            StartCoroutine(_client.ListModels(BaseUrl, Token,
                models =>
                {
                    if (models.Count > 0 && (string.IsNullOrWhiteSpace(Model) || !models.Contains(Model)))
                    {
                        Model = models[0];
                        PlayerPrefs.SetString(ModelKey, Model);
                        PlayerPrefs.Save();
                    }
                    _panel.SetModels(models, Model);
                    _panel.SetStatus(models.Count == 0
                        ? "Riggen svarede, men rapporterede ingen modeller."
                        : $"Rig · {Model}", false);
                },
                error => _panel.SetStatus(Friendly(error), true)));
        }

        public void SelectModel(string model)
        {
            if (string.IsNullOrWhiteSpace(model)) return;
            Model = model.Trim();
            PlayerPrefs.SetString(ModelKey, Model);
            PlayerPrefs.Save();
            _panel.SetStatus($"Rig · {Model}", false);
        }

        // =====================================================================================
        // Modes
        // =====================================================================================

        public void ToggleRag()
        {
            RagMode = !RagMode;
            PlayerPrefs.SetInt(RagKey, RagMode ? 1 : 0);
            PlayerPrefs.Save();
            _panel.SetModes(RagMode, ToolsMode, RagSource);
        }

        public void ToggleTools()
        {
            ToolsMode = !ToolsMode;
            PlayerPrefs.SetInt(ToolsKey, ToolsMode ? 1 : 0);
            PlayerPrefs.Save();
            _panel.SetModes(RagMode, ToolsMode, RagSource);
        }

        // =====================================================================================
        // Text turns
        // =====================================================================================

        public void Send(string prompt)
        {
            prompt = (prompt ?? "").Trim();
            if (!CanStartTurn()) return;
            if (prompt.Length == 0) return;

            _conversation.Add(new KalivMessage("user", prompt));
            SaveConversation();
            RunTurn(prompt);
        }

        /// <summary>
        /// Resend the last user message. The failed answer is removed first, so the retry
        /// answers the same question instead of stacking a second copy of it.
        /// </summary>
        public void Retry()
        {
            if (!CanStartTurn()) return;
            if (!_conversation.TryGetRetry(out string prompt)) return;
            _conversation.PrepareRetry();
            RunTurn(prompt);
        }

        public void NewConversation()
        {
            if (_busy) StopGeneration();
            _voice.CancelRecording();
            _voice.StopSpeaking();
            // A parked proposal belongs to the old conversation. Closing the card without an
            // answer is a refusal by default: the rig expires it and nothing runs.
            _pendingConfirmation = null;
            _panel.HideConfirmation();
            _live = null;
            _conversation.Clear();
            SaveConversation();
            UpdateRetry();
            _panel.SetStatus($"Ny samtale · {Model}", false);
        }

        private bool CanStartTurn()
        {
            if (!Paired) { _panel.SetStatus("Kaliv VR er ikke parret med en rig endnu.", true); return false; }
            if (string.IsNullOrWhiteSpace(Model)) { _panel.SetStatus("Vælg en model først.", true); return false; }
            if (_busy || _pendingConfirmation != null) return false;   // one turn at a time
            if (_voice != null && _voice.IsRecording) return false;    // the mic is open: that IS the turn
            return true;
        }

        /// <summary>Route and run one typed turn for the user message already in the conversation.</summary>
        private void RunTurn(string prompt)
        {
            var plan = KalivTurnPlan.For(ToolsMode, RagMode);
            BeginTurn(KalivTurnStatus.ForPlan(plan));

            switch (plan.Route)
            {
                case KalivTurnRoute.Tools:
                    // The current message goes separately; history is everything before it.
                    StartCoroutine(_client.ToolsChatStream(BaseUrl, Token, prompt, Model,
                        _conversation.ConversationId, _conversation.History(excludeLast: true), plan.ToolsWithRag,
                        RagSource, OnPhase, OnToolResult, OnStopped, OnFailed, RegisterCancel));
                    break;

                case KalivTurnRoute.Rag:
                    StartCoroutine(_client.RagChatStream(BaseUrl, Token, prompt, Model, RagSource,
                        names => { _live.Sources.Clear(); _live.Sources.AddRange(names); _panel.MarkTranscriptDirty(); },
                        OnDelta, OnPhase, OnDone, OnStopped, OnFailed, RegisterCancel));
                    break;

                default:
                    StartCoroutine(_client.ChatStream(BaseUrl, Token, Model, _conversation.History(),
                        OnDelta, OnPhase, OnDone, OnStopped, OnFailed, RegisterCancel));
                    break;
            }
        }

        private void BeginTurn(string status)
        {
            _busy = true;
            _live = _conversation.Add(new KalivMessage("assistant", ""));
            _panel.SetLiveSuffix(" …");   // Arial has …; it has no block glyph
            _panel.SetComposerBusy(true);
            _panel.SetStopAvailable(true);
            _panel.SetRetryAvailable(false);
            _panel.SetStatus(status, false);
        }

        private void RegisterCancel(Action cancel) => _cancel = cancel;

        private void OnDelta(string delta)
        {
            if (_live == null) return;
            _live.Text += delta;
            _panel.MarkTranscriptDirty();
        }

        private void OnPhase(string phase)
        {
            string text = KalivTurnStatus.ForPhase(phase);
            if (text != null) _panel.SetStatus(text, false);
        }

        private void OnDone() => FinishTurn(TurnEnd.Completed, null);
        private void OnStopped() => FinishTurn(TurnEnd.Stopped, null);
        private void OnFailed(string error) => FinishTurn(TurnEnd.Failed, error);

        public void StopGeneration()
        {
            if (!_busy) return;
            _voice.StopSpeaking();
            _cancel?.Invoke();
        }

        private enum TurnEnd { Completed, Stopped, Failed }

        /// <summary>
        /// One exit for every way a turn can end.
        ///
        /// * Completed: the answer stays and becomes history.
        /// * Stopped: what arrived stays — the user read those words, and a follow-up that
        ///   silently dropped them would make the model look amnesiac about its own sentence.
        /// * Failed: an error bubble, shown but never sent as history (Android's Msg.error),
        ///   and PRØV IGEN appears.
        /// </summary>
        private void FinishTurn(TurnEnd end, string error)
        {
            if (!_busy) return;
            _busy = false;
            _cancel = null;
            _panel.SetLiveSuffix(null);
            _panel.SetStopAvailable(false);
            _panel.SetComposerBusy(false);

            var live = _live;
            _live = null;

            if (live != null)
            {
                live.Text = (live.Text ?? "").Trim();
                switch (end)
                {
                    case TurnEnd.Failed:
                        if (live.Text.Length == 0) { live.Text = Friendly(error); live.Error = true; }
                        else
                        {
                            // Partial content then failure: keep what arrived visibly, but as an
                            // error — a truncated answer must not be persisted as a finished one.
                            live.Text += "\n— " + Friendly(error);
                            live.Error = true;
                        }
                        break;
                    case TurnEnd.Stopped:
                        live.Stopped = true;
                        if (live.Text.Length == 0) { live.Text = "(stoppet før svaret begyndte)"; live.Error = true; }
                        break;
                    case TurnEnd.Completed:
                        if (live.Text.Length == 0) { live.Text = "(tomt svar fra modellen)"; live.Error = true; }
                        break;
                }
                _conversation.NotifyChanged();
            }

            _panel.SetStatus(end == TurnEnd.Failed ? Friendly(error)
                : end == TurnEnd.Stopped ? $"Stoppet · {Model}" : $"Rig · {Model}",
                end == TurnEnd.Failed);
            SaveConversation();
            UpdateRetry();
        }

        private void UpdateRetry() =>
            _panel.SetRetryAvailable(!_busy && _pendingConfirmation == null && _conversation.TryGetRetry(out _));

        private void SaveConversation()
        {
            try { _conversation.Save(ConversationPath); }
            catch (Exception e) { Debug.LogWarning("[KalivVR] kunne ikke gemme samtalen: " + e.Message); }
        }

        // =====================================================================================
        // Tools & confirmation
        // =====================================================================================

        private void OnToolResult(KalivToolTurn turn)
        {
            if (_live == null) return;
            _live.Tool = turn.ExecutedWrite ?? turn.Tool;
            if (turn.PersonName != null) _live.Person = turn.PersonName;
            _live.Sources.Clear();
            _live.Sources.AddRange(turn.Sources);

            if (turn.NeedsConfirmation)
            {
                // Nothing has run. Park the turn behind the card; the composer stays locked so
                // a new message cannot race the decision.
                _pendingConfirmation = turn;
                _live.Text = "Jeg vil gerne udføre en handling og venter på din bekræftelse.";
                _panel.MarkTranscriptDirty();
                _busy = false;
                _cancel = null;
                _panel.SetLiveSuffix(null);
                _panel.SetStopAvailable(false);
                _panel.SetStatus("Venter på din bekræftelse …", false);
                _panel.ShowConfirmation(turn);
                return;
            }

            _live.Text = turn.Answer ?? "";
            FinishTurn(TurnEnd.Completed, null);
        }

        /// <summary>
        /// Approve or deny the parked proposal. The rig may answer with ANOTHER proposal — an
        /// approved write can lead the model to propose the next one — which gets its own card.
        /// </summary>
        public void AnswerConfirmation(bool approve)
        {
            var turn = _pendingConfirmation;
            if (turn == null) return;
            _panel.SetConfirmationBusy(true);
            _panel.SetStatus(approve ? "Udfører …" : "Afviser …", false);

            StartCoroutine(_client.ToolsConfirm(BaseUrl, Token, turn.ConfirmationId, approve,
                result =>
                {
                    _pendingConfirmation = null;
                    _panel.HideConfirmation();
                    _busy = true;   // re-enter the turn so FinishTurn stays the single exit
                    if (result.NeedsConfirmation)
                    {
                        OnToolResult(result);   // a chained proposal gets its own card
                        return;
                    }
                    if (_live != null)
                    {
                        _live.Tool = result.ExecutedWrite ?? result.Tool ?? turn.Tool;
                        _live.Text = string.IsNullOrWhiteSpace(result.Answer)
                            ? (result.Status == KalivToolTurn.StatusDenied ? "Handlingen blev afvist." : "Udført.")
                            : result.Answer;
                    }
                    FinishTurn(TurnEnd.Completed, null);
                },
                error =>
                {
                    // 409/410 and network errors all mean the same thing to the user: nothing
                    // ran on their say-so. Close the card and say so.
                    _pendingConfirmation = null;
                    _panel.HideConfirmation();
                    _busy = true;
                    FinishTurn(TurnEnd.Failed, error);
                }));
        }

        // =====================================================================================
        // Voice
        // =====================================================================================

        /// <summary>Tap to talk; tap again to send. Talking over Kaliv stops her (barge-in).</summary>
        public void ToggleVoice()
        {
            if (_voice.IsRecording)
            {
                byte[] wav = _voice.StopRecording(out string reason);
                if (wav == null) { _panel.SetStatus(reason, true); return; }
                SendVoice(wav);
                return;
            }

            if (!CanStartTurn()) return;

            // Say it BEFORE the user talks, not after: a fresh worker ships without ASR/TTS.
            string blocked = _caps.VoiceBlockedReason();
            if (blocked != null) { _panel.SetStatus(blocked, true); RefreshCapabilities(); return; }

            string err = _voice.StartRecording();
            if (err != null) { _panel.SetStatus(err, true); return; }
            _panel.SetStatus(KalivTurnStatus.Listening, false);
        }

        private void SendVoice(byte[] wav)
        {
            // A typed turn may have started while the mic was open; never run two at once.
            if (_busy || _pendingConfirmation != null)
            {
                _panel.SetStatus("Optagelsen blev ikke sendt — Kaliv er midt i et andet svar.", true);
                return;
            }

            // The current turn is the audio; history is everything before this placeholder.
            var heard = _conversation.Add(new KalivMessage("user", "…") { Spoken = true });
            BeginTurn(KalivTurnStatus.Hearing);
            _live.Spoken = true;
            _voice.BeginReply();

            StartCoroutine(_client.VoiceConverseStream(BaseUrl, Token, wav, Model, HistoryBefore(heard),
                transcript =>
                {
                    heard.Text = string.IsNullOrWhiteSpace(transcript) ? "(uhørligt)" : transcript;
                    _panel.SetStatus(KalivTurnStatus.Thinking, false);
                    _conversation.NotifyChanged();
                },
                chunk =>
                {
                    if (_live == null) return;
                    _live.Text = string.IsNullOrEmpty(_live.Text) ? chunk.Text : _live.Text + " " + chunk.Text;
                    _panel.MarkTranscriptDirty();
                    if (!_voice.EnqueueChunk(chunk.Index, chunk.AudioB64, chunk.UtteranceId, out string audioErr) &&
                        audioErr != null)
                        Debug.LogWarning("[KalivVR] lyd for sætning " + chunk.Index + " kunne ikke afspilles: " + audioErr);
                },
                OnPhase,
                (reply, model) =>
                {
                    // The full reply is authoritative over the joined sentences.
                    if (_live != null && !string.IsNullOrWhiteSpace(reply)) _live.Text = reply;
                    FinishTurn(TurnEnd.Completed, null);
                },
                () => { _voice.StopSpeaking(); FinishTurn(TurnEnd.Stopped, null); },
                error =>
                {
                    if (heard.Text == "…") { heard.Text = "(stemmebesked)"; }
                    // The rig's voice stack may have changed since we last asked.
                    RefreshCapabilities();
                    FinishTurn(TurnEnd.Failed, error);
                },
                RegisterCancel));
        }

        /// <summary>History up to (not including) the given message, bounded like every other path.</summary>
        private List<(string role, string content)> HistoryBefore(KalivMessage stop)
        {
            var convo = new List<(string role, string content)>();
            foreach (var m in _conversation.Messages)
            {
                if (ReferenceEquals(m, stop)) break;
                if (m.Error || string.IsNullOrWhiteSpace(m.Text)) continue;
                if (m.Role != "user" && m.Role != "assistant") continue;
                convo.Add((m.Role, m.Text));
            }
            return KalivConversation.Trim(convo, KalivConversation.MaxHistoryMessages, KalivConversation.MaxHistoryChars);
        }

        private void ReportBodySpeech(string utteranceId, string ev)
        {
            if (!_bodySpeechReporting || !Paired) return;
            StartCoroutine(_client.ReportBodySpeech(BaseUrl, Token, utteranceId, ev,
                ok => { if (!ok) _bodySpeechReporting = false; }));
        }

        // =====================================================================================
        // Media
        // =====================================================================================

        public void OpenMediaBrowser()
        {
            if (!Paired) return;
            _mediaItems.Clear();
            _mediaCursor = null;
            _panel.SetMediaItems(_mediaItems, false);
            _panel.SetMediaStatus("Henter medier fra riggen …", false);
            _panel.ShowMediaBrowser(true);
            LoadMediaPage(null);
        }

        public void MediaNextPage()
        {
            if (_mediaCursor != null) LoadMediaPage(_mediaCursor);
        }

        private void LoadMediaPage(string cursor)
        {
            StartCoroutine(_client.MediaPage(BaseUrl, Token, cursor,
                page =>
                {
                    _mediaItems.Clear();
                    _mediaItems.AddRange(page.Items);
                    _mediaCursor = page.NextCursor;
                    _panel.SetMediaItems(_mediaItems, _mediaCursor != null);
                    string skipped = page.Skipped > 0 ? $" ({page.Skipped} ugyldige sprunget over)" : "";
                    _panel.SetMediaStatus(page.Items.Count == 0
                        ? "Riggen har ingen medier endnu." + skipped
                        : $"{page.Items.Count} medier{skipped}. Vælg et for at afspille.", false);
                    foreach (var item in page.Items)
                        StartCoroutine(_client.MediaThumbnail(BaseUrl, Token, item,
                            tex => _panel.SetMediaThumbnail(item.Id, tex), _ => { }));
                },
                (status, error) => _panel.SetMediaStatus(status == 404
                    ? "Riggen har ikke mediebiblioteket endnu. Kontrakten (kaliv-media-gallery/v1) er aftalt, " +
                      "men backend serverer den ikke — Kaliv VR er klar, når riggen er."
                    : Friendly(error), true)));
        }

        public void PlayMedia(KalivMediaItem item)
        {
            if (item == null) return;
            if (item.Kind == KalivMediaKind.Image) { ShowImage(item); return; }
            string hint = item.FormatHint;
            if (hint == null)
            {
                _panel.SetMediaStatus($"Formatet ({item.Projection} / {item.Stereo}) kan afspilningsmotoren ikke vise.", true);
                return;
            }

            _cancelDownload?.Invoke();
            StartCoroutine(_client.MediaDownload(BaseUrl, Token, item,
                p => _panel.SetMediaStatus($"Henter video … {Mathf.RoundToInt(p * 100)} %", false),
                path =>
                {
                    _cancelDownload = null;
                    _panel.ShowMediaBrowser(false);
                    _mediaFormatIndex = Array.IndexOf(SkyPlayerFormats, hint);
                    _renderEngine.OpenMedia("file://" + path, hint);
                    _renderEngine.SetMediaScreenAsGazeTarget(true);
                    _mediaOpen = true;
                    _panel.ShowTransport(true);
                    UpdateTransport();
                },
                error => { _cancelDownload = null; _panel.SetMediaStatus(error, true); },
                cancel => _cancelDownload = cancel));
        }

        /// <summary>SkyPlayer-Engine's own format cycle (VrProjection.Cycle), for the FORMAT button.</summary>
        private static readonly string[] SkyPlayerFormats =
            { "FLAT", "SBS_3D", "VR180_MONO", "VR180_SBS", "VR360_MONO", "VR360_SBS", "OU_TB" };

        public void MediaTogglePlay() { _renderEngine.ToggleMediaPlayback(); UpdateTransport(); }
        public void MediaSeek(double seconds) { _renderEngine.SeekMediaRelative(seconds); UpdateTransport(); }
        public void MediaRecenter() => _renderEngine.RecenterMedia();

        public void MediaCycleFormat()
        {
            _mediaFormatIndex = (_mediaFormatIndex + 1 + SkyPlayerFormats.Length) % SkyPlayerFormats.Length;
            _renderEngine.SetMediaFormat(SkyPlayerFormats[_mediaFormatIndex]);
            UpdateTransport();
        }

        public void CloseMedia()
        {
            _cancelDownload?.Invoke();
            _renderEngine.StopMedia();
            _renderEngine.SetMediaScreenAsGazeTarget(false);
            _images?.Hide();
            if (_showingImage) _renderEngine.SetScreenTarget(_panel.PanelTransform);   // "screen" is the panel again
            _showingImage = false;
            _mediaOpen = false;
            _panel.ShowTransport(false);
        }

        private KalivImageViewer _images;
        private bool _showingImage;

        /// <summary>
        /// A still image: fetched like a video (Bearer header, local cache), then shown on a
        /// floating plane. Stereo photos show one eye's half so they read as one picture.
        /// </summary>
        private void ShowImage(KalivMediaItem item)
        {
            _cancelDownload?.Invoke();
            StartCoroutine(_client.MediaDownload(BaseUrl, Token, item,
                p => _panel.SetMediaStatus($"Henter billede … {Mathf.RoundToInt(p * 100)} %", false),
                path =>
                {
                    _cancelDownload = null;
                    byte[] bytes;
                    try { bytes = File.ReadAllBytes(path); }
                    catch (Exception e) { _panel.SetMediaStatus("Billedet kunne ikke læses: " + e.Message, true); return; }

                    var tex = new Texture2D(2, 2, TextureFormat.RGBA32, false);
                    if (!tex.LoadImage(bytes, true))
                    {
                        Destroy(tex);
                        // WebP is in the contract, but Unity's decoder only reads PNG and JPEG.
                        _panel.SetMediaStatus(item.MimeType == "image/webp"
                            ? "WebP-billeder kan Unity ikke afkode på headsettet — kun PNG og JPEG."
                            : "Billedet kunne ikke afkodes.", true);
                        return;
                    }

                    if (_images == null)
                    {
                        _images = KalivImageViewer.Create(_renderEngine.MediaRoot);
                        // Into the media layer, so the composition's camera setup draws it.
                        _renderEngine.AttachMedia(_images.gameObject);
                    }
                    _renderEngine.StopMedia();
                    _images.Show(tex, item.Stereo, _camera);
                    _renderEngine.SetScreenTarget(_images.transform);   // Kaliv can look at it
                    _showingImage = true;
                    _mediaOpen = true;
                    _panel.ShowMediaBrowser(false);
                    _panel.ShowTransport(true);
                    _panel.SetTransportInfo($"BILLEDE\n{item.Width}×{item.Height}", false);
                },
                error => { _cancelDownload = null; _panel.SetMediaStatus(error, true); },
                cancel => _cancelDownload = cancel));
        }

        private void OnMediaEnded() => UpdateTransport();

        private void UpdateTransport()
        {
            if (!_mediaOpen || _showingImage) return;
            string fmt = _renderEngine.MediaFormatLabel;
            string time = _renderEngine.MediaLength > 0
                ? $"{Clock(_renderEngine.MediaTime)} / {Clock(_renderEngine.MediaLength)}"
                : "";
            _panel.SetTransportInfo($"{fmt}\n{time}", _renderEngine.MediaPlaying);
        }

        private float _transportTick;

        private void Update()
        {
            // The talk button shows level and elapsed time while recording.
            if (_voice != null)
                _panel?.SetVoiceState(_voice.IsRecording, _voice.Level, _voice.RecordedSeconds,
                    !_busy && _pendingConfirmation == null && Paired);

            if (_mediaOpen)
            {
                if (!_showingImage) MediaSticks();
                if ((_transportTick -= Time.unscaledDeltaTime) <= 0f)
                {
                    _transportTick = 0.5f;
                    UpdateTransport();
                }
            }
        }

        private bool _seekLatched;

        /// <summary>
        /// Joysticks while a video is open — the same mapping as SkyPlayer, so the two apps on
        /// the same engine feel the same: right ↑/↓ zoom, right ←/→ skip 10 s, left stick pans.
        /// The skip is a flick, latched until the stick returns to centre, so holding it does
        /// not machine-gun through the video.
        /// </summary>
        private void MediaSticks()
        {
            Vector2 right = Stick(UnityEngine.XR.XRNode.RightHand);
            Vector2 left = Stick(UnityEngine.XR.XRNode.LeftHand);
            float dt = Time.unscaledDeltaTime;

            if (Mathf.Abs(right.y) > 0.2f && Mathf.Abs(right.y) > Mathf.Abs(right.x))
                _renderEngine.AdjustMediaZoom(right.y * dt);

            if (!_seekLatched && Mathf.Abs(right.x) > 0.75f && Mathf.Abs(right.x) > Mathf.Abs(right.y))
            {
                _seekLatched = true;
                MediaSeek(right.x > 0 ? 10 : -10);
            }
            else if (_seekLatched && Mathf.Abs(right.x) < 0.3f)
            {
                _seekLatched = false;
            }

            if (left.sqrMagnitude > 0.04f)
                _renderEngine.PanMedia(left.x * 60f * dt, left.y * 45f * dt);
        }

        private static Vector2 Stick(UnityEngine.XR.XRNode node)
        {
            var d = UnityEngine.XR.InputDevices.GetDeviceAtXRNode(node);
            return d.isValid && d.TryGetFeatureValue(UnityEngine.XR.CommonUsages.primary2DAxis, out Vector2 v)
                ? v : Vector2.zero;
        }

        private static string Clock(double seconds)
        {
            var t = TimeSpan.FromSeconds(Math.Max(0, seconds));
            return t.TotalHours >= 1 ? t.ToString(@"h\:mm\:ss") : t.ToString(@"m\:ss");
        }

        // =====================================================================================
        // Body & rig
        // =====================================================================================

        public void RefreshBody() => _renderEngine?.RefreshBody();

        /// <summary>CENTRER: Kaliv and the panel both come back in front of you.</summary>
        public void RecenterBody()
        {
            _renderEngine?.RecenterPresence();
            _panel?.PlaceInFront();
        }

        public void ForgetRig()
        {
            StopGeneration();
            _voice.CancelRecording();
            _voice.StopSpeaking();
            _cancelPull?.Invoke();
            _cancelPull = null;
            CloseMedia();
            _pendingConfirmation = null;
            _panel.HideConfirmation();

            BaseUrl = "";
            Token = "";
            Model = "";
            _conversation.Clear();
            SaveConversation();
            PlayerPrefs.DeleteKey(BaseUrlKey);
            PlayerPrefs.DeleteKey(TokenKey);
            PlayerPrefs.DeleteKey(ModelKey);
            PlayerPrefs.DeleteKey(DeviceIdKey);
            DeviceId = null;
            PlayerPrefs.Save();

            _renderEngine?.Disconnect();
            _panel.SetPaired(false);
            _panel.SetStatus("Rig glemt. Par Kaliv VR igen.", false);
        }

        private static string Friendly(string error)
        {
            if (string.IsNullOrWhiteSpace(error)) return "Ukendt forbindelsesfejl.";
            if (error.Contains("(401)")) return "Adgangen er udløbet eller tilbagekaldt. Par enheden igen.";
            if (error.Contains("(429)")) return "For mange forsøg. Vent lidt og prøv igen.";
            if (error.Contains("(502)") || error.Contains("(503)"))
                return "Riggen svarer, men en underliggende tjeneste er ikke klar.";
            if (error.Contains("(0)")) return "Riggen kunne ikke nås. Er headsettet på samme netværk?";
            return error;
        }
    }
}

using System.Collections.Generic;
using UnityEngine;
using Kaliv.VR.Rendering;

namespace Kaliv.VR
{
    /// <summary>
    /// Product-level state for the VR client. Backend semantics stay here;
    /// reusable XR/media mechanics stay in SkyPlayer-Engine.
    /// </summary>
    public sealed class KalivVrApp : MonoBehaviour
    {
        private const string BaseUrlKey = "kaliv.vr.rig_url";
        private const string TokenKey = "kaliv.vr.rig_token";
        private const string ModelKey = "kaliv.vr.model";

        private ModelRigVrClient _client;
        private KalivVrPanel _panel;
        private KalivVrRenderEngine _renderEngine;
        private readonly List<ModelRigVrClient.ChatMessage> _history = new();
        private readonly System.Text.StringBuilder _reply = new();
        private bool _streaming;
        private System.Action _cancelChat;

        public string BaseUrl { get; private set; }
        public string Token { get; private set; }
        public string Model { get; private set; }

        public bool Paired => !string.IsNullOrWhiteSpace(BaseUrl) &&
                              !string.IsNullOrWhiteSpace(Token);

        public void Initialize(Camera camera)
        {
            _client = gameObject.AddComponent<ModelRigVrClient>();
            BaseUrl = PlayerPrefs.GetString(BaseUrlKey, "http://192.168.1.10:8080");
            Token = PlayerPrefs.GetString(TokenKey, "");
            Model = PlayerPrefs.GetString(ModelKey, "");

            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = new Color(0f, 0f, 0f, 0f);

            _renderEngine = gameObject.AddComponent<KalivVrRenderEngine>();
            _renderEngine.Initialize(camera);

            _panel = KalivVrPanel.Create(camera, this, _renderEngine.UiRoot);
            _renderEngine.AttachUi(_panel.gameObject);
            _renderEngine.StatusChanged += (status, error) => _panel.SetBodyStatus(status, error);
            _panel.SetConnectionDefaults(BaseUrl, "");
            _panel.SetPaired(Paired);
            _panel.SetBodyStatus("Renderer klar", false);

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

            StartCoroutine(_client.ClaimPairing(
                baseUrl,
                code,
                response =>
                {
                    BaseUrl = baseUrl.Trim().TrimEnd('/');
                    Token = response.token.Trim();

                    PlayerPrefs.SetString(BaseUrlKey, BaseUrl);
                    PlayerPrefs.SetString(TokenKey, Token);
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

        public void RefreshModels()
        {
            if (!Paired) return;

            _panel.SetStatus("Henter modeller …", false);
            StartCoroutine(_client.ListModels(
                BaseUrl,
                Token,
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

        public void Send(string prompt)
        {
            prompt = (prompt ?? "").Trim();
            if (!Paired)
            {
                _panel.SetStatus("Kaliv VR er ikke parret med en rig endnu.", true);
                return;
            }
            if (string.IsNullOrWhiteSpace(Model))
            {
                _panel.SetStatus("Vælg en model først.", true);
                return;
            }
            if (prompt.Length == 0) return;
            if (_streaming) return;   // one generation at a time; Stop ends the current one

            _history.Add(new ModelRigVrClient.ChatMessage("user", prompt));
            _panel.AppendUser(prompt);
            _panel.SetComposerBusy(true);
            _panel.SetStatus("Kaliv tænker …", false);

            // The reply is built here rather than read back out of the panel: the panel
            // shows text, it does not own conversation state.
            _reply.Length = 0;
            _streaming = true;
            _panel.BeginAssistant();
            _panel.SetStopAvailable(true);

            StartCoroutine(_client.ChatStream(
                BaseUrl,
                Token,
                Model,
                _history,
                delta =>
                {
                    _reply.Append(delta);
                    _panel.AppendAssistantDelta(delta);
                },
                phase => _panel.SetStatus(PhaseText(phase), false),
                () => FinishStream(committed: true, stopped: false, error: null),
                () => FinishStream(committed: true, stopped: true, error: null),
                error => FinishStream(committed: false, stopped: false, error: error),
                cancel => _cancelChat = cancel));
        }

        /// <summary>Stop an in-flight generation. What arrived so far is kept.</summary>
        public void StopGeneration()
        {
            if (!_streaming) return;
            _cancelChat?.Invoke();
        }

        /// <summary>
        /// One exit for every way a stream can end, so the composer, the stop button and
        /// the history can never be left in a half-finished state.
        ///
        /// A stopped generation still commits what arrived: the user read those words, and
        /// a follow-up question that silently dropped them would make the model look like
        /// it had amnesia about its own half-sentence.
        /// </summary>
        private void FinishStream(bool committed, bool stopped, string error)
        {
            if (!_streaming) return;
            _streaming = false;
            _cancelChat = null;
            _panel.SetStopAvailable(false);
            _panel.SetComposerBusy(false);

            string text = _reply.ToString().Trim();

            if (!committed)
            {
                // Nothing is added to history: a failed turn must not become context the
                // model later treats as something it said.
                _panel.EndAssistant(text.Length == 0 ? "(intet svar)" : null);
                _panel.SetStatus(Friendly(error), true);
                return;
            }

            if (text.Length == 0)
            {
                _panel.EndAssistant("(tomt svar fra modellen)");
                _panel.SetStatus($"Rig · {Model}", false);
                return;
            }

            _history.Add(new ModelRigVrClient.ChatMessage("assistant", text));
            _panel.EndAssistant(null);
            _panel.SetStatus(stopped ? $"Stoppet · {Model}" : $"Rig · {Model}", false);
        }

        /// <summary>
        /// The rig's own phase vocabulary, shown as-is when unknown. The client reports
        /// server state; it does not invent a local vocabulary that could drift.
        /// </summary>
        private static string PhaseText(string phase)
        {
            switch (phase)
            {
                case "searching": return "Kaliv søger i dine kilder …";
                case "generating": return "Kaliv svarer …";
                default: return string.IsNullOrWhiteSpace(phase) ? "Kaliv arbejder …" : "Kaliv: " + phase;
            }
        }

        public void RefreshBody() => _renderEngine?.RefreshBody();

        public void RecenterBody() => _renderEngine?.RecenterPresence();

        public void ForgetRig()
        {
            StopGeneration();
            BaseUrl = "";
            Token = "";
            Model = "";
            _history.Clear();
            PlayerPrefs.DeleteKey(BaseUrlKey);
            PlayerPrefs.DeleteKey(TokenKey);
            PlayerPrefs.DeleteKey(ModelKey);
            PlayerPrefs.Save();

            _renderEngine?.Disconnect();
            _panel.SetPaired(false);
            _panel.SetStatus("Rig glemt. Par Kaliv VR igen.", false);
        }

        private static string Friendly(string error)
        {
            if (string.IsNullOrWhiteSpace(error)) return "Ukendt forbindelsesfejl.";
            if (error.Contains("(401)")) return "Adgangen er udløbet eller tilbagekaldt. Par enheden igen.";
            if (error.Contains("(429)")) return "For mange parringsforsøg. Vent lidt og prøv igen.";
            if (error.Contains("(502)") || error.Contains("(503)"))
                return "Riggen svarer, men en underliggende tjeneste er ikke klar.";
            return error;
        }
    }
}

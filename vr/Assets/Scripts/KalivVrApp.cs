using System.Collections.Generic;
using System.Text;
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
        private readonly StringBuilder _streamedAnswer = new();
        private bool _chatInFlight;
        private int _chatGeneration;

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
            if (_chatInFlight)
            {
                _panel.SetStatus("Kaliv svarer allerede · tryk STOP for at afbryde.", false);
                return;
            }
            if (prompt.Length == 0) return;

            _history.Add(new ModelRigVrClient.ChatMessage("user", prompt));
            _panel.AppendUser(prompt);
            _panel.BeginAssistantStream();
            _panel.SetComposerBusy(true);
            _panel.SetStatus("Kaliv tænker …", false);

            _chatInFlight = true;
            _streamedAnswer.Clear();
            int generation = ++_chatGeneration;

            StartCoroutine(_client.ChatStream(
                BaseUrl,
                Token,
                Model,
                _history,
                delta =>
                {
                    if (!_chatInFlight || generation != _chatGeneration) return;
                    _streamedAnswer.Append(delta);
                    _panel.AppendAssistantDelta(delta);
                    _panel.SetStatus($"Rig · {Model} · streamer", false);
                },
                () => CompleteStreamingTurn(generation),
                error => FailStreamingTurn(generation, error)));
        }

        public void StopChat()
        {
            if (!_chatInFlight) return;
            _panel.SetStatus("Stopper svar …", false);
            _client?.CancelChat();
        }

        private void CompleteStreamingTurn(int generation)
        {
            if (!_chatInFlight || generation != _chatGeneration) return;

            string clean = _streamedAnswer.ToString().Trim();
            if (clean.Length == 0)
            {
                clean = "(tomt svar fra modellen)";
                _panel.AppendAssistantDelta(clean);
            }

            _history.Add(new ModelRigVrClient.ChatMessage("assistant", clean));
            _panel.FinishAssistantStream(null);
            _streamedAnswer.Clear();
            _chatInFlight = false;
            _panel.SetComposerBusy(false);
            _panel.SetStatus($"Rig · {Model}", false);
        }

        private void FailStreamingTurn(int generation, string error)
        {
            if (!_chatInFlight || generation != _chatGeneration) return;

            bool stopped = string.Equals(error, "Chat stoppet.", System.StringComparison.Ordinal);
            _panel.FinishAssistantStream(stopped
                ? "\n[stoppet]"
                : "\n[ufuldstændigt svar]");
            _streamedAnswer.Clear();
            _chatInFlight = false;

            if (_history.Count > 0 && _history[_history.Count - 1].role == "user")
                _history.RemoveAt(_history.Count - 1);

            _panel.SetComposerBusy(false);
            _panel.SetStatus(stopped ? "Svar stoppet." : Friendly(error), !stopped);
        }

        public void RefreshBody() => _renderEngine?.RefreshBody();

        public void RecenterBody() => _renderEngine?.RecenterPresence();

        public void ForgetRig()
        {
            ++_chatGeneration;
            _client?.CancelChat();
            _chatInFlight = false;
            _streamedAnswer.Clear();
            _panel?.SetComposerBusy(false);

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

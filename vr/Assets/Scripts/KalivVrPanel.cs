using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace Kaliv.VR
{
    /// <summary>Code-driven world-space UI using the shared Kaliv dark/gold design language.</summary>
    public sealed class KalivVrPanel : MonoBehaviour
    {
        private static readonly Color CanvasBg = Hex("#0B0A09");
        private static readonly Color Surface = Hex("#171411");
        private static readonly Color Elevated = Hex("#211B16");
        private static readonly Color Border = Hex("#2A2521");
        private static readonly Color TextMain = Hex("#F3EFE6");
        private static readonly Color Muted = Hex("#A89D90");
        private static readonly Color Accent = Hex("#D4AB52");
        private static readonly Color Danger = Hex("#C96B5D");
        private static readonly Color Ok = Hex("#77836D");

        private KalivVrApp _app;
        private Canvas _canvas;
        private GameObject _pairGroup;
        private GameObject _chatGroup;

        private InputField _url;
        private InputField _code;
        private InputField _prompt;
        private Text _status;
        private Text _transcript;
        private Text _modelLabel;
        private Text _bodyStatus;
        private Button _pairButton;
        private Button _sendButton;
        private Button _stopButton;
        private readonly List<string> _models = new();
        private int _modelIndex;
        private readonly StringBuilder _conversation = new();

        public static KalivVrPanel Create(Camera camera, KalivVrApp app, Transform persistentParent)
        {
            var go = new GameObject("KalivVrPanel");
            if (persistentParent != null)
                go.transform.SetParent(persistentParent, false);
            else
                DontDestroyOnLoad(go);

            var panel = go.AddComponent<KalivVrPanel>();
            panel._app = app;
            panel.Build(camera);
            return panel;
        }

        private void Build(Camera camera)
        {
            var canvasGo = new GameObject("KalivVR.Canvas", typeof(Canvas), typeof(CanvasScaler), typeof(GraphicRaycaster));
            canvasGo.transform.SetParent(transform, false);
            _canvas = canvasGo.GetComponent<Canvas>();
            _canvas.renderMode = RenderMode.WorldSpace;
            _canvas.worldCamera = camera;
            var rt = (RectTransform)_canvas.transform;
            rt.sizeDelta = new Vector2(1200, 760);
            rt.localScale = Vector3.one * 0.00155f;
            rt.position = camera.transform.position + camera.transform.forward * 2.15f;
            rt.rotation = Quaternion.LookRotation(camera.transform.forward, camera.transform.up);

            var bg = AddImage(_canvas.transform, "Background", new Vector2(1200, 760), Vector2.zero, CanvasBg);
            bg.transform.SetAsFirstSibling();

            AddText(_canvas.transform, "KALIV", 18, Accent, TextAnchor.MiddleLeft,
                new Vector2(1020, 42), new Vector2(-20, 337), FontStyle.Bold);
            AddText(_canvas.transform, "VR", 38, TextMain, TextAnchor.MiddleLeft,
                new Vector2(1020, 52), new Vector2(-20, 292), FontStyle.Normal);
            _status = AddText(_canvas.transform, "Ikke forbundet", 17, Muted, TextAnchor.MiddleRight,
                new Vector2(500, 42), new Vector2(320, 337));

            _pairGroup = new GameObject("PairGroup", typeof(RectTransform));
            _pairGroup.transform.SetParent(_canvas.transform, false);
            _url = AddInput(_pairGroup.transform, "Rig-adresse", "http://192.168.1.10:8080",
                new Vector2(780, 62), new Vector2(-90, 120));
            _code = AddInput(_pairGroup.transform, "Parringskode", "XXXX-XXXX",
                new Vector2(420, 62), new Vector2(-270, 35));
            _pairButton = AddButton(_pairGroup.transform, "FORBIND",
                new Vector2(300, 62), new Vector2(315, 35), Accent, () => _app.Pair(_url.text, _code.text));
            AddText(_pairGroup.transform,
                "Backend skal være tilgængelig fra Quest (LAN/Tailscale) — ikke kun 127.0.0.1.",
                15, Muted, TextAnchor.MiddleLeft, new Vector2(920, 54), new Vector2(-20, -60));

            _chatGroup = new GameObject("ChatGroup", typeof(RectTransform));
            _chatGroup.transform.SetParent(_canvas.transform, false);

            var transcriptBg = AddImage(_chatGroup.transform, "TranscriptPanel",
                new Vector2(1080, 410), new Vector2(0, 40), Surface);
            var border = transcriptBg.gameObject.AddComponent<Outline>();
            border.effectColor = Border;
            border.effectDistance = new Vector2(1.5f, -1.5f);

            _transcript = AddText(transcriptBg.transform,
                "Kaliv VR er forbundet. Skriv noget nedenfor.",
                18, TextMain, TextAnchor.UpperLeft, new Vector2(1010, 350), new Vector2(0, -8));
            _transcript.horizontalOverflow = HorizontalWrapMode.Wrap;
            _transcript.verticalOverflow = VerticalWrapMode.Truncate;

            _modelLabel = AddText(_chatGroup.transform, "MODEL", 14, Accent, TextAnchor.MiddleLeft,
                new Vector2(520, 42), new Vector2(-280, 278), FontStyle.Bold);
            _bodyStatus = AddText(_chatGroup.transform, "KROP · initialiserer", 13, Muted, TextAnchor.MiddleLeft,
                new Vector2(430, 42), new Vector2(210, 278), FontStyle.Normal);
            AddButton(_chatGroup.transform, "SKIFT MODEL",
                new Vector2(190, 44), new Vector2(440, 228), Elevated, CycleModel);

            _prompt = AddInput(_chatGroup.transform, "Besked til Kaliv", "Skriv en besked …",
                new Vector2(850, 68), new Vector2(-105, -245));
            _sendButton = AddButton(_chatGroup.transform, "SEND",
                new Vector2(190, 68), new Vector2(435, -245), Accent, () =>
                {
                    string value = _prompt.text;
                    _prompt.text = "";
                    _app.Send(value);
                });

            AddButton(_chatGroup.transform, "KROP IGEN",
                new Vector2(170, 44), new Vector2(-440, -318), Elevated, _app.RefreshBody);
            AddButton(_chatGroup.transform, "CENTRER KROP",
                new Vector2(190, 44), new Vector2(-245, -318), Elevated, _app.RecenterBody);
            _stopButton = AddButton(_chatGroup.transform, "STOP",
                new Vector2(150, 44), new Vector2(0, -318), Danger, _app.StopChat);
            _stopButton.interactable = false;
            AddButton(_chatGroup.transform, "GLEMME RIG",
                new Vector2(220, 44), new Vector2(410, -318), Elevated, _app.ForgetRig);

            SetPaired(false);
        }

        public void SetConnectionDefaults(string baseUrl, string code)
        {
            if (_url != null) _url.text = baseUrl ?? "";
            if (_code != null) _code.text = code ?? "";
        }

        public void SetPaired(bool paired)
        {
            _pairGroup?.SetActive(!paired);
            _chatGroup?.SetActive(paired);
        }

        public void SetStatus(string text, bool error)
        {
            if (_status == null) return;
            _status.text = text ?? "";
            _status.color = error ? Danger : (text != null && text.StartsWith("Forbundet") ? Ok : Muted);
        }

        public void SetBodyStatus(string text, bool error)
        {
            if (_bodyStatus == null) return;
            _bodyStatus.text = "KROP · " + (text ?? "");
            _bodyStatus.color = error ? Danger : Ok;
        }

        public void SetBusy(bool busy)
        {
            if (_pairButton != null) _pairButton.interactable = !busy;
        }

        public void SetComposerBusy(bool busy)
        {
            if (_sendButton != null) _sendButton.interactable = !busy;
            if (_prompt != null) _prompt.interactable = !busy;
            if (_stopButton != null) _stopButton.interactable = busy;
        }

        public void SetModels(List<string> models, string selected)
        {
            _models.Clear();
            if (models != null) _models.AddRange(models);
            _modelIndex = Math.Max(0, _models.IndexOf(selected));
            RefreshModelLabel();
        }

        public void AppendUser(string text) => Append("DIG", text);
        public void AppendAssistant(string text) => Append("KALIV", text);

        public void BeginAssistantStream()
        {
            if (_conversation.Length > 0) _conversation.Append("\n\n");
            _conversation.Append("KALIV\n");
            RefreshTranscript();
        }

        public void AppendAssistantDelta(string delta)
        {
            if (string.IsNullOrEmpty(delta)) return;
            _conversation.Append(delta);
            RefreshTranscript();
        }

        public void FinishAssistantStream(string suffix)
        {
            if (!string.IsNullOrEmpty(suffix)) _conversation.Append(suffix);
            TrimConversation();
            RefreshTranscript();
        }

        private void Append(string who, string text)
        {
            if (_conversation.Length > 0) _conversation.Append("\n\n");
            _conversation.Append(who).Append("\n").Append(text?.Trim());
            TrimConversation();
            RefreshTranscript();
        }

        private void TrimConversation()
        {
            if (_conversation.Length > 5000)
                _conversation.Remove(0, _conversation.Length - 5000);
        }

        private void RefreshTranscript()
        {
            if (_transcript != null) _transcript.text = _conversation.ToString();
        }

        private void CycleModel()
        {
            if (_models.Count == 0)
            {
                _app.RefreshModels();
                return;
            }
            _modelIndex = (_modelIndex + 1) % _models.Count;
            _app.SelectModel(_models[_modelIndex]);
            RefreshModelLabel();
        }

        private void RefreshModelLabel()
        {
            if (_modelLabel == null) return;
            _modelLabel.text = _models.Count == 0 ? "MODEL · ingen" : "MODEL · " + _models[_modelIndex];
        }

        private static Image AddImage(Transform parent, string name, Vector2 size, Vector2 pos, Color color)
        {
            var go = new GameObject(name, typeof(Image));
            go.transform.SetParent(parent, false);
            var image = go.GetComponent<Image>();
            image.color = color;
            var rt = image.rectTransform;
            rt.sizeDelta = size;
            rt.anchoredPosition = pos;
            return image;
        }

        private static Text AddText(Transform parent, string value, int size, Color color,
                                    TextAnchor anchor, Vector2 box, Vector2 pos,
                                    FontStyle style = FontStyle.Normal)
        {
            var go = new GameObject("Text", typeof(Text));
            go.transform.SetParent(parent, false);
            var text = go.GetComponent<Text>();
            text.font = Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");
            text.fontSize = size;
            text.fontStyle = style;
            text.color = color;
            text.alignment = anchor;
            text.text = value;
            text.raycastTarget = false;
            var rt = text.rectTransform;
            rt.sizeDelta = box;
            rt.anchoredPosition = pos;
            return text;
        }

        private static InputField AddInput(Transform parent, string name, string placeholder,
                                           Vector2 size, Vector2 pos)
        {
            var root = new GameObject(name, typeof(Image), typeof(InputField), typeof(BoxCollider));
            root.transform.SetParent(parent, false);
            var image = root.GetComponent<Image>();
            image.color = Elevated;
            var rt = image.rectTransform;
            rt.sizeDelta = size;
            rt.anchoredPosition = pos;

            var outline = root.AddComponent<Outline>();
            outline.effectColor = Border;
            outline.effectDistance = new Vector2(1.5f, -1.5f);

            var text = AddText(root.transform, "", 18, TextMain, TextAnchor.MiddleLeft,
                new Vector2(size.x - 36, size.y - 12), Vector2.zero);
            var hint = AddText(root.transform, placeholder, 18, Muted, TextAnchor.MiddleLeft,
                new Vector2(size.x - 36, size.y - 12), Vector2.zero);

            var input = root.GetComponent<InputField>();
            input.textComponent = text;
            input.placeholder = hint;
            input.lineType = InputField.LineType.SingleLine;

            var collider = root.GetComponent<BoxCollider>();
            collider.size = new Vector3(size.x, size.y, 60f);
            return input;
        }

        private static Button AddButton(Transform parent, string label, Vector2 size, Vector2 pos,
                                        Color color, UnityEngine.Events.UnityAction click)
        {
            var root = new GameObject(label, typeof(Image), typeof(Button), typeof(BoxCollider));
            root.transform.SetParent(parent, false);
            var image = root.GetComponent<Image>();
            image.color = color;
            var rt = image.rectTransform;
            rt.sizeDelta = size;
            rt.anchoredPosition = pos;

            AddText(root.transform, label, 15,
                color == Accent ? Hex("#2B1C05") : TextMain,
                TextAnchor.MiddleCenter, size, Vector2.zero, FontStyle.Bold);

            var button = root.GetComponent<Button>();
            button.targetGraphic = image;
            button.onClick.AddListener(click);

            var collider = root.GetComponent<BoxCollider>();
            collider.size = new Vector3(size.x, size.y, 60f);
            return button;
        }

        private static Color Hex(string value)
        {
            ColorUtility.TryParseHtmlString(value, out Color color);
            return color;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Text;
using UnityEngine;
using UnityEngine.UI;

namespace Kaliv.VR
{
    /// <summary>
    /// Code-driven world-space UI in the shared Kaliv dark/gold design language.
    ///
    /// The panel shows state; it does not own it. The conversation lives in
    /// KalivConversation, turn logic in KalivVrApp. That split is why the transcript is
    /// re-rendered from the conversation rather than appended to: retry, history restore and
    /// error bubbles all change what is on screen, and a panel that kept its own copy of the
    /// text would drift from what is actually sent to the rig.
    /// </summary>
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
        private static readonly Color OnAccent = Hex("#2B1C05");

        private const string AccentHex = "#D4AB52";
        private const string MutedHex = "#A89D90";
        private const string DangerHex = "#C96B5D";
        private const string OkHex = "#9DAA91";

        /// <summary>Characters of transcript kept in the Text component. Older text scrolls off the top.</summary>
        private const int TranscriptWindow = 3200;

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
        private Button _retryButton;
        private Button _talkButton;
        private Text _talkLabel;
        private Image _talkImage;
        private Text _ragLabel;
        private Image _ragImage;
        private Text _toolsLabel;
        private Image _toolsImage;

        private KalivConversation _conversation;
        private bool _transcriptDirty;
        private string _liveSuffix;          // e.g. "▌" while streaming

        private readonly List<string> _models = new();
        private int _modelIndex;

        // Confirmation card
        private GameObject _confirmGroup;
        private Text _confirmTitle;
        private Text _confirmBody;
        private Text _confirmExpiry;
        private Button _approveButton;
        private Button _denyButton;
        private float _confirmDeadline;

        // Media browser + transport
        private GameObject _mediaGroup;
        private Text _mediaStatus;
        private readonly List<MediaRow> _mediaRows = new();
        private Button _mediaMore;
        private GameObject _transportGroup;
        private Text _transportInfo;
        private Text _transportPlay;

        // Keyboard
        private GameObject _keyboardGroup;
        private Text _kbTitle;
        private Text _kbPreview;
        private readonly List<Button[]> _kbRows = new();
        private Text _kbShiftLabel;
        private Text _kbLayerLabel;
        private Text _kbOkLabel;
        private KalivKeyboardModel _kb;
        private InputField _kbTarget;
        private bool _keyboardOpen;

        private sealed class MediaRow
        {
            public GameObject Root;
            public Text Label;
            public RawImage Thumb;
            public KalivMediaItem Item;
        }

        public Transform PanelTransform => _canvas != null ? _canvas.transform : transform;

        public static KalivVrPanel Create(Camera camera, KalivVrApp app, Transform persistentParent)
        {
            var go = new GameObject("KalivVrPanel");
            if (persistentParent != null) go.transform.SetParent(persistentParent, false);
            else DontDestroyOnLoad(go);

            var panel = go.AddComponent<KalivVrPanel>();
            panel._app = app;
            panel.Build(camera);
            return panel;
        }

        // =====================================================================================
        // Layout
        // =====================================================================================

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
                new Vector2(1020, 52), new Vector2(-20, 292));
            _status = AddText(_canvas.transform, "Ikke forbundet", 17, Muted, TextAnchor.MiddleRight,
                new Vector2(640, 42), new Vector2(250, 337));

            BuildPairGroup();
            BuildChatGroup();
            BuildConfirmCard();
            BuildMediaBrowser();
            BuildTransport();
            BuildRigOverlay();
            BuildKeyboard();

            // Every text field in the panel opens the in-headset keyboard instead of waiting for
            // a system keyboard that Quest will not show for this app.
            KalivVrPointer.InputFieldHandler = OpenKeyboard;

            SetPaired(false);
        }

        private void OnDestroy()
        {
            if (KalivVrPointer.InputFieldHandler == (Func<InputField, bool>)OpenKeyboard)
                KalivVrPointer.InputFieldHandler = null;
        }

        private void BuildKeyboard()
        {
            _keyboardGroup = Group("Keyboard", _canvas.transform);
            AddImage(_keyboardGroup.transform, "Backdrop", new Vector2(1200, 760), Vector2.zero, CanvasBg);
            _kbTitle = AddText(_keyboardGroup.transform, "", 16, Accent, TextAnchor.MiddleLeft,
                new Vector2(1080, 36), new Vector2(0, 322), FontStyle.Bold);
            var previewBg = AddImage(_keyboardGroup.transform, "Preview", new Vector2(1092, 74), new Vector2(0, 262), Elevated);
            var outline = previewBg.gameObject.AddComponent<Outline>();
            outline.effectColor = Border;
            outline.effectDistance = new Vector2(1.5f, -1.5f);
            previewBg.gameObject.AddComponent<RectMask2D>();
            _kbPreview = AddText(previewBg.transform, "", 22, TextMain, TextAnchor.MiddleRight,
                new Vector2(1060, 64), Vector2.zero);
            _kbPreview.horizontalOverflow = HorizontalWrapMode.Overflow;

            const float keyW = 92f, keyH = 78f, gap = 8f;
            int perRow = KalivKeyboardModel.MaxKeysPerRow;
            for (int r = 0; r < KalivKeyboardModel.Rows; r++)
            {
                var row = new Button[perRow];
                float y = 160f - r * (keyH + gap);
                for (int c = 0; c < perRow; c++)
                {
                    int rr = r, cc = c;
                    row[c] = AddButton(_keyboardGroup.transform, "", new Vector2(keyW, keyH), new Vector2(0, y),
                        Surface, () => PressKey(rr, cc));
                    row[c].GetComponentInChildren<Text>().fontSize = 24;
                }
                _kbRows.Add(row);
            }

            float by = 160f - KalivKeyboardModel.Rows * (keyH + gap);
            var shift = AddButton(_keyboardGroup.transform, KalivKeyboardModel.Shift, new Vector2(130, keyH), new Vector2(-480, by),
                Elevated, () => PressNamed(KalivKeyboardModel.Shift));
            _kbShiftLabel = shift.GetComponentInChildren<Text>();
            var layer = AddButton(_keyboardGroup.transform, KalivKeyboardModel.ToSymbols, new Vector2(140, keyH), new Vector2(-340, by),
                Elevated, () => PressNamed(_kb != null && _kb.Current == KalivKeyboardModel.Layer.Symbols
                    ? KalivKeyboardModel.ToLetters : KalivKeyboardModel.ToSymbols));
            _kbLayerLabel = layer.GetComponentInChildren<Text>();
            AddButton(_keyboardGroup.transform, KalivKeyboardModel.Space, new Vector2(400, keyH), new Vector2(-55, by),
                Surface, () => PressNamed(KalivKeyboardModel.Space));
            AddButton(_keyboardGroup.transform, KalivKeyboardModel.Delete, new Vector2(150, keyH), new Vector2(230, by),
                Elevated, () => PressNamed(KalivKeyboardModel.Delete));
            AddButton(_keyboardGroup.transform, KalivKeyboardModel.Clear, new Vector2(130, keyH), new Vector2(380, by),
                Elevated, () => PressNamed(KalivKeyboardModel.Clear));
            AddButton(_keyboardGroup.transform, "LUK", new Vector2(110, keyH), new Vector2(505, by),
                Danger, () => CloseKeyboard(false));

            var ok = AddButton(_keyboardGroup.transform, "OK", new Vector2(360, 64), new Vector2(0, by - 90),
                Accent, () => CloseKeyboard(true));
            _kbOkLabel = ok.GetComponentInChildren<Text>();

            _keyboardGroup.SetActive(false);
        }

        /// <summary>Called by the pointer when a text field is clicked. Returns true when handled.</summary>
        private bool OpenKeyboard(InputField field)
        {
            if (field == null || _keyboardGroup == null) return false;
            if (!field.transform.IsChildOf(_canvas.transform)) return false;   // not ours

            _kbTarget = field;
            _kbCallback = null;
            bool prompt = field == _prompt;
            int max = field == _code ? 32 : field == _url ? 200 : 2000;
            _kb = new KalivKeyboardModel(field.text, max, capitalizeFirst: prompt);
            string name = field.gameObject.name;
            _kbTitle.text = name.ToUpperInvariant();
            _kbOkLabel.text = prompt ? "SEND" : "OK";
            _keyboardOpen = true;
            RefreshGroups();
            _keyboardGroup.transform.SetAsLastSibling();
            RefreshKeyboard();
            return true;
        }

        private void PressKey(int row, int col)
        {
            if (_kb == null) return;
            string keys = _kb.RowKeys(row);
            if (col < 0 || col >= keys.Length) return;
            _kb.Press(keys[col].ToString());
            RefreshKeyboard();
        }

        private void PressNamed(string key)
        {
            if (_kb == null) return;
            _kb.Press(key);
            RefreshKeyboard();
        }

        private void RefreshKeyboard()
        {
            if (_kb == null) return;
            for (int r = 0; r < _kbRows.Count; r++)
            {
                string keys = _kb.RowKeys(r);
                var row = _kbRows[r];
                float keyW = 92f, gap = 8f;
                float width = keys.Length * (keyW + gap) - gap;
                for (int c = 0; c < row.Length; c++)
                {
                    bool used = c < keys.Length;
                    row[c].gameObject.SetActive(used);
                    if (!used) continue;
                    row[c].GetComponentInChildren<Text>().text = keys[c].ToString();
                    var rt = (RectTransform)row[c].transform;
                    rt.anchoredPosition = new Vector2(-width / 2f + keyW / 2f + c * (keyW + gap), rt.anchoredPosition.y);
                }
            }
            _kbShiftLabel.text = _kb.Current == KalivKeyboardModel.Layer.Upper ? "SHIFT ●" : KalivKeyboardModel.Shift;
            _kbLayerLabel.text = _kb.Current == KalivKeyboardModel.Layer.Symbols
                ? KalivKeyboardModel.ToLetters : KalivKeyboardModel.ToSymbols;
            // The caret makes "is there a trailing space?" answerable at a glance.
            _kbPreview.text = _kb.Text + "|";
        }

        private Action<string> _kbCallback;

        /// <summary>
        /// Ask for free text — a model name to download, a note to add to the documents.
        /// Same keyboard as the fields; the result goes to <paramref name="onOk"/> instead.
        /// </summary>
        public void RequestText(string title, string initial, int maxLength, string okLabel, Action<string> onOk)
        {
            if (_keyboardGroup == null) return;
            _kbTarget = null;
            _kbCallback = onOk;
            _kb = new KalivKeyboardModel(initial, maxLength);
            _kbTitle.text = title;
            _kbOkLabel.text = okLabel;
            _keyboardOpen = true;
            RefreshGroups();
            _keyboardGroup.transform.SetAsLastSibling();
            RefreshKeyboard();
        }

        private void CloseKeyboard(bool commit)
        {
            var target = _kbTarget;
            var callback = _kbCallback;
            string text = _kb?.Text ?? "";
            _kbTarget = null;
            _kbCallback = null;
            _kb = null;
            _keyboardOpen = false;
            RefreshGroups();

            if (commit && callback != null) { callback(text); return; }
            if (!commit || target == null) return;
            if (target == _prompt)
            {
                target.text = "";
                _app.Send(text);
                return;
            }
            target.text = text;
        }

        public bool KeyboardOpen => _keyboardOpen;

        // ---- RIG overlay: document sources & tool registry ------------------------------

        /// <summary>One row in the RIG overlay: a main action and an optional on/off switch.</summary>
        public sealed class RigRow
        {
            public string Label;
            public string Toggle;          // null = no switch
            public bool ToggleOn;
            public bool Selected;
            public Action OnMain;
            public Action OnToggle;
        }

        private GameObject _rigGroup;
        private bool _rigOpen;
        private Text _rigStatus;
        public static readonly string[] RigTabs =
            { "KILDER", "VÆRKTØJER", "PERSONER", "MODELLER", "STATUS", "ENHEDER", "PLANER", "LOG" };
        private readonly List<Image> _rigTabImages = new();
        private readonly List<(Button main, Text mainText, Button toggle, Text toggleText)> _rigRowUi = new();
        private Button _rigMore;
        private List<RigRow> _rigRows = new();
        private int _rigPage;
        private const int RigRowsPerPage = 7;

        private void BuildRigOverlay()
        {
            _rigGroup = Group("RigOverlay", _canvas.transform);
            AddImage(_rigGroup.transform, "Backdrop", new Vector2(1200, 760), Vector2.zero, CanvasBg);
            // One tab per rig surface Android has a screen for, in the order you reach for them.
            const float tabW = 134f, tabGap = 6f;
            float tabsWidth = RigTabs.Length * (tabW + tabGap) - tabGap;
            for (int i = 0; i < RigTabs.Length; i++)
            {
                int tab = i;
                var b = AddButton(_rigGroup.transform, RigTabs[i], new Vector2(tabW, 48),
                    new Vector2(-tabsWidth / 2f + tabW / 2f + i * (tabW + tabGap), 330),
                    Elevated, () => _app.RigShowTab(tab));
                b.GetComponentInChildren<Text>().fontSize = 13;
                _rigTabImages.Add(b.GetComponent<Image>());
            }

            _rigStatus = AddText(_rigGroup.transform, "", 15, Muted, TextAnchor.MiddleLeft,
                new Vector2(1080, 44), new Vector2(0, 278));
            _rigStatus.horizontalOverflow = HorizontalWrapMode.Wrap;

            for (int i = 0; i < RigRowsPerPage; i++)
            {
                int index = i;
                float y = 215 - i * 68;
                var main = AddButton(_rigGroup.transform, "", new Vector2(860, 58), new Vector2(-110, y),
                    Surface, () => OnRigMain(index));
                var mt = main.GetComponentInChildren<Text>();
                mt.alignment = TextAnchor.MiddleLeft;
                mt.fontStyle = FontStyle.Normal;
                mt.rectTransform.sizeDelta = new Vector2(820, 54);
                var toggle = AddButton(_rigGroup.transform, "", new Vector2(200, 58), new Vector2(430, y),
                    Elevated, () => OnRigToggle(index));
                _rigRowUi.Add((main, mt, toggle, toggle.GetComponentInChildren<Text>()));
                main.gameObject.SetActive(false);
                toggle.gameObject.SetActive(false);
            }

            _rigMore = AddButton(_rigGroup.transform, "FLERE", new Vector2(200, 52), new Vector2(-150, -300),
                Elevated, () => { _rigPage++; RenderRigRows(); });
            AddButton(_rigGroup.transform, "LUK", new Vector2(200, 52), new Vector2(150, -300),
                Elevated, () => ShowRig(false));
            _rigGroup.SetActive(false);
        }

        public void ShowRig(bool show)
        {
            _rigOpen = show;
            RefreshGroups();
            if (show) _rigGroup.transform.SetAsLastSibling();
        }

        public void SetRigTab(int tab)
        {
            for (int i = 0; i < _rigTabImages.Count; i++)
                _rigTabImages[i].color = i == tab ? Accent : Elevated;
        }

        public void SetRigStatus(string text, bool error)
        {
            if (_rigStatus == null) return;
            _rigStatus.text = text ?? "";
            _rigStatus.color = error ? Danger : Muted;
        }

        public void SetRigRows(List<RigRow> rows, bool keepPage = false)
        {
            _rigRows = rows ?? new List<RigRow>();
            if (!keepPage) _rigPage = 0;
            RenderRigRows();
        }

        private void RenderRigRows()
        {
            int pages = Math.Max(1, (_rigRows.Count + RigRowsPerPage - 1) / RigRowsPerPage);
            if (_rigPage >= pages) _rigPage = 0;
            int start = _rigPage * RigRowsPerPage;
            for (int i = 0; i < _rigRowUi.Count; i++)
            {
                var ui = _rigRowUi[i];
                int idx = start + i;
                var row = idx < _rigRows.Count ? _rigRows[idx] : null;
                ui.main.gameObject.SetActive(row != null);
                ui.toggle.gameObject.SetActive(row != null && row.Toggle != null);
                if (row == null) continue;
                ui.mainText.text = (row.Selected ? "● " : "   ") + row.Label;
                ((Image)ui.main.targetGraphic).color = row.Selected ? Elevated : Surface;
                if (row.Toggle != null)
                {
                    ui.toggleText.text = row.Toggle;
                    ((Image)ui.toggle.targetGraphic).color = row.ToggleOn ? Ok : Danger;
                }
            }
            if (_rigMore != null) _rigMore.gameObject.SetActive(pages > 1);
        }

        private void OnRigMain(int index)
        {
            int idx = _rigPage * RigRowsPerPage + index;
            if (idx < _rigRows.Count) _rigRows[idx].OnMain?.Invoke();
        }

        private void OnRigToggle(int index)
        {
            int idx = _rigPage * RigRowsPerPage + index;
            if (idx < _rigRows.Count) _rigRows[idx].OnToggle?.Invoke();
        }

        private void BuildPairGroup()
        {
            _pairGroup = Group("PairGroup", _canvas.transform);
            _url = AddInput(_pairGroup.transform, "Rig-adresse", "http://192.168.1.10:8080",
                new Vector2(780, 62), new Vector2(-90, 120));
            _code = AddInput(_pairGroup.transform, "Parringskode", "XXXX-XXXX",
                new Vector2(420, 62), new Vector2(-270, 35));
            _pairButton = AddButton(_pairGroup.transform, "FORBIND",
                new Vector2(300, 62), new Vector2(315, 35), Accent, () => _app.Pair(_url.text, _code.text));
            AddText(_pairGroup.transform,
                "Backend skal være tilgængelig fra Quest (LAN/Tailscale) — ikke kun 127.0.0.1.",
                15, Muted, TextAnchor.MiddleLeft, new Vector2(920, 54), new Vector2(-20, -60));
        }

        private void BuildChatGroup()
        {
            _chatGroup = Group("ChatGroup", _canvas.transform);

            // Header row: model + body status
            _modelLabel = AddText(_chatGroup.transform, "MODEL", 14, Accent, TextAnchor.MiddleLeft,
                new Vector2(520, 36), new Vector2(-280, 250), FontStyle.Bold);
            _bodyStatus = AddText(_chatGroup.transform, "KROP · initialiserer", 13, Muted, TextAnchor.MiddleRight,
                new Vector2(480, 36), new Vector2(290, 250));

            // Mode row: the two switches that decide the turn's route, then model + media.
            // Same two toggles as Android's composer, so the same turn routes the same way.
            var rag = AddButton(_chatGroup.transform, "VIDEN · FRA", new Vector2(220, 44), new Vector2(-430, 205),
                Elevated, () => _app.ToggleRag());
            _ragLabel = rag.GetComponentInChildren<Text>();
            _ragImage = rag.GetComponent<Image>();
            var tools = AddButton(_chatGroup.transform, "VÆRKTØJER · FRA", new Vector2(220, 44), new Vector2(-200, 205),
                Elevated, () => _app.ToggleTools());
            // Which documents VIDEN searches, and which tools exist and are allowed — the
            // rig's own switches, so the headset can pull the brake without a phone.
            AddButton(_chatGroup.transform, "RIG", new Vector2(110, 44), new Vector2(-25, 205),
                Elevated, () => _app.OpenRig());
            _toolsLabel = tools.GetComponentInChildren<Text>();
            _toolsImage = tools.GetComponent<Image>();
            AddButton(_chatGroup.transform, "SKIFT MODEL", new Vector2(190, 44), new Vector2(255, 205), Elevated, CycleModel);
            AddButton(_chatGroup.transform, "MEDIER", new Vector2(150, 44), new Vector2(440, 205), Elevated, () => _app.OpenMediaBrowser());

            // Transcript. Bottom-anchored inside a mask: the NEWEST line is always visible and
            // older text scrolls off the top. The first VR slice was top-anchored with
            // Truncate, which silently cut off exactly the part you had just asked for.
            var transcriptBg = AddImage(_chatGroup.transform, "TranscriptPanel",
                new Vector2(1080, 360), new Vector2(0, 0), Surface);
            var border = transcriptBg.gameObject.AddComponent<Outline>();
            border.effectColor = Border;
            border.effectDistance = new Vector2(1.5f, -1.5f);
            transcriptBg.gameObject.AddComponent<RectMask2D>();

            _transcript = AddText(transcriptBg.transform, "", 18, TextMain, TextAnchor.LowerLeft,
                new Vector2(1030, 340), new Vector2(0, 0));
            _transcript.supportRichText = true;
            _transcript.horizontalOverflow = HorizontalWrapMode.Wrap;
            _transcript.verticalOverflow = VerticalWrapMode.Overflow;
            var trt = _transcript.rectTransform;
            trt.pivot = new Vector2(0.5f, 0f);
            trt.anchoredPosition = new Vector2(0, -170 + 10);

            // Composer
            _prompt = AddInput(_chatGroup.transform, "Besked til Kaliv", "Skriv en besked …",
                new Vector2(690, 64), new Vector2(-185, -225));
            var talk = AddButton(_chatGroup.transform, "TAL", new Vector2(160, 64), new Vector2(255, -225),
                Elevated, () => _app.ToggleVoice());
            _talkButton = talk;
            _talkLabel = talk.GetComponentInChildren<Text>();
            _talkImage = talk.GetComponent<Image>();
            _sendButton = AddButton(_chatGroup.transform, "SEND", new Vector2(170, 64), new Vector2(440, -225),
                Accent, () =>
                {
                    string value = _prompt.text;
                    _prompt.text = "";
                    _app.Send(value);
                });

            // Bottom row
            _stopButton = AddButton(_chatGroup.transform, "STOP", new Vector2(150, 44), new Vector2(-455, -305),
                Danger, () => _app.StopGeneration());
            _retryButton = AddButton(_chatGroup.transform, "PRØV IGEN", new Vector2(170, 44), new Vector2(-290, -305),
                Elevated, () => _app.Retry());
            AddButton(_chatGroup.transform, "NY SAMTALE", new Vector2(180, 44), new Vector2(-110, -305),
                Elevated, () => _app.NewConversation());
            AddButton(_chatGroup.transform, "KROP IGEN", new Vector2(160, 44), new Vector2(70, -305),
                Elevated, () => _app.RefreshBody());
            AddButton(_chatGroup.transform, "CENTRER", new Vector2(150, 44), new Vector2(235, -305),
                Elevated, () => _app.RecenterBody());
            AddButton(_chatGroup.transform, "GLEM RIG", new Vector2(160, 44), new Vector2(405, -305),
                Elevated, () => _app.ForgetRig());

            SetStopAvailable(false);
            SetRetryAvailable(false);
        }

        /// <summary>
        /// The confirmation card. It shows what the RIG says the action is — tool, its own
        /// risk and impact, the summary it parked — and nothing the client composed. The
        /// client never sends the arguments back, so what you approve is exactly what runs.
        /// </summary>
        private void BuildConfirmCard()
        {
            _confirmGroup = Group("ConfirmCard", _canvas.transform);
            var card = AddImage(_confirmGroup.transform, "Card", new Vector2(820, 380), new Vector2(0, 10), Elevated);
            var outline = card.gameObject.AddComponent<Outline>();
            outline.effectColor = Accent;
            outline.effectDistance = new Vector2(2f, -2f);

            _confirmTitle = AddText(_confirmGroup.transform, "KALIV VIL UDFØRE EN HANDLING", 17, Accent,
                TextAnchor.MiddleLeft, new Vector2(740, 40), new Vector2(0, 160), FontStyle.Bold);
            _confirmBody = AddText(_confirmGroup.transform, "", 18, TextMain, TextAnchor.UpperLeft,
                new Vector2(740, 190), new Vector2(0, 40));
            _confirmBody.horizontalOverflow = HorizontalWrapMode.Wrap;
            _confirmBody.supportRichText = true;
            _confirmExpiry = AddText(_confirmGroup.transform, "", 14, Muted, TextAnchor.MiddleLeft,
                new Vector2(740, 30), new Vector2(0, -78));
            _approveButton = AddButton(_confirmGroup.transform, "GODKEND", new Vector2(250, 60), new Vector2(-150, -130),
                Accent, () => _app.AnswerConfirmation(true));
            _denyButton = AddButton(_confirmGroup.transform, "AFVIS", new Vector2(250, 60), new Vector2(150, -130),
                Danger, () => _app.AnswerConfirmation(false));
            _confirmGroup.SetActive(false);
        }

        private void BuildMediaBrowser()
        {
            _mediaGroup = Group("MediaBrowser", _canvas.transform);
            AddImage(_mediaGroup.transform, "Backdrop", new Vector2(1200, 760), Vector2.zero, CanvasBg);
            AddText(_mediaGroup.transform, "MEDIER", 18, Accent, TextAnchor.MiddleLeft,
                new Vector2(1080, 40), new Vector2(0, 330), FontStyle.Bold);
            _mediaStatus = AddText(_mediaGroup.transform, "", 16, Muted, TextAnchor.MiddleLeft,
                new Vector2(1080, 40), new Vector2(0, 290));
            _mediaStatus.horizontalOverflow = HorizontalWrapMode.Wrap;

            for (int i = 0; i < 6; i++)
            {
                int index = i;
                float y = 220 - i * 80;
                var root = AddButton(_mediaGroup.transform, "", new Vector2(1080, 70), new Vector2(0, y),
                    Surface, () => OnMediaRow(index));
                var thumbGo = new GameObject("Thumb", typeof(RawImage));
                thumbGo.transform.SetParent(root.transform, false);
                var thumb = thumbGo.GetComponent<RawImage>();
                thumb.rectTransform.sizeDelta = new Vector2(104, 58);
                thumb.rectTransform.anchoredPosition = new Vector2(-480, 0);
                thumb.color = Border;
                thumb.raycastTarget = false;
                var label = root.GetComponentInChildren<Text>();
                label.alignment = TextAnchor.MiddleLeft;
                label.fontStyle = FontStyle.Normal;
                label.rectTransform.sizeDelta = new Vector2(920, 64);
                label.rectTransform.anchoredPosition = new Vector2(70, 0);
                _mediaRows.Add(new MediaRow { Root = root.gameObject, Label = label, Thumb = thumb });
                root.gameObject.SetActive(false);
            }

            _mediaMore = AddButton(_mediaGroup.transform, "FLERE", new Vector2(200, 52), new Vector2(-150, -300),
                Elevated, () => _app.MediaNextPage());
            AddButton(_mediaGroup.transform, "LUK", new Vector2(200, 52), new Vector2(150, -300),
                Elevated, () => ShowMediaBrowser(false));
            _mediaGroup.SetActive(false);
        }

        /// <summary>A floating strip under the panel while a video is open.</summary>
        private void BuildTransport()
        {
            _transportGroup = Group("Transport", _canvas.transform);
            AddImage(_transportGroup.transform, "Strip", new Vector2(1200, 90), new Vector2(0, -440), CanvasBg);
            _transportInfo = AddText(_transportGroup.transform, "", 14, Muted, TextAnchor.MiddleLeft,
                new Vector2(300, 60), new Vector2(-430, -440));
            AddButton(_transportGroup.transform, "−10s", new Vector2(110, 52), new Vector2(-215, -440), Elevated, () => _app.MediaSeek(-10));
            var play = AddButton(_transportGroup.transform, "PAUSE", new Vector2(140, 52), new Vector2(-85, -440), Accent, () => _app.MediaTogglePlay());
            _transportPlay = play.GetComponentInChildren<Text>();
            AddButton(_transportGroup.transform, "+10s", new Vector2(110, 52), new Vector2(45, -440), Elevated, () => _app.MediaSeek(10));
            AddButton(_transportGroup.transform, "FORMAT", new Vector2(130, 52), new Vector2(180, -440), Elevated, () => _app.MediaCycleFormat());
            AddButton(_transportGroup.transform, "CENTRER", new Vector2(130, 52), new Vector2(320, -440), Elevated, () => _app.MediaRecenter());
            AddButton(_transportGroup.transform, "LUK", new Vector2(110, 52), new Vector2(450, -440), Danger, () => _app.CloseMedia());
            _transportGroup.SetActive(false);
        }

        // =====================================================================================
        // State in
        // =====================================================================================

        public void SetConnectionDefaults(string baseUrl, string code)
        {
            if (_url != null) _url.text = baseUrl ?? "";
            if (_code != null) _code.text = code ?? "";
        }

        private bool _paired;
        private bool _mediaOpen;
        private bool _confirmOpen;

        public void SetPaired(bool paired)
        {
            _paired = paired;
            if (!paired) { _mediaOpen = false; _confirmOpen = false; _rigOpen = false; }
            RefreshGroups();
        }

        /// <summary>
        /// Exactly one interactive layer at a time. The pointer hits BoxColliders by physics
        /// raycast and every group sits in the same plane, so an overlay drawn "on top" of the
        /// chat would still have the chat's buttons under it at the same depth — and the ray
        /// could click a button you cannot see. Hiding the layer underneath is the only
        /// arrangement where what you see is what you click.
        /// </summary>
        private void RefreshGroups()
        {
            // The keyboard sits above everything: it is always opened FROM a field on screen and
            // closes back to it. A confirmation card that arrives meanwhile waits underneath.
            bool kb = _keyboardOpen;
            _keyboardGroup?.SetActive(kb);
            _pairGroup?.SetActive(!_paired && !kb);
            _confirmGroup?.SetActive(_paired && _confirmOpen && !kb);
            bool overlay = _confirmOpen || kb;
            _rigGroup?.SetActive(_paired && _rigOpen && !overlay);
            _mediaGroup?.SetActive(_paired && _mediaOpen && !_rigOpen && !overlay);
            _chatGroup?.SetActive(_paired && !_mediaOpen && !_rigOpen && !overlay);
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
        }

        public void SetModels(List<string> models, string selected)
        {
            _models.Clear();
            if (models != null) _models.AddRange(models);
            _modelIndex = Math.Max(0, _models.IndexOf(selected));
            RefreshModelLabel();
        }

        public void SetModes(bool rag, bool tools, string ragSource = null)
        {
            string src = string.IsNullOrEmpty(ragSource) ? "TIL"
                : (ragSource.Length > 10 ? ragSource.Substring(0, 9) + "…" : ragSource);
            if (_ragLabel != null) _ragLabel.text = rag ? "VIDEN · " + src : "VIDEN · FRA";
            if (_ragImage != null) _ragImage.color = rag ? Ok : Elevated;
            if (_toolsLabel != null) _toolsLabel.text = tools ? "VÆRKTØJER · TIL" : "VÆRKTØJER · FRA";
            if (_toolsImage != null) _toolsImage.color = tools ? Ok : Elevated;
        }

        public void SetStopAvailable(bool available)
        {
            if (_stopButton != null) _stopButton.gameObject.SetActive(available);
        }

        public void SetRetryAvailable(bool available)
        {
            if (_retryButton != null) _retryButton.gameObject.SetActive(available);
        }

        /// <summary>The talk button doubles as the recording indicator.</summary>
        public void SetVoiceState(bool recording, float level, float seconds, bool enabled)
        {
            if (_talkButton != null) _talkButton.interactable = enabled || recording;
            if (_talkLabel != null)
                _talkLabel.text = recording ? $"SEND TALE {Mathf.FloorToInt(seconds)}s" : "TAL";
            if (_talkImage != null)
                _talkImage.color = recording ? Color.Lerp(Danger, Accent, Mathf.Clamp01(level * 3f)) : Elevated;
        }

        // ---- transcript -------------------------------------------------------------------

        public void BindConversation(KalivConversation conversation)
        {
            if (_conversation != null) _conversation.Changed -= MarkTranscriptDirty;
            _conversation = conversation;
            if (_conversation != null) _conversation.Changed += MarkTranscriptDirty;
            MarkTranscriptDirty();
        }

        /// <summary>A streaming caret, or null. Shown after the last message while it grows.</summary>
        public void SetLiveSuffix(string suffix)
        {
            _liveSuffix = suffix;
            MarkTranscriptDirty();
        }

        /// <summary>
        /// Called per token. The Text component is NOT rebuilt here: a token arrives every few
        /// tens of milliseconds and each assignment re-lays out the whole transcript, which is
        /// real work on a Quest. LateUpdate coalesces it to at most one rebuild per frame.
        /// </summary>
        public void MarkTranscriptDirty() => _transcriptDirty = true;

        private void LateUpdate()
        {
            if (_confirmGroup != null && _confirmGroup.activeSelf && _confirmDeadline > 0f)
            {
                float left = _confirmDeadline - Time.realtimeSinceStartup;
                _confirmExpiry.text = left > 0
                    ? $"Udløber om {Mathf.CeilToInt(left)} s — intet sker, hvis du ikke svarer."
                    : "Forslaget er udløbet — intet blev udført.";
                if (left <= 0) { _approveButton.interactable = false; }
            }

            if (!_transcriptDirty || _transcript == null) return;
            _transcriptDirty = false;
            _transcript.text = RenderTranscript();
        }

        private string RenderTranscript()
        {
            if (_conversation == null || _conversation.Count == 0)
                return $"<color={MutedHex}>Kaliv VR er forbundet. Skriv eller tal nedenfor.</color>";

            // Build from the newest message backwards until the window is full, so a long
            // conversation costs the same as a short one.
            var blocks = new List<string>();
            int total = 0;
            var msgs = _conversation.Messages;
            for (int i = msgs.Count - 1; i >= 0 && total < TranscriptWindow; i--)
            {
                string block = RenderMessage(msgs[i], i == msgs.Count - 1);
                blocks.Add(block);
                total += block.Length;
            }
            blocks.Reverse();
            return string.Join("\n\n", blocks);
        }

        private string RenderMessage(KalivMessage m, bool isLast)
        {
            var sb = new StringBuilder();
            bool user = m.Role == "user";
            // When the rig has a Person Profile selected, say who answered — as Android does.
            string who = user ? "DIG" : string.IsNullOrEmpty(m.Person) ? "KALIV" : "KALIV · " + m.Person.ToUpperInvariant();
            sb.Append("<b><color=").Append(AccentHex).Append('>').Append(who);
            if (m.Spoken) sb.Append(" · tale");
            sb.Append("</color></b>\n");

            string text = m.Text ?? "";
            if (m.Error)
                sb.Append("<color=").Append(DangerHex).Append('>').Append(Escape(text)).Append("</color>");
            else
                sb.Append(Escape(text));

            if (isLast && !string.IsNullOrEmpty(_liveSuffix)) sb.Append(_liveSuffix);
            if (m.Stopped) sb.Append("\n<color=").Append(MutedHex).Append(">— stoppet</color>");
            if (!string.IsNullOrEmpty(m.Tool))
                sb.Append("\n<color=").Append(OkHex).Append(">værktøj · ").Append(Escape(m.Tool)).Append("</color>");
            if (m.Sources.Count > 0)
                sb.Append("\n<color=").Append(MutedHex).Append(">kilder · ")
                  .Append(Escape(string.Join(" · ", m.Sources))).Append("</color>");
            return sb.ToString();
        }

        /// <summary>
        /// Unity's Text has no escape for rich text. A zero-width space after '<' stops the
        /// model's own output (say, "<b>" in a code answer) from being read as markup.
        /// </summary>
        private static string Escape(string s) =>
            string.IsNullOrEmpty(s) ? "" : s.Replace("<", "<​");

        // ---- confirmation -----------------------------------------------------------------

        public void ShowConfirmation(KalivToolTurn turn)
        {
            if (_confirmGroup == null || turn == null) return;
            var sb = new StringBuilder();
            sb.Append("<b>").Append(Escape(turn.Tool ?? "værktøj")).Append("</b>");
            if (!string.IsNullOrEmpty(turn.Risk) || !string.IsNullOrEmpty(turn.Impact))
            {
                sb.Append("   <color=").Append(DangerHex).Append('>');
                sb.Append(Escape(turn.Impact ?? turn.Risk));
                sb.Append("</color>");
            }
            sb.Append("\n\n").Append(Escape(turn.Summary ?? "Riggen sendte ingen beskrivelse af handlingen."));
            _confirmBody.text = sb.ToString();
            _confirmDeadline = turn.ExpiresInSeconds > 0 ? Time.realtimeSinceStartup + turn.ExpiresInSeconds : 0f;
            _confirmExpiry.text = _confirmDeadline > 0 ? "" : "Intet sker, hvis du ikke svarer.";
            SetConfirmationBusy(false);
            _confirmOpen = true;
            RefreshGroups();
            _confirmGroup.transform.SetAsLastSibling();
        }

        public void SetConfirmationBusy(bool busy)
        {
            if (_approveButton != null) _approveButton.interactable = !busy;
            if (_denyButton != null) _denyButton.interactable = !busy;
        }

        public void HideConfirmation()
        {
            _confirmDeadline = 0f;
            _confirmOpen = false;
            RefreshGroups();
        }

        public bool ConfirmationOpen => _confirmOpen;

        // ---- media ------------------------------------------------------------------------

        public void ShowMediaBrowser(bool show)
        {
            if (_mediaGroup == null) return;
            _mediaOpen = show;
            RefreshGroups();
            if (show) _mediaGroup.transform.SetAsLastSibling();
        }

        public void SetMediaStatus(string text, bool error)
        {
            if (_mediaStatus == null) return;
            _mediaStatus.text = text ?? "";
            _mediaStatus.color = error ? Danger : Muted;
        }

        public void SetMediaItems(IReadOnlyList<KalivMediaItem> items, bool hasMore)
        {
            for (int i = 0; i < _mediaRows.Count; i++)
            {
                var row = _mediaRows[i];
                row.Item = items != null && i < items.Count ? items[i] : null;
                row.Root.SetActive(row.Item != null);
                row.Thumb.texture = null;
                row.Thumb.color = Border;
                if (row.Item != null) row.Label.text = DescribeMedia(row.Item);
            }
            if (_mediaMore != null) _mediaMore.gameObject.SetActive(hasMore);
        }

        public void SetMediaThumbnail(string itemId, Texture2D texture)
        {
            foreach (var row in _mediaRows)
            {
                if (row.Item == null || row.Item.Id != itemId) continue;
                row.Thumb.texture = texture;
                row.Thumb.color = Color.white;
            }
        }

        private static string DescribeMedia(KalivMediaItem item)
        {
            var sb = new StringBuilder();
            sb.Append(item.Kind == KalivMediaKind.Video ? "VIDEO" : "BILLEDE");
            sb.Append("  ·  ").Append(item.CreatedAtUtc.ToLocalTime().ToString("dd-MM-yyyy HH:mm"));
            if (item.DurationSeconds != null)
            {
                var t = TimeSpan.FromSeconds(item.DurationSeconds.Value);
                sb.Append("  ·  ").Append(t.TotalHours >= 1 ? t.ToString(@"h\:mm\:ss") : t.ToString(@"m\:ss"));
            }
            sb.Append("  ·  ").Append(FormatSize(item.SizeBytes));
            string hint = item.FormatHint;
            sb.Append("  ·  ").Append(hint ?? "format ikke understøttet");
            return sb.ToString();
        }

        private static string FormatSize(long bytes)
        {
            if (bytes >= 1L << 30) return (bytes / (double)(1L << 30)).ToString("0.0") + " GB";
            if (bytes >= 1L << 20) return (bytes / (double)(1L << 20)).ToString("0") + " MB";
            return Math.Max(1, bytes / 1024) + " KB";
        }

        private void OnMediaRow(int index)
        {
            if (index < 0 || index >= _mediaRows.Count) return;
            var item = _mediaRows[index].Item;
            if (item != null) _app.PlayMedia(item);
        }

        public void ShowTransport(bool show)
        {
            _transportGroup?.SetActive(show);
        }

        public void SetTransportInfo(string info, bool playing)
        {
            if (_transportInfo != null) _transportInfo.text = info ?? "";
            if (_transportPlay != null) _transportPlay.text = playing ? "PAUSE" : "AFSPIL";
        }

        // =====================================================================================
        // Helpers
        // =====================================================================================

        private void CycleModel()
        {
            if (_models.Count == 0) { _app.RefreshModels(); return; }
            _modelIndex = (_modelIndex + 1) % _models.Count;
            _app.SelectModel(_models[_modelIndex]);
            RefreshModelLabel();
        }

        private void RefreshModelLabel()
        {
            if (_modelLabel == null) return;
            _modelLabel.text = _models.Count == 0 ? "MODEL · ingen" : "MODEL · " + _models[_modelIndex];
        }

        private static GameObject Group(string name, Transform parent)
        {
            var go = new GameObject(name, typeof(RectTransform));
            go.transform.SetParent(parent, false);
            return go;
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
            var root = new GameObject(string.IsNullOrEmpty(label) ? "Button" : label,
                typeof(Image), typeof(Button), typeof(BoxCollider));
            root.transform.SetParent(parent, false);
            var image = root.GetComponent<Image>();
            image.color = color;
            var rt = image.rectTransform;
            rt.sizeDelta = size;
            rt.anchoredPosition = pos;

            AddText(root.transform, label, 15, color == Accent ? OnAccent : TextMain,
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

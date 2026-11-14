using System;
using System.Collections.Generic;
using SkyPlayer.Engine;
using UnityEngine;

namespace Kaliv.VR
{
    /// <summary>
    /// STASH in the media browser: SkyPlayer's library — order pills, studio and category,
    /// search, ROULETTE, resume — played in Kaliv VR's own engine, with RUM (the AR background
    /// key) on top.
    ///
    /// The Stash server is a DIFFERENT MACHINE from the rig. Nothing here uses the rig's
    /// address or token: the companion is found with its own UDP discovery (FIND STASH, the
    /// same probe as SkyPlayer's FIND SERVER) and its address is kept separately. The rig can
    /// be down while Stash works, and the other way round.
    /// </summary>
    public sealed partial class KalivVrApp
    {
        private const string StashUrlKey = "kaliv.vr.stash.url";
        private const string KeyPrefsKey = "kaliv.vr.key";

        private KalivStashClient _stash;
        private bool _stashSource;
        private KalivStashOrder _stashOrder = KalivStashOrder.Newest;
        private string _stashQuery;
        private KalivStashFacet _stashStudio, _stashTag;
        private int _stashPage = 1;
        private string _stashSeed;
        private int _stashCount;
        private KalivStashScene _stashPlaying;
        private float _stashProgressTimer;
        private readonly List<Texture2D> _stashThumbs = new List<Texture2D>();

        private BackgroundKeySettings _key = BackgroundKeySettings.Default;
        private bool _pipetActive;

        private static readonly string[] KeyModeLabels =
            { "AUTO BG", "SORT BG", "HVID BG", "GRØN BG", "GRÅ/BLÅ", "RØD BG", "LILLA BG", "PIPET" };
        private static readonly string[] DetailLabels = { "HUL-FIX FRA", "HUL-FIX LET", "HUL-FIX", "HUL-FIX STÆRK" };

        private void InitializeStash()
        {
            _stash = gameObject.AddComponent<KalivStashClient>();
            _stash.BaseUrl = PlayerPrefs.GetString(StashUrlKey, "");
            _stashSource = PlayerPrefs.GetInt(MediaSourceKey, 0) == 1;
            LoadKey();
        }

        // =====================================================================================
        // Browsing
        // =====================================================================================

        public void MediaShowStash()
        {
            _stashSource = true;
            PlayerPrefs.SetInt(MediaSourceKey, 1);
            PlayerPrefs.Save();
            _panel.SetMediaSource(true);
            UpdateStashControls();
            if (string.IsNullOrWhiteSpace(_stash.BaseUrl)) { StashFind(); return; }
            StashLoad(1);
        }

        /// <summary>FIND STASH: the companion answers SkyPlayer's own UDP probe.</summary>
        public void StashFind()
        {
            _panel.SetMediaRows(new List<KalivVrPanel.MediaRowData>(), false, false);
            _panel.SetMediaStatus("Leder efter Stash-serveren på netværket …", false);
            StartCoroutine(_stash.Discover(4f, url =>
            {
                if (url == null)
                {
                    _panel.SetMediaStatus(
                        "Ingen Stash-server svarede. Kører SkyPlayer-companion på Stash-serveren, og er UDP 8098 åben i dens firewall?", true);
                    return;
                }
                _stash.BaseUrl = url;
                PlayerPrefs.SetString(StashUrlKey, url);
                PlayerPrefs.Save();
                _panel.SetMediaStatus($"Stash-server fundet: {url}", false);
                StashLoad(1);
            }));
        }

        public void StashCycleOrder()
        {
            _stashOrder = (KalivStashOrder)(((int)_stashOrder + 1) % KalivStash.OrderLabels.Length);
            UpdateStashControls();
            StashLoad(1);
        }

        public void StashSearch()
        {
            _panel.RequestText("SØG I STASH", _stashQuery ?? "", 120, "SØG", text =>
            {
                _stashQuery = string.IsNullOrWhiteSpace(text) ? null : text.Trim();
                UpdateStashControls();
                StashLoad(1);
            });
        }

        /// <summary>
        /// Pick a studio or a category. Counts are scoped to the other filter, so a choice can
        /// never lead to an empty list — SkyPlayer's faceted filter, served by the companion.
        /// </summary>
        public void StashPickFacet(bool studios)
        {
            string scope = studios ? _stashTag?.Id : _stashStudio?.Id;
            _panel.SetMediaStatus(studios ? "Henter studier …" : "Henter kategorier …", false);
            StartCoroutine(_stash.Facets(studios, scope, facets =>
            {
                _facetList = facets;
                _facetStudios = studios;
                ShowFacetPage(0);
            }, error => _panel.SetMediaStatus(error, true)));
        }

        private List<KalivStashFacet> _facetList;
        private bool _facetStudios;
        private int _facetPage;

        private void ShowFacetPage(int page)
        {
            _facetPage = Math.Max(0, page);
            const int per = KalivStash.PageSize - 1;   // first row is always "all"
            var rows = new List<KalivVrPanel.MediaRowData>
            {
                new KalivVrPanel.MediaRowData
                {
                    Label = _facetStudios ? "ALLE STUDIER" : "ALLE KATEGORIER",
                    OnClick = () => ChooseFacet(null),
                },
            };
            int start = _facetPage * per;
            for (int i = start; i < Math.Min(_facetList.Count, start + per); i++)
            {
                var f = _facetList[i];
                rows.Add(new KalivVrPanel.MediaRowData
                {
                    Label = $"{f.Name}  ·  {f.SceneCount} scener",
                    OnClick = () => ChooseFacet(f),
                });
            }
            _facetPicking = true;
            _panel.SetMediaRows(rows, _facetPage > 0, start + per < _facetList.Count);
            _panel.SetMediaStatus(_facetStudios ? "Vælg et studie." : "Vælg en kategori.", false);
        }

        private bool _facetPicking;

        private void ChooseFacet(KalivStashFacet f)
        {
            _facetPicking = false;
            if (_facetStudios) _stashStudio = f; else _stashTag = f;
            UpdateStashControls();
            StashLoad(1);
        }

        private void UpdateStashControls() =>
            _panel.SetStashControls(KalivStash.OrderLabels[(int)_stashOrder], _stashStudio?.Name, _stashTag?.Name, _stashQuery);

        /// <summary>FORRIGE/FLERE: through the studio/category list while it is shown, else through scenes.</summary>
        private void StashPageStep(int step)
        {
            if (_facetPicking) { ShowFacetPage(_facetPage + step); return; }
            if (_stashPage + step >= 1) StashLoad(_stashPage + step);
        }

        /// <summary>Load one page of scenes. A new shuffle per first page; the same seed while paging.</summary>
        private void StashLoad(int page)
        {
            _facetPicking = false;
            if (page <= 1) _stashSeed = UnityEngine.Random.Range(1, 99_999_999).ToString();
            _stashPage = Math.Max(1, page);
            _panel.SetMediaStatus("Henter fra Stash …", false);

            StartCoroutine(_stash.Scenes(_stashOrder, _stashQuery, _stashStudio?.Id, _stashTag?.Id, _stashPage, _stashSeed,
                result =>
                {
                    ReleaseStashThumbs();
                    _stashCount = result.Count;
                    var rows = new List<KalivVrPanel.MediaRowData>();
                    foreach (var s in result.Scenes)
                    {
                        var scene = s;
                        rows.Add(new KalivVrPanel.MediaRowData
                        {
                            Key = "stash:" + scene.Id,
                            Label = KalivStash.Describe(scene),
                            OnClick = () => StashPlay(scene),
                        });
                    }
                    bool more = _stashPage * KalivStash.PageSize < _stashCount;
                    _panel.SetMediaRows(rows, _stashPage > 1, more);
                    int pages = Math.Max(1, (_stashCount + KalivStash.PageSize - 1) / KalivStash.PageSize);
                    _panel.SetMediaStatus(_stashCount == 0
                        ? "Ingen scener matcher filtrene."
                        : $"{_stashCount} scener  ·  side {_stashPage} af {pages}", false);

                    foreach (var s in result.Scenes)
                    {
                        string key = "stash:" + s.Id;
                        StartCoroutine(_stash.Thumbnail(s.ThumbnailUrl, tex =>
                        {
                            _stashThumbs.Add(tex);
                            _panel.SetMediaThumbnail(key, tex);
                        }));
                    }
                },
                error => _panel.SetMediaStatus(error, true)));
        }

        /// <summary>Thumbnails of the last page are freed before the next: a headset's RAM is not a desktop's.</summary>
        private void ReleaseStashThumbs()
        {
            foreach (var t in _stashThumbs) if (t != null) Destroy(t);
            _stashThumbs.Clear();
        }

        /// <summary>ROULETTE: just start something, within the active filters.</summary>
        public void StashRoulette()
        {
            _panel.SetMediaStatus("Roulette …", false);
            StartCoroutine(_stash.Random(_stashQuery, _stashStudio?.Id, _stashTag?.Id,
                StashPlay, error => _panel.SetMediaStatus(error, true)));
        }

        // =====================================================================================
        // Playback, resume
        // =====================================================================================

        /// <summary>
        /// Stream straight from the companion: unlike the rig's gallery it needs no token, so
        /// the engine can open the URL itself — no download first. Resumes where it was left.
        /// </summary>
        private void StashPlay(KalivStashScene scene)
        {
            if (scene == null) return;
            CloseMedia();
            _stashPlaying = scene;
            _stashProgressTimer = 0f;
            double resume = KalivStash.ResumeFrom(scene);
            _mediaFormatIndex = Array.IndexOf(SkyPlayerFormats, scene.FormatHint);
            _renderEngine.OpenMedia(scene.StreamUrl, scene.FormatHint, resume);
            _renderEngine.SetMediaScreenAsGazeTarget(true);
            _mediaOpen = true;
            _panel.ShowMediaBrowser(false);
            _panel.ShowTransport(true);
            ApplyKey();
            UpdateTransport();
            _panel.SetStatus(resume > 0 ? $"Fortsætter {scene.Title} fra {Clock(resume)}" : scene.Title, false);
        }

        private void StashProgressTick()
        {
            if (_stashPlaying == null) return;
            if ((_stashProgressTimer += Time.unscaledDeltaTime) < 15f) return;
            _stashProgressTimer = 0f;
            StashReportProgress(finished: false);
        }

        /// <summary>Resume is local-first on the companion — nothing is written to Stash itself.</summary>
        private void StashReportProgress(bool finished)
        {
            var scene = _stashPlaying;
            if (scene == null || _stash == null) return;
            double pos = _renderEngine.MediaTime, len = _renderEngine.MediaLength;
            if (!finished && pos < 5) return;   // nothing worth remembering yet
            StartCoroutine(_stash.Progress(scene.Id, finished ? 0 : pos, len, finished));
        }

        // =====================================================================================
        // RUM — the AR background key
        // =====================================================================================

        public void KeyToggle()
        {
            _key.Enabled = !_key.Enabled;
            if (_key.Enabled && !_renderEngine.MediaIsImmersive)
                _panel.SetStatus("RUM virker kun på 180°/360°-video — skift FORMAT, hvis den er forkert.", true);
            ApplyKey();
        }

        public void KeyAdjust(int direction)
        {
            _key.Threshold = Mathf.Clamp(_key.Threshold + direction * 0.02f, 0.02f, 0.95f);
            ApplyKey();
        }

        public void KeyCycleMode()
        {
            _key.Mode = (_key.Mode + 1) % KeyModeLabels.Length;
            _pipetActive = _key.Mode == 7;
            ApplyKey();
        }

        public void KeyCycleDetail()
        {
            _key.DetailMode = (_key.DetailMode + 1) % DetailLabels.Length;
            ApplyKey();
        }

        /// <summary>
        /// PIPET: take the colour where you are looking and key exactly that. A green screen is
        /// easy because it is one colour; picking the wall's colour makes any backdrop that case.
        /// </summary>
        public void KeyPipette()
        {
            if (!_renderEngine.TrySampleMediaKeyColor(out Color c))
            {
                _panel.SetStatus("PIPET: kig på baggrunden i en 180°/360°-video, og tryk igen.", true);
                return;
            }
            _key.KeyColor = c;
            _key.Mode = 7;
            _key.Enabled = true;
            _pipetActive = true;
            ApplyKey();
            _panel.SetStatus("PIPET: farven er valgt — juster med KEY − / KEY +.", false);
        }

        private void ApplyKey()
        {
            _renderEngine.ApplyMediaBackgroundKey(_key);
            _panel.SetKeyState(_key.Enabled, KeyModeLabels[Mathf.Clamp(_key.Mode, 0, 7)], _key.Threshold,
                DetailLabels[Mathf.Clamp(_key.DetailMode, 0, 3)], _pipetActive, _renderEngine.MediaIsImmersive);
            SaveKey();
        }

        private void SaveKey()
        {
            PlayerPrefs.SetString(KeyPrefsKey, KalivJson.Serialize(new Dictionary<string, object>
            {
                ["threshold"] = (double)_key.Threshold,
                ["mode"] = (long)_key.Mode,
                ["detail"] = (long)_key.DetailMode,
                ["spill"] = (long)_key.SpillMode,
                ["r"] = (double)_key.KeyColor.r, ["g"] = (double)_key.KeyColor.g, ["b"] = (double)_key.KeyColor.b,
            }));
        }

        /// <summary>Key settings survive a restart; RUM itself always starts off, so a video never opens keyed by surprise.</summary>
        private void LoadKey()
        {
            var o = KalivJson.TryParseObject(PlayerPrefs.GetString(KeyPrefsKey, ""));
            if (o == null) return;
            _key.Threshold = Mathf.Clamp((float)KalivJson.Num(o, "threshold", _key.Threshold), 0.02f, 0.95f);
            _key.Mode = Mathf.Clamp(KalivJson.Int(o, "mode", _key.Mode), 0, 7);
            _key.DetailMode = Mathf.Clamp(KalivJson.Int(o, "detail", _key.DetailMode), 0, 3);
            _key.SpillMode = Mathf.Clamp(KalivJson.Int(o, "spill", _key.SpillMode), 0, 3);
            _key.KeyColor = new Color((float)KalivJson.Num(o, "r", _key.KeyColor.r),
                (float)KalivJson.Num(o, "g", _key.KeyColor.g), (float)KalivJson.Num(o, "b", _key.KeyColor.b), 1f);
            _key.Enabled = false;
            _pipetActive = _key.Mode == 7;
        }
    }
}

using System;
using System.Collections.Generic;
using System.Text;

namespace Kaliv.VR
{
    /// <summary>One Stash scene, as the SkyPlayer companion reports it.</summary>
    public sealed class KalivStashScene
    {
        public string Id;
        public string Title;
        public int DurationSeconds;
        public int ResumeSeconds;
        public bool Favorite;
        public bool Watched;
        public string Studio;
        public string ThumbnailUrl;
        public string StreamUrl;
        /// <summary>SkyPlayer-Engine's own vocabulary (FLAT, VR180_SBS …) — the companion already speaks it.</summary>
        public string FormatHint;
        public int Width;
        public int Height;

        public bool IsImmersive => FormatHint != null && (FormatHint.StartsWith("VR180") || FormatHint.StartsWith("VR360") || FormatHint == "OU_TB");
    }

    /// <summary>A studio or a tag: the companion uses one shape for both.</summary>
    public sealed class KalivStashFacet
    {
        public string Id;
        public string Name;
        public int SceneCount;
    }

    public sealed class KalivStashPage
    {
        public List<KalivStashScene> Scenes = new List<KalivStashScene>();
        public int Count;
    }

    /// <summary>The library's sort/filter pills, exactly SkyPlayer's (LibraryScreen.cs).</summary>
    public enum KalivStashOrder { All, Newest, Favorites, Vr, Random }

    /// <summary>
    /// The Stash side of Kaliv VR: the SkyPlayer companion's HTTP API, read with the same
    /// field names SkyPlayer's Models.cs uses, so the two clients cannot drift apart.
    ///
    /// The companion runs on the STASH SERVER, a different machine from the rig. It has no
    /// pairing and no token: it is a LAN service, found by its own UDP discovery on 8098
    /// (SkyPlayer's FIND SERVER), and nothing about it touches the rig.
    /// </summary>
    public static class KalivStash
    {
        public const int DiscoveryPort = 8098;
        public const string DiscoveryProbe = "SKYPLAYER_DISCOVER";
        public const string ServiceName = "stash-skyplayer-companion";
        public const int DefaultPort = 8099;
        public const int PageSize = 6;   // what the media browser shows at once

        public static readonly string[] OrderLabels = { "ALLE", "SENESTE", "FAVORITTER", "VR", "TILFÆLDIG" };

        public static string FilterFor(KalivStashOrder o) =>
            o == KalivStashOrder.Favorites ? "favorites" : o == KalivStashOrder.Vr ? "vr" : "";

        public static string SortFor(KalivStashOrder o) =>
            o == KalivStashOrder.Newest ? "created_at" : o == KalivStashOrder.Random ? "random" : "";

        /// <summary>
        /// GET /api/v1/scenes with SkyPlayer's parameters. A random order needs the SAME seed on
        /// every page — a fresh shuffle per request would repeat scenes on page two and hide others.
        /// </summary>
        public static string ScenesUrl(string baseUrl, KalivStashOrder order, string query, string studioId,
                                       string tagId, int page, string seed)
        {
            var sb = new StringBuilder(Normalize(baseUrl));
            sb.Append("/api/v1/scenes?per_page=").Append(PageSize).Append("&page=").Append(Math.Max(1, page));
            string filter = FilterFor(order), sort = SortFor(order);
            if (filter.Length > 0) sb.Append("&filter=").Append(Uri.EscapeDataString(filter));
            if (!string.IsNullOrWhiteSpace(query)) sb.Append("&q=").Append(Uri.EscapeDataString(query.Trim()));
            if (sort.Length > 0) sb.Append("&sort=").Append(sort).Append("&direction=desc");
            if (!string.IsNullOrEmpty(studioId)) sb.Append("&studio=").Append(Uri.EscapeDataString(studioId));
            if (!string.IsNullOrEmpty(tagId)) sb.Append("&tag=").Append(Uri.EscapeDataString(tagId));
            if (order == KalivStashOrder.Random && !string.IsNullOrEmpty(seed))
                sb.Append("&seed=").Append(Uri.EscapeDataString(seed));
            return sb.ToString();
        }

        /// <summary>GET /api/v1/random — ROULETTE: one scene within the active filters.</summary>
        public static string RandomUrl(string baseUrl, string query, string studioId, string tagId)
        {
            var parts = new List<string>();
            if (!string.IsNullOrWhiteSpace(query)) parts.Add("q=" + Uri.EscapeDataString(query.Trim()));
            if (!string.IsNullOrEmpty(studioId)) parts.Add("studio=" + Uri.EscapeDataString(studioId));
            if (!string.IsNullOrEmpty(tagId)) parts.Add("tag=" + Uri.EscapeDataString(tagId));
            return Normalize(baseUrl) + "/api/v1/random" + (parts.Count > 0 ? "?" + string.Join("&", parts) : "");
        }

        /// <summary>Studio counts are scoped to the active tag and vice versa, so a choice never leads to nothing.</summary>
        public static string FacetsUrl(string baseUrl, bool studios, string scopeId)
        {
            string url = Normalize(baseUrl) + (studios ? "/api/v1/studios" : "/api/v1/tags");
            if (!string.IsNullOrEmpty(scopeId)) url += (studios ? "?tag=" : "?studio=") + Uri.EscapeDataString(scopeId);
            return url;
        }

        public static KalivStashPage ParseScenes(string body)
        {
            var o = KalivJson.TryParseObject(body);
            var page = new KalivStashPage { Count = KalivJson.Int(o, "count") };
            var arr = KalivJson.Arr(o, "scenes");
            if (arr == null) return page;
            foreach (var item in arr)
            {
                var s = ParseScene(item as Dictionary<string, object>);
                if (s != null) page.Scenes.Add(s);
            }
            return page;
        }

        /// <summary>Null when the scene has nothing to play: no id or no stream address.</summary>
        public static KalivStashScene ParseScene(Dictionary<string, object> s)
        {
            string id = KalivJson.Str(s, "id");
            string stream = KalivJson.Str(s, "streamUrl");
            if (id.Length == 0 || stream.Length == 0) return null;
            var video = KalivJson.Obj(s, "video");
            string hint = KalivJson.Str(video, "formatHint");
            string title = KalivJson.Str(s, "title");
            return new KalivStashScene
            {
                Id = id,
                Title = title.Length > 0 ? title : "Scene " + id,
                DurationSeconds = KalivJson.Int(s, "duration"),
                ResumeSeconds = KalivJson.Int(s, "resumeTime"),
                Favorite = KalivJson.Bool(s, "favorite"),
                Watched = KalivJson.Bool(s, "watched"),
                Studio = NullIfBlank(KalivJson.Str(s, "studio")),
                ThumbnailUrl = NullIfBlank(KalivJson.Str(s, "thumbnailUrl")),
                StreamUrl = stream,
                FormatHint = hint.Length > 0 ? hint : "FLAT",
                Width = KalivJson.Int(video, "width"),
                Height = KalivJson.Int(video, "height"),
            };
        }

        public static KalivStashScene ParseRandom(string body) =>
            ParseScene(KalivJson.Obj(KalivJson.TryParseObject(body), "scene"));

        public static List<KalivStashFacet> ParseFacets(string body, bool studios)
        {
            var list = new List<KalivStashFacet>();
            var arr = KalivJson.Arr(KalivJson.TryParseObject(body), studios ? "studios" : "tags");
            if (arr == null) return list;
            foreach (var item in arr)
            {
                var f = item as Dictionary<string, object>;
                string id = KalivJson.Str(f, "id");
                if (id.Length == 0) continue;
                string name = KalivJson.Str(f, "name");
                list.Add(new KalivStashFacet { Id = id, Name = name.Length > 0 ? name : id, SceneCount = KalivJson.Int(f, "sceneCount") });
            }
            return list;
        }

        /// <summary>The companion's discovery reply → its base URL, or null if it is not the companion.</summary>
        public static string ParseDiscoveryReply(string json, string fromIp)
        {
            var o = KalivJson.TryParseObject(json);
            if (o == null || KalivJson.Str(o, "service") != ServiceName || string.IsNullOrEmpty(fromIp)) return null;
            int port = KalivJson.Int(o, "port", DefaultPort);
            if (port <= 0 || port > 65535) port = DefaultPort;
            return $"http://{fromIp}:{port}";
        }

        /// <summary>POST /api/v1/progress body — resume is local-first on the companion, nothing is written to Stash.</summary>
        public static string ProgressBody(string sceneId, double position, double duration, bool finished) =>
            KalivJson.Serialize(new Dictionary<string, object>
            {
                ["sceneId"] = sceneId,
                ["positionSeconds"] = Math.Max(0, position),
                ["durationSeconds"] = Math.Max(0, duration),
                ["finished"] = finished,
            });

        /// <summary>Resume only from a meaningful point, and not from the very end.</summary>
        public static double ResumeFrom(KalivStashScene s)
        {
            if (s == null || s.ResumeSeconds < 10) return 0;
            if (s.DurationSeconds > 0 && s.ResumeSeconds > s.DurationSeconds - 15) return 0;
            return s.ResumeSeconds;
        }

        public static string Describe(KalivStashScene s)
        {
            var t = TimeSpan.FromSeconds(Math.Max(0, s.DurationSeconds));
            string dur = s.DurationSeconds <= 0 ? "" : "  ·  " + (t.TotalHours >= 1 ? t.ToString(@"h\:mm\:ss") : t.ToString(@"m\:ss"));
            string studio = s.Studio == null ? "" : "  ·  " + s.Studio;
            string flags = (s.Favorite ? "  ·  ♥" : "") + (s.ResumeSeconds >= 10 ? "  ·  fortsæt" : "");
            string title = s.Title.Length > 60 ? s.Title.Substring(0, 57) + "…" : s.Title;
            return $"{title}{studio}{dur}  ·  {s.FormatHint}{flags}";
        }

        private static string NullIfBlank(string s) => string.IsNullOrWhiteSpace(s) ? null : s;

        private static string Normalize(string baseUrl)
        {
            string v = (baseUrl ?? "").Trim();
            while (v.EndsWith("/")) v = v.Substring(0, v.Length - 1);
            return v;
        }
    }
}

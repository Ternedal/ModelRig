using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace Kaliv.VR
{
    public enum KalivMediaKind { Image, Video }

    public sealed class KalivMediaItem
    {
        public string Id;
        public KalivMediaKind Kind;
        public string MimeType;
        public DateTime CreatedAtUtc;
        public long SizeBytes;
        public int? Width;
        public int? Height;
        public double? DurationSeconds;
        public string Projection;    // flat | equirectangular_180 | equirectangular_360
        public string Stereo;        // mono | left_right | top_bottom
        public string ThumbnailId;
        public bool SupportsRange;

        /// <summary>Always derived from the ID; a path from the server is only compared, never used.</summary>
        public string MediaPath => KalivMediaGallery.MediaPath(Id);
        public string ThumbnailPath => ThumbnailId == null ? null : KalivMediaGallery.MediaPath(ThumbnailId);

        /// <summary>
        /// The SkyPlayer-Engine format hint for this item. The engine speaks in its own
        /// vocabulary (FLAT / VR180 / VR360 with SBS / OU); the gallery speaks in projection
        /// + stereo. This is the one place the two meet.
        /// </summary>
        public string FormatHint => KalivMediaGallery.FormatHintFor(Projection, Stereo);
    }

    public sealed class KalivMediaPage
    {
        public List<KalivMediaItem> Items = new List<KalivMediaItem>();
        /// <summary>Null at the end of the list. Opaque: only ever echoed back.</summary>
        public string NextCursor;
        /// <summary>Items in this page that failed validation and are not shown.</summary>
        public int Skipped;
    }

    /// <summary>
    /// `kaliv-media-gallery/v1`, the read-only media contract agreed on ModelRig #2275 — the
    /// VR port of Android's MediaGalleryContract, rule for rule.
    ///
    /// <code>
    /// GET /api/v1/media?limit=1..100[&amp;cursor=&lt;opaque&gt;]
    /// 200 {"schema":"kaliv-media-gallery/v1","items":[Item],"next_cursor":string|null}
    /// GET|HEAD /api/v1/media/{id}
    /// </code>
    ///
    /// The contract is the target; the rig does not implement it yet, so today the VR
    /// client gets a 404 and says so. The parser fails closed per item: an invalid item is
    /// skipped and counted, never shown, and never takes the rest of the page with it.
    /// Page-level damage (wrong schema, missing list, bad cursor) rejects the whole page.
    /// </summary>
    public static class KalivMediaGallery
    {
        public const string Schema = "kaliv-media-gallery/v1";
        public const int MaxLimit = 100;
        public const int DefaultLimit = 50;
        private const int MaxCursorChars = 1024;

        private static readonly Regex SafeId = new Regex("^[A-Za-z0-9_-]{1,128}$", RegexOptions.CultureInvariant);
        private static readonly HashSet<string> ImageMime = new HashSet<string> { "image/png", "image/jpeg", "image/webp" };
        private static readonly HashSet<string> VideoMime = new HashSet<string> { "video/mp4" };
        public static readonly HashSet<string> Projections = new HashSet<string> { "flat", "equirectangular_180", "equirectangular_360" };
        public static readonly HashSet<string> StereoModes = new HashSet<string> { "mono", "left_right", "top_bottom" };

        public static bool IsSafeId(string value) => value != null && SafeId.IsMatch(value);

        /// <summary>Only safe IDs become paths. For this alphabet URL-encoding is the identity.</summary>
        public static string MediaPath(string id)
        {
            if (!IsSafeId(id)) throw new ArgumentException("unsafe media id");
            return "/api/v1/media/" + id;
        }

        /// <summary>Opaque, but bounded and printable ASCII so it can be echoed as a query value.</summary>
        public static bool IsValidCursor(string value)
        {
            if (string.IsNullOrEmpty(value) || value.Length > MaxCursorChars) return false;
            foreach (char c in value) if (c < 0x21 || c > 0x7e) return false;
            return true;
        }

        /// <summary>
        /// Map the gallery's projection + stereo onto SkyPlayer-Engine's exact hint vocabulary
        /// (VrProjection.FromHint). Returns null for combinations the engine cannot render —
        /// flat top/bottom and 360° top/bottom. FromHint falls back to "Flad 2D" on anything
        /// it does not know, so passing a guessed name would silently show both eyes side by
        /// side; refusing is the honest outcome.
        /// </summary>
        public static string FormatHintFor(string projection, string stereo)
        {
            switch (projection)
            {
                case "flat":
                    return stereo == "mono" ? "FLAT" : stereo == "left_right" ? "SBS_3D" : null;
                case "equirectangular_180":
                    return stereo == "mono" ? "VR180_MONO" : stereo == "left_right" ? "VR180_SBS" : "OU_TB";
                case "equirectangular_360":
                    return stereo == "mono" ? "VR360_MONO" : stereo == "left_right" ? "VR360_SBS" : null;
                default:
                    return null;
            }
        }

        /// <summary>
        /// Which part of a stereo image ONE eye should see, as a UV rect (x, y, w, h).
        /// A side-by-side photo shown whole is two photos next to each other; showing the left
        /// eye's half gives a correct flat picture. Top/bottom keeps the top half (Unity's UV
        /// origin is bottom-left, hence y = 0.5).
        /// </summary>
        public static UnityEngine.Rect ImageUvRect(string stereo) => stereo switch
        {
            "left_right" => new UnityEngine.Rect(0f, 0f, 0.5f, 1f),
            "top_bottom" => new UnityEngine.Rect(0f, 0.5f, 1f, 0.5f),
            _ => new UnityEngine.Rect(0f, 0f, 1f, 1f),
        };

        /// <summary>Parse one page. Throws FormatException on page-level damage.</summary>
        public static KalivMediaPage ParsePage(string body)
        {
            Dictionary<string, object> root;
            try { root = KalivJson.Parse(body) as Dictionary<string, object>; }
            catch (FormatException) { throw new FormatException("Mediebiblioteket svarede ikke med gyldig JSON"); }
            if (root == null) throw new FormatException("Mediebiblioteket svarede ikke med gyldig JSON");

            if (!(root.TryGetValue("schema", out var schema) && schema as string == Schema))
                throw new FormatException("Ukendt mediebibliotek-format");
            if (!(root.TryGetValue("items", out var rawItems) && rawItems is List<object> items))
                throw new FormatException("Manglende medieliste");
            if (items.Count > MaxLimit) throw new FormatException("For mange medier i ét svar");
            if (!root.ContainsKey("next_cursor")) throw new FormatException("Manglende next_cursor");

            var page = new KalivMediaPage();
            object rawCursor = root["next_cursor"];
            if (rawCursor != null)
            {
                if (!(rawCursor is string cursor) || !IsValidCursor(cursor))
                    throw new FormatException("Ugyldig next_cursor");
                page.NextCursor = cursor;
            }

            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var raw in items)
            {
                var item = ParseItem(raw as Dictionary<string, object>);
                if (item == null || !seen.Add(item.Id)) page.Skipped++;
                else page.Items.Add(item);
            }
            return page;
        }

        /// <summary>Null when the item breaks the contract in any way. Unknown fields are ignored.</summary>
        public static KalivMediaItem ParseItem(Dictionary<string, object> o)
        {
            if (o == null) return null;
            if (!(Get(o, "id") is string id) || !IsSafeId(id)) return null;

            KalivMediaKind kind;
            string kindWire = Get(o, "kind") as string;
            if (kindWire == "image") kind = KalivMediaKind.Image;
            else if (kindWire == "video") kind = KalivMediaKind.Video;
            else return null;

            if (!(Get(o, "mime_type") is string mime)) return null;
            if (!(kind == KalivMediaKind.Image ? ImageMime : VideoMime).Contains(mime)) return null;

            if (!(Get(o, "created_at") is string createdRaw) || !TryParseUtc(createdRaw, out DateTime created)) return null;

            long? size = KalivJson.StrictLong(Get(o, "size_bytes"));
            if (size == null || size < 0) return null;

            if (!TryDimension(o, "width", out int? width)) return null;
            if (!TryDimension(o, "height", out int? height)) return null;

            double? duration = null;
            object rawDuration = Get(o, "duration_seconds");
            if (rawDuration != null)
            {
                double d;
                if (rawDuration is long l) d = l;
                else if (rawDuration is double dd) d = dd;
                else return null;
                if (double.IsNaN(d) || double.IsInfinity(d) || d < 0) return null;
                duration = d;
            }
            if (kind == KalivMediaKind.Image && duration != null) return null;

            if (!(Get(o, "projection") is string projection) || !Projections.Contains(projection)) return null;
            if (!(Get(o, "stereo") is string stereo) || !StereoModes.Contains(stereo)) return null;

            string thumbnailId = null;
            object rawThumb = Get(o, "thumbnail_id");
            if (rawThumb != null)
            {
                if (!(rawThumb is string t) || !IsSafeId(t)) return null;
                thumbnailId = t;
            }

            if (!(Get(o, "playback") is Dictionary<string, object> playback)) return null;
            if (!(Get(playback, "supports_range") is bool supportsRange)) return null;

            // The server's paths must equal what the ID implies. They are never used.
            if (Get(o, "url") as string != MediaPath(id)) return null;
            object thumbUrl = Get(o, "thumbnail_url");
            string expectedThumb = thumbnailId == null ? null : MediaPath(thumbnailId);
            if (!Equals(thumbUrl as string, expectedThumb) || (thumbUrl != null && !(thumbUrl is string))) return null;

            return new KalivMediaItem
            {
                Id = id, Kind = kind, MimeType = mime, CreatedAtUtc = created, SizeBytes = size.Value,
                Width = width, Height = height, DurationSeconds = duration,
                Projection = projection, Stereo = stereo, ThumbnailId = thumbnailId,
                SupportsRange = supportsRange,
            };
        }

        /// <summary>Absent and explicit JSON null both read as null.</summary>
        private static object Get(Dictionary<string, object> o, string key) =>
            o != null && o.TryGetValue(key, out var v) ? v : null;

        /// <summary>Absent/null is valid (null); a present value must be a non-negative int.</summary>
        private static bool TryDimension(Dictionary<string, object> o, string key, out int? value)
        {
            value = null;
            object raw = Get(o, key);
            if (raw == null) return true;
            long? l = KalivJson.StrictLong(raw);
            if (l == null || l < 0 || l > int.MaxValue) return false;
            value = (int)l.Value;
            return true;
        }

        /// <summary>RFC 3339 in UTC only ("…Z"); an offset or a local time is a contract break.</summary>
        private static bool TryParseUtc(string value, out DateTime utc)
        {
            utc = default;
            if (!value.EndsWith("Z", StringComparison.Ordinal)) return false;
            return DateTime.TryParse(value, CultureInfo.InvariantCulture,
                DateTimeStyles.AdjustToUniversal | DateTimeStyles.AssumeUniversal, out utc);
        }
    }
}

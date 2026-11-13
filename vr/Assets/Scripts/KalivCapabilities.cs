using System.Collections.Generic;
using System.Linq;

namespace Kaliv.VR
{
    /// <summary>
    /// What the connected worker can actually do: the `capabilities` object inside
    /// GET /api/v1/health/full. The VR port of Android's WorkerCapabilities.
    ///
    /// The point is the dead-button rule: a surface must not promise what the rig cannot do.
    /// The released core worker ships WITHOUT ASR and TTS, so on a fresh install a voice
    /// button that ignores this would let you speak a whole sentence and only then fail.
    ///
    /// THE LOAD-BEARING RULE (same as Android): something is unsupported only when the rig
    /// has EXPLICITLY said false. Unknown, missing, unreadable or never fetched all mean
    /// available — an older rig that does not know the field must behave as it does today,
    /// and a failed probe must never amputate a working feature.
    /// </summary>
    public sealed class KalivCapabilities
    {
        public const string Asr = "asr";
        public const string Tts = "tts";

        private readonly Dictionary<string, bool> _reported;

        public static readonly KalivCapabilities Unknown = new KalivCapabilities(new Dictionary<string, bool>());

        private KalivCapabilities(Dictionary<string, bool> reported) { _reported = reported; }

        public bool Known => _reported.Count > 0;

        public bool Supports(string capability) =>
            !_reported.TryGetValue(capability, out bool v) || v;

        public IReadOnlyList<string> ExplicitlyMissing() =>
            _reported.Where(kv => !kv.Value).Select(kv => kv.Key).OrderBy(k => k).ToList();

        /// <summary>
        /// Read `capabilities` from a /health/full body. Only real booleans count: a string or
        /// a number is an answer we do not understand, and then we do not guess "no".
        /// </summary>
        public static KalivCapabilities FromHealthFull(string body)
        {
            var root = KalivJson.TryParseObject(body);
            var inner = KalivJson.Obj(root, "capabilities");
            if (inner == null) return Unknown;
            var reported = new Dictionary<string, bool>();
            foreach (var kv in inner)
                if (kv.Value is bool b) reported[kv.Key] = b;
            return reported.Count == 0 ? Unknown : new KalivCapabilities(reported);
        }

        /// <summary>
        /// Can the rig run a spoken turn? It needs BOTH steps — hearing and speaking — and
        /// cloud does not rescue it: only the model's answer can move, the audio models live
        /// on the rig. Returns null when allowed, else the reason to show.
        /// </summary>
        public string VoiceBlockedReason()
        {
            bool asr = Supports(Asr), tts = Supports(Tts);
            if (asr && tts) return null;
            string what = !asr && !tts ? "hverken tale-til-tekst eller tekst-til-tale"
                : !asr ? "tale-til-tekst" : "tekst-til-tale";
            string packages = !asr && !tts ? "faster-whisper og piper-tts"
                : !asr ? "faster-whisper" : "piper-tts";
            return $"Riggen har ikke {what}. Den udgivne worker sendes uden {packages} — " +
                   "installér det på riggen for at bruge stemme.";
        }
    }
}

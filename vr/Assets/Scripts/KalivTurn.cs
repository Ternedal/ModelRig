using System.Collections.Generic;

namespace Kaliv.VR
{
    /// <summary>
    /// Which rig path a turn takes. The VR port of Android's TurnRouter.
    ///
    /// Android learned this the hard way: its send path and retry path computed these flags
    /// separately, the retry path had no tools branch, and a retried action turn silently
    /// became plain chat. Here, as there, both paths ask this one function.
    ///
    /// VR is rig-only — there is no cloud key on the headset — so the cloud columns of the
    /// Android table collapse: tools win when on, then document knowledge, then plain chat.
    /// </summary>
    public enum KalivTurnRoute
    {
        Chat,
        Rag,
        Tools,
    }

    public readonly struct KalivTurnPlan
    {
        public readonly KalivTurnRoute Route;

        /// <summary>A tools turn may also search documents, when knowledge is on.</summary>
        public readonly bool ToolsWithRag;

        public KalivTurnPlan(KalivTurnRoute route, bool toolsWithRag)
        {
            Route = route;
            ToolsWithRag = toolsWithRag;
        }

        public static KalivTurnPlan For(bool toolsMode, bool ragMode)
        {
            if (toolsMode) return new KalivTurnPlan(KalivTurnRoute.Tools, ragMode);
            if (ragMode) return new KalivTurnPlan(KalivTurnRoute.Rag, false);
            return new KalivTurnPlan(KalivTurnRoute.Chat, false);
        }
    }

    /// <summary>
    /// The status lines from the Kaliv design guide, section 07 — identical strings to
    /// Android's TurnStatus, so the same turn reads the same on both surfaces.
    /// </summary>
    public static class KalivTurnStatus
    {
        public const string Thinking = "Kaliv tænker …";
        public const string Rag = "Søger i din viden …";
        public const string Tools = "Kører værktøj …";
        public const string Listening = "Lytter …";
        public const string Hearing = "Kaliv lytter til dig …";

        public static string ForPlan(KalivTurnPlan plan) => plan.Route switch
        {
            KalivTurnRoute.Tools => Tools,
            KalivTurnRoute.Rag => Rag,
            _ => Thinking,
        };

        /// <summary>
        /// The rig's own phase, translated. Null means "keep the current status": an unknown
        /// phase from a newer worker must not blank the UI or force a guess. The client
        /// translates the server's words; it does not invent them.
        /// </summary>
        public static string ForPhase(string name) => name switch
        {
            "searching" => Rag,
            "generating" => Thinking,
            "tool_run" => Tools,
            _ => null,
        };
    }

    /// <summary>One retrieved excerpt: where it came from, how well it matched, what it said.</summary>
    public sealed class KalivUsedChunk
    {
        public string Source;
        public int? ChunkIndex;
        public double Score;
        public string Excerpt;
    }

    /// <summary>
    /// The outcome of a tools turn, as the rig reports it: an answer, or a proposal that has
    /// executed NOTHING and waits for a human.
    ///
    /// The confirmation id is opaque on purpose. The client never sends the arguments back,
    /// so it cannot change them between the card and the execution — the worker parked them.
    /// </summary>
    public sealed class KalivToolTurn
    {
        public const string StatusAnswered = "answered";
        public const string StatusConfirmationRequired = "confirmation_required";
        public const string StatusExecuted = "executed";
        public const string StatusDenied = "denied";

        public string Status = "";
        public string Answer = "";
        public string Tool;
        public string ConfirmationId;
        public string Summary;
        /// <summary>The tool's own risk class (read/write/desktop …), shown on the card.</summary>
        public string Risk;
        /// <summary>The finer question the human is asked: what the action actually does.</summary>
        public string Impact;
        public int ExpiresInSeconds;
        public string ExecutedWrite;
        public List<string> Sources = new List<string>();
        public List<KalivUsedChunk> Context = new List<KalivUsedChunk>();
        public string PersonName;

        public bool NeedsConfirmation =>
            Status == StatusConfirmationRequired && !string.IsNullOrEmpty(ConfirmationId);

        public static KalivToolTurn Parse(Dictionary<string, object> o)
        {
            var turn = new KalivToolTurn
            {
                Status = KalivJson.Str(o, "status"),
                Answer = KalivJson.Str(o, "answer"),
                Tool = NullIfBlank(KalivJson.Str(o, "tool")),
                ConfirmationId = NullIfBlank(KalivJson.Str(o, "confirmation_id")),
                Summary = NullIfBlank(KalivJson.Str(o, "summary")),
                Risk = NullIfBlank(KalivJson.Str(o, "risk")),
                Impact = NullIfBlank(KalivJson.Str(o, "impact")),
                ExpiresInSeconds = KalivJson.Int(o, "expires_in_seconds"),
                ExecutedWrite = NullIfBlank(KalivJson.Str(o, "executed_write")),
                PersonName = NullIfBlank(KalivJson.Str(KalivJson.Obj(o, "person"), "display_name")),
            };

            var sources = KalivJson.Arr(o, "sources");
            if (sources != null)
                foreach (var s in sources)
                    if (s is string name && name.Length > 0) turn.Sources.Add(name);

            var context = KalivJson.Arr(o, "context");
            if (context != null)
            {
                foreach (var item in context)
                {
                    var c = item as Dictionary<string, object>;
                    string src = KalivJson.Str(c, "source");
                    if (src.Length == 0) continue;   // fail closed per excerpt, as Android does
                    turn.Context.Add(new KalivUsedChunk
                    {
                        Source = src,
                        ChunkIndex = KalivJson.IsNull(c, "chunk_index") ? (int?)null : KalivJson.Int(c, "chunk_index"),
                        Score = KalivJson.Num(c, "score"),
                        Excerpt = KalivJson.Str(c, "excerpt"),
                    });
                }
            }
            return turn;
        }

        // org.json's optString returns "null" for an explicit JSON null in some paths;
        // Android filters it by hand (`it != "null"`). Do the same so both agree.
        private static string NullIfBlank(string s) =>
            string.IsNullOrWhiteSpace(s) || s == "null" ? null : s;
    }

    /// <summary>
    /// How a tool-stream line reads. The tools stream is NOT the chat contract: it has no
    /// deltas, only phases and one `result` line — and, like every other stream, an EOF
    /// without that result line is a failure rather than an empty success.
    /// </summary>
    public static class KalivToolStream
    {
        public enum LineKind { Ignored, Phase, Result, Failure }

        public static LineKind Parse(string line, out string phaseOrError, out KalivToolTurn result)
        {
            phaseOrError = null;
            result = null;
            var o = KalivJson.TryParseObject((line ?? "").Trim());
            if (o == null) return LineKind.Ignored;

            string err = KalivJson.Str(o, "error");
            if (err.Length > 0) { phaseOrError = err; return LineKind.Failure; }

            var r = KalivJson.Obj(o, "result");
            if (r != null) { result = KalivToolTurn.Parse(r); return LineKind.Result; }

            string phase = KalivJson.Str(o, "phase");
            if (phase.Length > 0) { phaseOrError = phase; return LineKind.Phase; }
            return LineKind.Ignored;
        }

        public const string Truncated =
            "værktøjsturen blev afbrudt undervejs — forbindelsen lukkede før riggen var færdig; prøv igen";
    }
}

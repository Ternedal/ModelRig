using System;
using UnityEngine;

namespace Kaliv.VR
{
    /// <summary>
    /// The rig's NDJSON streams, as typed events — and the rule that a stream is only
    /// complete when it SAYS so.
    ///
    /// This is a deliberate port of the Android client's StreamContract
    /// (android/app/src/main/java/dk/ternedal/modelrig/logic/StreamContract.kt), not a
    /// VR-specific re-invention: three clients reading the same wire format must agree on
    /// what a finished answer is, or they disagree about whether the user got a whole one.
    ///
    /// The rule that matters: a body running out is NOT completion. A proxy timeout, a
    /// dropped link or a crashed upstream end the body exactly like a finished answer
    /// does, so a truncated reply looks complete unless a terminal event was seen.
    ///
    /// Scope note: the voice events (transcript/chunk) in the Android contract are
    /// intentionally not ported yet — Kaliv VR has no voice turn to feed them to. They
    /// belong with that slice, so the parser is never ahead of a consumer.
    /// </summary>
    public enum KalivStreamEventKind
    {
        Ignored = 0,
        Delta,
        Phase,
        Done,
        Failure,
    }

    public readonly struct KalivStreamEvent
    {
        public readonly KalivStreamEventKind Kind;

        /// <summary>Delta: the piece of answer. Done: content riding on the terminal line.</summary>
        public readonly string Text;

        /// <summary>Phase name, or the failure message.</summary>
        public readonly string Info;

        private KalivStreamEvent(KalivStreamEventKind kind, string text, string info)
        {
            Kind = kind;
            Text = text ?? "";
            Info = info ?? "";
        }

        public static readonly KalivStreamEvent Ignored =
            new KalivStreamEvent(KalivStreamEventKind.Ignored, "", "");

        public static KalivStreamEvent Delta(string text) =>
            new KalivStreamEvent(KalivStreamEventKind.Delta, text, "");

        public static KalivStreamEvent Phase(string name) =>
            new KalivStreamEvent(KalivStreamEventKind.Phase, "", name);

        /// <summary>
        /// The stream said it finished. trailingDelta carries content that rode along on
        /// the terminal line — Ollama may put the last token there, and dropping it loses
        /// the tail of the answer.
        /// </summary>
        public static KalivStreamEvent Done(string trailingDelta) =>
            new KalivStreamEvent(KalivStreamEventKind.Done, trailingDelta, "");

        public static KalivStreamEvent Failure(string message) =>
            new KalivStreamEvent(KalivStreamEventKind.Failure, "", message);
    }

    public static class KalivStreamContract
    {
        // One flat shape for every line we care about. JsonUtility ignores unknown fields
        // and leaves missing ones at their default, which matches the Android parser's
        // opt* semantics exactly (absent "done" == false, absent "error" == empty).
        [Serializable]
        private sealed class Line
        {
            public string type;
            public string error;
            public string detail;
            public string phase;
            public bool done;
            public Message message;
        }

        [Serializable]
        private sealed class Message
        {
            public string content;
        }

        public static KalivStreamEvent Parse(string line)
        {
            string t = (line ?? "").Trim();
            if (t.Length == 0 || t[0] != '{') return KalivStreamEvent.Ignored;

            Line o;
            try { o = JsonUtility.FromJson<Line>(t); }
            catch (Exception) { return KalivStreamEvent.Ignored; }
            if (o == null) return KalivStreamEvent.Ignored;

            // Typed worker events first: they are unambiguous.
            if (!string.IsNullOrEmpty(o.type))
            {
                if (o.type == "done") return KalivStreamEvent.Done("");
                if (o.type == "error")
                    return KalivStreamEvent.Failure(
                        string.IsNullOrWhiteSpace(o.detail) ? "ukendt fejl" : o.detail);
            }

            // A bare {"error": "..."} line. This is the one that used to vanish on Android:
            // it has no message.content, so a naive reader scores it as an empty delta and
            // drops it, ending the stream with nothing to show.
            if (!string.IsNullOrEmpty(o.error)) return KalivStreamEvent.Failure(o.error);

            // A phase is deliberately NOT content: a stream that announced a phase and then
            // died must read as an answer that never started, not a truncated one.
            if (!string.IsNullOrEmpty(o.phase)) return KalivStreamEvent.Phase(o.phase);

            string content = o.message != null ? (o.message.content ?? "") : "";
            if (o.done) return KalivStreamEvent.Done(content);
            if (content.Length > 0) return KalivStreamEvent.Delta(content);
            return KalivStreamEvent.Ignored;
        }

        /// <summary>
        /// What an exhausted stream means. Null = a real completion.
        ///
        /// The distinction matters to the person reading the screen: a truncated answer and
        /// an answer that never started are different failures, and neither is success.
        /// </summary>
        public static string TerminalFailure(bool sawTerminal, bool sawContent)
        {
            if (sawTerminal) return null;
            if (sawContent)
                return "svaret blev afbrudt undervejs — forbindelsen lukkede før modellen var færdig; prøv igen";
            return "intet svar modtaget (tom stream) — prøv igen";
        }
    }
}

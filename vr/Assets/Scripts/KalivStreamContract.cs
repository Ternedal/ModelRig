using System.Collections.Generic;

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
    /// Two wire shapes, one parser, same as Android: Ollama's chat NDJSON
    /// (`message.content`, `done`, `error`) through /chat and /rag/chat, and the worker's
    /// typed voice events (`type: transcript|chunk|done|error`). The voice events were held
    /// back in the first VR slice because nothing consumed them; the voice turn does now.
    /// </summary>
    public enum KalivStreamEventKind
    {
        Ignored = 0,
        Delta,
        Phase,
        Done,
        Failure,
        Sources,
        Transcript,
        Chunk,
    }

    public sealed class KalivStreamEvent
    {
        public readonly KalivStreamEventKind Kind;

        /// <summary>
        /// Delta: the piece of answer. Done: content that rode on the terminal line.
        /// Transcript: what the rig heard. Chunk: the spoken sentence.
        /// </summary>
        public readonly string Text;

        /// <summary>Phase name, or the failure message.</summary>
        public readonly string Info;

        /// <summary>Sources: the source names that grounded a RAG answer, in the rig's order.</summary>
        public readonly IReadOnlyList<string> Names;

        /// <summary>Chunk: position in the spoken reply.</summary>
        public readonly int Index;

        /// <summary>Chunk: base64 WAV for this sentence.</summary>
        public readonly string AudioB64;

        /// <summary>Chunk: the rig's body utterance for this sentence; null from an older rig.</summary>
        public readonly string UtteranceId;

        /// <summary>Typed done: the whole reply, as the voice pipeline reports it.</summary>
        public readonly string Reply;

        /// <summary>Typed done: which model answered, when the rig says.</summary>
        public readonly string Model;

        /// <summary>Typed error: the HTTP-like status the worker attached, or 0.</summary>
        public readonly int Status;

        private static readonly string[] NoNames = new string[0];

        private KalivStreamEvent(KalivStreamEventKind kind, string text = "", string info = "",
                                 IReadOnlyList<string> names = null, int index = 0,
                                 string audioB64 = "", string utteranceId = null,
                                 string reply = "", string model = null, int status = 0)
        {
            Kind = kind;
            Text = text ?? "";
            Info = info ?? "";
            Names = names ?? NoNames;
            Index = index;
            AudioB64 = audioB64 ?? "";
            UtteranceId = utteranceId;
            Reply = reply ?? "";
            Model = model;
            Status = status;
        }

        public static readonly KalivStreamEvent Ignored = new KalivStreamEvent(KalivStreamEventKind.Ignored);

        public static KalivStreamEvent Delta(string text) =>
            new KalivStreamEvent(KalivStreamEventKind.Delta, text: text);

        public static KalivStreamEvent Phase(string name) =>
            new KalivStreamEvent(KalivStreamEventKind.Phase, info: name);

        /// <summary>
        /// The stream said it finished. trailingDelta carries content that rode along on
        /// the terminal line — Ollama may put the last token there, and dropping it loses
        /// the tail of the answer.
        /// </summary>
        public static KalivStreamEvent Done(string trailingDelta, string reply = "", string model = null) =>
            new KalivStreamEvent(KalivStreamEventKind.Done, text: trailingDelta, reply: reply, model: model);

        public static KalivStreamEvent Failure(string message, int status = 0) =>
            new KalivStreamEvent(KalivStreamEventKind.Failure, info: message, status: status);

        public static KalivStreamEvent Sources(IReadOnlyList<string> names) =>
            new KalivStreamEvent(KalivStreamEventKind.Sources, names: names);

        public static KalivStreamEvent Transcript(string text) =>
            new KalivStreamEvent(KalivStreamEventKind.Transcript, text: text);

        public static KalivStreamEvent Chunk(int index, string text, string audioB64, string utteranceId) =>
            new KalivStreamEvent(KalivStreamEventKind.Chunk, text: text, index: index,
                audioB64: audioB64, utteranceId: utteranceId);
    }

    public static class KalivStreamContract
    {
        public static KalivStreamEvent Parse(string line)
        {
            string t = (line ?? "").Trim();
            if (t.Length == 0 || t[0] != '{') return KalivStreamEvent.Ignored;

            var o = KalivJson.TryParseObject(t);
            if (o == null) return KalivStreamEvent.Ignored;

            // Typed worker events first: they are unambiguous.
            switch (KalivJson.Str(o, "type"))
            {
                case "transcript":
                    return KalivStreamEvent.Transcript(KalivJson.Str(o, "text"));
                case "chunk":
                    return KalivStreamEvent.Chunk(
                        KalivJson.Int(o, "index"),
                        KalivJson.Str(o, "text"),
                        KalivJson.Str(o, "audio_base64"),
                        Blank(KalivJson.Str(o, "utterance_id")));
                case "done":
                    return KalivStreamEvent.Done("",
                        reply: KalivJson.Str(o, "reply"),
                        model: Blank(KalivJson.Str(o, "model")));
                case "error":
                {
                    string detail = KalivJson.Str(o, "detail");
                    return KalivStreamEvent.Failure(
                        string.IsNullOrWhiteSpace(detail) ? "ukendt fejl" : detail,
                        KalivJson.Int(o, "status"));
                }
            }

            // A bare {"error": "..."} line. This is the one that used to vanish on Android:
            // it has no message.content, so a naive reader scores it as an empty delta and
            // drops it, ending the stream with nothing to show.
            string err = KalivJson.Str(o, "error");
            if (err.Length > 0) return KalivStreamEvent.Failure(err, KalivJson.Int(o, "status"));

            // A phase is deliberately NOT content: a stream that announced a phase and then
            // died must read as an answer that never started, not a truncated one.
            string phase = KalivJson.Str(o, "phase");
            if (phase.Length > 0) return KalivStreamEvent.Phase(phase);

            // RAG's header, recognised by SHAPE rather than position. Android used to rely on
            // "the first line", which quietly meant a stream that opened with a phase lost it.
            var sources = KalivJson.Arr(o, "sources");
            if (sources != null)
            {
                var names = new List<string>();
                foreach (var item in sources)
                {
                    string name = KalivJson.Str(item as Dictionary<string, object>, "source");
                    if (name.Length > 0) names.Add(name);
                }
                return KalivStreamEvent.Sources(names);
            }

            string content = KalivJson.Str(KalivJson.Obj(o, "message"), "content");
            if (KalivJson.Bool(o, "done")) return KalivStreamEvent.Done(content);
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

        private static string Blank(string s) => string.IsNullOrWhiteSpace(s) ? null : s;
    }
}

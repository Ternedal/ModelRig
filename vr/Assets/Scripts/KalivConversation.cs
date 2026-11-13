using System;
using System.Collections.Generic;
using System.IO;

namespace Kaliv.VR
{
    /// <summary>One message as the user saw it.</summary>
    public sealed class KalivMessage
    {
        public string Role;          // "user" | "assistant"
        public string Text;
        /// <summary>Shown, never persisted as context and never sent as history — as on Android.</summary>
        public bool Error;
        /// <summary>RAG source names that grounded this answer, if any.</summary>
        public List<string> Sources = new List<string>();
        /// <summary>The tool that ran (or was proposed) in this turn, if any.</summary>
        public string Tool;
        /// <summary>True when the answer was cut short by Stop.</summary>
        public bool Stopped;
        /// <summary>True when this turn came in by voice.</summary>
        public bool Spoken;
        /// <summary>Who answered, when the rig has a Person Profile selected (#752); null otherwise.</summary>
        public string Person;
        public long At;

        public KalivMessage() { }

        public KalivMessage(string role, string text)
        {
            Role = role;
            Text = text ?? "";
            At = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        }
    }

    /// <summary>
    /// The conversation: what is on screen, what is sent as history, and what survives a
    /// restart — three different questions with one owner.
    ///
    /// The rules are Android's (AppUi.kt), so a turn means the same thing on both surfaces:
    /// * a failed turn shows an error bubble that is NEVER sent back as history — the model
    ///   must not later treat a failure as something it said;
    /// * the user's message stays, because the user did say it;
    /// * history is bounded to the last 20 messages and 24 000 characters, trimmed from the
    ///   front — without that, a long conversation resends its whole text on every turn.
    /// </summary>
    public sealed class KalivConversation
    {
        public const int MaxHistoryMessages = 20;
        public const int MaxHistoryChars = 24_000;
        /// <summary>Kept on disk and on screen. Older turns are dropped from the front.</summary>
        public const int MaxStoredMessages = 200;

        private readonly List<KalivMessage> _messages = new List<KalivMessage>();

        public IReadOnlyList<KalivMessage> Messages => _messages;
        public int Count => _messages.Count;
        public string ConversationId { get; private set; } = NewId();

        public event Action Changed;

        public KalivMessage Add(KalivMessage m)
        {
            _messages.Add(m);
            if (_messages.Count > MaxStoredMessages)
                _messages.RemoveRange(0, _messages.Count - MaxStoredMessages);
            Changed?.Invoke();
            return m;
        }

        public void Clear()
        {
            _messages.Clear();
            ConversationId = NewId();
            Changed?.Invoke();
        }

        public void NotifyChanged() => Changed?.Invoke();

        /// <summary>
        /// History to send: errors filtered out, bounded the same way as Android.
        /// <paramref name="excludeLast"/> drops the trailing message — the rig's tools and
        /// voice endpoints take the CURRENT message separately, so it must not also appear
        /// at the end of the history.
        /// </summary>
        public List<(string role, string content)> History(bool excludeLast = false)
        {
            var convo = new List<(string role, string content)>();
            int end = excludeLast ? _messages.Count - 1 : _messages.Count;
            for (int i = 0; i < end; i++)
            {
                var m = _messages[i];
                if (m.Error) continue;
                if (m.Role != "user" && m.Role != "assistant") continue;
                if (string.IsNullOrWhiteSpace(m.Text)) continue;
                convo.Add((m.Role, m.Text));
            }
            return Trim(convo, MaxHistoryMessages, MaxHistoryChars);
        }

        public static List<(string role, string content)> Trim(
            List<(string role, string content)> convo, int maxMessages, int maxChars)
        {
            var list = convo.Count > maxMessages
                ? convo.GetRange(convo.Count - maxMessages, maxMessages)
                : new List<(string role, string content)>(convo);
            int total = 0;
            foreach (var m in list) total += m.content.Length;
            while (list.Count > 1 && total > maxChars)
            {
                total -= list[0].content.Length;
                list.RemoveAt(0);
            }
            return list;
        }

        /// <summary>
        /// The last user message that a retry would resend, and the index of what to replace.
        /// Retry is only offered when the conversation ENDS on a failed or empty answer — or
        /// on a user message with no answer at all — so it never rewrites a good turn.
        /// </summary>
        public bool TryGetRetry(out string prompt)
        {
            prompt = null;
            int n = _messages.Count;
            if (n == 0) return false;
            var last = _messages[n - 1];
            if (last.Role == "user") { prompt = last.Text; return true; }
            if (last.Role == "assistant" && (last.Error || string.IsNullOrWhiteSpace(last.Text)) && n >= 2 &&
                _messages[n - 2].Role == "user")
            {
                prompt = _messages[n - 2].Text;
                return true;
            }
            return false;
        }

        /// <summary>Drop the failed answer (if any) so a retry answers the same user message.</summary>
        public void PrepareRetry()
        {
            int n = _messages.Count;
            if (n > 0 && _messages[n - 1].Role == "assistant") _messages.RemoveAt(n - 1);
            Changed?.Invoke();
        }

        // ---- persistence ------------------------------------------------------------------

        public string ToJson()
        {
            var list = new List<object>(_messages.Count);
            foreach (var m in _messages)
            {
                // Errors are UI, not conversation. Android never persists them either; a
                // stale "riggen svarede ikke" from last week is noise on the next launch.
                if (m.Error) continue;
                var o = new Dictionary<string, object>
                {
                    ["role"] = m.Role,
                    ["text"] = m.Text ?? "",
                    ["at"] = (double)m.At,
                };
                if (m.Sources.Count > 0) o["sources"] = new List<object>(m.Sources);
                if (!string.IsNullOrEmpty(m.Tool)) o["tool"] = m.Tool;
                if (m.Stopped) o["stopped"] = true;
                if (m.Spoken) o["spoken"] = true;
                if (!string.IsNullOrEmpty(m.Person)) o["person"] = m.Person;
                list.Add(o);
            }
            return KalivJson.Serialize(new Dictionary<string, object>
            {
                ["schema"] = "kaliv-vr-conversation/v1",
                ["conversation_id"] = ConversationId,
                ["messages"] = list,
            });
        }

        /// <summary>
        /// Restore from disk. A file that does not parse, or has the wrong schema, is ignored
        /// rather than half-loaded: a broken history must never stop the app from starting.
        /// </summary>
        public bool LoadJson(string json)
        {
            var root = KalivJson.TryParseObject(json);
            if (root == null || KalivJson.Str(root, "schema") != "kaliv-vr-conversation/v1") return false;
            var arr = KalivJson.Arr(root, "messages");
            if (arr == null) return false;

            var loaded = new List<KalivMessage>();
            foreach (var item in arr)
            {
                var o = item as Dictionary<string, object>;
                string role = KalivJson.Str(o, "role");
                if (role != "user" && role != "assistant") continue;
                var m = new KalivMessage
                {
                    Role = role,
                    Text = KalivJson.Str(o, "text"),
                    At = (long)KalivJson.Num(o, "at"),
                    Tool = KalivJson.Has(o, "tool") ? KalivJson.Str(o, "tool") : null,
                    Stopped = KalivJson.Bool(o, "stopped"),
                    Spoken = KalivJson.Bool(o, "spoken"),
                    Person = KalivJson.Has(o, "person") ? KalivJson.Str(o, "person") : null,
                };
                var src = KalivJson.Arr(o, "sources");
                if (src != null) foreach (var s in src) if (s is string name) m.Sources.Add(name);
                loaded.Add(m);
            }

            _messages.Clear();
            _messages.AddRange(loaded);
            string id = KalivJson.Str(root, "conversation_id");
            ConversationId = string.IsNullOrWhiteSpace(id) ? NewId() : id;
            Changed?.Invoke();
            return true;
        }

        public void Save(string path)
        {
            // Write-then-rename: a crash mid-write must not leave a half file that the next
            // launch reads as "no history". Same atomic-write habit as the SkyPlayer companion.
            string tmp = path + ".tmp";
            File.WriteAllText(tmp, ToJson());
            if (File.Exists(path)) File.Delete(path);
            File.Move(tmp, path);
        }

        public bool Load(string path)
        {
            try { return File.Exists(path) && LoadJson(File.ReadAllText(path)); }
            catch (IOException) { return false; }
            catch (UnauthorizedAccessException) { return false; }
        }

        private static string NewId() => "vr-" + Guid.NewGuid().ToString("N").Substring(0, 12);
    }
}

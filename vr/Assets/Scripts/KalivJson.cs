using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace Kaliv.VR
{
    /// <summary>
    /// A small, strict JSON reader/writer for the rig's wire shapes.
    ///
    /// JsonUtility cannot answer the question the rig's protocols keep asking: "is this key
    /// PRESENT?" It fills absent fields with defaults, so a missing `sources` array and an
    /// empty one look identical, and a nested `result` object cannot be told apart from no
    /// result at all. The Android client reads with org.json's opt* semantics; this gives the
    /// VR client the same footing, so both parse the same line the same way.
    ///
    /// Objects become Dictionary&lt;string, object&gt;, arrays List&lt;object&gt;, numbers double,
    /// plus string, bool and null. Malformed input throws FormatException — callers that read
    /// a stream catch it and treat the line as junk, exactly like Android's runCatching.
    /// </summary>
    public static class KalivJson
    {
        public static object Parse(string json)
        {
            if (json == null) throw new FormatException("null input");
            int i = 0;
            object value = ReadValue(json, ref i, 0);
            SkipWs(json, ref i);
            if (i != json.Length) throw new FormatException("trailing data at " + i);
            return value;
        }

        /// <summary>Parse an object, or null when the text is not a JSON object.</summary>
        public static Dictionary<string, object> TryParseObject(string json)
        {
            if (string.IsNullOrWhiteSpace(json)) return null;
            try { return Parse(json) as Dictionary<string, object>; }
            catch (FormatException) { return null; }
        }

        // ---- opt* accessors: org.json semantics -------------------------------------------

        public static bool Has(Dictionary<string, object> o, string key) =>
            o != null && o.ContainsKey(key);

        /// <summary>org.json optString: absent or null → fallback; numbers/bools stringify.</summary>
        public static string Str(Dictionary<string, object> o, string key, string fallback = "")
        {
            if (o == null || !o.TryGetValue(key, out var v) || v == null) return fallback;
            return v switch
            {
                string s => s,
                bool b => b ? "true" : "false",
                long l => l.ToString(CultureInfo.InvariantCulture),
                double d => FormatNumber(d),
                _ => fallback,
            };
        }

        public static int Int(Dictionary<string, object> o, string key, int fallback = 0)
        {
            if (o == null || !o.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is long l) return (int)l;
            if (v is double d) return (int)d;
            if (v is string s && int.TryParse(s, NumberStyles.Integer, CultureInfo.InvariantCulture, out int n)) return n;
            return fallback;
        }

        public static double Num(Dictionary<string, object> o, string key, double fallback = 0)
        {
            if (o == null || !o.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is long l) return l;
            if (v is double d) return d;
            if (v is string s && double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out double n)) return n;
            return fallback;
        }

        public static bool Bool(Dictionary<string, object> o, string key, bool fallback = false)
        {
            if (o == null || !o.TryGetValue(key, out var v) || v == null) return fallback;
            if (v is bool b) return b;
            if (v is string s) return s.Equals("true", StringComparison.OrdinalIgnoreCase);
            return fallback;
        }

        public static Dictionary<string, object> Obj(Dictionary<string, object> o, string key) =>
            o != null && o.TryGetValue(key, out var v) ? v as Dictionary<string, object> : null;

        public static List<object> Arr(Dictionary<string, object> o, string key) =>
            o != null && o.TryGetValue(key, out var v) ? v as List<object> : null;

        public static bool IsNull(Dictionary<string, object> o, string key) =>
            o == null || !o.TryGetValue(key, out var v) || v == null;

        // ---- writer -----------------------------------------------------------------------

        public static string Serialize(object value)
        {
            var sb = new StringBuilder();
            Write(sb, value);
            return sb.ToString();
        }

        private static void Write(StringBuilder sb, object value)
        {
            switch (value)
            {
                case null: sb.Append("null"); break;
                case string s: WriteString(sb, s); break;
                case bool b: sb.Append(b ? "true" : "false"); break;
                case double d: sb.Append(FormatNumber(d)); break;
                case float f: sb.Append(FormatNumber(f)); break;
                case int n: sb.Append(n.ToString(CultureInfo.InvariantCulture)); break;
                case long l: sb.Append(l.ToString(CultureInfo.InvariantCulture)); break;
                case IDictionary<string, object> dict:
                {
                    sb.Append('{');
                    bool first = true;
                    foreach (var kv in dict)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        WriteString(sb, kv.Key);
                        sb.Append(':');
                        Write(sb, kv.Value);
                    }
                    sb.Append('}');
                    break;
                }
                case System.Collections.IEnumerable list:
                {
                    sb.Append('[');
                    bool first = true;
                    foreach (var item in list)
                    {
                        if (!first) sb.Append(',');
                        first = false;
                        Write(sb, item);
                    }
                    sb.Append(']');
                    break;
                }
                default: WriteString(sb, value.ToString()); break;
            }
        }

        private static string FormatNumber(double d)
        {
            if (double.IsNaN(d) || double.IsInfinity(d)) return "null";
            if (Math.Abs(d % 1) < double.Epsilon && Math.Abs(d) < 1e15)
                return ((long)d).ToString(CultureInfo.InvariantCulture);
            return d.ToString("R", CultureInfo.InvariantCulture);
        }

        private static void WriteString(StringBuilder sb, string s)
        {
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    case '\b': sb.Append("\\b"); break;
                    case '\f': sb.Append("\\f"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
        }

        // ---- reader -----------------------------------------------------------------------

        private const int MaxDepth = 64;

        private static object ReadValue(string s, ref int i, int depth)
        {
            if (depth > MaxDepth) throw new FormatException("nesting too deep");
            SkipWs(s, ref i);
            if (i >= s.Length) throw new FormatException("unexpected end");
            char c = s[i];
            switch (c)
            {
                case '{': return ReadObject(s, ref i, depth);
                case '[': return ReadArray(s, ref i, depth);
                case '"': return ReadString(s, ref i);
                case 't': Expect(s, ref i, "true"); return true;
                case 'f': Expect(s, ref i, "false"); return false;
                case 'n': Expect(s, ref i, "null"); return null;
                default:
                    if (c == '-' || (c >= '0' && c <= '9')) return ReadNumber(s, ref i);
                    throw new FormatException($"unexpected '{c}' at {i}");
            }
        }

        private static Dictionary<string, object> ReadObject(string s, ref int i, int depth)
        {
            var o = new Dictionary<string, object>(StringComparer.Ordinal);
            i++; // {
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == '}') { i++; return o; }
            while (true)
            {
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != '"') throw new FormatException("expected key at " + i);
                string key = ReadString(s, ref i);
                SkipWs(s, ref i);
                if (i >= s.Length || s[i] != ':') throw new FormatException("expected ':' at " + i);
                i++;
                o[key] = ReadValue(s, ref i, depth + 1);
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("unterminated object");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == '}') { i++; return o; }
                throw new FormatException("expected ',' or '}' at " + i);
            }
        }

        private static List<object> ReadArray(string s, ref int i, int depth)
        {
            var list = new List<object>();
            i++; // [
            SkipWs(s, ref i);
            if (i < s.Length && s[i] == ']') { i++; return list; }
            while (true)
            {
                list.Add(ReadValue(s, ref i, depth + 1));
                SkipWs(s, ref i);
                if (i >= s.Length) throw new FormatException("unterminated array");
                if (s[i] == ',') { i++; continue; }
                if (s[i] == ']') { i++; return list; }
                throw new FormatException("expected ',' or ']' at " + i);
            }
        }

        private static string ReadString(string s, ref int i)
        {
            i++; // opening quote
            var sb = new StringBuilder();
            while (true)
            {
                if (i >= s.Length) throw new FormatException("unterminated string");
                char c = s[i++];
                if (c == '"') return sb.ToString();
                if (c != '\\') { sb.Append(c); continue; }
                if (i >= s.Length) throw new FormatException("bad escape");
                char e = s[i++];
                switch (e)
                {
                    case '"': sb.Append('"'); break;
                    case '\\': sb.Append('\\'); break;
                    case '/': sb.Append('/'); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (i + 4 > s.Length) throw new FormatException("bad unicode escape");
                        sb.Append((char)int.Parse(s.Substring(i, 4), NumberStyles.HexNumber, CultureInfo.InvariantCulture));
                        i += 4;
                        break;
                    default: throw new FormatException($"bad escape '\\{e}'");
                }
            }
        }

        /// <summary>
        /// Integer tokens become long; anything with a fraction or exponent becomes double.
        /// The distinction is load-bearing: the media gallery contract rejects 1.0 and 1e3
        /// where it requires an integer, exactly as Android's strictLong does, and that is
        /// only possible if the reader remembers which one it saw.
        /// </summary>
        private static object ReadNumber(string s, ref int i)
        {
            int start = i;
            if (s[i] == '-') i++;
            bool integral = true;
            while (i < s.Length && "0123456789+-.eE".IndexOf(s[i]) >= 0)
            {
                char c = s[i];
                if (c == '.' || c == 'e' || c == 'E') integral = false;
                i++;
            }
            string token = s.Substring(start, i - start);
            if (integral && long.TryParse(token, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out long l))
                return l;
            if (!double.TryParse(token, NumberStyles.Float, CultureInfo.InvariantCulture, out double d))
                throw new FormatException("bad number '" + token + "'");
            return d;
        }

        /// <summary>A JSON integer that fits in a long; null for decimals, exponents, strings or overflow.</summary>
        public static long? StrictLong(object raw) => raw is long l ? l : (long?)null;

        private static void Expect(string s, ref int i, string word)
        {
            if (string.CompareOrdinal(s, i, word, 0, word.Length) != 0)
                throw new FormatException($"expected '{word}' at {i}");
            i += word.Length;
        }

        private static void SkipWs(string s, ref int i)
        {
            while (i < s.Length && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r')) i++;
        }
    }
}

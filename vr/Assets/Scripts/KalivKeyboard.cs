using System;

namespace Kaliv.VR
{
    /// <summary>
    /// The in-headset keyboard's logic, separate from its buttons so it can be tested.
    ///
    /// Why Kaliv VR has its own keyboard at all: Quest only shows the system overlay keyboard
    /// for apps that declare `oculus.software.overlay_keyboard`, and that path belongs to the
    /// Meta XR SDK, which this project deliberately does not use. Without it, focusing a
    /// Unity InputField does nothing visible — so the rig address, the pairing code and every
    /// typed message had no way in. SkyPlayer solved the same problem the same way.
    ///
    /// Danish layout: æ, ø and å sit where a Danish keyboard has them, because the person
    /// typing is Danish and the model is asked in Danish.
    /// </summary>
    public sealed class KalivKeyboardModel
    {
        public enum Layer { Lower, Upper, Symbols }

        // Plain labels: the panel's built-in font is Arial-based and has no ⇧ glyph — on the
        // headset it would render as an empty box.
        public const string Shift = "SHIFT";
        public const string ToSymbols = "?123";
        public const string ToLetters = "ABC";
        public const string Space = "MELLEMRUM";
        public const string Delete = "SLET";
        public const string Clear = "RYD";

        private static readonly string[] LowerRows =
        {
            "1234567890",
            "qwertyuiopå",
            "asdfghjklæø",
            "zxcvbnm,.-",
        };

        private static readonly string[] SymbolRows =
        {
            "1234567890",
            ":/@_-.?!'\"",
            "()+=&%#*;~",
            "[]{}<>|\\$€",
        };

        public string Text { get; private set; } = "";
        public Layer Current { get; private set; } = Layer.Lower;
        public int MaxLength { get; }

        /// <summary>Upper case lasts for one letter, as on a phone; then it drops back.</summary>
        private bool _shiftOnce;

        public KalivKeyboardModel(string initial = "", int maxLength = 2000, bool capitalizeFirst = false)
        {
            MaxLength = Math.Max(1, maxLength);
            Text = Truncate(initial ?? "");
            if (capitalizeFirst && Text.Length == 0) { Current = Layer.Upper; _shiftOnce = true; }
        }

        public const int Rows = 4;

        /// <summary>The characters on row <paramref name="row"/> for the current layer.</summary>
        public string RowKeys(int row)
        {
            if (row < 0 || row >= Rows) return "";
            if (Current == Layer.Symbols) return SymbolRows[row];
            string keys = LowerRows[row];
            return Current == Layer.Upper ? keys.ToUpperInvariant() : keys;
        }

        public static int MaxKeysPerRow
        {
            get
            {
                int max = 0;
                foreach (var r in LowerRows) max = Math.Max(max, r.Length);
                foreach (var r in SymbolRows) max = Math.Max(max, r.Length);
                return max;
            }
        }

        /// <summary>Press one key: a character, or one of the named control keys.</summary>
        public void Press(string key)
        {
            if (string.IsNullOrEmpty(key)) return;
            switch (key)
            {
                case Shift:
                    if (Current == Layer.Symbols) return;
                    bool up = Current != Layer.Upper;
                    Current = up ? Layer.Upper : Layer.Lower;
                    _shiftOnce = up;
                    return;
                case ToSymbols:
                    Current = Layer.Symbols;
                    _shiftOnce = false;
                    return;
                case ToLetters:
                    Current = Layer.Lower;
                    _shiftOnce = false;
                    return;
                case Space:
                    Type(" ");
                    return;
                case Delete:
                    if (Text.Length > 0) Text = RemoveLast(Text);
                    return;
                case Clear:
                    Text = "";
                    return;
                default:
                    Type(key);
                    if (_shiftOnce && Current == Layer.Upper && char.IsLetter(key[0]))
                    {
                        Current = Layer.Lower;
                        _shiftOnce = false;
                    }
                    return;
            }
        }

        private void Type(string s)
        {
            if (Text.Length + s.Length > MaxLength) return;   // full: ignore, never truncate silently
            Text += s;
        }

        /// <summary>Remove one character — a surrogate pair (an emoji pasted in) counts as one.</summary>
        private static string RemoveLast(string s)
        {
            int n = s.Length - 1;
            if (n > 0 && char.IsLowSurrogate(s[n]) && char.IsHighSurrogate(s[n - 1])) n--;
            return s.Substring(0, n);
        }

        private string Truncate(string s) => s.Length > MaxLength ? s.Substring(0, MaxLength) : s;
    }
}

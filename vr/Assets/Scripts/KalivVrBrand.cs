using UnityEngine;

namespace Kaliv.VR
{
    /// <summary>
    /// Quest/VR adapter for the canonical Kaliv design tokens.
    ///
    /// Ember is identity + primary human-facing action.
    /// Signal is live cognition/runtime/perception activity.
    /// Semantic colors are reserved for health/result state.
    ///
    /// Keep these values aligned with assets/design/kaliv-ui-guide/kaliv-ui-tokens.json.
    /// tests/workflow_brand_signal_roles.py guards the canonical values.
    /// </summary>
    internal static class KalivVrBrand
    {
        internal static readonly Color Canvas = Hex("#0B0A09");
        internal static readonly Color Surface = Hex("#171411");
        internal static readonly Color Elevated = Hex("#211B16");
        internal static readonly Color Border = Hex("#2A2521");
        internal static readonly Color Text = Hex("#F3EFE6");
        internal static readonly Color Muted = Hex("#A89D90");

        // Ember / identity.
        internal static readonly Color Ember = Hex("#D4AB52");
        internal static readonly Color EmberFill = Hex("#B08A3E");
        internal static readonly Color OnEmber = Hex("#2B1C05");

        // Signal / living-system activity.
        internal static readonly Color Signal = Hex("#48C7FF");
        internal static readonly Color SignalLight = Hex("#73D6FF");
        internal static readonly Color SignalStrong = Hex("#159FDB");

        // Semantic state.
        internal static readonly Color Success = Hex("#77836D");
        internal static readonly Color Danger = Hex("#C96B5D");

        // World-space interaction targets: visual controls may be slimmer, but
        // the collider must remain comfortably targetable in-headset.
        internal const float MinWorldButtonHeight = 56f;
        internal const float MinWorldButtonWidth = 96f;

        private static Color Hex(string value)
        {
            ColorUtility.TryParseHtmlString(value, out Color color);
            return color;
        }
    }
}

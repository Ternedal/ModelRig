package dk.ternedal.modelrig.desktop

/**
 * Canonical desktop navigation metadata shared by the wide and icon-only rails.
 *
 * Keeping labels here prevents the compact rail from drifting into decorative
 * glyph-only accessibility while the wide rail exposes meaningful names.
 */
internal data class KalivNavDestination(
    val screen: KalivScreen,
    val label: String,
    val wideGlyph: String,
    val iconGlyph: String,
    val showInIconRail: Boolean,
) {
    fun isSelected(active: KalivScreen): Boolean = screen == active
}

internal val kalivNavDestinations = listOf(
    KalivNavDestination(KalivScreen.CHAT, "Chat", "\u25AC", "\u2709", true),
    KalivNavDestination(KalivScreen.AGENT, "Agent", "\u25C8", "\u25C6", true),
    KalivNavDestination(KalivScreen.COMPUTER, "Computer-use", "\u25A6", "\u25A3", true),
    KalivNavDestination(KalivScreen.MODELS, "Modeller", "\u25F0", "\u25A4", true),
    KalivNavDestination(KalivScreen.DOCS, "Dokumenter", "\u25A4", "\u25A4", false),
    KalivNavDestination(KalivScreen.SETTINGS, "Indstillinger", "\u2699", "\u2699", true),
)

internal val kalivIconRailDestinations: List<KalivNavDestination>
    get() = kalivNavDestinations.filter(KalivNavDestination::showInIconRail)

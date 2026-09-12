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
    fun isSelected(selected: KalivScreen): Boolean = screen == selected
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

/**
 * MODELS and SETTINGS are hosted inside the CHAT content surface. Selection is
 * therefore presentation state: it follows the panel the operator actually
 * sees without changing App's content-layout authority.
 */
internal fun desktopNavigationSelection(
    activeScreen: KalivScreen,
    showSettings: Boolean,
    showModels: Boolean,
): KalivScreen = when {
    activeScreen != KalivScreen.CHAT -> activeScreen
    showSettings -> KalivScreen.SETTINGS
    showModels -> KalivScreen.MODELS
    else -> KalivScreen.CHAT
}

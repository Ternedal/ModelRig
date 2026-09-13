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
 * Navigation selection is presentation state, not content-layout state.
 *
 * MODELS and SETTINGS are hosted inside the CHAT surface, so App keeps
 * `activeScreen == CHAT` while either panel is visible. Selection must follow
 * what the user actually sees without changing the shell/rail layout authority.
 * Panel flags may remain true while AGENT/COMPUTER is showing, so they only
 * override selection while CHAT is the displayed content surface.
 * Conversation overlays remain CHAT, and DOCS is a RAG action rather than a
 * persistent panel, so neither receives a synthetic selected destination here.
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

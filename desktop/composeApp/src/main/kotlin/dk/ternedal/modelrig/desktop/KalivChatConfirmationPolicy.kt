package dk.ternedal.modelrig.desktop

/**
 * Presentation authority for the normal desktop Chat tool confirmation.
 *
 * A worker write confirmation remains authoritative until the worker
 * acknowledges a decision. While unresolved, no new chat turn may start on the
 * same surface and duplicate decision submissions stay disabled.
 */
internal data class KalivChatConfirmationPresentation(
    val showCard: Boolean,
    val decisionEnabled: Boolean,
    val newTurnEnabled: Boolean,
)

internal fun presentChatConfirmation(
    hasPendingConfirmation: Boolean,
    busy: Boolean,
): KalivChatConfirmationPresentation = KalivChatConfirmationPresentation(
    showCard = hasPendingConfirmation,
    decisionEnabled = hasPendingConfirmation && !busy,
    newTurnEnabled = !busy && !hasPendingConfirmation,
)

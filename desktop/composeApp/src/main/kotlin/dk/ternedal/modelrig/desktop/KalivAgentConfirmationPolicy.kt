package dk.ternedal.modelrig.desktop

/**
 * Presentation authority while an Agent write confirmation is unresolved.
 *
 * The card remains authoritative until the worker acknowledges a decision.
 * While it exists, a second Agent turn must not be started.
 */
internal data class KalivAgentConfirmationPresentation(
    val showCard: Boolean,
    val decisionEnabled: Boolean,
    val newTurnEnabled: Boolean,
)

internal fun presentAgentConfirmation(
    hasPendingConfirmation: Boolean,
    busy: Boolean,
): KalivAgentConfirmationPresentation = KalivAgentConfirmationPresentation(
    showCard = hasPendingConfirmation,
    decisionEnabled = hasPendingConfirmation && !busy,
    newTurnEnabled = !busy && !hasPendingConfirmation,
)

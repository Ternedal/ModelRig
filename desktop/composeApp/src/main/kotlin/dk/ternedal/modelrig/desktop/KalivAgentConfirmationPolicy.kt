package dk.ternedal.modelrig.desktop

/**
 * Presentation authority for the Agent cockpit while a worker write
 * confirmation is pending or being decided.
 *
 * A pending confirmation remains authoritative until the worker acknowledges a
 * decision. While it exists, starting another Agent turn is not allowed.
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

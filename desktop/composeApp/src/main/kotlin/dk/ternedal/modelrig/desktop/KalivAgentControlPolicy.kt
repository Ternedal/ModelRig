package dk.ternedal.modelrig.desktop

/**
 * Presentation authority for the desktop Agent task clear affordance.
 *
 * The worker currently exposes no remote cancellation contract. A local clear
 * must therefore never be presented while a request or write confirmation may
 * still be authoritative. The only safe affordance is a local view reset after
 * the current turn has reached a terminal, error-free state.
 */
internal data class KalivAgentClearPresentation(
    val visible: Boolean,
    val label: String?,
    val claimsRemoteCancellation: Boolean,
)

internal fun presentAgentClear(
    taskStarted: Boolean,
    busy: Boolean,
    hasPendingConfirmation: Boolean,
    hasError: Boolean,
): KalivAgentClearPresentation {
    val safeLocalReset = taskStarted && !busy && !hasPendingConfirmation && !hasError
    return KalivAgentClearPresentation(
        visible = safeLocalReset,
        label = if (safeLocalReset) "Ryd visning" else null,
        claimsRemoteCancellation = false,
    )
}

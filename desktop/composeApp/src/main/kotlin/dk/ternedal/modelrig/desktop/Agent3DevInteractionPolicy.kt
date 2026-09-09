package dk.ternedal.modelrig.desktop

/** Shared local authority for the explicit --agent3 developer surface. */
internal object Agent3DevInteractionPolicy {
    fun canPreview(
        message: String,
        busy: Boolean,
        runState: String?,
        activeToolState: String? = null,
        activeToolRequestState: String? = null,
    ): Boolean {
        if (message.isBlank() || busy) return false
        if (runState == null) return true
        return Agent3TaskUiPolicy.canResetTerminalHistory(
            runTerminal = isTerminal(runState),
            activeToolState = activeToolState,
            activeToolRequestState = activeToolRequestState,
            busy = busy,
        )
    }

    fun canStart(
        planId: String?,
        planSize: Int,
        capabilityAllowed: Boolean?,
        busy: Boolean,
        hasRun: Boolean,
    ): Boolean =
        !busy && !hasRun && !planId.isNullOrBlank() && planSize > 0 && capabilityAllowed != false
}

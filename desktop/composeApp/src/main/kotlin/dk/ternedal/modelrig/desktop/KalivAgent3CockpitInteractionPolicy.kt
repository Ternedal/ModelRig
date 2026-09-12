package dk.ternedal.modelrig.desktop

/**
 * Narrow interaction policy for the design-guide Agent 3 cockpit.
 *
 * Preview authority deliberately reuses the normal Agent 3 task policy: once a
 * server run exists, another preview may not replace its visible state. Preview
 * Start/Discard are one local interaction boundary: both are disabled while an
 * authoritative request is in flight, and both require an actual preview with
 * no server run. Plan Stop authority reuses the server-driven normal task policy
 * and is never inferred from a merely non-terminal local run state. A terminal
 * run can be cleared locally only after it is actually terminal and no request
 * is in flight; that local reset never claims remote cancellation.
 *
 * Publication epochs are local ordering authority only. They never cancel or
 * reinterpret a server request; they only prevent an older asynchronous
 * refresh from publishing run, log or error state after a newer mutation/reset
 * has already taken ownership of the cockpit.
 */
internal data class KalivAgent3CockpitInteraction(
    val composerEnabled: Boolean,
    val previewStartEnabled: Boolean,
    val previewDiscardEnabled: Boolean,
    val stopPlanEnabled: Boolean,
    val clearTerminalRunEnabled: Boolean,
)

internal fun presentAgent3CockpitInteraction(
    busy: Boolean,
    runState: String?,
    planCanRequestStop: Boolean? = null,
    hasPreview: Boolean = false,
): KalivAgent3CockpitInteraction {
    val hasRun = runState != null
    val terminal = hasRun && isTerminal(runState)
    val previewActionsEnabled = !busy && !hasRun && hasPreview
    return KalivAgent3CockpitInteraction(
        composerEnabled = !busy && !hasRun,
        previewStartEnabled = previewActionsEnabled,
        previewDiscardEnabled = previewActionsEnabled,
        stopPlanEnabled = hasRun && !terminal && Agent3TaskUiPolicy.canStopPlan(
            planCanRequest = planCanRequestStop,
            busy = busy,
        ),
        clearTerminalRunEnabled = !busy && terminal,
    )
}

internal fun canAgent3CockpitPreview(
    message: String,
    busy: Boolean,
    hasRun: Boolean,
): Boolean = Agent3TaskUiPolicy.canPreview(
    serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
    message = message,
    busy = busy,
    hasRun = hasRun,
)

internal fun nextAgent3CockpitPublicationEpoch(current: Long): Long =
    if (current == Long.MAX_VALUE) 1L else current + 1L

internal fun canPublishAgent3CockpitResponse(
    requestEpoch: Long,
    currentEpoch: Long,
): Boolean = requestEpoch == currentEpoch

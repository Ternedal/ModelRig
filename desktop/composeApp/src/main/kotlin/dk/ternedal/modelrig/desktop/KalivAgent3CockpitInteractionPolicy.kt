package dk.ternedal.modelrig.desktop

/**
 * Narrow interaction policy for the design-guide Agent 3 cockpit.
 *
 * Preview authority deliberately reuses the normal Agent 3 task policy: once a
 * server run exists, another preview may not replace its visible state. Plan
 * Stop authority also reuses the server-driven normal task policy and is never
 * inferred from a merely non-terminal local run state. A terminal run can be
 * cleared locally only after it is actually terminal and no request is in
 * flight; that local reset never claims remote cancellation.
 */
internal data class KalivAgent3CockpitInteraction(
    val composerEnabled: Boolean,
    val stopPlanEnabled: Boolean,
    val clearTerminalRunEnabled: Boolean,
)

internal fun presentAgent3CockpitInteraction(
    busy: Boolean,
    runState: String?,
    planCanRequestStop: Boolean? = null,
): KalivAgent3CockpitInteraction {
    val hasRun = runState != null
    val terminal = hasRun && isTerminal(runState)
    return KalivAgent3CockpitInteraction(
        composerEnabled = !busy && !hasRun,
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

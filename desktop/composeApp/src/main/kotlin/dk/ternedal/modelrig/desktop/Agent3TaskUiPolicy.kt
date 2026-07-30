package dk.ternedal.modelrig.desktop

/**
 * Pure policy for the normal desktop read-only task surface.
 *
 * The server surface is the only routing input. Missing, stale or unknown values
 * normalize to Agent 2. An already-started task is different: status and the
 * server-authorized plan Stop remain visible even if readiness later falls back.
 * Cancelling a terminal plan is not the same as stopping an executing tool, so
 * polling continues until the active-tool receipt is no longer pending/running.
 */
object Agent3TaskUiPolicy {
    const val AGENT2 = "agent2"
    const val AGENT3_READONLY = "agent3_readonly"

    fun normalizedSurface(serverSurface: String?): String =
        if (serverSurface == AGENT3_READONLY) AGENT3_READONLY else AGENT2

    fun canPreview(
        serverSurface: String?,
        message: String,
        busy: Boolean,
        hasRun: Boolean,
    ): Boolean = normalizedSurface(serverSurface) == AGENT3_READONLY &&
        message.isNotBlank() &&
        !busy &&
        !hasRun

    fun canStart(
        serverSurface: String?,
        previewCanStart: Boolean,
        busy: Boolean,
        hasRun: Boolean,
    ): Boolean = normalizedSurface(serverSurface) == AGENT3_READONLY &&
        previewCanStart &&
        !busy &&
        !hasRun

    fun canStopPlan(planCanRequest: Boolean?, busy: Boolean): Boolean =
        planCanRequest == true && !busy

    fun shouldPoll(
        runTerminal: Boolean?,
        activeToolState: String?,
        activeToolRequestState: String?,
    ): Boolean = runTerminal == false ||
        activeToolState == "executing" ||
        activeToolRequestState == "pending"
}

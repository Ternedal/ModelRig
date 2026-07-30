package dk.ternedal.modelrig.logic

/**
 * Pure policy for the normal read-only task screen.
 *
 * The server surface is the only routing input. Missing, stale or unknown values
 * normalize to Agent 2. An already-started task is different: status and Stop
 * remain available even if readiness later falls back, because the rig run
 * already exists and must not disappear from the human control surface.
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

    fun canStop(runTerminal: Boolean?, busy: Boolean): Boolean =
        runTerminal == false && !busy

    fun shouldPoll(runTerminal: Boolean?): Boolean = runTerminal == false
}

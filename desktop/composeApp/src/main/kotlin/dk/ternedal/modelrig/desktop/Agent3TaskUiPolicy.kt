package dk.ternedal.modelrig.desktop

/** Pure policy for the normal desktop read-only task surface. */
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

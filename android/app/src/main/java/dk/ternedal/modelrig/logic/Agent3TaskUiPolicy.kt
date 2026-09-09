package dk.ternedal.modelrig.logic

/**
 * Pure policy for the normal read-only task screen.
 *
 * The server surface is the only routing input. Missing, stale or unknown values
 * normalize to Agent 2. An already-started task is different: status and the
 * server-authorized plan Stop remain visible even if readiness later falls back.
 * Cancelling a terminal plan is not the same as stopping an executing tool, so
 * polling continues until the active-tool receipt is no longer pending/running.
 * Publication epochs only order local async responses; they never cancel or
 * reinterpret a server request. A retained run id is local recovery authority,
 * not proof that the run is still active; only a server-terminal snapshot clears it.
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

    fun nextPublicationEpoch(current: Long): Long =
        if (current == Long.MAX_VALUE) 1L else current + 1L

    fun canPublish(requestEpoch: Long, currentEpoch: Long): Boolean =
        requestEpoch == currentEpoch

    fun hasRunAuthority(snapshotPresent: Boolean, retainedRunId: String?): Boolean =
        snapshotPresent || !retainedRunId.isNullOrBlank()

    fun canRecoverRun(retainedRunId: String?, busy: Boolean): Boolean =
        !retainedRunId.isNullOrBlank() && !busy

    fun retainedRunIdAfterSnapshot(runId: String, terminal: Boolean): String? =
        if (terminal) null else runId.takeIf { it.isNotBlank() }
}

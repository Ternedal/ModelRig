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
        previewFresh: Boolean,
        busy: Boolean,
        hasRun: Boolean,
        recoveryPending: Boolean = false,
    ): Boolean = previewCanStart &&
        !busy &&
        !hasRun &&
        (recoveryPending || (normalizedSurface(serverSurface) == AGENT3_READONLY && previewFresh))

    fun readinessBindingMatches(
        currentPilotReportSha256: String?,
        currentPilotCandidateGitSha: String?,
        currentRigValidationReportSha256: String?,
        previewPilotReportSha256: String,
        previewPilotCandidateGitSha: String,
        previewRigValidationReportSha256: String,
    ): Boolean =
        !currentPilotReportSha256.isNullOrBlank() &&
        !currentPilotCandidateGitSha.isNullOrBlank() &&
        !currentRigValidationReportSha256.isNullOrBlank() &&
        currentPilotReportSha256 == previewPilotReportSha256 &&
        currentPilotCandidateGitSha == previewPilotCandidateGitSha &&
        currentRigValidationReportSha256 == previewRigValidationReportSha256

    fun previewDeadlineMillis(requestStartedAtMillis: Long, expiresInSeconds: Int?): Long? {
        if (requestStartedAtMillis < 0L || expiresInSeconds == null || expiresInSeconds <= 0) return null
        val ttlMillis = expiresInSeconds.toLong() * 1_000L
        return if (requestStartedAtMillis > Long.MAX_VALUE - ttlMillis) {
            Long.MAX_VALUE
        } else {
            requestStartedAtMillis + ttlMillis
        }
    }

    fun isPreviewFresh(deadlineMillis: Long?, nowMillis: Long): Boolean =
        deadlineMillis != null && nowMillis >= 0L && nowMillis < deadlineMillis

    fun isPreviewExpired(deadlineMillis: Long?, nowMillis: Long): Boolean =
        deadlineMillis != null && !isPreviewFresh(deadlineMillis, nowMillis)

    fun canStopPlan(planCanRequest: Boolean?, busy: Boolean): Boolean =
        planCanRequest == true && !busy

    fun shouldPoll(
        runTerminal: Boolean?,
        activeToolState: String?,
        activeToolRequestState: String?,
    ): Boolean = runTerminal == false ||
        activeToolState == "executing" ||
        activeToolRequestState == "pending"

    fun canResetTerminalHistory(
        runTerminal: Boolean?,
        activeToolState: String?,
        activeToolRequestState: String?,
        busy: Boolean,
    ): Boolean = runTerminal == true &&
        !shouldPoll(runTerminal, activeToolState, activeToolRequestState) &&
        !busy

    fun canCreateReviewPreview(
        message: String,
        busy: Boolean,
        hasRun: Boolean,
        runTerminal: Boolean?,
        terminationPresent: Boolean,
        activeToolState: String?,
        activeToolRequestState: String?,
    ): Boolean {
        if (message.isBlank() || busy) return false
        if (!hasRun) return true
        if (!terminationPresent) return false
        return canResetTerminalHistory(
            runTerminal = runTerminal,
            activeToolState = activeToolState,
            activeToolRequestState = activeToolRequestState,
            busy = false,
        )
    }

    fun canStartReviewPreview(
        planId: String?,
        hasSteps: Boolean,
        busy: Boolean,
        hasRun: Boolean,
    ): Boolean = !planId.isNullOrBlank() && hasSteps && !busy && !hasRun

    fun nextPublicationEpoch(current: Long): Long =
        if (current == Long.MAX_VALUE) 1L else current + 1L

    fun canPublish(requestEpoch: Long, currentEpoch: Long): Boolean =
        requestEpoch == currentEpoch

    fun hasRunAuthority(snapshotPresent: Boolean, retainedRunId: String?): Boolean =
        snapshotPresent || !retainedRunId.isNullOrBlank()

    fun hasTaskAuthority(
        snapshotPresent: Boolean,
        retainedRunId: String?,
        retainedStartPlanId: String?,
    ): Boolean =
        hasRunAuthority(snapshotPresent, retainedRunId) || !retainedStartPlanId.isNullOrBlank()

    fun canRecoverStart(
        retainedStartPlanId: String?,
        busy: Boolean,
        hasRun: Boolean,
    ): Boolean = !retainedStartPlanId.isNullOrBlank() && !busy && !hasRun

    fun canRecoverRun(retainedRunId: String?, busy: Boolean): Boolean =
        !retainedRunId.isNullOrBlank() && !busy

    fun retainedRunIdAfterSnapshot(runId: String, terminal: Boolean): String? =
        if (terminal) null else runId.takeIf { it.isNotBlank() }
}

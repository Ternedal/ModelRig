package dk.ternedal.modelrig.logic

/** Immutable operator intent that produced one reviewed replan Preview. */
internal data class Agent3ReplanPreviewIntent(
    val runId: String,
    val plannerModel: String?,
) {
    companion object {
        fun capture(runId: String, plannerModel: String): Agent3ReplanPreviewIntent? {
            val normalizedRunId = runId.trim()
            if (normalizedRunId.isBlank()) return null
            return Agent3ReplanPreviewIntent(
                runId = normalizedRunId,
                plannerModel = plannerModel.trim().takeIf { it.isNotEmpty() },
            )
        }
    }
}

/** Fail-closed publication/apply authority for Android reviewed replan previews. */
internal object Agent3ReplanPreviewPolicy {
    fun canPublish(
        requestIntent: Agent3ReplanPreviewIntent,
        currentIntent: Agent3ReplanPreviewIntent?,
        responseRunId: String,
    ): Boolean =
        currentIntent == requestIntent && responseRunId == requestIntent.runId

    fun canApply(
        previewId: String,
        previewRunId: String,
        busy: Boolean,
        currentIntent: Agent3ReplanPreviewIntent?,
        previewIntent: Agent3ReplanPreviewIntent?,
        currentConnection: Agent3ReviewConnectionBinding?,
        previewConnection: Agent3ReviewConnectionBinding?,
    ): Boolean =
        !busy &&
            previewId.isNotBlank() &&
            previewIntent != null &&
            currentIntent == previewIntent &&
            previewRunId == previewIntent.runId &&
            currentConnection != null &&
            currentConnection == previewConnection
}

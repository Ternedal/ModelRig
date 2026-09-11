package dk.ternedal.modelrig.desktop

/** Immutable operator intent represented by one reviewed replan Preview request. */
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

/** Fail-closed publication and Apply authority for desktop reviewed replan Previews. */
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
        currentConnection: Agent3DevConnectionBinding?,
        previewConnection: Agent3DevConnectionBinding?,
    ): Boolean =
        !busy &&
            previewId.isNotBlank() &&
            previewIntent != null &&
            currentIntent == previewIntent &&
            previewRunId == previewIntent.runId &&
            currentConnection != null &&
            currentConnection == previewConnection
}

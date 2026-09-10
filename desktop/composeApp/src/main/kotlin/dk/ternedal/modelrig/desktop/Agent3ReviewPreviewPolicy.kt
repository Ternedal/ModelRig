package dk.ternedal.modelrig.desktop

/** Local Start authority for the isolated reviewed Preview surface. */
internal object Agent3ReviewPreviewPolicy {
    fun canStart(
        planId: String?,
        planSize: Int,
        busy: Boolean,
        currentConnection: Agent3DevConnectionBinding?,
        previewConnection: Agent3DevConnectionBinding?,
    ): Boolean =
        !busy &&
            !planId.isNullOrBlank() &&
            planSize > 0 &&
            currentConnection != null &&
            currentConnection == previewConnection
}

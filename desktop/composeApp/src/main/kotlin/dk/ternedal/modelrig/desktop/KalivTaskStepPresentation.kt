package dk.ternedal.modelrig.desktop

/** Human-facing labels for the validated Agent 3 worker step-state contract. */
internal fun presentTaskStepState(raw: String?): String? {
    val state = raw?.trim()?.lowercase().orEmpty()
    if (state.isEmpty()) return null
    return when (state) {
        "pending" -> "Afventer"
        "completed_after_cancel" -> "Færdig efter stop"
        "waiting_confirmation" -> "Afventer godkendelse"
        "approved" -> "Godkendt"
        "executing" -> "Kører"
        "succeeded" -> "Fuldført"
        "denied" -> "Afvist"
        "blocked" -> "Blokeret"
        "failed" -> "Fejlet"
        else -> "Status ukendt"
    }
}

/**
 * The read-only task client accepts a step only when the server contract says
 * read risk, local egress and idempotent execution. Present exactly those
 * validated properties without exposing the transport key/value syntax.
 */
internal fun presentTaskStepReadOnlyMetadata(
    risk: String?,
    egress: String?,
    idempotent: Boolean,
): String = if (
    risk?.trim()?.lowercase() == "read" &&
    egress?.trim()?.lowercase() == "local" &&
    idempotent
) {
    "Kun læsning · lokal dataudgang · kan gentages"
} else {
    "Sikkerhedsmetadata ukendt"
}

/**
 * Human-facing error copy for the normal read-only task card. The persisted
 * worker/tool diagnostic remains untouched; arbitrary exception text is never
 * promoted to primary UI copy.
 */
internal fun presentTaskStepError(state: String?, rawError: String?): String? {
    val error = rawError?.trim().orEmpty()
    if (error.isEmpty()) return null
    val normalizedError = error.lowercase()
    val normalizedState = state?.trim()?.lowercase()
    return when {
        normalizedError == "read-only task policy drifted outside execute" ->
            "Trinnet blev blokeret af read-only-politikken."
        normalizedError == "run changed before execution could start" ->
            "Trinnet kunne ikke starte, fordi kørslens tilstand ændrede sig."
        normalizedState == "blocked" -> "Trinnet blev blokeret på riggen."
        normalizedState == "failed" -> "Trinnet fejlede på riggen."
        else -> "Riggen rapporterede et problem med trinnet."
    }
}

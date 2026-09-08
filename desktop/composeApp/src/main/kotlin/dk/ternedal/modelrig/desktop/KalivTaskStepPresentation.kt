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

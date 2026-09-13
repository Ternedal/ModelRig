package dk.ternedal.modelrig.ui

internal fun presentAgent3TaskStepHeadline(summary: String?): String =
    summary?.trim()?.takeIf { it.isNotEmpty() } ?: "Trin uden beskrivelse"

internal fun presentAgent3TaskStepState(raw: String?): String? {
    val state = raw?.trim()?.lowercase().orEmpty()
    if (state.isEmpty()) return null
    return when (state) {
        "pending" -> "Afventer"
        "executing" -> "Kører"
        "succeeded" -> "Fuldført"
        "completed_after_cancel" -> "Færdig efter stop"
        "blocked" -> "Blokeret"
        "failed" -> "Fejlet"
        else -> "Status ukendt"
    }
}

internal fun presentAgent3TaskStepToolAudit(tool: String): String = "Værktøjskode: $tool"

internal fun presentAgent3TaskStepReadOnlyMetadata(
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

internal fun presentAgent3TaskStepStructuredDetail(hasArgs: Boolean): String? =
    if (hasArgs) "Tekniske parametre skjult i oversigten" else null

internal fun presentAgent3TaskStepError(state: String?, rawError: String?): String? {
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

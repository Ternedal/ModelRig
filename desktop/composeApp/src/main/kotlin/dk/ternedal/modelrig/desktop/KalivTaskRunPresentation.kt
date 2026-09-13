package dk.ternedal.modelrig.desktop

/** Human-facing labels for validated Agent 3 task-run machine identifiers. */
internal fun presentTaskRunState(raw: String?): String = when (raw?.trim()?.lowercase()) {
    "running" -> "Kører"
    "blocked" -> "Blokeret"
    "completed" -> "Fuldført"
    "failed" -> "Fejlet"
    "cancelled" -> "Annulleret"
    else -> "Status ukendt"
}

internal fun presentTaskRunRoute(raw: String?): String = when (raw?.trim()?.lowercase()) {
    "rig_tools_local" -> "Lokal rig · værktøjer"
    else -> "Rute ukendt"
}

/**
 * Bound arbitrary persisted run errors to state-derived product copy.
 * Raw worker/tool diagnostics remain transport data and are never echoed here.
 */
internal fun presentTaskRunError(state: String?, rawError: String?): String? {
    if (rawError.isNullOrBlank()) return null
    return when (state?.trim()?.lowercase()) {
        "failed" -> "Kørslen fejlede på riggen."
        "blocked" -> "Kørslen blev blokeret på riggen."
        "cancelled" -> "Kørslen blev annulleret."
        else -> "Riggen rapporterede et problem med kørslen."
    }
}

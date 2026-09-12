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

package dk.ternedal.modelrig.desktop

/** Human-facing primary copy for the server-authoritative Agent 3 task-readiness contract. */
internal fun presentTaskReadinessHeadline(selectedSurface: String?): String = when (selectedSurface?.trim()?.lowercase()) {
    "agent3_readonly" -> "Agent 3 read-only valgt af serveren"
    "agent2" -> "Agent 2 fallback"
    else -> "Task-routing ikke tilgængelig"
}

internal fun presentTaskReadinessStatus(selectedSurface: String?, reason: String?): String {
    val surface = selectedSurface?.trim()?.lowercase()
    val why = reason?.trim()?.lowercase()
    return when {
        surface == "agent3_readonly" && why == "agent3_readonly_selected" ->
            "Agent 3 read-only er klar til denne taskflade."
        surface == "agent2" && why == "operator_disabled" ->
            "Agent 3 read-only er ikke slået til; Agent 2 bruges."
        surface == "agent2" && why == "pilot_report_path_not_configured" ->
            "Pilotbevis er ikke konfigureret; Agent 2 bruges."
        surface == "agent2" && why == "pilot_report_stale" ->
            "Pilotbeviset er udløbet; Agent 2 bruges."
        surface == "agent2" && why == "rig_validation_not_ready" ->
            "Rigvalideringen er ikke klar; Agent 2 bruges."
        surface == "agent2" ->
            "Agent 3 read-only er ikke klar; Agent 2 bruges."
        else -> "Kunne ikke hente task-routing fra riggen."
    }
}

internal fun presentTaskReadinessSurface(raw: String?): String = when (raw?.trim()?.lowercase()) {
    "agent3_readonly" -> "Agent 3 read-only"
    "agent2" -> "Agent 2"
    else -> "Ikke tilgængelig"
}

internal fun presentTaskReadinessRouteSource(raw: String?): String = when (raw?.trim()?.lowercase()) {
    "server_authoritative" -> "Serverstyret"
    else -> "Routing ukendt"
}

/**
 * The physical task-UI proof requires the exact server reason to remain visible.
 * Keep it explicitly secondary evidence rather than using the machine code as primary copy.
 */
internal fun presentTaskReadinessServerReason(raw: String?): String? =
    raw?.trim()?.takeIf { it.isNotEmpty() }?.let { "Serverkode: $it" }

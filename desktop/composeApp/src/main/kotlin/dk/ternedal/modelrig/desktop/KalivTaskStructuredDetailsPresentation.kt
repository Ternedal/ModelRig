package dk.ternedal.modelrig.desktop

/**
 * Human-facing policy for structured Agent 3 task details.
 *
 * Unknown JsonObject/JsonElement content is never serialized into primary operator copy.
 * The task surface may acknowledge that technical details exist without guessing at their meaning.
 */
internal fun presentTaskStepStructuredDetail(hasArgs: Boolean): String? =
    if (hasArgs) "Tekniske parametre skjult i oversigten" else null

internal fun presentTaskEventStructuredDetail(hasPayload: Boolean): String? =
    if (hasPayload) "Tekniske eventdetaljer skjult i oversigten" else null

/**
 * Event kinds are journal/audit vocabulary, not product copy. Known read-only task events get
 * bounded Danish labels. Unknown/future kinds fail closed to a generic human label.
 */
internal fun presentTaskEventKind(kind: String): String = when (kind) {
    "run_created" -> "Kørsel oprettet"
    "task_surface_bound" -> "Read-only-kørsel klargjort"
    "policy_decision" -> "Sikkerhedstjek udført"
    "step_started" -> "Trin startet"
    "step_succeeded" -> "Trin fuldført"
    "step_failed" -> "Trin fejlede"
    "step_failed_after_cancel" -> "Trin fejlede efter stop"
    "step_completed_after_cancel" -> "Trin blev færdigt efter stop"
    "run_completed" -> "Opgaven fuldført"
    "run_cancelled" -> "Opgaven stoppet"
    "task_surface_violation" -> "Read-only-politikken blokerede opgaven"
    "task_execution_failed" -> "Opgaven fejlede under udførelse"
    else -> "Teknisk hændelse"
}

/** Preserve the exact server-authored journal kind as secondary audit evidence. */
internal fun presentTaskEventAuditCode(kind: String): String = "Eventkode: $kind"

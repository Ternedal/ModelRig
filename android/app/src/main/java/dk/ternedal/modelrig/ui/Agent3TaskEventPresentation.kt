package dk.ternedal.modelrig.ui

/** Human-facing labels for the validated Agent 3 task journal contract. */
internal fun presentAgent3TaskEventKind(kind: String): String = when (kind.trim().lowercase()) {
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
internal fun presentAgent3TaskEventAuditCode(kind: String): String = "Eventkode: $kind"

/** Never serialize structured event payload into the normal operator overview. */
internal fun presentAgent3TaskEventStructuredDetail(payload: String?): String? =
    payload?.takeIf { it.isNotBlank() }?.let { "Tekniske eventdetaljer skjult i oversigten" }

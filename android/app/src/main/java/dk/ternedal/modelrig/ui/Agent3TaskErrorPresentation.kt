package dk.ternedal.modelrig.ui

internal enum class Agent3TaskFailureOperation {
    READINESS,
    PREVIEW,
    START,
    START_NOT_ACCEPTED,
    START_REFUSED,
    STATUS,
    STOP_PLAN,
    AUTOMATIC_STATUS,
    LOCAL_REFERENCE,
    START_RECOVERY_REFERENCE,
}

/**
 * Keep arbitrary client/server diagnostics out of primary task UI.
 * Only local configuration messages owned by this screen are allowed through as
 * specific actionable copy; all other failures are bounded by operation.
 */
internal fun presentAgent3TaskScreenError(
    operation: Agent3TaskFailureOperation,
    rawMessage: String?,
): String {
    return when (rawMessage?.trim()) {
        "Ingen rig-URL er gemt" -> "Ingen rig-URL er gemt."
        "Ingen device-token er gemt" -> "Ingen device-token er gemt."
        else -> when (operation) {
            Agent3TaskFailureOperation.READINESS -> "Task-routing kunne ikke hentes."
            Agent3TaskFailureOperation.PREVIEW -> "Plan-preview kunne ikke hentes."
            Agent3TaskFailureOperation.START ->
                "Startstatus kunne ikke bekræftes. Prøv Start igen; samme preview starter ikke en ny task."
            Agent3TaskFailureOperation.START_NOT_ACCEPTED ->
                "Opgaven blev ikke accepteret. Prøv samme preview igen."
            Agent3TaskFailureOperation.START_REFUSED ->
                "Opgaven blev ikke accepteret. Lav et nyt plan-preview."
            Agent3TaskFailureOperation.STATUS -> "Task-status kunne ikke hentes."
            Agent3TaskFailureOperation.STOP_PLAN -> "Planen kunne ikke stoppes."
            Agent3TaskFailureOperation.AUTOMATIC_STATUS -> "Automatisk task-status kunne ikke hentes."
            Agent3TaskFailureOperation.LOCAL_REFERENCE ->
                "Task-referencen kunne ikke gemmes lokalt. Hold taskfladen åben."
            Agent3TaskFailureOperation.START_RECOVERY_REFERENCE ->
                "Start blev ikke sendt, fordi recovery-referencen ikke kunne gemmes lokalt."
        }
    }
}

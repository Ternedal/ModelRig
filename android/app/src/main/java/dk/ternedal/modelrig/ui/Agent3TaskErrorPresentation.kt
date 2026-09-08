package dk.ternedal.modelrig.ui

internal enum class Agent3TaskFailureOperation {
    READINESS,
    PREVIEW,
    START,
    STATUS,
    STOP_PLAN,
    AUTOMATIC_STATUS,
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
            Agent3TaskFailureOperation.START -> "Opgaven kunne ikke startes."
            Agent3TaskFailureOperation.STATUS -> "Task-status kunne ikke hentes."
            Agent3TaskFailureOperation.STOP_PLAN -> "Planen kunne ikke stoppes."
            Agent3TaskFailureOperation.AUTOMATIC_STATUS -> "Automatisk task-status kunne ikke hentes."
        }
    }
}

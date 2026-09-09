package dk.ternedal.modelrig.desktop

internal enum class TaskRequestOperation {
    READINESS,
    PREVIEW,
    START,
    STATUS,
    STOP_PLAN,
    POLLING,
    LOCAL_REFERENCE,
    UNKNOWN,
}

private const val MISSING_BACKEND = "Ingen ModelRig backend-URL er gemt"
private const val MISSING_TOKEN = "Ingen device-token er gemt"

/**
 * Keep arbitrary transport/client diagnostics out of the human-facing task surface.
 * Only exact product-owned prerequisite messages retain distinct presentation.
 */
internal fun presentTaskRequestError(operation: TaskRequestOperation, rawError: String?): String {
    return when (rawError?.trim()) {
        MISSING_BACKEND -> "Backend-adressen mangler."
        MISSING_TOKEN -> "Device-token mangler."
        else -> when (operation) {
            TaskRequestOperation.READINESS -> "Task-readiness kunne ikke hentes."
            TaskRequestOperation.PREVIEW -> "Plan-preview kunne ikke hentes."
            TaskRequestOperation.START -> "Opgaven kunne ikke startes."
            TaskRequestOperation.STATUS -> "Task-status kunne ikke hentes."
            TaskRequestOperation.STOP_PLAN -> "Planen kunne ikke stoppes."
            TaskRequestOperation.POLLING -> "Automatisk task-status kunne ikke hentes."
            TaskRequestOperation.LOCAL_REFERENCE ->
                "Task-referencen kunne ikke gemmes lokalt. Hold taskfladen åben."
            TaskRequestOperation.UNKNOWN -> "Task-handlingen kunne ikke gennemføres."
        }
    }
}

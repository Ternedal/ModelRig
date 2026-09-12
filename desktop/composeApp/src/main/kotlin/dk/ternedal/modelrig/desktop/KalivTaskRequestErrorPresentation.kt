package dk.ternedal.modelrig.desktop

internal enum class TaskRequestOperation {
    READINESS,
    PREVIEW,
    START,
    START_NOT_ACCEPTED,
    START_REFUSED,
    STATUS,
    STOP_PLAN,
    POLLING,
    LOCAL_REFERENCE,
    START_RECOVERY_REFERENCE,
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
            TaskRequestOperation.START ->
                "Startstatus kunne ikke bekræftes. Prøv Start igen; samme preview starter ikke en ny task."
            TaskRequestOperation.START_NOT_ACCEPTED ->
                "Opgaven blev ikke accepteret. Prøv samme preview igen."
            TaskRequestOperation.START_REFUSED ->
                "Opgaven blev ikke accepteret. Lav et nyt plan-preview."
            TaskRequestOperation.STATUS -> "Task-status kunne ikke hentes."
            TaskRequestOperation.STOP_PLAN ->
                "Stop-resultatet kunne ikke bekræftes. Planen kan allerede være stoppet på serveren. Opdatér task-status før du konkluderer eller prøver igen."
            TaskRequestOperation.POLLING -> "Automatisk task-status kunne ikke hentes."
            TaskRequestOperation.LOCAL_REFERENCE ->
                "Task-referencen kunne ikke gemmes lokalt. Hold taskfladen åben."
            TaskRequestOperation.START_RECOVERY_REFERENCE ->
                "Start blev ikke sendt, fordi recovery-referencen ikke kunne gemmes lokalt."
            TaskRequestOperation.UNKNOWN -> "Task-handlingen kunne ikke gennemføres."
        }
    }
}

package dk.ternedal.modelrig.desktop

/** Human-facing primary copy for the read-only capability gate. */
internal fun presentTaskCapabilityStatus(allowed: Boolean?): String = when (allowed) {
    true -> "Read-only-planen bestod kapabilitetstjekket."
    false -> "Read-only-planen er blokeret af kapabilitetstjekket."
    null -> "Kapabilitetskvittering er ikke tilgængelig."
}

/** Route presentation shares the already bounded task-run route policy. */
internal fun presentTaskCapabilityRoute(route: String?): String = presentTaskRunRoute(route)

/** Blocker count is safe bounded product copy; blocker contents are not interpreted here. */
internal fun presentTaskCapabilityBlockerCount(count: Int): String = when {
    count <= 0 -> "Ingen blokeringer"
    count == 1 -> "1 blokering"
    else -> "$count blokeringer"
}

internal data class TaskCapabilityEvidence(
    val label: String,
    val value: String,
)

/**
 * Preserve exact server-authored blocker fields only as explicitly labelled technical receipt evidence.
 * These values are deliberately never interpreted into primary product claims.
 */
internal fun taskCapabilityBlockerEvidence(
    capabilityId: String,
    state: String,
    reason: String,
): List<TaskCapabilityEvidence> = listOf(
    TaskCapabilityEvidence("Capability-id", capabilityId),
    TaskCapabilityEvidence("State", state),
    TaskCapabilityEvidence("Reason", reason),
)

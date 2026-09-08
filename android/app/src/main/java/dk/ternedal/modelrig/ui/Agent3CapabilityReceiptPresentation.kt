package dk.ternedal.modelrig.ui

internal fun presentAgent3CapabilityStatusLabel(allowed: Boolean): String =
    if (allowed) "KLAR" else "BLOKERET"

internal fun presentAgent3CapabilityStatusMessage(allowed: Boolean): String =
    if (allowed) {
        "Planen bestod kapabilitetstjekket."
    } else {
        "Planen er blokeret af kapabilitetstjekket."
    }

internal fun presentAgent3CapabilityRoute(route: String?): String = when (route?.trim()?.lowercase()) {
    "rig_tools_local" -> "Lokal rig · værktøjer"
    else -> "Rute ukendt"
}

internal fun presentAgent3RequiredCapabilityCount(count: Int): String = when {
    count <= 0 -> "Ingen krav"
    count == 1 -> "1 krav"
    else -> "$count krav"
}

internal fun presentAgent3CapabilityBlockerCount(count: Int): String = when {
    count <= 0 -> "Ingen blokeringer"
    count == 1 -> "1 blokering"
    else -> "$count blokeringer"
}

internal data class Agent3CapabilityEvidence(
    val label: String,
    val value: String,
)

internal fun agent3RequiredCapabilityEvidence(capabilityId: String): Agent3CapabilityEvidence =
    Agent3CapabilityEvidence("Capability-id", capabilityId)

internal fun agent3CapabilityBlockerEvidence(
    capabilityId: String,
    state: String,
    reason: String,
): List<Agent3CapabilityEvidence> = listOf(
    Agent3CapabilityEvidence("Capability-id", capabilityId),
    Agent3CapabilityEvidence("State", state),
    Agent3CapabilityEvidence("Reason", reason),
)

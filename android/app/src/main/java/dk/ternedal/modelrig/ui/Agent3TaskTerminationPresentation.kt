package dk.ternedal.modelrig.ui

/** Human-facing copy is bounded; exact receipt values live only in explicit audit evidence. */
internal fun presentAgent3TerminationPlanState(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "available" -> "Planen kan stoppes"
    "terminal" -> "Planen er afsluttet"
    else -> "Planstatus ukendt"
}

internal fun presentAgent3TerminationPlanScope(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "plan" -> "Hele planen"
    else -> "Stopomfang ukendt"
}

internal fun presentAgent3TerminationPlanEffect(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "prevent_future_steps" -> "Kommende trin forhindres"
    "prevent_future_steps_active_tool_continues" -> "Kommende trin forhindres; aktivt værktøj kan fortsætte"
    else -> "Stopeffekt ukendt"
}

internal fun presentAgent3TerminationModelState(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "not_active" -> "Ingen aktiv modelstream"
    else -> "Modelstream-status ukendt"
}

internal fun presentAgent3TerminationSemantics(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "none" -> "Ingen afbrydelsesmekanisme"
    "cooperative" -> "Kooperativ afbrydelse"
    "runtime" -> "Runtime-afbrydelse"
    else -> "Afbrydelsesmekanisme ukendt"
}

internal fun presentAgent3TerminationRequestState(raw: String?): String = when (raw.normalizedTerminationValue()) {
    "available" -> "Stop kan anmodes"
    "pending" -> "Stopanmodning behandles"
    "terminal" -> "Stoptilstanden er afsluttet"
    "unavailable" -> "Direkte stop er ikke tilgængeligt"
    "not_active" -> "Værktøjet er ikke aktivt"
    else -> "Stopstatus ukendt"
}

internal data class Agent3TaskTerminationEvidence(val label: String, val value: String)

internal fun agent3TerminationPlanEvidence(
    state: String,
    canRequest: Boolean,
    requestScope: String,
    effect: String,
    reason: String,
): List<Agent3TaskTerminationEvidence> = listOf(
    Agent3TaskTerminationEvidence("state", state),
    Agent3TaskTerminationEvidence("can_request", canRequest.toString()),
    Agent3TaskTerminationEvidence("request_scope", requestScope),
    Agent3TaskTerminationEvidence("effect", effect),
    Agent3TaskTerminationEvidence("reason", reason),
)

internal fun agent3TerminationModelEvidence(
    state: String,
    active: Boolean,
    canRequest: Boolean,
    handlePresent: Boolean,
    reason: String,
): List<Agent3TaskTerminationEvidence> = listOf(
    Agent3TaskTerminationEvidence("state", state),
    Agent3TaskTerminationEvidence("active", active.toString()),
    Agent3TaskTerminationEvidence("can_request", canRequest.toString()),
    Agent3TaskTerminationEvidence("handle_present", handlePresent.toString()),
    Agent3TaskTerminationEvidence("reason", reason),
)

internal fun agent3TerminationActiveToolEvidence(
    stepId: String,
    tool: String,
    state: String,
    semantics: String?,
    handlePresent: Boolean,
    canRequest: Boolean,
    requestState: String,
    reason: String,
): List<Agent3TaskTerminationEvidence> = listOf(
    Agent3TaskTerminationEvidence("step_id", stepId),
    Agent3TaskTerminationEvidence("tool", tool),
    Agent3TaskTerminationEvidence("state", state),
    Agent3TaskTerminationEvidence("semantics", semantics ?: "null"),
    Agent3TaskTerminationEvidence("handle_present", handlePresent.toString()),
    Agent3TaskTerminationEvidence("can_request", canRequest.toString()),
    Agent3TaskTerminationEvidence("request_state", requestState),
    Agent3TaskTerminationEvidence("reason", reason),
)

private fun String?.normalizedTerminationValue(): String = this?.trim()?.lowercase().orEmpty()

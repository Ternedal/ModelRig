package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.Agent3TerminationActiveTool
import dk.ternedal.modelrig.desktop.net.Agent3TerminationModelStream
import dk.ternedal.modelrig.desktop.net.Agent3TerminationPlan

/** Human-facing copy is bounded; raw receipt values live only in explicit audit evidence. */
internal fun presentTerminationPlanState(raw: String?): String = when (raw.normalized()) {
    "available" -> "Planen kan stoppes"
    "terminal" -> "Planen er afsluttet"
    else -> "Planstatus ukendt"
}

internal fun presentTerminationPlanScope(raw: String?): String = when (raw.normalized()) {
    "plan" -> "Hele planen"
    else -> "Stopomfang ukendt"
}

internal fun presentTerminationPlanEffect(raw: String?): String = when (raw.normalized()) {
    "prevent_future_steps" -> "Kommende trin forhindres"
    "prevent_future_steps_active_tool_continues" -> "Kommende trin forhindres; aktivt værktøj kan fortsætte"
    else -> "Stopeffekt ukendt"
}

internal fun presentTerminationModelState(raw: String?): String = when (raw.normalized()) {
    "not_active" -> "Ingen aktiv modelstream"
    else -> "Modelstream-status ukendt"
}

internal fun presentTerminationSemantics(raw: String?): String = when (raw.normalized()) {
    "none" -> "Ingen afbrydelsesmekanisme"
    "cooperative" -> "Kooperativ afbrydelse"
    "runtime" -> "Runtime-afbrydelse"
    else -> "Afbrydelsesmekanisme ukendt"
}

internal fun presentTerminationRequestState(raw: String?): String = when (raw.normalized()) {
    "available" -> "Stop kan anmodes"
    "pending" -> "Stopanmodning behandles"
    "terminal" -> "Stoptilstanden er afsluttet"
    "unavailable" -> "Direkte stop er ikke tilgængeligt"
    "not_active" -> "Værktøjet er ikke aktivt"
    else -> "Stopstatus ukendt"
}

internal data class TaskTerminationEvidence(val label: String, val value: String)

internal fun terminationPlanEvidence(plan: Agent3TerminationPlan): List<TaskTerminationEvidence> = listOf(
    TaskTerminationEvidence("state", plan.state),
    TaskTerminationEvidence("can_request", plan.canRequest.toString()),
    TaskTerminationEvidence("request_scope", plan.requestScope),
    TaskTerminationEvidence("effect", plan.effect),
    TaskTerminationEvidence("reason", plan.reason),
)

internal fun terminationModelEvidence(model: Agent3TerminationModelStream): List<TaskTerminationEvidence> = listOf(
    TaskTerminationEvidence("state", model.state),
    TaskTerminationEvidence("active", model.active.toString()),
    TaskTerminationEvidence("can_request", model.canRequest.toString()),
    TaskTerminationEvidence("handle_present", model.handlePresent.toString()),
    TaskTerminationEvidence("reason", model.reason),
)

internal fun terminationActiveToolEvidence(active: Agent3TerminationActiveTool): List<TaskTerminationEvidence> = listOf(
    TaskTerminationEvidence("step_id", active.stepId),
    TaskTerminationEvidence("tool", active.tool),
    TaskTerminationEvidence("state", active.state),
    TaskTerminationEvidence("semantics", active.semantics ?: "null"),
    TaskTerminationEvidence("handle_present", active.handlePresent.toString()),
    TaskTerminationEvidence("can_request", active.canRequest.toString()),
    TaskTerminationEvidence("request_state", active.requestState),
    TaskTerminationEvidence("reason", active.reason),
)

private fun String?.normalized(): String = this?.trim()?.lowercase().orEmpty()

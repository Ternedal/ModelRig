package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.Agent3TerminationActiveTool
import dk.ternedal.modelrig.desktop.net.Agent3TerminationModelStream
import dk.ternedal.modelrig.desktop.net.Agent3TerminationPlan
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class KalivTaskTerminationPresentationTest {
    @Test
    fun validatedPlanAndModelStatesUseDeterministicHumanCopy() {
        assertEquals("Planen kan stoppes", presentTerminationPlanState("available"))
        assertEquals("Planen er afsluttet", presentTerminationPlanState("terminal"))
        assertEquals("Hele planen", presentTerminationPlanScope("plan"))
        assertEquals("Kommende trin forhindres", presentTerminationPlanEffect("prevent_future_steps"))
        assertEquals(
            "Kommende trin forhindres; aktivt værktøj kan fortsætte",
            presentTerminationPlanEffect("prevent_future_steps_active_tool_continues"),
        )
        assertEquals("Ingen aktiv modelstream", presentTerminationModelState("not_active"))
    }

    @Test
    fun validatedToolSemanticsAndRequestStatesUseDeterministicHumanCopy() {
        val semantics = mapOf(
            "none" to "Ingen afbrydelsesmekanisme",
            "cooperative" to "Kooperativ afbrydelse",
            "runtime" to "Runtime-afbrydelse",
        )
        semantics.forEach { (raw, expected) -> assertEquals(expected, presentTerminationSemantics(raw)) }

        val requestStates = mapOf(
            "available" to "Stop kan anmodes",
            "pending" to "Stopanmodning behandles",
            "terminal" to "Stoptilstanden er afsluttet",
            "unavailable" to "Direkte stop er ikke tilgængeligt",
            "not_active" to "Værktøjet er ikke aktivt",
        )
        requestStates.forEach { (raw, expected) -> assertEquals(expected, presentTerminationRequestState(raw)) }
    }

    @Test
    fun unknownFutureValuesFailClosedWithoutBeingEchoedAsPrimaryCopy() {
        val future = "future_internal_state_secret"
        val primary = listOf(
            presentTerminationPlanState(future),
            presentTerminationPlanScope(future),
            presentTerminationPlanEffect(future),
            presentTerminationModelState(future),
            presentTerminationSemantics(future),
            presentTerminationRequestState(future),
        )
        assertEquals(
            listOf(
                "Planstatus ukendt",
                "Stopomfang ukendt",
                "Stopeffekt ukendt",
                "Modelstream-status ukendt",
                "Afbrydelsesmekanisme ukendt",
                "Stopstatus ukendt",
            ),
            primary,
        )
        assertFalse(primary.any { future in it })
    }

    @Test
    fun technicalPlanAndModelEvidencePreservesExactReceiptValues() {
        val reason = "server_reason C:\\rig\\private /internal?token=abc\nsecond-line"
        val plan = Agent3TerminationPlan(
            state = "available",
            canRequest = true,
            requestScope = "plan",
            effect = "prevent_future_steps_active_tool_continues",
            reason = reason,
        )
        val model = Agent3TerminationModelStream(
            state = "not_active",
            active = false,
            canRequest = false,
            handlePresent = false,
            reason = "agent3_run_has_no_model_stream_handle",
        )

        assertEquals("available", terminationPlanEvidence(plan).value("state"))
        assertEquals("true", terminationPlanEvidence(plan).value("can_request"))
        assertEquals("plan", terminationPlanEvidence(plan).value("request_scope"))
        assertEquals("prevent_future_steps_active_tool_continues", terminationPlanEvidence(plan).value("effect"))
        assertEquals(reason, terminationPlanEvidence(plan).value("reason"))
        assertEquals("not_active", terminationModelEvidence(model).value("state"))
        assertEquals("agent3_run_has_no_model_stream_handle", terminationModelEvidence(model).value("reason"))
    }

    @Test
    fun technicalActiveToolEvidencePreservesT023FieldsExactly() {
        val active = Agent3TerminationActiveTool(
            stepId = "step-17",
            tool = "rig_status",
            state = "completed_after_cancel",
            semantics = "runtime",
            handlePresent = true,
            canRequest = false,
            requestState = "terminal",
            reason = "tool_completed_after_plan_cancel",
        )
        val evidence = terminationActiveToolEvidence(active)

        assertEquals("step-17", evidence.value("step_id"))
        assertEquals("rig_status", evidence.value("tool"))
        assertEquals("completed_after_cancel", evidence.value("state"))
        assertEquals("runtime", evidence.value("semantics"))
        assertEquals("true", evidence.value("handle_present"))
        assertEquals("false", evidence.value("can_request"))
        assertEquals("terminal", evidence.value("request_state"))
        assertEquals("tool_completed_after_plan_cancel", evidence.value("reason"))
    }

    private fun List<TaskTerminationEvidence>.value(label: String): String = single { it.label == label }.value
}

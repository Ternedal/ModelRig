package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3TaskTerminationPresentationTest {
    @Test
    fun `plan receipt values map to bounded human copy`() {
        assertEquals("Planen kan stoppes", presentAgent3TerminationPlanState("available"))
        assertEquals("Planen er afsluttet", presentAgent3TerminationPlanState("terminal"))
        assertEquals("Hele planen", presentAgent3TerminationPlanScope("plan"))
        assertEquals("Kommende trin forhindres", presentAgent3TerminationPlanEffect("prevent_future_steps"))
        assertEquals(
            "Kommende trin forhindres; aktivt værktøj kan fortsætte",
            presentAgent3TerminationPlanEffect("prevent_future_steps_active_tool_continues"),
        )
    }

    @Test
    fun `unknown plan and model values fail closed without echoing raw text`() {
        val rawState = "https://worker.local/internal?token=secret"
        val rawEffect = "future_effect_secret"

        val planState = presentAgent3TerminationPlanState(rawState)
        val planScope = presentAgent3TerminationPlanScope(rawState)
        val planEffect = presentAgent3TerminationPlanEffect(rawEffect)
        val modelState = presentAgent3TerminationModelState(rawState)

        assertEquals("Planstatus ukendt", planState)
        assertEquals("Stopomfang ukendt", planScope)
        assertEquals("Stopeffekt ukendt", planEffect)
        assertEquals("Modelstream-status ukendt", modelState)
        listOf(planState, planScope, planEffect, modelState).forEach { copy ->
            assertFalse(copy.contains("worker.local"))
            assertFalse(copy.contains("secret"))
        }
    }

    @Test
    fun `termination semantics and request states are bounded`() {
        assertEquals("Ingen afbrydelsesmekanisme", presentAgent3TerminationSemantics("none"))
        assertEquals("Kooperativ afbrydelse", presentAgent3TerminationSemantics("cooperative"))
        assertEquals("Runtime-afbrydelse", presentAgent3TerminationSemantics("runtime"))
        assertEquals("Afbrydelsesmekanisme ukendt", presentAgent3TerminationSemantics("custom-runtime-secret"))

        assertEquals("Stop kan anmodes", presentAgent3TerminationRequestState("available"))
        assertEquals("Stopanmodning behandles", presentAgent3TerminationRequestState("pending"))
        assertEquals("Stoptilstanden er afsluttet", presentAgent3TerminationRequestState("terminal"))
        assertEquals("Direkte stop er ikke tilgængeligt", presentAgent3TerminationRequestState("unavailable"))
        assertEquals("Værktøjet er ikke aktivt", presentAgent3TerminationRequestState("not_active"))
        assertEquals("Stopstatus ukendt", presentAgent3TerminationRequestState("custom-request-secret"))
    }

    @Test
    fun `exact raw receipt values remain available only as audit evidence`() {
        val planReason = "policy://plan?token=secret"
        val modelReason = "model://runtime/internal"
        val toolReason = "tool://worker/private"
        val toolId = "filesystem.read.secret"

        val planEvidence = agent3TerminationPlanEvidence(
            state = "available",
            canRequest = true,
            requestScope = "plan",
            effect = "prevent_future_steps_active_tool_continues",
            reason = planReason,
        )
        val modelEvidence = agent3TerminationModelEvidence(
            state = "not_active",
            active = false,
            canRequest = false,
            handlePresent = false,
            reason = modelReason,
        )
        val toolEvidence = agent3TerminationActiveToolEvidence(
            stepId = "step-7",
            tool = toolId,
            state = "executing",
            semantics = "cooperative",
            handlePresent = true,
            canRequest = true,
            requestState = "available",
            reason = toolReason,
        )

        assertTrue(planEvidence.contains(Agent3TaskTerminationEvidence("reason", planReason)))
        assertTrue(modelEvidence.contains(Agent3TaskTerminationEvidence("reason", modelReason)))
        assertTrue(toolEvidence.contains(Agent3TaskTerminationEvidence("tool", toolId)))
        assertTrue(toolEvidence.contains(Agent3TaskTerminationEvidence("reason", toolReason)))
        assertTrue(toolEvidence.contains(Agent3TaskTerminationEvidence("step_id", "step-7")))
    }
}

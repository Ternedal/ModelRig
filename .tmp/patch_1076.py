from pathlib import Path
import re

client_path = Path('android/app/src/main/java/dk/ternedal/modelrig/net/Agent3Client.kt')
text = client_path.read_text(encoding='utf-8')

old = '''        val termination = parseTerminationReceipt(root.optJSONObject("termination"))
        val envelope = RunEnvelope(
            run = parseRun(root.requireObject("run")).copy(termination = termination),
'''
new = '''        val parsedRun = parseRun(root.requireObject("run"))
        val termination = validateTerminationReceipt(
            parseTerminationReceipt(root.optJSONObject("termination")),
            parsedRun,
        )
        val envelope = RunEnvelope(
            run = parsedRun.copy(termination = termination),
'''
if old not in text:
    raise SystemExit('parseRunEnvelope anchor not found')
text = text.replace(old, new, 1)

old = '''        validateTerminationReceipt(parsed)
        return parsed
    }

    private fun validateTerminationReceipt(receipt: TerminationReceipt) {
'''
new = '''        return parsed
    }

    private fun validateTerminationReceipt(
        receipt: TerminationReceipt?,
        run: Run,
    ): TerminationReceipt {
'''
if old not in text:
    raise SystemExit('termination validator anchor not found')
text = text.replace(old, new, 1)

start = text.index('    private fun validateTerminationReceipt(\n')
end = text.index('    private fun parseMemoryReceipt', start)
validator = '''    private fun validateTerminationReceipt(
        receipt: TerminationReceipt?,
        run: Run,
    ): TerminationReceipt {
        val value = receipt
            ?: throw ModelRigException("Ugyldigt termination receipt: mangler for run-svar")
        if (value.schema != "kaliv-agent3-termination/v1") {
            throw ModelRigException("Ukendt termination receipt-schema: ${value.schema}")
        }
        if (value.productionActivation) {
            throw ModelRigException("Ugyldigt termination receipt: produktion må aldrig aktiveres")
        }

        val runStates = setOf(
            "running",
            "waiting_confirmation",
            "blocked",
            "completed",
            "failed",
            "cancelled",
        )
        val terminalStates = setOf("blocked", "completed", "failed", "cancelled")
        val stepStates = setOf(
            "pending",
            "completed_after_cancel",
            "waiting_confirmation",
            "approved",
            "executing",
            "succeeded",
            "denied",
            "blocked",
            "failed",
        )
        val requestStates = setOf("available", "pending", "terminal", "unavailable", "not_active")
        val semantics = setOf<String?>(null, "none", "cooperative", "runtime")

        if (run.id.isBlank() || run.state !in runStates || run.currentStep < 0 || run.currentStep > run.steps.size) {
            throw ModelRigException("Ugyldigt termination receipt: run-identitet/tilstand/current step er ugyldig")
        }
        if (run.steps.any { it.state == null || it.state !in stepStates }) {
            throw ModelRigException("Ugyldigt termination receipt: step-tilstand er uden for Agent 3")
        }

        val terminal = run.state in terminalStates
        val expectedPlanState = if (terminal) "terminal" else "available"
        val current = run.steps.getOrNull(run.currentStep)
        val executing = current?.state == "executing"
        val expectedEffect = if (executing) {
            "prevent_future_steps_active_tool_continues"
        } else {
            "prevent_future_steps"
        }
        val plan = value.plan
        if (
            plan.state != expectedPlanState ||
            plan.canRequest != !terminal ||
            plan.requestScope != "plan" ||
            plan.effect != expectedEffect ||
            plan.reason.isBlank()
        ) {
            throw ModelRigException("Ugyldigt termination receipt: plan-scope er inkonsistent med run")
        }

        val stream = value.modelStream
        if (
            stream.state != "not_active" ||
            stream.active ||
            stream.canRequest ||
            stream.handlePresent ||
            stream.reason.isBlank()
        ) {
            throw ModelRigException("Ugyldigt termination receipt: model-stream er inkonsistent med run")
        }

        val active = value.activeTool
        if ((active == null) != (current == null)) {
            throw ModelRigException("Ugyldigt termination receipt: active_tool matcher ikke current step")
        }
        if (active == null) return value

        if (
            active.stepId.isBlank() ||
            active.tool.isBlank() ||
            active.state !in stepStates ||
            active.requestState !in requestStates ||
            active.reason.isBlank() ||
            active.semantics !in semantics ||
            active.stepId != current?.id ||
            active.tool != current?.tool ||
            active.state != current?.state ||
            (active.canRequest && !active.handlePresent) ||
            (active.canRequest && active.semantics !in setOf("cooperative", "runtime"))
        ) {
            throw ModelRigException("Ugyldigt termination receipt: active_tool matcher ikke current step")
        }
        if (active.state == "executing" && active.requestState == "terminal") {
            throw ModelRigException("Ugyldigt termination receipt: executing tool kan ikke være terminal")
        }
        if (active.state == "completed_after_cancel" && active.requestState != "terminal") {
            throw ModelRigException("Ugyldigt termination receipt: late completion er ikke terminal")
        }
        if (active.requestState == "available" && !active.canRequest) {
            throw ModelRigException("Ugyldigt termination receipt: available tool-control kan ikke være ikke-requestable")
        }
        return value
    }

'''
text = text[:start] + validator + text[end:]
client_path.write_text(text, encoding='utf-8')

test_path = Path('android/app/src/test/java/dk/ternedal/modelrig/net/Agent3TerminationRunTruthTest.kt')
test_path.write_text(r'''package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3TerminationRunTruthTest {
    @Test
    fun missingReceiptFailsClosed() {
        val error = call(runEnvelope("completed", emptyList(), 0, null))
        assertTrue(error is ModelRigException)
        assertEquals("Ugyldigt termination receipt: mangler for run-svar", error?.message)
    }

    @Test
    fun terminalRunCannotClaimAvailablePlan() {
        val error = call(
            runEnvelope(
                state = "completed",
                steps = emptyList(),
                currentStep = 0,
                termination = termination(planState = "available", planCanRequest = true),
            )
        )
        assertTrue(error is ModelRigException)
        assertEquals("Ugyldigt termination receipt: plan-scope er inkonsistent med run", error?.message)
    }

    @Test
    fun activeToolMustMatchCurrentStep() {
        val error = call(
            runEnvelope(
                state = "running",
                steps = listOf(step("step-1", "rig_status", "pending")),
                currentStep = 0,
                termination = termination(
                    planState = "available",
                    planCanRequest = true,
                    active = active("step-2", "rig_status", "pending", "not_active"),
                ),
            )
        )
        assertTrue(error is ModelRigException)
        assertEquals("Ugyldigt termination receipt: active_tool matcher ikke current step", error?.message)
    }

    @Test
    fun validRunningReceiptIsAccepted() {
        val body = runEnvelope(
            state = "running",
            steps = listOf(step("step-1", "rig_status", "pending")),
            currentStep = 0,
            termination = termination(
                planState = "available",
                planCanRequest = true,
                active = active("step-1", "rig_status", "pending", "not_active"),
            ),
        )
        val run = run(body)
        assertEquals("running", run.state)
        assertEquals("step-1", run.termination?.activeTool?.stepId)
    }

    @Test
    fun validWaitingConfirmationReceiptIsAccepted() {
        val body = runEnvelope(
            state = "waiting_confirmation",
            steps = listOf(step("step-1", "write_setting", "waiting_confirmation")),
            currentStep = 0,
            termination = termination(
                planState = "available",
                planCanRequest = true,
                active = active("step-1", "write_setting", "waiting_confirmation", "not_active"),
            ),
        )
        assertEquals("waiting_confirmation", run(body).state)
    }

    @Test
    fun validCancelledExecutingReceiptKeepsActiveToolTruth() {
        val body = runEnvelope(
            state = "cancelled",
            steps = listOf(step("step-1", "rig_status", "executing")),
            currentStep = 0,
            termination = termination(
                planState = "terminal",
                planCanRequest = false,
                effect = "prevent_future_steps_active_tool_continues",
                active = active("step-1", "rig_status", "executing", "unavailable"),
            ),
        )
        val run = run(body)
        assertEquals("cancelled", run.state)
        assertEquals("executing", run.termination?.activeTool?.state)
    }

    @Test
    fun validLateCompletionReceiptIsAccepted() {
        val body = runEnvelope(
            state = "cancelled",
            steps = listOf(step("step-1", "rig_status", "completed_after_cancel")),
            currentStep = 0,
            termination = termination(
                planState = "terminal",
                planCanRequest = false,
                active = active("step-1", "rig_status", "completed_after_cancel", "terminal"),
            ),
        )
        assertEquals("completed_after_cancel", run(body).termination?.activeTool?.state)
    }

    private fun call(body: String): Throwable? = runCatching { run(body) }.exceptionOrNull()

    private fun run(body: String): Agent3Client.Run {
        val server = MockWebServer()
        server.enqueue(MockResponse().setHeader("Content-Type", "application/json").setBody(body))
        server.start()
        return try {
            Agent3Client(server.url("/").toString(), "token").getRun("run-1")
        } finally {
            server.shutdown()
        }
    }

    private fun step(id: String, tool: String, state: String): String =
        """{"id":"$id","tool":"$tool","state":"$state","risk":"read"}"""

    private fun active(
        stepId: String,
        tool: String,
        state: String,
        requestState: String,
    ): String = """
        {
          "step_id":"$stepId",
          "tool":"$tool",
          "state":"$state",
          "semantics":"none",
          "handle_present":false,
          "can_request":false,
          "request_state":"$requestState",
          "reason":"fixture"
        }
    """.trimIndent()

    private fun termination(
        planState: String,
        planCanRequest: Boolean,
        effect: String = "prevent_future_steps",
        active: String? = null,
    ): String = """
        {
          "schema":"kaliv-agent3-termination/v1",
          "plan":{
            "state":"$planState",
            "can_request":$planCanRequest,
            "request_scope":"plan",
            "effect":"$effect",
            "reason":"fixture"
          },
          "model_stream":{
            "state":"not_active",
            "active":false,
            "can_request":false,
            "handle_present":false,
            "reason":"fixture"
          },
          "active_tool":${active ?: "null"},
          "production_activation":false
        }
    """.trimIndent()

    private fun runEnvelope(
        state: String,
        steps: List<String>,
        currentStep: Int,
        termination: String?,
    ): String = """
        {
          "run":{
            "id":"run-1",
            "state":"$state",
            "current_step":$currentStep,
            "steps":[${steps.joinToString(",")}]
          }${termination?.let { ",\"termination\":$it" } ?: ""}
        }
    """.trimIndent()
}
''', encoding='utf-8')

print('patched Android Agent3 termination/run truth + tests')

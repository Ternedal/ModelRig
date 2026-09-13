package dk.ternedal.modelrig.net

import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3TerminationAuthorityTest {
    private val client = Agent3Client("http://127.0.0.1", "token")

    private fun step(
        state: String,
        id: String = "step-1",
        tool: String = "rig_status",
    ) = Agent3Client.Step(
        id = id,
        tool = tool,
        args = "{}",
        risk = "read",
        sensitivity = "operational",
        egress = "local",
        summary = "fixture",
        state = state,
        confirmationDigest = null,
        confirmationExpiresAt = null,
        error = null,
    )

    private fun run(
        state: String,
        stepState: String? = "executing",
        currentStep: Int = 0,
        id: String = "run-1",
    ): Agent3Client.Run {
        val steps = if (stepState == null) emptyList() else listOf(step(stepState))
        return Agent3Client.Run(
            id = id,
            state = state,
            routeKind = "rig_tools_local",
            currentStep = currentStep,
            steps = steps,
            answer = null,
            error = null,
            termination = null,
        )
    }

    private fun receipt(
        run: Agent3Client.Run,
        planState: String = if (run.state in setOf("blocked", "completed", "failed", "cancelled")) "terminal" else "available",
        planCanRequest: Boolean = planState == "available",
        effect: String = if (run.steps.getOrNull(run.currentStep)?.state == "executing")
            "prevent_future_steps_active_tool_continues" else "prevent_future_steps",
        activeState: String? = run.steps.getOrNull(run.currentStep)?.state,
        requestState: String = if (activeState == "completed_after_cancel") "terminal" else if (activeState == "executing") "unavailable" else "not_active",
        activeStepId: String? = run.steps.getOrNull(run.currentStep)?.id,
        activeToolName: String? = run.steps.getOrNull(run.currentStep)?.tool,
        activeCanRequest: Boolean = false,
        activeHandlePresent: Boolean = false,
        activeSemantics: String? = "none",
        modelStreamState: String = "not_active",
        modelStreamActive: Boolean = false,
        modelStreamCanRequest: Boolean = false,
        modelStreamHandlePresent: Boolean = false,
    ): Agent3Client.TerminationReceipt {
        val active = activeState?.let {
            Agent3Client.TerminationActiveTool(
                stepId = activeStepId.orEmpty(),
                tool = activeToolName.orEmpty(),
                state = it,
                semantics = activeSemantics,
                handlePresent = activeHandlePresent,
                canRequest = activeCanRequest,
                requestState = requestState,
                reason = "fixture",
            )
        }
        return Agent3Client.TerminationReceipt(
            schema = "kaliv-agent3-termination/v1",
            plan = Agent3Client.TerminationPlan(
                state = planState,
                canRequest = planCanRequest,
                requestScope = "plan",
                effect = effect,
                reason = "fixture",
            ),
            modelStream = Agent3Client.TerminationModelStream(
                state = modelStreamState,
                active = modelStreamActive,
                canRequest = modelStreamCanRequest,
                handlePresent = modelStreamHandlePresent,
                reason = "fixture",
            ),
            activeTool = active,
            productionActivation = false,
        )
    }

    private fun rejects(block: () -> Unit) {
        assertTrue(runCatching(block).exceptionOrNull() is ModelRigException)
    }

    @Test
    fun missingReceiptFailsClosed() {
        rejects { client.validateTerminationReceipt(null, run("completed", stepState = null)) }
    }

    @Test
    fun validRunningExecutingReceiptIsAccepted() {
        val run = run("running")
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun validWaitingConfirmationReceiptIsAccepted() {
        val run = run("waiting_confirmation", stepState = "waiting_confirmation")
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun terminalRunMayTruthfullyRetainExecutingTool() {
        val run = run("cancelled", stepState = "executing")
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun fullyTerminalRunWithoutCurrentStepIsAccepted() {
        val run = run("completed", stepState = null)
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun planTerminalAuthorityMustAgreeWithRun() {
        val run = run("cancelled", stepState = "executing")
        rejects { client.validateTerminationReceipt(receipt(run, planState = "available", planCanRequest = true), run) }
    }

    @Test
    fun activeToolMustMatchExactCurrentStep() {
        val run = run("running")
        rejects { client.validateTerminationReceipt(receipt(run, activeStepId = "another-step"), run) }
    }

    @Test
    fun activeToolNameMustMatchExactCurrentStep() {
        val run = run("running")
        rejects { client.validateTerminationReceipt(receipt(run, activeToolName = "other_tool"), run) }
    }

    @Test
    fun activeToolStateMustMatchCurrentStepState() {
        val run = run("cancelled", stepState = "completed_after_cancel")
        rejects { client.validateTerminationReceipt(receipt(run, activeState = "failed", requestState = "terminal"), run) }
    }

    @Test
    fun unknownToolRequestStateFailsClosed() {
        val run = run("running")
        rejects { client.validateTerminationReceipt(receipt(run, requestState = "future_state"), run) }
    }

    @Test
    fun executingToolCannotClaimTerminalRequestState() {
        val run = run("cancelled", stepState = "executing")
        rejects { client.validateTerminationReceipt(receipt(run, requestState = "terminal"), run) }
    }

    @Test
    fun completedAfterCancelRequiresTerminalRequestState() {
        val run = run("cancelled", stepState = "completed_after_cancel")
        rejects { client.validateTerminationReceipt(receipt(run, requestState = "not_active"), run) }
    }

    @Test
    fun modelStreamCannotInventActiveAuthority() {
        val run = run("running")
        rejects { client.validateTerminationReceipt(receipt(run, modelStreamActive = true), run) }
    }

    @Test
    fun unknownRunStateFailsClosed() {
        val run = run("future_state")
        rejects { client.validateTerminationReceipt(receipt(run), run) }
    }

    @Test
    fun outOfBoundsCurrentStepFailsClosed() {
        val run = run("running", stepState = "executing", currentStep = 2)
        rejects { client.validateTerminationReceipt(receipt(run), run) }
    }

    @Test
    fun unknownStepStateFailsClosed() {
        val run = run("running", stepState = "future_step")
        rejects { client.validateTerminationReceipt(receipt(run), run) }
    }

    @Test
    fun availableToolControlRequiresRequestAuthority() {
        val run = run("running")
        rejects { client.validateTerminationReceipt(receipt(run, requestState = "available"), run) }
    }
}

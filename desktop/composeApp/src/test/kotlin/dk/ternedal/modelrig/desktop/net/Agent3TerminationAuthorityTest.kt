package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertFailsWith

class Agent3TerminationAuthorityTest {
    private val client = Agent3Client("http://127.0.0.1", "token")

    private fun step(state: String, id: String = "step-1", tool: String = "rig_status") = Agent3Step(
        id = id,
        tool = tool,
        risk = "read",
        state = state,
    )

    private fun run(
        state: String,
        stepState: String? = "executing",
        currentStep: Int = 0,
    ): Agent3Run {
        val steps = if (stepState == null) emptyList() else listOf(step(stepState))
        return Agent3Run(
            id = "run-1",
            state = state,
            currentStep = currentStep,
            steps = steps,
        )
    }

    private fun receipt(
        run: Agent3Run,
        planState: String = if (run.state in setOf("blocked", "completed", "failed", "cancelled")) "terminal" else "available",
        planCanRequest: Boolean = planState == "available",
        effect: String = if (run.steps.getOrNull(run.currentStep)?.state == "executing")
            "prevent_future_steps_active_tool_continues" else "prevent_future_steps",
        activeState: String? = run.steps.getOrNull(run.currentStep)?.state,
        requestState: String = if (activeState == "completed_after_cancel") "terminal" else if (activeState == "executing") "unavailable" else "not_active",
        activeStepId: String? = run.steps.getOrNull(run.currentStep)?.id,
        activeToolName: String? = run.steps.getOrNull(run.currentStep)?.tool,
        modelStreamActive: Boolean = false,
    ): Agent3TerminationReceipt {
        val active = activeState?.let {
            Agent3TerminationActiveTool(
                stepId = activeStepId.orEmpty(),
                tool = activeToolName.orEmpty(),
                state = it,
                semantics = "none",
                handlePresent = false,
                canRequest = false,
                requestState = requestState,
                reason = "fixture",
            )
        }
        return Agent3TerminationReceipt(
            schema = "kaliv-agent3-termination/v1",
            plan = Agent3TerminationPlan(
                state = planState,
                canRequest = planCanRequest,
                requestScope = "plan",
                effect = effect,
                reason = "fixture",
            ),
            modelStream = Agent3TerminationModelStream(
                state = "not_active",
                active = modelStreamActive,
                canRequest = false,
                handlePresent = false,
                reason = "fixture",
            ),
            activeTool = active,
            productionActivation = false,
        )
    }

    @Test
    fun missingReceiptFailsClosed() {
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(null, run("completed", stepState = null))
        }
    }

    @Test
    fun validRunningExecutingReceiptIsAccepted() {
        val run = run("running")
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun terminalRunMayTruthfullyRetainExecutingTool() {
        val run = run("cancelled", stepState = "executing")
        client.validateTerminationReceipt(receipt(run), run)
    }


    @Test
    fun validWaitingConfirmationReceiptIsAccepted() {
        val run = run("waiting_confirmation", stepState = "waiting_confirmation")
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun fullyTerminalRunWithoutCurrentStepIsAccepted() {
        val run = run("completed", stepState = null, currentStep = 0)
        client.validateTerminationReceipt(receipt(run), run)
    }

    @Test
    fun planTerminalAuthorityMustAgreeWithRun() {
        val run = run("cancelled", stepState = "executing")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(
                receipt(run, planState = "available", planCanRequest = true),
                run,
            )
        }
    }

    @Test
    fun activeToolMustMatchExactCurrentStep() {
        val run = run("running", stepState = "executing")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(
                receipt(run, activeStepId = "another-step"),
                run,
             )
        }
    }

    @Test
    fun activeToolStateMustMatchCurrentStepState() {
        val run = run("cancelled", stepState = "completed_after_cancel")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(
                receipt(run, activeState = "failed", requestState = "terminal"),
                run,
             )
        }
    }

    @Test
    fun unknownToolRequestStateFailsClosed() {
        val run = run("running", stepState = "executing")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(receipt(run, requestState = "future_state"), run)
        }
    }

    @Test
    fun executingToolCannotClaimTerminalRequestState() {
        val run = run("cancelled", stepState = "executing")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(receipt(run, requestState = "terminal"), run)
        }
    }

    @Test
    fun completedAfterCancelRequiresTerminalRequestState() {
        val run = run("cancelled", stepState = "completed_after_cancel")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(receipt(run, requestState = "not_active"), run)
        }
    }

    @Test
    fun modelStreamCannotInventActiveAuthority() {
        val run = run("running", stepState = "executing")
        assertFailsWith<Agent3Exception> {
            client.validateTerminationReceipt(receipt(run, modelStreamActive = true), run)
        }
    }
}

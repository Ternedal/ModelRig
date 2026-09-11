package dk.ternedal.modelrig.desktop.net

import kotlin.test.Test
import kotlin.test.assertFailsWith

class Agent3ReviewedStartCheckpointBindingTest {
    @Test
    fun validWaitingCheckpointMatchesReturnedRun() {
        validateReviewedStartCheckpoint(
            envelope = envelope(waitingReview()),
            expectedReviewReads = true,
        )
    }

    @Test
    fun validClearedCheckpointIsAcceptedForEnabledAndDisabledReview() {
        listOf(true, false).forEach { enabled ->
            validateReviewedStartCheckpoint(
                envelope = envelope(
                    Agent3ReadReview(enabled = enabled, waiting = false),
                    run = Agent3Run(
                        id = "run-1",
                        state = "completed",
                        currentStep = 0,
                        steps = emptyList(),
                    ),
                ),
                expectedReviewReads = enabled,
            )
        }
    }

    @Test
    fun waitingCheckpointRequiresReviewedModeAndRunningRun() {
        assertCheckpointFailure(
            review = waitingReview(enabled = false),
            expectedReviewReads = false,
        )
        assertCheckpointFailure(
            review = waitingReview(),
            run = baseRun(state = "completed"),
        )
    }

    @Test
    fun waitingCheckpointRequiresExactCurrentStepWindowBounds() {
        listOf(
            waitingReview(windowStart = 0),
            waitingReview(windowStart = 2),
            waitingReview(windowEnd = 1),
            waitingReview(windowEnd = 4),
        ).forEach { review ->
            assertCheckpointFailure(review = review)
        }
    }

    @Test
    fun waitingCheckpointRequiresPendingReadStepsWithStableIds() {
        val blankId = baseRun(
            steps = listOf(
                readStep("read-1", "rig_status", "succeeded"),
                readStep("", "list_models", "pending"),
                writeStep(),
            )
        )
        val writeWindow = baseRun(
            steps = listOf(
                readStep("read-1", "rig_status", "succeeded"),
                Agent3Step(id = "read-2", tool = "list_models", risk = "write", state = "pending"),
                writeStep(),
            )
        )
        val completedWindow = baseRun(
            steps = listOf(
                readStep("read-1", "rig_status", "succeeded"),
                readStep("read-2", "list_models", "succeeded"),
                writeStep(),
            )
        )
        listOf(blankId, writeWindow, completedWindow).forEach { run ->
            assertCheckpointFailure(review = waitingReview(), run = run)
        }
    }

    @Test
    fun waitingCheckpointRequiresExactOrderedRemovableIds() {
        assertCheckpointFailure(
            review = waitingReview(removableStepIds = emptyList()),
        )
        assertCheckpointFailure(
            review = waitingReview(removableStepIds = listOf("other")),
        )
    }

    @Test
    fun waitingCheckpointRequiresCompletedReadIdentityFromPreviousStep() {
        listOf(
            waitingReview(completedStepId = null),
            waitingReview(completedStepId = "other"),
            waitingReview(completedTool = null),
            waitingReview(completedTool = "other_tool"),
        ).forEach { review ->
            assertCheckpointFailure(review = review)
        }

        assertCheckpointFailure(
            review = waitingReview(),
            run = baseRun(
                steps = listOf(
                    Agent3Step(id = "read-1", tool = "rig_status", risk = "write", state = "succeeded"),
                    readStep("read-2", "list_models", "pending"),
                    writeStep(),
                )
            ),
        )
        assertCheckpointFailure(
            review = waitingReview(),
            run = baseRun(
                steps = listOf(
                    readStep("read-1", "rig_status", "pending"),
                    readStep("read-2", "list_models", "pending"),
                    writeStep(),
                )
            ),
        )
    }

    @Test
    fun clearedCheckpointRejectsStalePayload() {
        listOf(
            Agent3ReadReview(enabled = true, waiting = false, windowStart = 1),
            Agent3ReadReview(enabled = true, waiting = false, windowEnd = 2),
            Agent3ReadReview(enabled = true, waiting = false, removableStepIds = listOf("read-2")),
            Agent3ReadReview(enabled = true, waiting = false, completedStepId = "read-1"),
            Agent3ReadReview(enabled = true, waiting = false, completedTool = "rig_status"),
        ).forEach { review ->
            assertCheckpointFailure(
                review = review,
                run = Agent3Run(
                    id = "run-1",
                    state = "completed",
                    currentStep = 0,
                    steps = emptyList(),
                ),
            )
        }
    }

    private fun assertCheckpointFailure(
        review: Agent3ReadReview,
        run: Agent3Run = baseRun(),
        expectedReviewReads: Boolean = true,
    ) {
        assertFailsWith<Agent3Exception> {
            validateReviewedStartCheckpoint(
                envelope = envelope(review, run),
                expectedReviewReads = expectedReviewReads,
            )
        }
    }

    private fun envelope(
        review: Agent3ReadReview,
        run: Agent3Run = baseRun(),
    ): Agent3RunEnvelope = Agent3RunEnvelope(
        run = run,
        planId = "plan-1",
        reviewReads = review.enabled,
        readReview = review,
    )

    private fun waitingReview(
        enabled: Boolean = true,
        windowStart: Int? = 1,
        windowEnd: Int? = 2,
        removableStepIds: List<String> = listOf("read-2"),
        completedStepId: String? = "read-1",
        completedTool: String? = "rig_status",
    ): Agent3ReadReview = Agent3ReadReview(
        enabled = enabled,
        waiting = true,
        windowStart = windowStart,
        windowEnd = windowEnd,
        removableStepIds = removableStepIds,
        completedStepId = completedStepId,
        completedTool = completedTool,
    )

    private fun baseRun(
        state: String = "running",
        currentStep: Int = 1,
        steps: List<Agent3Step> = listOf(
            readStep("read-1", "rig_status", "succeeded"),
            readStep("read-2", "list_models", "pending"),
            writeStep(),
        ),
    ): Agent3Run = Agent3Run(
        id = "run-1",
        state = state,
        currentStep = currentStep,
        steps = steps,
    )

    private fun readStep(id: String, tool: String, state: String): Agent3Step =
        Agent3Step(
            id = id,
            tool = tool,
            risk = "read",
            state = state,
        )

    private fun writeStep(): Agent3Step =
        Agent3Step(
            id = "write-1",
            tool = "note_append",
            risk = "write",
            state = "pending",
        )
}

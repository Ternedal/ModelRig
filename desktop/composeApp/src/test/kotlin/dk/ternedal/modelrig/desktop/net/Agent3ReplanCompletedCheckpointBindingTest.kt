package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertFailsWith

class Agent3ReplanCompletedCheckpointBindingTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun waitingCheckpointAcceptsSuccessfulReadImmediatelyBeforeWindow() {
        validateReviewedReplanCheckpoint(
            raw = rawReview(),
            result = result(),
        )
    }

    @Test
    fun waitingCheckpointRejectsImpossibleCurrentStepZero() {
        val run = Agent3Run(
            id = "run-1",
            state = "running",
            currentStep = 0,
            steps = listOf(
                Agent3Step(id = "read-1", tool = "list_models", risk = "read", state = "pending"),
                Agent3Step(id = "write-1", tool = "note_append", risk = "write", state = "pending"),
            ),
        )
        assertCheckpointFailure(
            raw = rawReview(
                windowStart = 0,
                windowEnd = 1,
                removableIds = listOf("read-1"),
                completedStepId = "read-0",
            ),
            result = result(
                run = run,
                review = waitingReview(
                    windowStart = 0,
                    windowEnd = 1,
                    removableIds = listOf("read-1"),
                    completedStepId = "read-0",
                ),
            ),
        )
    }

    @Test
    fun waitingCheckpointRejectsCompletedIdOrToolNotBoundToPrecedingRunStep() {
        assertCheckpointFailure(
            raw = rawReview(completedStepId = "other-read"),
            result = result(review = waitingReview(completedStepId = "other-read")),
        )
        assertCheckpointFailure(
            raw = rawReview(completedTool = "other_tool"),
            result = result(review = waitingReview(completedTool = "other_tool")),
        )
    }

    @Test
    fun waitingCheckpointRejectsNonReadPredecessor() {
        assertCheckpointFailure(
            raw = rawReview(),
            result = result(
                run = baseRun(
                    predecessor = Agent3Step(
                        id = "read-1",
                        tool = "rig_status",
                        risk = "write",
                        state = "succeeded",
                    ),
                ),
            ),
        )
    }

    @Test
    fun waitingCheckpointRejectsPredecessorThatDidNotSucceed() {
        assertCheckpointFailure(
            raw = rawReview(),
            result = result(
                run = baseRun(
                    predecessor = Agent3Step(
                        id = "read-1",
                        tool = "rig_status",
                        risk = "read",
                        state = "pending",
                    ),
                ),
            ),
        )
    }

    private fun assertCheckpointFailure(
        raw: JsonObject,
        result: Agent3ReplanApplyResult,
    ) {
        assertFailsWith<Agent3Exception> {
            validateReviewedReplanCheckpoint(raw, result)
        }
    }

    private fun result(
        run: Agent3Run = baseRun(),
        review: Agent3ReadReview = waitingReview(),
    ): Agent3ReplanApplyResult = Agent3ReplanApplyResult(
        run = run,
        readReview = review,
    )

    private fun baseRun(
        predecessor: Agent3Step = Agent3Step(
            id = "read-1",
            tool = "rig_status",
            risk = "read",
            state = "succeeded",
        ),
    ): Agent3Run = Agent3Run(
        id = "run-1",
        state = "running",
        currentStep = 1,
        steps = listOf(
            predecessor,
            Agent3Step(id = "read-2", tool = "list_models", risk = "read", state = "pending"),
            Agent3Step(id = "write-1", tool = "note_append", risk = "write", state = "pending"),
        ),
    )

    private fun waitingReview(
        windowStart: Int = 1,
        windowEnd: Int = 2,
        removableIds: List<String> = listOf("read-2"),
        completedStepId: String = "read-1",
        completedTool: String = "rig_status",
    ): Agent3ReadReview = Agent3ReadReview(
        enabled = true,
        waiting = true,
        windowStart = windowStart,
        windowEnd = windowEnd,
        removableStepIds = removableIds,
        completedStepId = completedStepId,
        completedTool = completedTool,
    )

    private fun rawReview(
        windowStart: Int = 1,
        windowEnd: Int = 2,
        removableIds: List<String> = listOf("read-2"),
        completedStepId: String = "read-1",
        completedTool: String = "rig_status",
    ): JsonObject {
        val ids = removableIds.joinToString(",") { "\"$it\"" }
        return json.parseToJsonElement(
            """
            {
              "enabled": true,
              "waiting": true,
              "window_start": $windowStart,
              "window_end": $windowEnd,
              "removable_step_ids": [$ids],
              "completed_step_id": "$completedStepId",
              "completed_tool": "$completedTool"
            }
            """.trimIndent()
        ).jsonObject
    }
}

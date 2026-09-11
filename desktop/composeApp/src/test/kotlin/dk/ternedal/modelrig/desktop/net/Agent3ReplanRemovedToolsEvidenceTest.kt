package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Agent3ReplanRemovedToolsEvidenceTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun reviewedReceiptAcceptsTypedRemovedToolsWithMatchingCardinality() {
        val authority = validateReviewedReplanReceiptShape(
            raw = receiptJson("[\"rig_status\"]"),
            reviewed = reviewed(),
        )

        assertEquals(listOf("old-read"), authority.removedStepIds)
        assertEquals(listOf("rig_status"), authority.removedTools)
    }

    @Test
    fun reviewedReceiptRejectsMissingWrongTypedBlankOrCardinalityDriftedRemovedTools() {
        listOf(
            receiptJson(removedToolsJson = null),
            receiptJson("7"),
            receiptJson("[7]"),
            receiptJson("[\"\"]"),
            receiptJson("[\"rig_status\",\"list_models\"]"),
        ).forEach { raw ->
            val error = assertFailsWith<Agent3Exception> {
                validateReviewedReplanReceiptShape(raw, reviewed())
            }
            assertTrue(error.message.orEmpty().contains("replan.removed_tools"))
        }
    }

    @Test
    fun reviewedReceiptRequiresTypedDecodeToPreserveRawRemovedToolsEvidence() {
        val authority = validateReviewedReplanReceiptShape(
            raw = receiptJson("[\"rig_status\"]"),
            reviewed = reviewed(),
        )
        val valid = result(removedTools = listOf("rig_status"))

        validateReviewedReplanReceiptBinding(authority, valid)

        val error = assertFailsWith<Agent3Exception> {
            validateReviewedReplanReceiptBinding(
                authority,
                valid.copy(replan = valid.replan.copy(removedTools = listOf("tampered_tool"))),
            )
        }
        assertTrue(error.message.orEmpty().contains("typed receipt"))
    }

    private fun receiptJson(removedToolsJson: String?): kotlinx.serialization.json.JsonObject {
        val removedToolsField = removedToolsJson?.let { "\"removed_tools\":$it," }.orEmpty()
        return json.parseToJsonElement(
            """
            {
              "start": 1,
              "old_end": 2,
              "new_end": 2,
              "removed_step_ids": ["old-read"],
              $removedToolsField
              "added_step_ids": ["read-2"],
              "added_tools": ["list_models"],
              "immutable_prefix_ids": ["read-1"],
              "immutable_tail_ids": ["write-1"]
            }
            """.trimIndent()
        ).jsonObject
    }

    private fun reviewed(): Agent3ReplanPreview = Agent3ReplanPreview(
        previewId = "preview-1",
        runId = "run-1",
        revision = 2,
        replanCount = 4,
        rationale = "replace stale reads",
        plannerModel = "planner-a",
        promptSha256 = "a".repeat(64),
        window = Agent3ReplanWindow(
            start = 1,
            end = 2,
            removableStepIds = listOf("old-read"),
            immutablePrefixIds = listOf("read-1"),
            immutableTailIds = listOf("write-1"),
        ),
        plan = listOf(
            Agent3Step(
                id = "proposal-read",
                tool = "list_models",
                risk = "read",
                sensitivity = "internal",
                egress = "local",
            )
        ),
    )

    private fun result(removedTools: List<String>): Agent3ReplanApplyResult =
        Agent3ReplanApplyResult(
            run = Agent3Run(
                id = "run-1",
                state = "running",
                currentStep = 1,
                steps = listOf(
                    Agent3Step(id = "read-1", tool = "rig_status", risk = "read", state = "succeeded"),
                    Agent3Step(id = "read-2", tool = "list_models", risk = "read", state = "pending"),
                    Agent3Step(id = "write-1", tool = "note_append", risk = "write", state = "pending"),
                ),
            ),
            replan = Agent3ReplanReceipt(
                reason = "replace stale reads",
                fromRevision = 2,
                toRevision = 3,
                replanNumber = 5,
                start = 1,
                oldEnd = 2,
                newEnd = 2,
                removedStepIds = listOf("old-read"),
                removedTools = removedTools,
                addedStepIds = listOf("read-2"),
                addedTools = listOf("list_models"),
                immutablePrefixIds = listOf("read-1"),
                immutableTailIds = listOf("write-1"),
            ),
        )
}

package dk.ternedal.modelrig.desktop.net

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

class Agent3ReplanAddedStepIdAuthorityTest {
    private val json = Json { ignoreUnknownKeys = true }

    @Test
    fun reviewedReceiptBindsCompleteReviewedReplacementIdsExactly() {
        val reviewed = reviewed(
            listOf(
                Agent3Step(id = "new-read-1", tool = "list_models"),
                Agent3Step(id = "new-read-2", tool = "rig_status"),
            )
        )
        val authority = validateReviewedReplanReceiptShape(
            raw = receipt(
                addedStepIds = listOf("new-read-1", "new-read-2"),
                addedTools = listOf("list_models", "rig_status"),
            ),
            reviewed = reviewed,
        )

        assertEquals(listOf("new-read-1", "new-read-2"), authority.addedStepIds)
    }

    @Test
    fun reviewedReceiptRejectsAddedIdsThatDriftFromCompleteReviewedPreview() {
        val reviewed = reviewed(
            listOf(
                Agent3Step(id = "new-read-1", tool = "list_models"),
                Agent3Step(id = "new-read-2", tool = "rig_status"),
            )
        )

        val error = assertFailsWith<Agent3Exception> {
            validateReviewedReplanReceiptShape(
                raw = receipt(
                    addedStepIds = listOf("other-read", "new-read-2"),
                    addedTools = listOf("list_models", "rig_status"),
                ),
                reviewed = reviewed,
            )
        }

        assertTrue(error.message.orEmpty().contains("replan.added_step_ids"))
    }

    @Test
    fun compatibilityPreviewWithoutCompleteIdsRetainsCardinalityAndRunBindingBoundary() {
        listOf(null, " ").forEach { missingId ->
            val reviewed = reviewed(
                listOf(
                    Agent3Step(id = "new-read-1", tool = "list_models"),
                    Agent3Step(id = missingId, tool = "rig_status"),
                )
            )
            val authority = validateReviewedReplanReceiptShape(
                raw = receipt(
                    addedStepIds = listOf("server-read-1", "server-read-2"),
                    addedTools = listOf("list_models", "rig_status"),
                ),
                reviewed = reviewed,
            )

            assertEquals(2, authority.addedStepIds.size)
        }
    }

    @Test
    fun emptyReplacementPlanStillRequiresAndAcceptsEmptyAddedIds() {
        val authority = validateReviewedReplanReceiptShape(
            raw = receipt(
                addedStepIds = emptyList(),
                addedTools = emptyList(),
            ),
            reviewed = reviewed(emptyList()),
        )

        assertTrue(authority.addedStepIds.isEmpty())
        assertTrue(authority.addedTools.isEmpty())
    }

    private fun reviewed(plan: List<Agent3Step>): Agent3ReplanPreview = Agent3ReplanPreview(
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
        plan = plan,
    )

    private fun receipt(
        addedStepIds: List<String>,
        addedTools: List<String>,
    ): JsonObject {
        val newEnd = 1 + addedStepIds.size
        return json.parseToJsonElement(
            """
            {
              "start": 1,
              "old_end": 2,
              "new_end": $newEnd,
              "removed_step_ids": ["old-read"],
              "removed_tools": ["rig_status"],
              "added_step_ids": ${stringArray(addedStepIds)},
              "added_tools": ${stringArray(addedTools)},
              "immutable_prefix_ids": ["read-1"],
              "immutable_tail_ids": ["write-1"]
            }
            """.trimIndent()
        ).jsonObject
    }

    private fun stringArray(values: List<String>): String =
        values.joinToString(prefix = "[", postfix = "]") { value -> "\"$value\"" }
}

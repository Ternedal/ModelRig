package dk.ternedal.modelrig.net

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReplanReceiptBindingTest {
    @Test
    fun exactReviewedReceiptBindsRawTypedAndCommittedRunAuthority() {
        val reviewed = reviewedPreview()
        val authority = validateReviewedReplanReceiptShape(receiptJson(), reviewed)
        val result = applyResult()

        validateReviewedReplanReceiptBinding(authority, result)

        assertEquals(1, authority.start)
        assertEquals(2, authority.oldEnd)
        assertEquals(2, authority.newEnd)
        assertEquals(listOf("step-old"), authority.removedStepIds)
        assertEquals(listOf("list_models"), authority.removedTools)
        assertEquals(listOf("step-new"), authority.addedStepIds)
        assertEquals(listOf("current_datetime"), authority.addedTools)
        assertEquals(listOf("step-1"), authority.immutablePrefixIds)
        assertEquals(listOf("step-3"), authority.immutableTailIds)
    }

    @Test
    fun reviewedReceiptRejectsMissingOrWrongTypedDeterministicFields() {
        val cases = listOf<Pair<String, (JSONObject) -> Unit>>(
            "replan.start" to { it.remove("start") },
            "replan.old_end" to { it.put("old_end", "2") },
            "replan.new_end" to { it.put("new_end", true) },
            "replan.removed_step_ids" to { it.put("removed_step_ids", JSONArray().put(7)) },
            "replan.removed_tools" to { it.put("removed_tools", JSONArray().put("")) },
            "replan.added_step_ids" to { it.put("added_step_ids", "step-new") },
            "replan.added_tools" to { it.put("added_tools", JSONArray().put(9)) },
            "replan.immutable_prefix_ids" to { it.remove("immutable_prefix_ids") },
            "replan.immutable_tail_ids" to { it.put("immutable_tail_ids", JSONArray().put(JSONObject())) },
        )

        cases.forEach { (field, mutate) ->
            val raw = receiptJson()
            mutate(raw)
            assertReceiptFailure(field) {
                validateReviewedReplanReceiptShape(raw, reviewedPreview())
            }
        }
    }

    @Test
    fun reviewedReceiptRejectsWindowToolAndReplacementDrift() {
        val cases = listOf<Pair<String, (JSONObject) -> Unit>>(
            "replan.start" to { it.put("start", 0) },
            "replan.old_end" to { it.put("old_end", 3) },
            "replan.new_end" to { it.put("new_end", 3) },
            "replan.removed_step_ids" to {
                it.put("removed_step_ids", JSONArray().put("other-old"))
            },
            "replan.removed_tools" to {
                it.put("removed_tools", JSONArray().put("list_models").put("extra"))
            },
            "replan.added_step_ids" to {
                it.put("added_step_ids", JSONArray().put("other-new"))
            },
            "replan.added_tools" to {
                it.put("added_tools", JSONArray().put("rig_status"))
            },
            "replan.immutable_prefix_ids" to {
                it.put("immutable_prefix_ids", JSONArray().put("other-prefix"))
            },
            "replan.immutable_tail_ids" to {
                it.put("immutable_tail_ids", JSONArray().put("other-tail"))
            },
        )

        cases.forEach { (field, mutate) ->
            val raw = receiptJson()
            mutate(raw)
            assertReceiptFailure(field) {
                validateReviewedReplanReceiptShape(raw, reviewedPreview())
            }
        }
    }

    @Test
    fun directlyConstructedCompatibilityPreviewWithoutReplacementIdUsesRunBindingFallback() {
        val reviewed = reviewedPreview(replacementId = null)
        val authority = validateReviewedReplanReceiptShape(receiptJson(), reviewed)

        validateReviewedReplanReceiptBinding(authority, applyResult())

        assertEquals(listOf("step-new"), authority.addedStepIds)
    }

    @Test
    fun completeReviewedReplacementIdsRemainExactAuthority() {
        assertReceiptFailure("replan.added_step_ids") {
            validateReviewedReplanReceiptShape(
                receiptJson(),
                reviewedPreview(replacementId = "reviewed-different"),
            )
        }
    }

    @Test
    fun typedReceiptMustPreserveRawAuthority() {
        val authority = validateReviewedReplanReceiptShape(receiptJson(), reviewedPreview())
        val drifted = applyResult(
            receipt = receipt().copy(addedTools = listOf("rig_status")),
        )

        assertReceiptFailure("replan typed receipt") {
            validateReviewedReplanReceiptBinding(authority, drifted)
        }
    }

    @Test
    fun committedRunMustPreserveReceiptWindowAndSlices() {
        val authority = validateReviewedReplanReceiptShape(receiptJson(), reviewedPreview())
        val cases = listOf(
            "run replacement window" to applyResult(run = run(currentStep = 0)),
            "run immutable prefix" to applyResult(run = run(prefixId = "other-prefix")),
            "run replacement slice" to applyResult(run = run(replacementId = "other-new")),
            "run replacement slice" to applyResult(run = run(replacementTool = "rig_status")),
            "run immutable tail" to applyResult(run = run(tailId = "other-tail")),
        )

        cases.forEach { (field, result) ->
            assertReceiptFailure(field) {
                validateReviewedReplanReceiptBinding(authority, result)
            }
        }
    }

    private fun assertReceiptFailure(field: String, block: () -> Unit) {
        val error = runCatching(block).exceptionOrNull()
        assertTrue("Expected ModelRigException for $field, got $error", error is ModelRigException)
        assertTrue(
            "Expected receipt authority error to name $field, got ${error?.message}",
            error?.message?.contains(field) == true,
        )
    }

    private fun reviewedPreview(
        replacementId: String? = "step-new",
    ): Agent3ReplanClient.Preview = Agent3ReplanClient.Preview(
        previewId = "preview-1",
        expiresInSeconds = 300,
        runId = "run-1",
        revision = 2,
        replanCount = 1,
        rationale = "reviewed rationale",
        plannerModel = "planner-a",
        promptSha256 = "a".repeat(64),
        observationCharacters = 42,
        window = Agent3ReplanClient.Window(
            start = 1,
            end = 2,
            removableStepIds = listOf("step-old"),
            immutablePrefixIds = listOf("step-1"),
            immutableTailIds = listOf("step-3"),
        ),
        plan = listOf(
            step(
                id = replacementId,
                tool = "current_datetime",
                state = null,
                summary = "replacement read",
            ),
        ),
        executed = false,
    )

    private fun receiptJson(): JSONObject = JSONObject()
        .put("start", 1)
        .put("old_end", 2)
        .put("new_end", 2)
        .put("removed_step_ids", JSONArray().put("step-old"))
        .put("removed_tools", JSONArray().put("list_models"))
        .put("added_step_ids", JSONArray().put("step-new"))
        .put("added_tools", JSONArray().put("current_datetime"))
        .put("immutable_prefix_ids", JSONArray().put("step-1"))
        .put("immutable_tail_ids", JSONArray().put("step-3"))

    private fun receipt(): Agent3ReplanClient.Receipt = Agent3ReplanClient.Receipt(
        reason = "reviewed rationale",
        fromRevision = 2,
        toRevision = 3,
        replanNumber = 2,
        start = 1,
        oldEnd = 2,
        newEnd = 2,
        removedStepIds = listOf("step-old"),
        removedTools = listOf("list_models"),
        addedStepIds = listOf("step-new"),
        addedTools = listOf("current_datetime"),
        immutablePrefixIds = listOf("step-1"),
        immutableTailIds = listOf("step-3"),
    )

    private fun applyResult(
        run: Agent3Client.Run = run(),
        receipt: Agent3ReplanClient.Receipt = receipt(),
    ): Agent3ReplanClient.ApplyResult = Agent3ReplanClient.ApplyResult(
        run = run,
        replan = receipt,
        preview = Agent3ReplanClient.AppliedPreview(
            previewId = "preview-1",
            runId = "run-1",
            plannerModel = "planner-a",
            promptSha256 = "a".repeat(64),
            rationale = "reviewed rationale",
        ),
        readReview = Agent3Client.ReadReview(
            enabled = true,
            waiting = true,
            windowStart = 1,
            windowEnd = 2,
            removableStepIds = listOf("step-new"),
            completedStepId = "step-1",
            completedTool = "rig_status",
            updatedAt = 123.5,
        ),
    )

    private fun run(
        currentStep: Int = 1,
        prefixId: String = "step-1",
        replacementId: String = "step-new",
        replacementTool: String = "current_datetime",
        tailId: String = "step-3",
    ): Agent3Client.Run = Agent3Client.Run(
        id = "run-1",
        state = "running",
        routeKind = "rig_tools_local",
        currentStep = currentStep,
        steps = listOf(
            step(prefixId, "rig_status", state = "succeeded", summary = "completed read"),
            step(replacementId, replacementTool, state = "pending", summary = "replacement read"),
            step(
                tailId,
                "note_append",
                risk = "write",
                state = "pending",
                summary = "immutable write",
            ),
        ),
        answer = null,
        error = null,
        termination = null,
    )

    private fun step(
        id: String?,
        tool: String,
        risk: String = "read",
        state: String?,
        summary: String,
    ): Agent3Client.Step = Agent3Client.Step(
        id = id,
        tool = tool,
        args = "{}",
        risk = risk,
        sensitivity = "operational",
        egress = "local",
        summary = summary,
        state = state,
        confirmationDigest = null,
        confirmationExpiresAt = null,
        error = null,
    )
}

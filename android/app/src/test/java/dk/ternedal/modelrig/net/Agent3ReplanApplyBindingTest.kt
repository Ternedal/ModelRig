package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReplanApplyBindingTest {
    @Test
    fun reviewedApplyAcceptsExactConsumedPreviewRevisionAndWaitingCheckpoint() {
        val reviewed = reviewedPreview()
        val server = server(applyResponse())
        try {
            val result = Agent3ReplanClient(server.url("/").toString(), "token")
                .applyReviewed(reviewed)
            assertEquals("run-1", result.run.id)
            assertEquals("preview-1", result.preview.previewId)
            assertEquals(2, result.replan.fromRevision)
            assertEquals(3, result.replan.toRevision)
            assertEquals(2, result.replan.replanNumber)
            assertEquals(1, result.replan.start)
            assertEquals(2, result.replan.oldEnd)
            assertEquals(2, result.replan.newEnd)
            assertEquals(listOf("step-old"), result.replan.removedStepIds)
            assertEquals(listOf("list_models"), result.replan.removedTools)
            assertEquals(listOf("step-new"), result.replan.addedStepIds)
            assertEquals(listOf("current_datetime"), result.replan.addedTools)
            assertEquals(listOf("step-1"), result.replan.immutablePrefixIds)
            assertEquals(listOf("step-3"), result.replan.immutableTailIds)
            assertTrue(result.readReview.enabled)
            assertTrue(result.readReview.waiting)
            assertEquals(1, result.readReview.windowStart)
            assertEquals(2, result.readReview.windowEnd)
            assertEquals(listOf("step-new"), result.readReview.removableStepIds)
            assertEquals("step-1", result.readReview.completedStepId)
            assertEquals("rig_status", result.readReview.completedTool)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedApplyAcceptsClearedEnabledAndDisabledReviewStates() {
        listOf(true, false).forEach { enabled ->
            val server = server(
                applyResponse(
                    reviewEnabledJson = enabled.toString(),
                    reviewWaitingJson = "false",
                    reviewWindowStartJson = "null",
                    reviewWindowEndJson = "null",
                    reviewRemovableIdsJson = "[]",
                    reviewCompletedStepIdJson = "null",
                    reviewCompletedToolJson = "null",
                ),
            )
            try {
                val result = Agent3ReplanClient(server.url("/").toString(), "token")
                    .applyReviewed(reviewedPreview())
                assertEquals(enabled, result.readReview.enabled)
                assertFalse(result.readReview.waiting)
                assertEquals(null, result.readReview.windowStart)
                assertEquals(null, result.readReview.windowEnd)
                assertTrue(result.readReview.removableStepIds.isEmpty())
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedApplyPreservesExplicitNullablePlannerModelAuthority() {
        val reviewed = reviewedPreview(plannerModel = null)
        val server = server(applyResponse(plannerModelJson = "null"))
        try {
            val result = Agent3ReplanClient(server.url("/").toString(), "token")
                .applyReviewed(reviewed)
            assertEquals(null, result.preview.plannerModel)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsConsumedPreviewIdentityOrContentDrift() {
        val cases = listOf(
            "run.id" to applyResponse(runId = "run-other"),
            "preview.preview_id" to applyResponse(previewId = "preview-other"),
            "preview.run_id" to applyResponse(previewRunId = "run-other"),
            "preview.planner_model" to applyResponse(plannerModelJson = "\"planner-other\""),
            "preview.prompt_sha256" to applyResponse(promptSha256 = "b".repeat(64)),
            "preview.rationale" to applyResponse(previewRationale = "other rationale"),
        )

        cases.forEach { (field, body) ->
            val server = server(body)
            try {
                assertAuthorityFailure(server, reviewedPreview(), field)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedApplyRejectsReceiptAuthorityDrift() {
        val cases = listOf(
            "replan.reason" to applyResponse(receiptReason = "other rationale"),
            "replan.from_revision" to applyResponse(fromRevisionJson = "1"),
            "replan.to_revision" to applyResponse(toRevisionJson = "4"),
            "replan.replan_number" to applyResponse(replanNumberJson = "3"),
        )

        cases.forEach { (field, body) ->
            val server = server(body)
            try {
                assertAuthorityFailure(server, reviewedPreview(), field)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedApplyRejectsMissingOrWrongTypeRevisionAuthority() {
        val missing = server(applyResponse(includeFromRevision = false))
        try {
            assertAuthorityFailure(missing, reviewedPreview(), "replan.from_revision")
        } finally {
            missing.shutdown()
        }

        val wrongType = server(applyResponse(fromRevisionJson = "\"2\""))
        try {
            assertAuthorityFailure(wrongType, reviewedPreview(), "replan.from_revision")
        } finally {
            wrongType.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsMissingNullablePlannerModelField() {
        val server = server(applyResponse(includePlannerModel = false))
        try {
            assertAuthorityFailure(
                server,
                reviewedPreview(plannerModel = null),
                "preview.planner_model",
            )
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsMissingReadReviewOrBooleanAuthority() {
        val missingObject = server(applyResponse(includeReadReview = false))
        try {
            assertAuthorityFailure(missingObject, reviewedPreview(), "read_review")
        } finally {
            missingObject.shutdown()
        }

        val missingEnabled = server(applyResponse(includeReviewEnabled = false))
        try {
            assertAuthorityFailure(missingEnabled, reviewedPreview(), "read_review.enabled")
        } finally {
            missingEnabled.shutdown()
        }

        val missingWaiting = server(applyResponse(includeReviewWaiting = false))
        try {
            assertAuthorityFailure(missingWaiting, reviewedPreview(), "read_review.waiting")
        } finally {
            missingWaiting.shutdown()
        }

        val wrongEnabled = server(applyResponse(reviewEnabledJson = "\"true\""))
        try {
            assertAuthorityFailure(wrongEnabled, reviewedPreview(), "read_review.enabled")
        } finally {
            wrongEnabled.shutdown()
        }

        val wrongWaiting = server(applyResponse(reviewWaitingJson = "1"))
        try {
            assertAuthorityFailure(wrongWaiting, reviewedPreview(), "read_review.waiting")
        } finally {
            wrongWaiting.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsStaleOrMismatchedWaitingWindow() {
        val cases = listOf(
            "read_review window" to applyResponse(reviewWindowStartJson = "0"),
            "read_review window" to applyResponse(reviewWindowEndJson = "4"),
            "read_review.removable_step_ids" to applyResponse(
                reviewRemovableIdsJson = "[\"stale-step\"]",
            ),
            "read_review.removable_step_ids" to applyResponse(
                reviewRemovableIdsJson = "[1]",
            ),
        )
        cases.forEach { (field, body) ->
            val server = server(body)
            try {
                assertAuthorityFailure(server, reviewedPreview(), field)
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedApplyRejectsNonReadOrNonPendingWaitingWindowStep() {
        val cases = listOf(
            applyResponse(replacementRisk = "write"),
            applyResponse(replacementState = "succeeded"),
        )
        cases.forEach { body ->
            val server = server(body)
            try {
                assertAuthorityFailure(server, reviewedPreview(), "read_review window steps")
            } finally {
                server.shutdown()
            }
        }
    }

    @Test
    fun reviewedApplyRejectsIncompleteOrStaleClearedCheckpointPayload() {
        val missingCompleted = server(applyResponse(reviewCompletedStepIdJson = "null"))
        try {
            assertAuthorityFailure(missingCompleted, reviewedPreview(), "read_review.completed_step_id")
        } finally {
            missingCompleted.shutdown()
        }

        val staleCleared = server(
            applyResponse(
                reviewWaitingJson = "false",
                reviewWindowStartJson = "1",
                reviewWindowEndJson = "2",
                reviewRemovableIdsJson = "[\"step-new\"]",
                reviewCompletedStepIdJson = "\"step-1\"",
                reviewCompletedToolJson = "\"rig_status\"",
            ),
        )
        try {
            assertAuthorityFailure(staleCleared, reviewedPreview(), "cleared read_review checkpoint")
        } finally {
            staleCleared.shutdown()
        }
    }

    @Test
    fun genericApplyKeepsExistingPermissiveCompatibilityContract() {
        val server = server(
            """
            {
              "run": {
                "id": "generic-run",
                "state": "running",
                "current_step": 0,
                "steps": []
              }
            }
            """.trimIndent(),
        )
        try {
            val result = Agent3ReplanClient(server.url("/").toString(), "token")
                .apply("preview-1")
            assertEquals("generic-run", result.run.id)
            assertEquals(0, result.replan.fromRevision)
            assertEquals(0, result.replan.start)
            assertTrue(result.replan.removedStepIds.isEmpty())
            assertTrue(result.replan.addedStepIds.isEmpty())
            assertTrue(result.replan.immutablePrefixIds.isEmpty())
            assertEquals("", result.preview.previewId)
            assertFalse(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
            assertTrue(result.readReview.removableStepIds.isEmpty())
            assertEquals(
                "/api/v1/experimental/agent3/replan-previews/preview-1/apply",
                server.takeRequest().path,
            )
        } finally {
            server.shutdown()
        }
    }

    private fun assertAuthorityFailure(
        server: MockWebServer,
        reviewed: Agent3ReplanClient.Preview,
        field: String,
    ) {
        val error = runCatching {
            Agent3ReplanClient(server.url("/").toString(), "token").applyReviewed(reviewed)
        }.exceptionOrNull()
        assertTrue("Expected ModelRigException for $field, got $error", error is ModelRigException)
        assertTrue(
            "Expected authority error to name $field, got ${error?.message}",
            error?.message?.contains(field) == true,
        )
    }

    private fun reviewedPreview(
        plannerModel: String? = "planner-a",
        replacementId: String? = "step-new",
    ): Agent3ReplanClient.Preview = Agent3ReplanClient.Preview(
        previewId = "preview-1",
        expiresInSeconds = 300,
        runId = "run-1",
        revision = 2,
        replanCount = 1,
        rationale = "reviewed rationale",
        plannerModel = plannerModel,
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
            Agent3Client.Step(
                id = replacementId,
                tool = "current_datetime",
                args = "{}",
                risk = "read",
                sensitivity = "operational",
                egress = "local",
                summary = "replacement read",
                state = null,
                confirmationDigest = null,
                confirmationExpiresAt = null,
                error = null,
            ),
        ),
        executed = false,
    )

    private fun server(body: String): MockWebServer = MockWebServer().also { server ->
        server.enqueue(
            MockResponse()
                .setHeader("Content-Type", "application/json")
                .setBody(body),
        )
        server.start()
    }

    private fun applyResponse(
        runId: String = "run-1",
        runState: String = "running",
        replacementRisk: String = "read",
        replacementState: String = "pending",
        previewId: String = "preview-1",
        previewRunId: String = "run-1",
        plannerModelJson: String = "\"planner-a\"",
        includePlannerModel: Boolean = true,
        promptSha256: String = "a".repeat(64),
        previewRationale: String = "reviewed rationale",
        receiptReason: String = "reviewed rationale",
        fromRevisionJson: String = "2",
        includeFromRevision: Boolean = true,
        toRevisionJson: String = "3",
        replanNumberJson: String = "2",
        includeReadReview: Boolean = true,
        includeReviewEnabled: Boolean = true,
        includeReviewWaiting: Boolean = true,
        reviewEnabledJson: String = "true",
        reviewWaitingJson: String = "true",
        reviewWindowStartJson: String = "1",
        reviewWindowEndJson: String = "2",
        reviewRemovableIdsJson: String = "[\"step-new\"]",
        reviewCompletedStepIdJson: String = "\"step-1\"",
        reviewCompletedToolJson: String = "\"rig_status\"",
    ): String {
        val plannerModelField = if (includePlannerModel) {
            "\"planner_model\": $plannerModelJson,"
        } else {
            ""
        }
        val fromRevisionField = if (includeFromRevision) {
            "\"from_revision\": $fromRevisionJson,"
        } else {
            ""
        }
        val reviewEnabledField = if (includeReviewEnabled) {
            "\"enabled\": $reviewEnabledJson,"
        } else {
            ""
        }
        val reviewWaitingField = if (includeReviewWaiting) {
            "\"waiting\": $reviewWaitingJson,"
        } else {
            ""
        }
        val readReviewField = if (includeReadReview) {
            """
              "read_review": {
                $reviewEnabledField
                $reviewWaitingField
                "window_start": $reviewWindowStartJson,
                "window_end": $reviewWindowEndJson,
                "removable_step_ids": $reviewRemovableIdsJson,
                "completed_step_id": $reviewCompletedStepIdJson,
                "completed_tool": $reviewCompletedToolJson,
                "updated_at": 123.5
              },
            """.trimIndent()
        } else {
            ""
        }
        return """
            {
              "run": {
                "id": "$runId",
                "state": "$runState",
                "current_step": 1,
                "steps": [
                  {
                    "id": "step-1",
                    "tool": "rig_status",
                    "args": {},
                    "risk": "read",
                    "sensitivity": "operational",
                    "egress": "local",
                    "summary": "completed read",
                    "state": "succeeded"
                  },
                  {
                    "id": "step-new",
                    "tool": "current_datetime",
                    "args": {},
                    "risk": "$replacementRisk",
                    "sensitivity": "operational",
                    "egress": "local",
                    "summary": "replacement read",
                    "state": "$replacementState"
                  },
                  {
                    "id": "step-3",
                    "tool": "note_append",
                    "args": {},
                    "risk": "write",
                    "sensitivity": "operational",
                    "egress": "local",
                    "summary": "immutable write",
                    "state": "pending"
                  }
                ]
              },
              "replan": {
                "reason": "$receiptReason",
                $fromRevisionField
                "to_revision": $toRevisionJson,
                "replan_number": $replanNumberJson,
                "start": 1,
                "old_end": 2,
                "new_end": 2,
                "removed_step_ids": ["step-old"],
                "removed_tools": ["list_models"],
                "added_step_ids": ["step-new"],
                "added_tools": ["current_datetime"],
                "immutable_prefix_ids": ["step-1"],
                "immutable_tail_ids": ["step-3"]
              },
              $readReviewField
              "preview": {
                "preview_id": "$previewId",
                "run_id": "$previewRunId",
                $plannerModelField
                "prompt_sha256": "$promptSha256",
                "rationale": "$previewRationale"
              }
            }
        """.trimIndent()
    }
}

package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReplanApplyBindingTest {
    @Test
    fun reviewedApplyAcceptsExactConsumedPreviewAndRevisionReceipt() {
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
            assertTrue(result.readReview.enabled)
            assertTrue(result.readReview.waiting)
            assertEquals(1, result.readReview.windowStart)
            assertEquals(2, result.readReview.windowEnd)
            assertEquals(listOf("read-new"), result.readReview.removableStepIds)
            assertEquals("read-completed", result.readReview.completedStepId)
            assertEquals("rig_status", result.readReview.completedTool)
        } finally {
            server.shutdown()
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
    fun reviewedApplyAcceptsClearedReadReviewWithoutStaleCheckpointAuthority() {
        val server = server(
            applyResponse(
                readReviewJson = """
                    {
                      "enabled": true,
                      "waiting": false,
                      "window_start": null,
                      "window_end": null,
                      "removable_step_ids": [],
                      "completed_step_id": null,
                      "completed_tool": null,
                      "updated_at": 1234.5
                    }
                """.trimIndent(),
            ),
        )
        try {
            val result = Agent3ReplanClient(server.url("/").toString(), "token")
                .applyReviewed(reviewedPreview())
            assertTrue(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
            assertNull(result.readReview.windowStart)
            assertNull(result.readReview.windowEnd)
            assertTrue(result.readReview.removableStepIds.isEmpty())
            assertNull(result.readReview.completedStepId)
            assertNull(result.readReview.completedTool)
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
    fun reviewedApplyRejectsMissingOrWrongTypeReadReviewBooleans() {
        val missing = server(applyResponse(includeReadReview = false))
        try {
            assertReadReviewFailure(missing)
        } finally {
            missing.shutdown()
        }

        val wrongType = server(
            applyResponse(
                readReviewJson = validReadReviewJson().replace("\"waiting\": true", "\"waiting\": \"true\""),
            ),
        )
        try {
            assertReadReviewFailure(wrongType)
        } finally {
            wrongType.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsReadReviewWindowAndRemovableIdentityDrift() {
        val staleWindow = server(
            applyResponse(
                readReviewJson = validReadReviewJson().replace("\"window_start\": 1", "\"window_start\": 0"),
            ),
        )
        try {
            assertReadReviewFailure(staleWindow)
        } finally {
            staleWindow.shutdown()
        }

        val wrongIds = server(
            applyResponse(
                readReviewJson = validReadReviewJson().replace("[\"read-new\"]", "[\"read-other\"]"),
            ),
        )
        try {
            assertReadReviewFailure(wrongIds)
        } finally {
            wrongIds.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsCompletedReadIdentityDrift() {
        val wrongStep = server(
            applyResponse(
                readReviewJson = validReadReviewJson().replace(
                    "\"completed_step_id\": \"read-completed\"",
                    "\"completed_step_id\": \"read-other\"",
                ),
            ),
        )
        try {
            assertReadReviewFailure(wrongStep)
        } finally {
            wrongStep.shutdown()
        }

        val wrongTool = server(
            applyResponse(
                readReviewJson = validReadReviewJson().replace(
                    "\"completed_tool\": \"rig_status\"",
                    "\"completed_tool\": \"list_models\"",
                ),
            ),
        )
        try {
            assertReadReviewFailure(wrongTool)
        } finally {
            wrongTool.shutdown()
        }
    }

    @Test
    fun reviewedApplyRejectsStaleCheckpointFieldsWhenNotWaiting() {
        val server = server(
            applyResponse(
                readReviewJson = """
                    {
                      "enabled": true,
                      "waiting": false,
                      "window_start": 1,
                      "window_end": 2,
                      "removable_step_ids": ["read-new"],
                      "completed_step_id": "read-completed",
                      "completed_tool": "rig_status",
                      "updated_at": 1234.5
                    }
                """.trimIndent(),
            ),
        )
        try {
            assertReadReviewFailure(server)
        } finally {
            server.shutdown()
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
            assertEquals("", result.preview.previewId)
            assertFalse(result.readReview.enabled)
            assertFalse(result.readReview.waiting)
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

    private fun assertReadReviewFailure(server: MockWebServer) {
        val error = runCatching {
            Agent3ReplanClient(server.url("/").toString(), "token").applyReviewed(reviewedPreview())
        }.exceptionOrNull()
        assertTrue("Expected ModelRigException for read_review, got $error", error is ModelRigException)
        assertTrue(
            "Expected authority error to name read_review, got ${error?.message}",
            error?.message?.contains("read_review") == true,
        )
    }

    private fun reviewedPreview(
        plannerModel: String? = "planner-a",
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
            removableStepIds = listOf("step-2"),
            immutablePrefixIds = listOf("step-1"),
            immutableTailIds = listOf("step-3"),
        ),
        plan = emptyList(),
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

    private fun validReadReviewJson(): String = """
        {
          "enabled": true,
          "waiting": true,
          "window_start": 1,
          "window_end": 2,
          "removable_step_ids": ["read-new"],
          "completed_step_id": "read-completed",
          "completed_tool": "rig_status",
          "updated_at": 1234.5
        }
    """.trimIndent()

    private fun applyResponse(
        runId: String = "run-1",
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
        readReviewJson: String = validReadReviewJson(),
        includeReadReview: Boolean = true,
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
        val readReviewField = if (includeReadReview) {
            "\"read_review\": $readReviewJson,"
        } else {
            ""
        }
        return """
            {
              "run": {
                "id": "$runId",
                "state": "running",
                "current_step": 1,
                "steps": [
                  {
                    "id": "read-completed",
                    "tool": "rig_status",
                    "args": {},
                    "risk": "read",
                    "sensitivity": "operational",
                    "egress": "none",
                    "summary": "completed read",
                    "state": "succeeded"
                  },
                  {
                    "id": "read-new",
                    "tool": "list_models",
                    "args": {},
                    "risk": "read",
                    "sensitivity": "operational",
                    "egress": "none",
                    "summary": "pending read",
                    "state": "pending"
                  },
                  {
                    "id": "step-3",
                    "tool": "note_append",
                    "args": {"text": "immutable-tail"},
                    "risk": "write",
                    "sensitivity": "operational",
                    "egress": "none",
                    "summary": "immutable tail",
                    "state": "pending"
                  }
                ]
              },
              "replan": {
                "reason": "$receiptReason",
                $fromRevisionField
                "to_revision": $toRevisionJson,
                "replan_number": $replanNumberJson,
                "removed_tools": ["read-a"],
                "added_tools": ["read-b"],
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

package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReadonlyTaskClientTest {
    @Test
    fun previewUsesOnlyAuthenticatedNormalTaskRoute() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(previewJson()))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val preview = client.preview("vis rigstatus", "conversation-1")

            assertEquals("plan-123", preview.planId)
            assertTrue(preview.canStart)
            assertEquals("rig_status", preview.steps.single().tool)
            assertFalse(preview.capabilityReceipt?.productionActivation ?: true)

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/experimental/agent3/task/plan", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            val body = JSONObject(request.body.readUtf8())
            assertEquals(setOf("message", "conversation_id"), body.keys().asSequence().toSet())
            assertEquals("vis rigstatus", body.getString("message"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun startUsesSinglePurposeRouteAndReturnsPollableRunWithTerminationReceipt() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(snapshotJson(state = "running", terminal = false), 202))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val started = client.start("plan-123")

            assertEquals("run-1", started.run.id)
            assertEquals("running", started.run.state)
            assertEquals("rig_tools_local", started.run.routeKind)
            assertFalse(started.terminal)
            assertTrue(started.termination.plan.canRequest)
            assertEquals(
                "prevent_future_steps_active_tool_continues",
                started.termination.plan.effect,
            )
            assertEquals("none", started.termination.activeTool?.semantics)
            assertFalse(started.termination.activeTool?.canRequest ?: true)
            assertTrue(started.events.any { it.kind == "task_surface_bound" })

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/experimental/agent3/task/plans/plan-123/start", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            assertEquals("{}", JSONObject(request.body.readUtf8()).toString())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun statusUsesTaskScopedGetAndParsesTerminalOutcome() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(snapshotJson(state = "completed", terminal = true)))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val status = client.status("run-1")

            assertTrue(status.terminal)
            assertEquals("completed", status.run.state)
            assertEquals("Rig is ready", status.run.answer)
            assertFalse(status.termination.plan.canRequest)
            assertEquals("terminal", status.termination.plan.state)
            assertNull(status.termination.activeTool)

            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/experimental/agent3/task/runs/run-1", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun cancelUsesTaskScopedPostAndKeepsPollingTruthForLateCompletion() {
        val server = MockWebServer()
        server.enqueue(
            jsonResponse(
                snapshotJson(
                    state = "cancelled",
                    terminal = true,
                    stepState = "executing",
                ),
            ),
        )
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "device-token")
            val cancelled = client.cancel("run-1")

            assertTrue(cancelled.terminal)
            assertEquals("cancelled", cancelled.run.state)
            assertFalse(cancelled.termination.plan.canRequest)
            assertEquals("executing", cancelled.termination.activeTool?.state)
            assertEquals("unavailable", cancelled.termination.activeTool?.requestState)
            assertFalse(cancelled.termination.activeTool?.canRequest ?: true)

            val request = server.takeRequest()
            assertEquals("POST", request.method)
            assertEquals("/api/v1/experimental/agent3/task/runs/run-1/cancel", request.path)
            assertEquals("Bearer device-token", request.getHeader("Authorization"))
            assertEquals("{}", JSONObject(request.body.readUtf8()).toString())
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun completedAfterCancelIsTerminalToolTruth() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val snapshot = client.parseStarted(
            JSONObject(
                snapshotJson(
                    state = "cancelled",
                    terminal = true,
                    stepState = "completed_after_cancel",
                ),
            ),
        )

        assertEquals("completed_after_cancel", snapshot.run.steps.single().state)
        assertEquals("terminal", snapshot.termination.activeTool?.requestState)
        assertEquals(
            "tool_completed_after_plan_cancel",
            snapshot.termination.activeTool?.reason,
        )
    }

    @Test
    fun blockedRunNeverOffersPlanStop() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val blocked = client.parseStarted(
            JSONObject(
                snapshotJson(
                    state = "blocked",
                    terminal = true,
                    stepState = "blocked",
                ),
            ),
        )

        assertTrue(blocked.terminal)
        assertEquals("terminal", blocked.termination.plan.state)
        assertFalse(blocked.termination.plan.canRequest)
        assertEquals("not_active", blocked.termination.activeTool?.requestState)
    }

    @Test
    fun unsafePreviewContractsFailClosed() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val write = JSONObject(previewJson()).also {
            it.getJSONArray("plan").getJSONObject(0).put("risk", "write")
        }
        val nonIdempotent = JSONObject(previewJson()).also {
            it.getJSONArray("plan").getJSONObject(0).put("idempotent", false)
        }
        val cloud = JSONObject(previewJson()).also {
            it.getJSONObject("route").put("uses_cloud", true)
        }
        val activation = JSONObject(previewJson()).put("production_activation", true)

        listOf(write, nonIdempotent, cloud, activation).forEach { value ->
            assertTrue(runCatching { client.parsePreview(value) }.exceptionOrNull() is ModelRigException)
        }
    }

    @Test
    fun confirmationWriteTerminalOrTerminationDriftFailsClosed() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val confirmation = JSONObject(snapshotJson(state = "waiting_confirmation", terminal = false))
        val write = JSONObject(snapshotJson(state = "completed", terminal = true)).also {
            it.getJSONObject("run").getJSONArray("steps").getJSONObject(0).put("risk", "write")
        }
        val terminalMismatch = JSONObject(snapshotJson(state = "completed", terminal = false))
        val missingTermination = JSONObject(snapshotJson(state = "running", terminal = false)).also {
            it.remove("termination")
        }
        val falseHandle = JSONObject(snapshotJson(state = "running", terminal = false)).also {
            it.getJSONObject("termination").getJSONObject("active_tool")
                .put("can_request", true)
                .put("handle_present", false)
                .put("request_state", "available")
        }
        val wrongPlanEffect = JSONObject(snapshotJson(state = "running", terminal = false)).also {
            it.getJSONObject("termination").getJSONObject("plan")
                .put("effect", "prevent_future_steps")
        }
        val mismatchedStep = JSONObject(snapshotJson(state = "running", terminal = false)).also {
            it.getJSONObject("termination").getJSONObject("active_tool")
                .put("step_id", "other-step")
        }

        listOf(
            confirmation,
            write,
            terminalMismatch,
            missingTermination,
            falseHandle,
            wrongPlanEffect,
            mismatchedStep,
        ).forEach { value ->
            assertTrue(runCatching { client.parseStarted(value) }.exceptionOrNull() is ModelRigException)
        }
    }

    @Test
    fun statusRejectsAResponseForAnotherRun() {
        val server = MockWebServer()
        server.enqueue(jsonResponse(snapshotJson(state = "completed", terminal = true, runId = "run-2")))
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "token")
            val error = runCatching { client.status("run-1") }.exceptionOrNull()
            assertTrue(error is ModelRigException)
            assertEquals(1, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun malformedOpaqueIdsNeverTouchNetwork() {
        val server = MockWebServer()
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(server.url("/").toString(), "token")
            val calls = listOf<() -> Unit>(
                { client.start("../generic-plan") },
                { client.status("../generic-run") },
                { client.cancel("run/other") },
            )
            calls.forEach { call ->
                assertTrue(runCatching(call).exceptionOrNull() is ModelRigException)
            }
            assertEquals(0, server.requestCount)
        } finally {
            server.shutdown()
        }
    }

    private fun jsonResponse(body: String, code: Int = 200) = MockResponse()
        .setResponseCode(code)
        .addHeader("Content-Type", "application/json")
        .setBody(body)

    private fun envelope(): JSONObject = JSONObject()
        .put("task_surface", "agent3_readonly")
        .put("selected_surface", "agent3_readonly")
        .put("fallback_surface", "agent2")
        .put("reason", "agent3_readonly_selected")
        .put("production_activation", false)
        .put("normal_chat_route_unchanged", true)
        .put(
            "readiness_binding",
            JSONObject()
                .put("pilot_report_sha256", "a".repeat(64))
                .put("pilot_candidate_git_sha", "b".repeat(40))
                .put("rig_validation_report_sha256", "c".repeat(64)),
        )
        .put(
            "capability_receipt",
            JSONObject()
                .put("schema", "kaliv-agent3-capability-receipt/v1")
                .put("graph_sha256", "d".repeat(64))
                .put("plan_sha256", "e".repeat(64))
                .put("route", "rig_tools_local")
                .put("allowed", true)
                .put("blockers", org.json.JSONArray())
                .put("production_activation", false),
        )

    private fun readStep(state: String = "succeeded"): JSONObject = JSONObject()
        .put("id", "step-1")
        .put("tool", "rig_status")
        .put("args", JSONObject())
        .put("risk", "read")
        .put("sensitivity", "operational")
        .put("egress", "local")
        .put("idempotent", true)
        .put("summary", "Read rig status")
        .put("state", state)

    private fun previewJson(): String = envelope()
        .put(
            "route",
            JSONObject()
                .put("kind", "rig_tools_local")
                .put("uses_cloud", false)
                .put("uses_rig", true)
                .put("uses_tools", true)
                .put("uses_rag", false),
        )
        .put("rationale", "Read current status")
        .put("plan", org.json.JSONArray().put(readStep("pending")))
        .put("plan_id", "plan-123")
        .put("expires_in_seconds", 120)
        .put("executed", false)
        .toString()

    private fun snapshotJson(
        state: String,
        terminal: Boolean,
        runId: String = "run-1",
        stepState: String? = null,
    ): String {
        val resolvedStepState = stepState ?: when (state) {
            "running" -> "executing"
            "cancelled" -> "completed_after_cancel"
            "blocked" -> "blocked"
            else -> "succeeded"
        }
        val currentStep = if (state == "completed" || state == "failed") 1 else 0
        return envelope()
            .put(
                "run",
                JSONObject()
                    .put("id", runId)
                    .put("state", state)
                    .put("route", JSONObject().put("kind", "rig_tools_local"))
                    .put("current_step", currentStep)
                    .put("steps", org.json.JSONArray().put(readStep(resolvedStepState)))
                    .put("answer", if (state == "completed") "Rig is ready" else JSONObject.NULL)
                    .put("error", if (state == "cancelled") "Cancelled by user" else JSONObject.NULL),
            )
            .put(
                "events",
                org.json.JSONArray().put(
                    JSONObject()
                        .put("ts", 1.0)
                        .put("kind", "task_surface_bound")
                        .put("payload", JSONObject().put("surface", "agent3_readonly")),
                ),
            )
            .put("termination", terminationJson(state, terminal, resolvedStepState, currentStep))
            .put("terminal", terminal)
            .toString()
    }

    private fun terminationJson(
        runState: String,
        terminal: Boolean,
        stepState: String,
        currentStep: Int,
    ): JSONObject {
        val executing = stepState == "executing"
        val active = if (currentStep == 0) {
            val completedAfterCancel = stepState == "completed_after_cancel"
            JSONObject()
                .put("step_id", "step-1")
                .put("tool", "rig_status")
                .put("state", stepState)
                .put("semantics", "none")
                .put("handle_present", false)
                .put("can_request", false)
                .put(
                    "request_state",
                    when {
                        completedAfterCancel -> "terminal"
                        executing -> "unavailable"
                        else -> "not_active"
                    },
                )
                .put(
                    "reason",
                    when {
                        completedAfterCancel -> "tool_completed_after_plan_cancel"
                        executing -> "synchronous_tool_has_no_cancellation_handle"
                        else -> "tool_is_not_executing"
                    },
                )
        } else {
            JSONObject.NULL
        }
        return JSONObject()
            .put("schema", "kaliv-agent3-termination/v1")
            .put(
                "plan",
                JSONObject()
                    .put("state", if (terminal) "terminal" else "available")
                    .put("can_request", !terminal)
                    .put("request_scope", "plan")
                    .put(
                        "effect",
                        if (executing) {
                            "prevent_future_steps_active_tool_continues"
                        } else {
                            "prevent_future_steps"
                        },
                    )
                    .put("reason", if (terminal) "run_is_terminal" else "plan_stop_is_available"),
            )
            .put(
                "model_stream",
                JSONObject()
                    .put("state", "not_active")
                    .put("active", false)
                    .put("can_request", false)
                    .put("handle_present", false)
                    .put("reason", "agent3_run_has_no_model_stream_handle"),
            )
            .put("active_tool", active)
            .put("production_activation", false)
    }
}

package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpExchange
import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReadonlyTaskClientTest {
    @Test
    fun authenticatedPreviewStartStatusAndPlanStopUseOnlyTaskRoutes() {
        val requests = CopyOnWriteArrayList<RequestSeen>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3/task") { exchange ->
            requests += RequestSeen(
                method = exchange.requestMethod,
                path = exchange.requestURI.path,
                authorization = exchange.requestHeaders.getFirst("Authorization"),
                body = exchange.requestBody.bufferedReader().use { it.readText() },
            )
            when (exchange.requestURI.path) {
                "/api/v1/experimental/agent3/task/plan" -> exchange.respond(200, previewJson())
                "/api/v1/experimental/agent3/task/plans/plan-123/start" ->
                    exchange.respond(202, snapshotJson("running", terminal = false))
                "/api/v1/experimental/agent3/task/runs/run-1" ->
                    exchange.respond(200, snapshotJson("completed", terminal = true))
                "/api/v1/experimental/agent3/task/runs/run-1/cancel" ->
                    exchange.respond(200, snapshotJson("cancelled", terminal = true))
                else -> exchange.respond(404, "{}")
            }
        }
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(
                "http://127.0.0.1:${server.address.port}",
                "device-token",
            )

            val preview = client.preview("vis \"rigstatus\"", "conversation-1")
            val started = client.start(preview.planId!!)
            val completed = client.status(started.run.id)
            val cancelled = client.cancel(started.run.id)

            assertTrue(preview.canStart)
            assertEquals("rig_status", preview.plan.single().tool)
            assertFalse(started.terminal)
            assertEquals("running", started.run.state)
            assertTrue(started.termination.plan.canRequest)
            assertEquals(
                "prevent_future_steps_active_tool_continues",
                started.termination.plan.effect,
            )
            assertEquals("none", started.termination.activeTool?.semantics)
            assertFalse(started.termination.activeTool?.canRequest ?: true)

            assertTrue(completed.terminal)
            assertEquals("Rig is ready", completed.run.answer)
            assertFalse(completed.termination.plan.canRequest)
            assertNull(completed.termination.activeTool)

            assertEquals("cancelled", cancelled.run.state)
            assertEquals("completed_after_cancel", cancelled.termination.activeTool?.state)
            assertEquals("terminal", cancelled.termination.activeTool?.requestState)

            assertEquals(
                listOf("POST", "POST", "GET", "POST"),
                requests.map { it.method },
            )
            assertEquals(
                listOf(
                    "/api/v1/experimental/agent3/task/plan",
                    "/api/v1/experimental/agent3/task/plans/plan-123/start",
                    "/api/v1/experimental/agent3/task/runs/run-1",
                    "/api/v1/experimental/agent3/task/runs/run-1/cancel",
                ),
                requests.map { it.path },
            )
            assertTrue(requests.all { it.authorization == "Bearer device-token" })
            assertTrue(requests.first().body.contains("\\\"rigstatus\\\""))
            assertTrue(requests.first().body.contains("\"conversation_id\":\"conversation-1\""))
            assertEquals("{}", requests[1].body)
            assertEquals("", requests[2].body)
            assertEquals("{}", requests[3].body)
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun cancelledPlanCanRemainTerminalWhileToolStillExecutes() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val value = client.parseSnapshot(
            snapshotJson(
                state = "cancelled",
                terminal = true,
                stepState = "executing",
            ),
        )

        assertTrue(value.terminal)
        assertFalse(value.termination.plan.canRequest)
        assertEquals("executing", value.termination.activeTool?.state)
        assertEquals("unavailable", value.termination.activeTool?.requestState)
        assertFalse(value.termination.activeTool?.canRequest ?: true)
    }

    @Test
    fun completedAfterCancelAndBlockedRunRemainTruthful() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")
        val late = client.parseSnapshot(
            snapshotJson(
                state = "cancelled",
                terminal = true,
                stepState = "completed_after_cancel",
            ),
        )
        val blocked = client.parseSnapshot(
            snapshotJson(
                state = "blocked",
                terminal = true,
                stepState = "blocked",
            ),
        )

        assertEquals("terminal", late.termination.activeTool?.requestState)
        assertEquals("tool_completed_after_plan_cancel", late.termination.activeTool?.reason)
        assertEquals("terminal", blocked.termination.plan.state)
        assertFalse(blocked.termination.plan.canRequest)
        assertEquals("not_active", blocked.termination.activeTool?.requestState)
    }

    @Test
    fun unsafeOrInconsistentContractsFailClosed() {
        val client = Agent3ReadonlyTaskClient("http://127.0.0.1", "token")

        val writePreview = previewJson().replace("\"risk\":\"read\"", "\"risk\":\"write\"")
        val confirmation = snapshotJson("waiting_confirmation", terminal = false)
        val terminalMismatch = snapshotJson("completed", terminal = false)
        val wrongRun = snapshotJson("completed", terminal = true, runId = "run-2")
        val productionActivation = previewJson().replace(
            "\"production_activation\":false",
            "\"production_activation\":true",
        )
        val missingTermination = snapshotJson(
            state = "running",
            terminal = false,
            includeTermination = false,
        )
        val falseHandle = snapshotJson(
            state = "running",
            terminal = false,
            activeCanRequest = true,
            activeHandlePresent = false,
            activeRequestState = "available",
        )
        val wrongPlanEffect = snapshotJson(
            state = "running",
            terminal = false,
            planEffectOverride = "prevent_future_steps",
        )
        val mismatchedStep = snapshotJson(
            state = "running",
            terminal = false,
            activeStepId = "other-step",
        )
        val invalidCurrentStep = snapshotJson(
            state = "running",
            terminal = false,
            currentStepOverride = 2,
        )

        assertIs<Agent3Exception>(runCatching { client.parsePreview(writePreview) }.exceptionOrNull())
        listOf(
            confirmation,
            terminalMismatch,
            missingTermination,
            falseHandle,
            wrongPlanEffect,
            mismatchedStep,
            invalidCurrentStep,
        ).forEach { payload ->
            assertIs<Agent3Exception>(runCatching { client.parseSnapshot(payload) }.exceptionOrNull())
        }
        assertIs<Agent3Exception>(
            runCatching { client.parseSnapshot(wrongRun, expectedRunId = "run-1") }.exceptionOrNull(),
        )
        assertIs<Agent3Exception>(
            runCatching { client.parsePreview(productionActivation) }.exceptionOrNull(),
        )
    }

    @Test
    fun malformedOpaqueIdsNeverTouchNetwork() {
        val hits = AtomicInteger(0)
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/") { exchange ->
            hits.incrementAndGet()
            exchange.respond(500, "{}")
        }
        server.start()
        try {
            val client = Agent3ReadonlyTaskClient(
                "http://127.0.0.1:${server.address.port}",
                "token",
            )
            listOf<() -> Unit>(
                { client.start("../generic-plan") },
                { client.status("../generic-run") },
                { client.cancel("run/other") },
            ).forEach { call ->
                assertIs<Agent3Exception>(runCatching(call).exceptionOrNull())
            }
            assertEquals(0, hits.get())
        } finally {
            server.stop(0)
        }
    }

    private data class RequestSeen(
        val method: String,
        val path: String,
        val authorization: String?,
        val body: String,
    )

    private fun HttpExchange.respond(code: Int, body: String) {
        val bytes = body.toByteArray()
        responseHeaders.add("Content-Type", "application/json")
        sendResponseHeaders(code, bytes.size.toLong())
        responseBody.use { it.write(bytes) }
    }

    private fun envelope(): String =
        """
        "task_surface":"agent3_readonly",
        "selected_surface":"agent3_readonly",
        "fallback_surface":"agent2",
        "reason":"agent3_readonly_selected",
        "production_activation":false,
        "normal_chat_route_unchanged":true,
        "readiness_binding":{
          "pilot_report_sha256":"${"a".repeat(64)}",
          "pilot_candidate_git_sha":"${"b".repeat(40)}",
          "rig_validation_report_sha256":"${"c".repeat(64)}"
        },
        "capability_receipt":{
          "schema":"kaliv-agent3-capability-receipt/v1",
          "graph_sha256":"${"d".repeat(64)}",
          "plan_sha256":"${"e".repeat(64)}",
          "route":"rig_tools_local",
          "allowed":true,
          "blockers":[],
          "production_activation":false
        }
        """.trimIndent()

    private fun step(state: String): String =
        """
        {
          "id":"step-1",
          "tool":"rig_status",
          "args":{},
          "risk":"read",
          "sensitivity":"operational",
          "egress":"local",
          "idempotent":true,
          "summary":"Read rig status",
          "state":"$state",
          "error":null
        }
        """.trimIndent()

    private fun previewJson(): String =
        """
        {
          ${envelope()},
          "route":{
            "kind":"rig_tools_local",
            "uses_cloud":false,
            "uses_rig":true,
            "uses_tools":true,
            "uses_rag":false
          },
          "rationale":"Read current status",
          "plan":[${step("pending")}],
          "plan_id":"plan-123",
          "expires_in_seconds":120,
          "executed":false
        }
        """.trimIndent()

    private fun snapshotJson(
        state: String,
        terminal: Boolean,
        runId: String = "run-1",
        stepState: String? = null,
        includeTermination: Boolean = true,
        planEffectOverride: String? = null,
        activeStepId: String = "step-1",
        activeCanRequest: Boolean = false,
        activeHandlePresent: Boolean = false,
        activeRequestState: String? = null,
        currentStepOverride: Int? = null,
    ): String {
        val resolvedStepState = stepState ?: when (state) {
            "running" -> "executing"
            "cancelled" -> "completed_after_cancel"
            "blocked" -> "blocked"
            else -> "succeeded"
        }
        val currentStep = currentStepOverride ?: if (state == "completed" || state == "failed") 1 else 0
        val answer = if (state == "completed") "\"Rig is ready\"" else "null"
        val error = if (state == "cancelled") "\"Cancelled by user\"" else "null"
        val termination = if (includeTermination) {
            ",\n          \"termination\":${terminationJson(
                terminal = terminal,
                stepState = resolvedStepState,
                currentStep = currentStep,
                planEffectOverride = planEffectOverride,
                activeStepId = activeStepId,
                activeCanRequest = activeCanRequest,
                activeHandlePresent = activeHandlePresent,
                activeRequestState = activeRequestState,
            )}"
        } else {
            ""
        }
        return """
        {
          ${envelope()},
          "run":{
            "id":"$runId",
            "state":"$state",
            "route":{"kind":"rig_tools_local"},
            "current_step":$currentStep,
            "steps":[${step(resolvedStepState)}],
            "answer":$answer,
            "error":$error
          },
          "events":[{
            "ts":1.0,
            "kind":"task_surface_bound",
            "payload":{"surface":"agent3_readonly"}
          }]$termination,
          "terminal":$terminal
        }
        """.trimIndent()
    }

    private fun terminationJson(
        terminal: Boolean,
        stepState: String,
        currentStep: Int,
        planEffectOverride: String?,
        activeStepId: String,
        activeCanRequest: Boolean,
        activeHandlePresent: Boolean,
        activeRequestState: String?,
    ): String {
        val executing = stepState == "executing"
        val completedAfterCancel = stepState == "completed_after_cancel"
        val requestState = activeRequestState ?: when {
            completedAfterCancel -> "terminal"
            executing -> "unavailable"
            else -> "not_active"
        }
        val activeReason = when {
            completedAfterCancel -> "tool_completed_after_plan_cancel"
            executing -> "synchronous_tool_has_no_cancellation_handle"
            else -> "tool_is_not_executing"
        }
        val activeTool = if (currentStep == 0) {
            """
            {
              "step_id":"$activeStepId",
              "tool":"rig_status",
              "state":"$stepState",
              "semantics":"none",
              "handle_present":$activeHandlePresent,
              "can_request":$activeCanRequest,
              "request_state":"$requestState",
              "reason":"$activeReason"
            }
            """.trimIndent()
        } else {
            "null"
        }
        val effect = planEffectOverride ?: if (executing) {
            "prevent_future_steps_active_tool_continues"
        } else {
            "prevent_future_steps"
        }
        return """
        {
          "schema":"kaliv-agent3-termination/v1",
          "plan":{
            "state":"${if (terminal) "terminal" else "available"}",
            "can_request":${!terminal},
            "request_scope":"plan",
            "effect":"$effect",
            "reason":"${if (terminal) "run_is_terminal" else "plan_stop_is_available"}"
          },
          "model_stream":{
            "state":"not_active",
            "active":false,
            "can_request":false,
            "handle_present":false,
            "reason":"agent3_run_has_no_model_stream_handle"
          },
          "active_tool":$activeTool,
          "production_activation":false
        }
        """.trimIndent()
    }
}

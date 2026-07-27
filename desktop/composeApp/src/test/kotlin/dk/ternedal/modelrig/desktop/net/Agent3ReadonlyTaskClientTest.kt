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
import kotlin.test.assertTrue

class Agent3ReadonlyTaskClientTest {
    @Test
    fun authenticatedPreviewStartStatusAndStopUseOnlyTaskRoutes() {
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
            assertTrue(completed.terminal)
            assertEquals("Rig is ready", completed.run.answer)
            assertEquals("cancelled", cancelled.run.state)

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

        assertIs<Agent3Exception>(runCatching { client.parsePreview(writePreview) }.exceptionOrNull())
        assertIs<Agent3Exception>(runCatching { client.parseSnapshot(confirmation) }.exceptionOrNull())
        assertIs<Agent3Exception>(runCatching { client.parseSnapshot(terminalMismatch) }.exceptionOrNull())
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
    ): String {
        val stepState = when (state) {
            "running" -> "executing"
            "cancelled" -> "completed_after_cancel"
            else -> "succeeded"
        }
        val answer = if (state == "completed") "\"Rig is ready\"" else "null"
        val error = if (state == "cancelled") "\"Cancelled by user\"" else "null"
        return """
        {
          ${envelope()},
          "run":{
            "id":"$runId",
            "state":"$state",
            "route":{"kind":"rig_tools_local"},
            "current_step":${if (state == "running") 0 else 1},
            "steps":[${step(stepState)}],
            "answer":$answer,
            "error":$error
          },
          "events":[{
            "ts":1.0,
            "kind":"task_surface_bound",
            "payload":{"surface":"agent3_readonly"}
          }],
          "terminal":$terminal
        }
        """.trimIndent()
    }
}

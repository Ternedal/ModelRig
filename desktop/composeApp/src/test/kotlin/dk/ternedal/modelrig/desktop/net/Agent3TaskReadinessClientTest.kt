package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import java.util.concurrent.atomic.AtomicReference
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class Agent3TaskReadinessClientTest {
    @Test
    fun authenticatedAgent2FallbackUsesOnlyReadinessGet() {
        val method = AtomicReference<String>()
        val authorization = AtomicReference<String>()
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3/task-readiness") { exchange ->
            method.set(exchange.requestMethod)
            authorization.set(exchange.requestHeaders.getFirst("Authorization"))
            val bytes = readinessJson().toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.sendResponseHeaders(200, bytes.size.toLong())
            exchange.responseBody.use { it.write(bytes) }
        }
        server.start()
        try {
            val client = Agent3TaskReadinessClient(
                "http://127.0.0.1:${server.address.port}",
                "device-token",
            )
            val value = client.readiness()

            assertEquals("agent2", value.selectedSurface)
            assertFalse(value.agent3ReadonlySelected)
            assertFalse(value.productionActivation)
            assertTrue(value.normalChatRouteUnchanged)
            assertEquals("GET", method.get())
            assertEquals("Bearer device-token", authorization.get())
        } finally {
            server.stop(0)
        }
    }

    @Test
    fun exactAgent3ReadonlySelectionIsAcceptedAsStateOnly() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val value = client.parse(
            readinessJson(
                selected = "agent3_readonly",
                eligible = true,
                operatorEnabled = true,
                reason = "agent3_readonly_selected",
                reasons = "[]",
            ),
        )

        assertTrue(value.agent3ReadonlySelected)
        assertEquals("agent2", value.fallbackSurface)
        assertTrue(value.uiContract.stopVisible)
        assertTrue(value.uiContract.receiptsVisible)
    }

    @Test
    fun unreadyOrUnknownAgent3ClaimsFailClosed() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")

        val unready = runCatching {
            client.parse(
                readinessJson(
                    selected = "agent3_readonly",
                    eligible = false,
                    operatorEnabled = true,
                    reason = "agent3_readonly_selected",
                    reasons = "[]",
                ),
            )
        }.exceptionOrNull()
        val unknownSchema = runCatching {
            client.parse(readinessJson(schema = "future/v9"))
        }.exceptionOrNull()
        val unknownSurface = runCatching {
            client.parse(readinessJson(selected = "agent4"))
        }.exceptionOrNull()

        assertIs<Agent3Exception>(unready)
        assertIs<Agent3Exception>(unknownSchema)
        assertIs<Agent3Exception>(unknownSurface)
    }

    @Test
    fun incompleteUiSafetyContractIsRejected() {
        val client = Agent3TaskReadinessClient("http://127.0.0.1", "token")
        val error = runCatching {
            client.parse(readinessJson(stopVisible = false))
        }.exceptionOrNull()

        assertIs<Agent3Exception>(error)
        assertTrue(error.message.orEmpty().contains("UI safety contract"))
    }

    private fun readinessJson(
        schema: String = "kaliv-agent3-task-readiness/v1",
        selected: String = "agent2",
        eligible: Boolean = false,
        operatorEnabled: Boolean = true,
        reason: String = "pilot_report_path_not_configured",
        reasons: String = "[\"pilot_report_path_not_configured\"]",
        stopVisible: Boolean = true,
    ): String =
        """
        {
          "schema":"$schema",
          "selected_surface":"$selected",
          "candidate_surface":"agent3_readonly",
          "fallback_surface":"agent2",
          "eligible_for_task_ui":$eligible,
          "operator_enabled":$operatorEnabled,
          "normal_chat_route_unchanged":true,
          "production_activation":false,
          "reason":"$reason",
          "reasons":$reasons,
          "pilot":{
            "configured":${selected == "agent3_readonly"},
            "present":${selected == "agent3_readonly"},
            "structurally_valid":${selected == "agent3_readonly"},
            "fresh":${selected == "agent3_readonly"},
            "version_match":${selected == "agent3_readonly"},
            "code_match":${selected == "agent3_readonly"},
            "tasks":${if (selected == "agent3_readonly") "20" else "null"},
            "successes":${if (selected == "agent3_readonly") "20" else "null"},
            "failures":${if (selected == "agent3_readonly") "0" else "null"},
            "replans":${if (selected == "agent3_readonly") "2" else "null"},
            "retry_events":${if (selected == "agent3_readonly") "0" else "null"},
            "stop_fallback_proven":${selected == "agent3_readonly"}
          },
          "rig_validation":{},
          "ui_contract":{
            "route_source":"server_authoritative",
            "stop_visible":$stopVisible,
            "fallback_visible":true,
            "receipts_visible":true,
            "replans_visible":true,
            "outcomes_visible":true
          }
        }
        """.trimIndent()
}

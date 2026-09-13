package dk.ternedal.modelrig.desktop.net

import com.sun.net.httpserver.HttpServer
import java.net.InetSocketAddress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewedStartDurableRecoveryTest {
    private val digestA = "a".repeat(64)
    private val digestB = "b".repeat(64)

    private fun receipt() = Agent3CapabilityReceipt(
        schema = "kaliv-agent3-capability-receipt/v1",
        graphSha256 = digestA,
        planSha256 = digestB,
        route = "rig",
        allowed = true,
        requiredCapabilityIds = listOf("rig.read"),
        blockers = emptyList(),
        productionActivation = false,
    )

    @Test
    fun recoveryAuthorityRoundTripsExactReviewedContract() {
        val original = Agent3ReviewedStartRecoveryAuthority.capture(" plan-1 ", true, receipt())
        assertNotNull(original)
        val decoded = Agent3ReviewedStartRecoveryAuthority.decode(original.encode())
        assertEquals("plan-1", decoded?.planId)
        assertEquals(true, decoded?.expectedReviewReads)
        assertEquals(receipt(), decoded?.expectedCapabilityReceipt)
    }

    @Test
    fun malformedOrProductionActivatingAuthorityFailsClosed() {
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode("{}"))
        assertNull(
            Agent3ReviewedStartRecoveryAuthority.capture(
                "plan-1",
                true,
                receipt().copy(productionActivation = true),
            )
        )
    }

    @Test
    fun onlyExplicitRefusalClearsRetainedAuthority() {
        assertFalse(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_refused", "refused")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(409, "reviewed_start_pending", "pending")
            )
        )
        assertTrue(
            shouldRetainReviewedStartRecovery(
                Agent3ReviewedStartHttpException(501, "reviewed_start_executor_unavailable", "offline")
            )
        )
        assertTrue(shouldRetainReviewedStartRecovery(IllegalStateException("lost response")))
    }

    @Test
    fun reviewedStartTransportPreservesMachineReadableRefusalReason() {
        val server = HttpServer.create(InetSocketAddress("127.0.0.1", 0), 0)
        server.createContext("/api/v1/experimental/agent3/plans/plan-1/start") { exchange ->
            val body = "{\"detail\":\"reviewed Start is no longer recoverable\"}".toByteArray()
            exchange.responseHeaders.add("Content-Type", "application/json")
            exchange.responseHeaders.add("X-ModelRig-Agent3-Reason", "reviewed_start_refused")
            exchange.sendResponseHeaders(409, body.size.toLong())
            exchange.responseBody.use { it.write(body) }
        }
        server.start()
        try {
            val failure = runCatching {
                Agent3Client("http://127.0.0.1:${server.address.port}", "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()
            assertTrue(failure is Agent3ReviewedStartHttpException)
            failure as Agent3ReviewedStartHttpException
            assertEquals(409, failure.statusCode)
            assertEquals("reviewed_start_refused", failure.reasonCode)
            assertTrue(failure.message.orEmpty().contains("reviewed Start is no longer recoverable"))
        } finally {
            server.stop(0)
        }
    }
}

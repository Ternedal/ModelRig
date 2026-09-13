package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewedStartDurableRecoveryTest {
    private val digestA = "a".repeat(64)
    private val digestB = "b".repeat(64)

    private fun receipt() = Agent3Client.CapabilityReceipt(
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
    fun `recovery authority round trips the exact reviewed contract`() {
        val original = Agent3ReviewedStartRecoveryAuthority.capture(" plan-1 ", true, receipt())
        assertNotNull(original)
        val decoded = Agent3ReviewedStartRecoveryAuthority.decode(original!!.encode())
        assertEquals("plan-1", decoded?.planId)
        assertEquals(true, decoded?.expectedReviewReads)
        assertEquals(receipt(), decoded?.expectedCapabilityReceipt)
    }

    @Test
    fun `malformed or production activating recovery authority fails closed`() {
        assertNull(Agent3ReviewedStartRecoveryAuthority.decode("{}"))
        val unsafe = receipt().copy(productionActivation = true)
        assertNull(Agent3ReviewedStartRecoveryAuthority.capture("plan-1", true, unsafe))
    }

    @Test
    fun `only explicit reviewed Start refusal clears retained authority`() {
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
    fun `reviewed Start transport preserves machine readable refusal reason`() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(409)
                .addHeader("X-ModelRig-Agent3-Reason", "reviewed_start_refused")
                .setBody("{\"detail\":\"reviewed Start is no longer recoverable\"}")
        )
        server.start()
        try {
            val failure = runCatching {
                Agent3Client(server.url("/").toString(), "token")
                    .startReviewedPlanEnvelope("plan-1", true, null)
            }.exceptionOrNull()
            assertTrue(failure is Agent3ReviewedStartHttpException)
            failure as Agent3ReviewedStartHttpException
            assertEquals(409, failure.statusCode)
            assertEquals("reviewed_start_refused", failure.reasonCode)
            assertTrue(failure.message.orEmpty().contains("reviewed Start is no longer recoverable"))
        } finally {
            server.shutdown()
        }
    }
}

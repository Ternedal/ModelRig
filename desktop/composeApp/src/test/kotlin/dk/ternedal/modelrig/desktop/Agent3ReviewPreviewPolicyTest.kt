package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReviewPreviewPolicyTest {
    private val connection = binding("http://rig-a:8080", "token-a")

    private fun binding(base: String, token: String): Agent3DevConnectionBinding =
        requireNotNull(Agent3DevConnectionBinding.capture(base, token))

    private fun intent(
        message: String = "vis status",
        reviewReads: Boolean = false,
    ): Agent3ReviewPreviewIntent =
        requireNotNull(Agent3ReviewPreviewIntent.capture(message, reviewReads))

    @Test
    fun intentCaptureNormalizesMessageAndPreservesReviewMode() {
        assertEquals(intent("vis status", true), intent("  vis status  ", true))
        assertFalse(intent("vis status", false) == intent("vis status", true))
        assertFalse(intent("vis status", false) == intent("vis logs", false))
        assertNull(Agent3ReviewPreviewIntent.capture("   ", false))
    }

    @Test
    fun previewPublicationRequiresExactCurrentIntent() {
        val requested = intent("vis status", false)
        assertTrue(Agent3ReviewPreviewPolicy.canPublish(requested, intent(" vis status ", false)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, intent("vis logs", false)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, intent("vis status", true)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, null))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(null, requested))
    }

    @Test
    fun startAcceptsExactNormalizedConnectionReviewedIntentAndFreshPreview() {
        val reviewed = intent("vis status", true)
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                planId = "plan-1",
                planSize = 1,
                previewFresh = true,
                busy = false,
                currentConnection = binding("  http://rig-a:8080/// ", " token-a "),
                previewConnection = connection,
                currentIntent = intent("  vis status  ", true),
                previewIntent = reviewed,
            )
        )
    }

    @Test
    fun startRejectsExpiredPreview() {
        val reviewed = intent()
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, false, false, connection, connection, reviewed, reviewed,
            )
        )
    }

    @Test
    fun startRejectsMessageReviewModeOrMissingIntentDrift() {
        val reviewed = intent("vis status", false)
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, true, false, connection, connection,
                intent("vis logs", false), reviewed,
            )
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, true, false, connection, connection,
                intent("vis status", true), reviewed,
            )
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, true, false, connection, connection,
                null, reviewed,
            )
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", 1, true, false, connection, connection,
                reviewed, null,
            )
        )
    }

    @Test
    fun existingConnectionPlanAndBusyGuardsRemainFailClosed() {
        val reviewed = intent()
        val otherUrl = binding("http://rig-b:8080", "token-a")
        val otherToken = binding("http://rig-a:8080", "token-b")
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, false, otherUrl, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, false, otherToken, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, false, null, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, false, connection, null, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart(null, 1, true, false, connection, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("", 1, true, false, connection, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 0, true, false, connection, connection, reviewed, reviewed))
        assertFalse(Agent3ReviewPreviewPolicy.canStart("plan-1", 1, true, true, connection, connection, reviewed, reviewed))
    }

    @Test
    fun ttlUsesSharedMonotonicDeadlineAndFailsClosedAtExactBoundary() {
        val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 5)
        assertEquals(15_000L, deadline)
        assertTrue(Agent3TaskUiPolicy.isPreviewFresh(deadline, 14_999L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(deadline, 15_000L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(null, 10_000L))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, null))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 0))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, -1))
    }

    @Test
    fun expiredCopyAppliesOnlyToOtherwiseExecutablePreview() {
        assertTrue(Agent3ReviewPreviewPolicy.shouldMarkExpired("plan-1", 1, false))
        assertFalse(Agent3ReviewPreviewPolicy.shouldMarkExpired("plan-1", 1, true))
        assertFalse(Agent3ReviewPreviewPolicy.shouldMarkExpired(null, 1, false))
        assertFalse(Agent3ReviewPreviewPolicy.shouldMarkExpired("", 1, false))
        assertFalse(Agent3ReviewPreviewPolicy.shouldMarkExpired("plan-1", 0, false))
    }
}

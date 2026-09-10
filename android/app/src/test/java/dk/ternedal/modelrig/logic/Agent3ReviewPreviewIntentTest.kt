package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReviewPreviewIntentTest {
    private val connection = requireNotNull(
        Agent3ReviewConnectionBinding.capture("http://rig-a:8080", "token-a"),
    )

    private fun intent(message: String = "vis status", reviewReads: Boolean = false): Agent3ReviewPreviewIntent =
        requireNotNull(Agent3ReviewPreviewIntent.capture(message, reviewReads))

    @Test
    fun intentCaptureNormalizesMessageAndPreservesReviewMode() {
        assertEquals(intent("vis status", true), intent("  vis status  ", true))
        assertFalse(intent("vis status", false) == intent("vis status", true))
        assertFalse(intent("vis status", false) == intent("vis noget andet", false))
        assertNull(Agent3ReviewPreviewIntent.capture("   ", false))
    }

    @Test
    fun previewPublicationRequiresExactCurrentIntentAndServerReviewMode() {
        val plain = intent("vis status", false)
        val reviewed = intent("vis status", true)
        assertTrue(Agent3ReviewPreviewPolicy.canPublish(plain, intent(" vis status ", false), false))
        assertTrue(Agent3ReviewPreviewPolicy.canPublish(reviewed, intent(" vis status ", true), true))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(plain, intent("vis logs", false), false))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(plain, intent("vis status", true), false))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(plain, plain, true))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(reviewed, reviewed, false))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(plain, null, false))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(null, plain, false))
    }

    @Test
    fun reviewedStartRequiresExactIntentAlongsideConnectionAuthority() {
        val reviewed = intent("vis status", false)
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                previewFresh = true,
                capabilityAllowed = true,
                busy = false,
                hasRun = false,
                currentConnection = connection,
                previewConnection = connection,
                currentIntent = intent(" vis status ", false),
                previewIntent = reviewed,
                previewReviewReads = false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                intent("vis logs", false), reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                intent("vis status", true), reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                null, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                reviewed, null, false,
            ),
        )
    }

    @Test
    fun reviewedStartRequiresFreshPreviewAuthority() {
        val reviewed = intent()
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, false, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
    }

    @Test
    fun reviewedStartUsesServerCapabilityReceiptAuthority() {
        val reviewed = intent()
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, null, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, false, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
    }

    @Test
    fun reviewedStartRequiresStoredServerReviewModeToMatchReviewedIntent() {
        val plain = intent(reviewReads = false)
        val reviewed = intent(reviewReads = true)
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, plain, plain, false,
            ),
        )
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed, true,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, plain, plain, true,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
    }

    @Test
    fun existingPlanRunAndConnectionGuardsRemainFailClosed() {
        val reviewed = intent()
        val otherConnection = requireNotNull(
            Agent3ReviewConnectionBinding.capture("http://rig-b:8080", "token-a"),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                null, true, true, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", false, true, true, false, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, true, false, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, true, connection, connection, reviewed, reviewed, false,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, otherConnection, connection, reviewed, reviewed, false,
            ),
        )
    }
}

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
    fun previewPublicationRequiresExactCurrentIntent() {
        val requested = intent("vis status", false)
        assertTrue(Agent3ReviewPreviewPolicy.canPublish(requested, intent(" vis status ", false)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, intent("vis logs", false)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, intent("vis status", true)))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(requested, null))
        assertFalse(Agent3ReviewPreviewPolicy.canPublish(null, requested))
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
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                intent("vis logs", false), reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                intent("vis status", true), reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                null, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection,
                reviewed, null,
            ),
        )
    }

    @Test
    fun reviewedStartRequiresFreshPreviewAuthority() {
        val reviewed = intent()
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, false, true, false, false, connection, connection, reviewed, reviewed,
            ),
        )
    }

    @Test
    fun reviewedStartUsesServerCapabilityReceiptAuthority() {
        val reviewed = intent()
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertTrue(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, null, false, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, false, false, false, connection, connection, reviewed, reviewed,
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
                null, true, true, true, false, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", false, true, true, false, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, true, false, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, true, connection, connection, reviewed, reviewed,
            ),
        )
        assertFalse(
            Agent3ReviewPreviewPolicy.canStart(
                "plan-1", true, true, true, false, false, otherConnection, connection, reviewed, reviewed,
            ),
        )
    }
}

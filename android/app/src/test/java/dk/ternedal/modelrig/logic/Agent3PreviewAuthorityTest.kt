package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3PreviewAuthorityTest {
    @Test
    fun intentNormalizesVisibleTaskAndMemorySelection() {
        val intent = Agent3PreviewIntent.capture(
            message = "  status please  ",
            useMemory = true,
            memorySubjects = " alpha, beta, alpha, , gamma ",
        )
        requireNotNull(intent)
        assertEquals("status please", intent.message)
        assertTrue(intent.useMemory)
        assertEquals(listOf("alpha", "beta", "gamma"), intent.memorySubjects)

        val withoutMemory = Agent3PreviewIntent.capture("task", false, "ignored")
        requireNotNull(withoutMemory)
        assertEquals(emptyList<String>(), withoutMemory.memorySubjects)
        assertNull(Agent3PreviewIntent.capture("   ", false, ""))
    }

    @Test
    fun staleAsyncPublicationIsRejected() {
        val request = Agent3PreviewIntent.capture("task A", false, "")
        val same = Agent3PreviewIntent.capture(" task A ", false, "ignored")
        val changedMessage = Agent3PreviewIntent.capture("task B", false, "")
        val changedMemory = Agent3PreviewIntent.capture("task A", true, "subject")

        assertTrue(Agent3PreviewAuthorityPolicy.canPublish(request, same))
        assertFalse(Agent3PreviewAuthorityPolicy.canPublish(request, changedMessage))
        assertFalse(Agent3PreviewAuthorityPolicy.canPublish(request, changedMemory))
        assertFalse(Agent3PreviewAuthorityPolicy.canPublish(request, null))
    }

    @Test
    fun startRequiresExactIntentConnectionAndFreshPreview() {
        val previewIntent = Agent3PreviewIntent.capture("task", true, "alpha")
        val connection = Agent3PreviewConnection.capture(" http://rig:8080/ ", " token ")
        requireNotNull(previewIntent)
        requireNotNull(connection)
        assertFalse(connection.toString().contains("token "))

        fun allowed(
            currentIntent: Agent3PreviewIntent? = previewIntent,
            currentConnection: Agent3PreviewConnection? = connection,
            previewFresh: Boolean = true,
        ): Boolean = Agent3PreviewAuthorityPolicy.canStart(
            planId = "plan-1",
            hasSteps = true,
            capabilityAllowed = true,
            previewFresh = previewFresh,
            busy = false,
            hasRun = false,
            currentConnection = currentConnection,
            previewConnection = connection,
            currentIntent = currentIntent,
            previewIntent = previewIntent,
        )

        assertTrue(allowed())
        assertFalse(allowed(currentIntent = Agent3PreviewIntent.capture("changed", true, "alpha")))
        assertFalse(allowed(currentConnection = Agent3PreviewConnection.capture("http://other:8080", "token")))
        assertFalse(allowed(previewFresh = false))
        assertFalse(
            Agent3PreviewAuthorityPolicy.canStart(
                planId = "plan-1",
                hasSteps = true,
                capabilityAllowed = true,
                previewFresh = true,
                busy = true,
                hasRun = false,
                currentConnection = connection,
                previewConnection = connection,
                currentIntent = previewIntent,
                previewIntent = previewIntent,
            ),
        )
    }
}

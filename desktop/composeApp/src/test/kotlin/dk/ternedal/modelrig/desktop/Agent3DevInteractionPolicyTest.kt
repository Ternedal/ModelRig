package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3DevInteractionPolicyTest {
    private val connection = binding("http://rig-a:8080", "token-a")
    private val intent = intent("status", false, "")

    private fun binding(base: String, token: String): Agent3DevConnectionBinding =
        requireNotNull(Agent3DevConnectionBinding.capture(base, token))

    private fun intent(message: String, useMemory: Boolean, subjects: String): Agent3DevPreviewIntent =
        requireNotNull(Agent3DevPreviewIntent.capture(message, useMemory, subjects))

    @Test fun connectionBindingNormalizesWithoutExposingCredential() {
        val value = binding("  http://rig-a:8080///  ", "  secret-token  ")
        assertEquals("http://rig-a:8080", value.baseUrl)
        assertEquals("secret-token", value.token)
        assertFalse(value.toString().contains("secret-token"))
        assertTrue(value.toString().contains("<redacted>"))
    }

    @Test fun blankConnectionFailsClosed() {
        assertNull(Agent3DevConnectionBinding.capture("   ", "token"))
        assertNull(Agent3DevConnectionBinding.capture("http://rig", "   "))
    }

    @Test fun equivalentConnectionMatchesButUrlOrTokenDriftDoesNot() {
        assertEquals(connection, binding(" http://rig-a:8080/ ", " token-a "))
        assertFalse(connection == binding("http://rig-b:8080", "token-a"))
        assertFalse(connection == binding("http://rig-a:8080", "token-b"))
    }

    @Test fun previewIntentNormalizesExactPlannerInputs() {
        val value = intent("  vis status  ", true, " beta, alpha, beta,  ")
        assertEquals("vis status", value.message)
        assertTrue(value.useMemory)
        assertEquals(listOf("beta", "alpha"), value.memorySubjects)
        assertEquals(value, intent("vis status", true, "beta,alpha"))
    }

    @Test fun previewIntentWithoutMemoryIgnoresSubjectTextAndBlankMessageFailsClosed() {
        assertEquals(emptyList(), intent("status", false, "alpha,beta").memorySubjects)
        assertNull(Agent3DevPreviewIntent.capture("   ", false, ""))
    }

    @Test fun previewIntentDriftIsDetected() {
        assertFalse(intent == intent("anden opgave", false, ""))
        assertFalse(intent == intent("status", true, ""))
        val withSubjects = intent("status", true, "alpha,beta")
        assertFalse(withSubjects == intent("status", true, "beta,alpha"))
    }

    @Test fun stalePreviewPublicationFailsClosed() {
        val request = intent("status", true, "alpha,beta")
        assertTrue(Agent3DevInteractionPolicy.canPublishPreview(request, intent(" status ", true, "alpha,beta")))
        assertFalse(Agent3DevInteractionPolicy.canPublishPreview(request, intent("nyere tekst", true, "alpha,beta")))
        assertFalse(Agent3DevInteractionPolicy.canPublishPreview(request, null))
    }

    @Test fun idleSurfaceMayPreview() = assertTrue(
        Agent3DevInteractionPolicy.canPreview("status", false, null)
    )

    @Test fun blankOrBusyPreviewFailsClosed() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("   ", false, null))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", true, null))
    }

    @Test fun activeWaitingAndUnknownRunsRetainAuthority() {
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "running"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "waiting_confirmation"))
        assertFalse(Agent3DevInteractionPolicy.canPreview("status", false, "future_state"))
    }

    @Test fun terminalRunWithExecutingToolCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "executing", "unavailable"
        )
    )

    @Test fun terminalRunWithPendingToolRequestCannotBeReplaced() = assertFalse(
        Agent3DevInteractionPolicy.canPreview(
            "status", false, "cancelled", "completed_after_cancel", "pending"
        )
    )

    @Test fun fullyTerminalRunMayBeReplaced() {
        assertTrue(Agent3DevInteractionPolicy.canPreview("ny opgave", false, "completed"))
        assertTrue(
            Agent3DevInteractionPolicy.canPreview(
                "ny opgave", false, "cancelled", "completed_after_cancel", "terminal"
            )
        )
    }

    @Test fun startRequiresUsablePreviewExactConnectionAndExactReviewedIntent() {
        assertTrue(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, null, true, false, false, connection, connection, intent, intent
            )
        )
        assertTrue(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, true, false, false, connection, connection, intent, intent
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, false, true, false, false, connection, connection, intent, intent
            )
        )
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, true, false, true, connection, connection, intent, intent
            )
        )
    }

    @Test fun startFailsClosedOnConnectionOrIntentDrift() {
        val otherUrl = binding("http://rig-b:8080", "token-a")
        val otherToken = binding("http://rig-a:8080", "token-b")
        val otherIntent = intent("anden opgave", false, "")
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, false, otherUrl, connection, intent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, false, otherToken, connection, intent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, false, connection, connection, otherIntent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, false, connection, connection, intent, null))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, false, false, connection, connection, null, intent))
    }

    @Test fun startRejectsBusyMissingOrEmptyPreview() {
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 1, true, true, true, false, connection, connection, intent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart(null, 1, true, true, false, false, connection, connection, intent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart("", 1, true, true, false, false, connection, connection, intent, intent))
        assertFalse(Agent3DevInteractionPolicy.canStart("plan-1", 0, true, true, false, false, connection, connection, intent, intent))
    }

    @Test fun previewExpiryUsesSharedMonotonicDeadlineAndFailsClosedAtBoundary() {
        val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 5)
        assertEquals(15_000L, deadline)
        assertTrue(Agent3TaskUiPolicy.isPreviewFresh(deadline, 14_999L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(deadline, 15_000L))
        assertTrue(Agent3TaskUiPolicy.isPreviewExpired(deadline, 15_000L))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, null))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 0))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(null, 10_000L))
    }

    @Test fun startFailsClosedWhenReviewedPreviewIsNotFresh() {
        assertFalse(
            Agent3DevInteractionPolicy.canStart(
                "plan-1", 1, true, false, false, false, connection, connection, intent, intent
            )
        )
    }
}

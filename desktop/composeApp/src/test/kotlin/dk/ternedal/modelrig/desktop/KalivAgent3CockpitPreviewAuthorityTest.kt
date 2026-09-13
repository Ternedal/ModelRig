package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivAgent3CockpitPreviewAuthorityTest {
    @Test
    fun intent_is_trimmed_and_blank_is_rejected() {
        assertEquals(
            KalivAgent3CockpitPreviewIntent("inspect rig"),
            KalivAgent3CockpitPreviewIntent.capture("  inspect rig  "),
        )
        assertNull(KalivAgent3CockpitPreviewIntent.capture("   "))
    }

    @Test
    fun connection_is_normalized_and_secret_is_redacted() {
        val connection = KalivAgent3CockpitPreviewConnection.capture(
            "  http://rig.local:8080/  ",
            "  secret-token  ",
        )
        requireNotNull(connection)
        assertEquals("http://rig.local:8080", connection.baseUrl)
        assertEquals("secret-token", connection.bearer)
        assertFalse(connection.toString().contains("secret-token"))
        assertTrue(connection.toString().contains("<redacted>"))
    }

    @Test
    fun empty_bearer_remains_a_valid_local_connection_authority() {
        val connection = KalivAgent3CockpitPreviewConnection.capture("http://127.0.0.1:8080", null)
        requireNotNull(connection)
        assertEquals("", connection.bearer)
    }

    @Test
    fun stale_intent_or_connection_cannot_publish_preview() {
        val requestIntent = KalivAgent3CockpitPreviewIntent.capture("task a")
        val sameIntent = KalivAgent3CockpitPreviewIntent.capture(" task a ")
        val changedIntent = KalivAgent3CockpitPreviewIntent.capture("task b")
        val requestConnection = KalivAgent3CockpitPreviewConnection.capture("http://rig-a", "token-a")
        val sameConnection = KalivAgent3CockpitPreviewConnection.capture("http://rig-a/", " token-a ")
        val changedConnection = KalivAgent3CockpitPreviewConnection.capture("http://rig-b", "token-b")

        assertTrue(
            KalivAgent3CockpitPreviewAuthorityPolicy.canPublish(
                requestIntent,
                sameIntent,
                requestConnection,
                sameConnection,
            )
        )
        assertFalse(
            KalivAgent3CockpitPreviewAuthorityPolicy.canPublish(
                requestIntent,
                changedIntent,
                requestConnection,
                sameConnection,
            )
        )
        assertFalse(
            KalivAgent3CockpitPreviewAuthorityPolicy.canPublish(
                requestIntent,
                sameIntent,
                requestConnection,
                changedConnection,
            )
        )
    }

    @Test
    fun start_requires_exact_intent_connection_and_fresh_preview() {
        val intent = KalivAgent3CockpitPreviewIntent.capture("task")
        val otherIntent = KalivAgent3CockpitPreviewIntent.capture("other")
        val connection = KalivAgent3CockpitPreviewConnection.capture("http://rig", "token")
        val otherConnection = KalivAgent3CockpitPreviewConnection.capture("http://other", "token")

        fun canStart(
            fresh: Boolean = true,
            currentIntent: KalivAgent3CockpitPreviewIntent? = intent,
            currentConnection: KalivAgent3CockpitPreviewConnection? = connection,
        ): Boolean = KalivAgent3CockpitPreviewAuthorityPolicy.canStart(
            planId = "plan-1",
            hasSteps = true,
            previewFresh = fresh,
            busy = false,
            hasRun = false,
            currentIntent = currentIntent,
            previewIntent = intent,
            currentConnection = currentConnection,
            previewConnection = connection,
        )

        assertTrue(canStart())
        assertFalse(canStart(fresh = false))
        assertFalse(canStart(currentIntent = otherIntent))
        assertFalse(canStart(currentConnection = otherConnection))
        assertFalse(
            KalivAgent3CockpitPreviewAuthorityPolicy.canStart(
                planId = null,
                hasSteps = true,
                previewFresh = true,
                busy = false,
                hasRun = false,
                currentIntent = intent,
                previewIntent = intent,
                currentConnection = connection,
                previewConnection = connection,
            )
        )
    }
}

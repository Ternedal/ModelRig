package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3ReplanPreviewAuthorityTest {
    @Test
    fun captureNormalizesRunIdAndOptionalPlannerModel() {
        assertEquals(
            Agent3ReplanPreviewIntent("run-1", "planner-a"),
            Agent3ReplanPreviewIntent.capture("  run-1  ", "  planner-a  "),
        )
        assertEquals(
            Agent3ReplanPreviewIntent("run-1", null),
            Agent3ReplanPreviewIntent.capture("run-1", "   "),
        )
        assertNull(Agent3ReplanPreviewIntent.capture("   ", "planner-a"))
    }

    @Test
    fun publishRequiresExactCurrentIntentAndServerRunId() {
        val request = Agent3ReplanPreviewIntent("run-1", "planner-a")

        assertTrue(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = request,
                responseRunId = "run-1",
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = Agent3ReplanPreviewIntent("run-2", "planner-a"),
                responseRunId = "run-1",
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = Agent3ReplanPreviewIntent("run-1", "planner-b"),
                responseRunId = "run-1",
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = request,
                responseRunId = "run-2",
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = null,
                responseRunId = "run-1",
            ),
        )
    }

    @Test
    fun applyRequiresExactIntentConnectionPreviewBindingAndFreshness() {
        val intent = Agent3ReplanPreviewIntent("run-1", "planner-a")
        val connection = requireNotNull(
            Agent3ReviewConnectionBinding.capture(" https://rig.local/ ", " token-a "),
        )

        assertTrue(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                previewFresh = true,
                busy = false,
                currentIntent = intent,
                previewIntent = intent,
                currentConnection = connection,
                previewConnection = Agent3ReviewConnectionBinding.capture(
                    "https://rig.local",
                    "token-a",
                ),
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                previewFresh = false,
                busy = false,
                currentIntent = intent,
                previewIntent = intent,
                currentConnection = connection,
                previewConnection = connection,
            ),
        )
    }

    @Test
    fun sharedDeadlineTreatsMissingInvalidAndExpiredTtlAsNoApplyAuthority() {
        val started = 10_000L
        val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(started, 30)
        assertEquals(40_000L, deadline)
        assertTrue(Agent3TaskUiPolicy.isPreviewFresh(deadline, 39_999L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(deadline, 40_000L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(null, 10_001L))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(started, 0))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(started, -1))
    }

    @Test
    fun applyRejectsIntentOrConnectionDrift() {
        val intent = Agent3ReplanPreviewIntent("run-1", null)
        val connection = requireNotNull(
            Agent3ReviewConnectionBinding.capture("https://rig.local", "token-a"),
        )

        assertFalse(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                previewFresh = true,
                busy = false,
                currentIntent = Agent3ReplanPreviewIntent("run-2", null),
                previewIntent = intent,
                currentConnection = connection,
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                previewFresh = true,
                busy = false,
                currentIntent = intent,
                previewIntent = intent,
                currentConnection = Agent3ReviewConnectionBinding.capture(
                    "https://rig.local",
                    "token-b",
                ),
                previewConnection = connection,
            ),
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                previewFresh = true,
                busy = false,
                currentIntent = intent,
                previewIntent = intent,
                currentConnection = Agent3ReviewConnectionBinding.capture(
                    "https://other-rig.local",
                    "token-a",
                ),
                previewConnection = connection,
            ),
        )
    }

    @Test
    fun applyRejectsMissingOrMismatchedPreviewAuthorityBusyStateAndStalePreview() {
        val intent = Agent3ReplanPreviewIntent("run-1", null)
        val connection = requireNotNull(
            Agent3ReviewConnectionBinding.capture("https://rig.local", "token-a"),
        )

        fun allowed(
            previewId: String = "preview-1",
            previewRunId: String = "run-1",
            previewFresh: Boolean = true,
            busy: Boolean = false,
            previewIntent: Agent3ReplanPreviewIntent? = intent,
            currentConnection: Agent3ReviewConnectionBinding? = connection,
            previewConnection: Agent3ReviewConnectionBinding? = connection,
        ): Boolean = Agent3ReplanPreviewPolicy.canApply(
            previewId = previewId,
            previewRunId = previewRunId,
            previewFresh = previewFresh,
            busy = busy,
            currentIntent = intent,
            previewIntent = previewIntent,
            currentConnection = currentConnection,
            previewConnection = previewConnection,
        )

        assertFalse(allowed(previewId = ""))
        assertFalse(allowed(previewRunId = "run-2"))
        assertFalse(allowed(previewFresh = false))
        assertFalse(allowed(busy = true))
        assertFalse(allowed(previewIntent = null))
        assertFalse(allowed(currentConnection = null))
        assertFalse(allowed(previewConnection = null))
    }
}

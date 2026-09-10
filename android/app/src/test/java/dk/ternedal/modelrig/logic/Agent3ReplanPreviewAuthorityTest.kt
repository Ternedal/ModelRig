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
    fun applyRequiresExactIntentConnectionAndPreviewBinding() {
        val intent = Agent3ReplanPreviewIntent("run-1", "planner-a")
        val connection = requireNotNull(
            Agent3ReviewConnectionBinding.capture(" https://rig.local/ ", " token-a "),
        )

        assertTrue(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
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
    fun applyRejectsMissingOrMismatchedPreviewAuthorityAndBusyState() {
        val intent = Agent3ReplanPreviewIntent("run-1", null)
        val connection = requireNotNull(
            Agent3ReviewConnectionBinding.capture("https://rig.local", "token-a"),
        )

        fun allowed(
            previewId: String = "preview-1",
            previewRunId: String = "run-1",
            busy: Boolean = false,
            previewIntent: Agent3ReplanPreviewIntent? = intent,
            currentConnection: Agent3ReviewConnectionBinding? = connection,
            previewConnection: Agent3ReviewConnectionBinding? = connection,
        ): Boolean = Agent3ReplanPreviewPolicy.canApply(
            previewId = previewId,
            previewRunId = previewRunId,
            busy = busy,
            currentIntent = intent,
            previewIntent = previewIntent,
            currentConnection = currentConnection,
            previewConnection = previewConnection,
        )

        assertFalse(allowed(previewId = ""))
        assertFalse(allowed(previewRunId = "run-2"))
        assertFalse(allowed(busy = true))
        assertFalse(allowed(previewIntent = null))
        assertFalse(allowed(currentConnection = null))
        assertFalse(allowed(previewConnection = null))
    }
}

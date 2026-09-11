package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class Agent3ReplanPreviewAuthorityTest {
    private val connection = requireNotNull(
        Agent3DevConnectionBinding.capture("http://rig-a:8080", "token-a")
    )

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
                currentIntent = Agent3ReplanPreviewIntent("run-1", "planner-a"),
                responseRunId = "run-1",
            )
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = Agent3ReplanPreviewIntent("run-2", "planner-a"),
                responseRunId = "run-1",
            )
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = Agent3ReplanPreviewIntent("run-1", "planner-b"),
                responseRunId = "run-1",
            )
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = request,
                responseRunId = "run-other",
            )
        )
        assertFalse(
            Agent3ReplanPreviewPolicy.canPublish(
                requestIntent = request,
                currentIntent = null,
                responseRunId = "run-1",
            )
        )
    }

    @Test
    fun applyAcceptsExactNormalizedIntentConnectionAndPreviewRun() {
        val reviewed = Agent3ReplanPreviewIntent("run-1", null)
        val normalizedConnection = requireNotNull(
            Agent3DevConnectionBinding.capture("  http://rig-a:8080///  ", " token-a ")
        )

        assertTrue(
            Agent3ReplanPreviewPolicy.canApply(
                previewId = "preview-1",
                previewRunId = "run-1",
                busy = false,
                currentIntent = Agent3ReplanPreviewIntent.capture(" run-1 ", "   "),
                previewIntent = reviewed,
                currentConnection = normalizedConnection,
                previewConnection = connection,
            )
        )
    }

    @Test
    fun applyRejectsRunModelOrServerPreviewRunDrift() {
        val reviewed = Agent3ReplanPreviewIntent("run-1", "planner-a")
        assertFalse(canApply(reviewed, currentIntent = Agent3ReplanPreviewIntent("run-2", "planner-a")))
        assertFalse(canApply(reviewed, currentIntent = Agent3ReplanPreviewIntent("run-1", "planner-b")))
        assertFalse(canApply(reviewed, previewRunId = "run-other"))
    }

    @Test
    fun applyRejectsConnectionDriftMissingAuthorityBusyOrBlankPreviewId() {
        val reviewed = Agent3ReplanPreviewIntent("run-1", "planner-a")
        val otherUrl = Agent3DevConnectionBinding.capture("http://rig-b:8080", "token-a")
        val otherToken = Agent3DevConnectionBinding.capture("http://rig-a:8080", "token-b")

        assertFalse(canApply(reviewed, currentConnection = otherUrl))
        assertFalse(canApply(reviewed, currentConnection = otherToken))
        assertFalse(canApply(reviewed, currentConnection = null))
        assertFalse(canApply(reviewed, previewConnection = null))
        assertFalse(canApply(reviewed, currentIntent = null))
        assertFalse(canApply(reviewed, previewIntent = null))
        assertFalse(canApply(reviewed, busy = true))
        assertFalse(canApply(reviewed, previewId = ""))
    }

    private fun canApply(
        reviewed: Agent3ReplanPreviewIntent,
        previewId: String = "preview-1",
        previewRunId: String = reviewed.runId,
        busy: Boolean = false,
        currentIntent: Agent3ReplanPreviewIntent? = reviewed,
        previewIntent: Agent3ReplanPreviewIntent? = reviewed,
        currentConnection: Agent3DevConnectionBinding? = connection,
        previewConnection: Agent3DevConnectionBinding? = connection,
    ): Boolean = Agent3ReplanPreviewPolicy.canApply(
        previewId = previewId,
        previewRunId = previewRunId,
        busy = busy,
        currentIntent = currentIntent,
        previewIntent = previewIntent,
        currentConnection = currentConnection,
        previewConnection = previewConnection,
    )
}

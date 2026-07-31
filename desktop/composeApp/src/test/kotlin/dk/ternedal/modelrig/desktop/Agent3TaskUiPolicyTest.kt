package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class Agent3TaskUiPolicyTest {
    @Test
    fun unknownReadinessIsAgent2AndCannotPreview() {
        listOf(null, "", "agent3", "future_surface").forEach { value ->
            assertEquals(Agent3TaskUiPolicy.AGENT2, Agent3TaskUiPolicy.normalizedSurface(value))
            assertFalse(
                Agent3TaskUiPolicy.canPreview(
                    serverSurface = value,
                    message = "vis rigstatus",
                    busy = false,
                    hasRun = false,
                ),
            )
        }
    }

    @Test
    fun exactServerSurfaceOwnsPreviewAndStart() {
        assertTrue(
            Agent3TaskUiPolicy.canPreview(
                Agent3TaskUiPolicy.AGENT3_READONLY,
                "vis rigstatus",
                busy = false,
                hasRun = false,
            ),
        )
        assertTrue(
            Agent3TaskUiPolicy.canStart(
                Agent3TaskUiPolicy.AGENT3_READONLY,
                previewCanStart = true,
                busy = false,
                hasRun = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canStart(
                Agent3TaskUiPolicy.AGENT2,
                previewCanStart = true,
                busy = false,
                hasRun = false,
            ),
        )
    }

    @Test
    fun persistedRunKeepsServerAuthorizedPlanStopAfterFallback() {
        assertEquals(Agent3TaskUiPolicy.AGENT2, Agent3TaskUiPolicy.normalizedSurface("stale"))
        assertTrue(Agent3TaskUiPolicy.canStopPlan(planCanRequest = true, busy = false))
        assertFalse(Agent3TaskUiPolicy.canStopPlan(planCanRequest = false, busy = false))
        assertFalse(Agent3TaskUiPolicy.canStopPlan(planCanRequest = true, busy = true))
    }

    @Test
    fun cancelledPlanKeepsPollingWhileActiveToolStillRuns() {
        assertTrue(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = true,
                activeToolState = "executing",
                activeToolRequestState = "unavailable",
            ),
        )
        assertTrue(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = true,
                activeToolState = "executing",
                activeToolRequestState = "pending",
            ),
        )
    }

    @Test
    fun pollingStopsOnlyAfterRunAndToolAreTruthfullyTerminal() {
        assertTrue(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = false,
                activeToolState = null,
                activeToolRequestState = null,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = true,
                activeToolState = "completed_after_cancel",
                activeToolRequestState = "terminal",
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = true,
                activeToolState = null,
                activeToolRequestState = null,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.shouldPoll(
                runTerminal = null,
                activeToolState = null,
                activeToolRequestState = null,
            ),
        )
    }
}

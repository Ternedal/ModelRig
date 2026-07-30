package dk.ternedal.modelrig.logic

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class Agent3TaskUiPolicyTest {
    @Test
    fun missingOrUnknownReadinessFallsBackToAgent2() {
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
    fun previewAndStartRequireExactServerSelectedReadonlySurface() {
        assertTrue(
            Agent3TaskUiPolicy.canPreview(
                serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
                message = "vis rigstatus",
                busy = false,
                hasRun = false,
            ),
        )
        assertTrue(
            Agent3TaskUiPolicy.canStart(
                serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
                previewCanStart = true,
                busy = false,
                hasRun = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canStart(
                serverSurface = Agent3TaskUiPolicy.AGENT2,
                previewCanStart = true,
                busy = false,
                hasRun = false,
            ),
        )
    }

    @Test
    fun planStopRemainsAvailableAfterReadinessFallbackOnlyWhenServerAllowsIt() {
        assertTrue(Agent3TaskUiPolicy.canStopPlan(planCanRequest = true, busy = false))

        // Deliberately independent of the current selected surface: once the rig
        // persisted a task run, fallback must not hide its server-authored control plane.
        assertEquals(Agent3TaskUiPolicy.AGENT2, Agent3TaskUiPolicy.normalizedSurface("stale"))
        assertTrue(Agent3TaskUiPolicy.canStopPlan(planCanRequest = true, busy = false))
        assertFalse(Agent3TaskUiPolicy.canStopPlan(planCanRequest = false, busy = false))
        assertFalse(Agent3TaskUiPolicy.canStopPlan(planCanRequest = true, busy = true))
        assertFalse(Agent3TaskUiPolicy.canStopPlan(planCanRequest = null, busy = false))
    }

    @Test
    fun cancelledPlanKeepsPollingWhileToolStillExecutes() {
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
    fun pollingEndsOnlyWhenRunAndActiveToolAreTerminal() {
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
                activeToolState = "blocked",
                activeToolRequestState = "not_active",
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

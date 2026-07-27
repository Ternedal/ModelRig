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
    fun activeRunCanStillBeStoppedAfterReadinessFallback() {
        assertTrue(Agent3TaskUiPolicy.canStop(runTerminal = false, busy = false))
        assertTrue(Agent3TaskUiPolicy.shouldPoll(runTerminal = false))

        // Deliberately independent of the current selected surface: once the rig
        // persisted a task run, fallback must not hide its control plane.
        assertEquals(Agent3TaskUiPolicy.AGENT2, Agent3TaskUiPolicy.normalizedSurface("stale"))
        assertTrue(Agent3TaskUiPolicy.canStop(runTerminal = false, busy = false))
    }

    @Test
    fun terminalOrBusyRunCannotBeStoppedOrPolled() {
        assertFalse(Agent3TaskUiPolicy.canStop(runTerminal = true, busy = false))
        assertFalse(Agent3TaskUiPolicy.canStop(runTerminal = false, busy = true))
        assertFalse(Agent3TaskUiPolicy.shouldPoll(runTerminal = true))
        assertFalse(Agent3TaskUiPolicy.shouldPoll(runTerminal = null))
    }
}

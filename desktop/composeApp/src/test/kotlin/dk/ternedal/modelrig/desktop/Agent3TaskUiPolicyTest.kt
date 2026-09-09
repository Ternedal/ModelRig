package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
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
                previewFresh = true,
                busy = false,
                hasRun = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canStart(
                Agent3TaskUiPolicy.AGENT2,
                previewCanStart = true,
                previewFresh = true,
                busy = false,
                hasRun = false,
            ),
        )
    }

    @Test
    fun previewAuthorityUsesFiniteMonotonicDeadlineAndFailsClosed() {
        val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 120)
        assertEquals(130_000L, deadline)
        assertTrue(Agent3TaskUiPolicy.isPreviewFresh(deadline, 129_999L))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(deadline, 130_000L))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, null))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, 0))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(10_000L, -1))
        assertNull(Agent3TaskUiPolicy.previewDeadlineMillis(-1L, 120))
        assertFalse(Agent3TaskUiPolicy.isPreviewFresh(null, 10_000L))
        assertFalse(Agent3TaskUiPolicy.isPreviewExpired(null, 10_000L))
        assertFalse(Agent3TaskUiPolicy.isPreviewExpired(deadline, 129_999L))
        assertTrue(Agent3TaskUiPolicy.isPreviewExpired(deadline, 130_000L))
        assertEquals(
            Long.MAX_VALUE,
            Agent3TaskUiPolicy.previewDeadlineMillis(Long.MAX_VALUE - 500L, 1),
        )
        assertTrue(
            Agent3TaskUiPolicy.canStart(
                serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
                previewCanStart = true,
                previewFresh = true,
                busy = false,
                hasRun = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canStart(
                serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
                previewCanStart = true,
                previewFresh = false,
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

    @Test
    fun stalePollCannotPublishAfterNewerTaskMutationOwnsTheScreen() {
        val pollEpoch = 41L
        val mutationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(pollEpoch)

        assertEquals(42L, mutationEpoch)
        assertTrue(Agent3TaskUiPolicy.canPublish(mutationEpoch, mutationEpoch))
        assertFalse(Agent3TaskUiPolicy.canPublish(pollEpoch, mutationEpoch))
    }

    @Test
    fun publicationEpochWrapsDeterministically() {
        assertEquals(1L, Agent3TaskUiPolicy.nextPublicationEpoch(Long.MAX_VALUE))
    }

    @Test
    fun retainedRunReferenceBlocksNewTaskUntilServerTruthIsRecovered() {
        assertTrue(Agent3TaskUiPolicy.hasRunAuthority(snapshotPresent = false, retainedRunId = "run_abc123"))
        assertFalse(
            Agent3TaskUiPolicy.canPreview(
                serverSurface = Agent3TaskUiPolicy.AGENT3_READONLY,
                message = "ny opgave",
                busy = false,
                hasRun = Agent3TaskUiPolicy.hasRunAuthority(false, "run_abc123"),
            ),
        )
        assertTrue(Agent3TaskUiPolicy.canRecoverRun("run_abc123", busy = false))
        assertFalse(Agent3TaskUiPolicy.canRecoverRun("run_abc123", busy = true))
    }

    @Test
    fun onlyServerTerminalSnapshotClearsRetainedRunReference() {
        assertEquals(
            "run_abc123",
            Agent3TaskUiPolicy.retainedRunIdAfterSnapshot("run_abc123", terminal = false),
        )
        assertNull(Agent3TaskUiPolicy.retainedRunIdAfterSnapshot("run_abc123", terminal = true))
    }

    @Test
    fun actionTimeReadinessBindingMustExactlyMatchReviewedPreview() {
        val pilot = "a".repeat(64)
        val candidate = "b".repeat(40)
        val rig = "c".repeat(64)
        assertTrue(Agent3TaskUiPolicy.readinessBindingMatches(pilot, candidate, rig, pilot, candidate, rig))
        assertFalse(Agent3TaskUiPolicy.readinessBindingMatches(null, candidate, rig, pilot, candidate, rig))
        assertFalse(Agent3TaskUiPolicy.readinessBindingMatches(pilot, null, rig, pilot, candidate, rig))
        assertFalse(Agent3TaskUiPolicy.readinessBindingMatches(pilot, candidate, null, pilot, candidate, rig))
        assertFalse(
            Agent3TaskUiPolicy.readinessBindingMatches(
                "d".repeat(64), candidate, rig, pilot, candidate, rig,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.readinessBindingMatches(
                pilot, "d".repeat(40), rig, pilot, candidate, rig,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.readinessBindingMatches(
                pilot, candidate, "d".repeat(64), pilot, candidate, rig,
            ),
        )
    }

    @Test
    fun terminalHistoryResetWaitsForFullRunAndToolTruth() {
        assertFalse(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = false,
                activeToolState = null,
                activeToolRequestState = null,
                busy = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = true,
                activeToolState = "executing",
                activeToolRequestState = "unavailable",
                busy = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = true,
                activeToolState = "completed_after_cancel",
                activeToolRequestState = "pending",
                busy = false,
            ),
        )
        assertTrue(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = true,
                activeToolState = "completed_after_cancel",
                activeToolRequestState = "terminal",
                busy = false,
            ),
        )
        assertTrue(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = true,
                activeToolState = null,
                activeToolRequestState = null,
                busy = false,
            ),
        )
        assertFalse(
            Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = true,
                activeToolState = null,
                activeToolRequestState = null,
                busy = true,
            ),
        )
    }
}

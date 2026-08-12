package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleGrant
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleRuntime
import kotlin.test.Test
import kotlin.test.assertEquals

class ControlCenterSchedulesSectionTest {
    @Test
    fun runtimeLabelsDoNotTurnStoppedOrUnconfiguredIntoRunning() {
        assertEquals("Scheduler kører", desktopScheduleRuntimeLabel(runtime(running = true)))
        assertEquals(
            "Konfigureret · stoppet",
            desktopScheduleRuntimeLabel(runtime(running = false, configured = true)),
        )
        assertEquals(
            "Ikke konfigureret",
            desktopScheduleRuntimeLabel(runtime(running = false, configured = false)),
        )
    }

    @Test
    fun grantStateLabelsPreserveBlockingReasonsBeforeEligibility() {
        assertEquals("Deaktiveret", desktopScheduleGrantStateLabel(grant(enabled = false)))
        assertEquals("Udløbet", desktopScheduleGrantStateLabel(grant(expired = true)))
        assertEquals("Budget opbrugt", desktopScheduleGrantStateLabel(grant(budgetExhausted = true)))
        assertEquals("Strukturelt klar", desktopScheduleGrantStateLabel(grant()))
        assertEquals(
            "Blokeret",
            desktopScheduleGrantStateLabel(grant(structurallyEligible = false, blockedReason = "policy")),
        )
    }

    @Test
    fun budgetLabelDistinguishesUnlimitedAndBoundedGrants() {
        assertEquals("2/5 kørsler", desktopScheduleBudgetLabel(grant(runsUsed = 2, maxRuns = 5)))
        assertEquals(
            "7 kørsler · intet run-loft",
            desktopScheduleBudgetLabel(grant(runsUsed = 7, maxRuns = 0)),
        )
    }

    @Test
    fun schedulerErrorsStayUnavailableInsteadOfHealthy() {
        assertEquals(
            "Scheduler-status er ikke eksponeret på denne rig.",
            desktopControlCenterSchedulesError("failed (404): scheduler api disabled"),
        )
        assertEquals(
            "Scheduler-status er midlertidigt utilgængelig fra riggen.",
            desktopControlCenterSchedulesError("failed (502)"),
        )
        assertEquals(
            "Scheduler-status kunne ikke hentes.",
            desktopControlCenterSchedulesError(null),
        )
    }

    private fun runtime(
        running: Boolean,
        configured: Boolean = true,
    ) = ControlCenterScheduleRuntime(
        configured = configured,
        running = running,
        resourcesOpen = running,
        lastError = null,
        maxConcurrency = 1,
        queueCapacity = 0,
        activeExecutions = 0,
        acceptedTicks = 0,
        overlapRejections = 0,
    )

    private fun grant(
        enabled: Boolean = true,
        expired: Boolean = false,
        budgetExhausted: Boolean = false,
        structurallyEligible: Boolean = true,
        blockedReason: String? = null,
        runsUsed: Int = 2,
        maxRuns: Int = 5,
    ) = ControlCenterScheduleGrant(
        id = "0a1b2c3d4e5f",
        tool = "note_append",
        cadence = "daily:08:00",
        timezone = "Europe/Copenhagen",
        misfirePolicy = "run_once",
        dueAtLocal = "2026-08-12T08:00:00+02:00",
        risk = "write",
        sensitivity = "private",
        expiresAt = 2_000_000_000.0,
        expired = expired,
        maxRuns = maxRuns,
        runsUsed = runsUsed,
        budgetExhausted = budgetExhausted,
        dueAt = 1_900_000_000.0,
        missed = 0,
        enabled = enabled,
        structurallyEligible = structurallyEligible,
        blockedReason = blockedReason,
    )
}

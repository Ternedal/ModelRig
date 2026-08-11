package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ControlCenterScheduleGrant
import dk.ternedal.modelrig.net.ControlCenterScheduleRuntime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ControlCenterScreenTest {
    @Test
    fun overallLabelsNeverTurnUnknownIntoHealthy() {
        assertEquals("Alt ser godt ud", controlCenterOverallLabel("healthy"))
        assertEquals("Kræver opmærksomhed", controlCenterOverallLabel("attention"))
        assertEquals("Utilgængelig", controlCenterOverallLabel("unavailable"))
        assertEquals("Status er ukendt", controlCenterOverallLabel("unknown"))
        assertEquals("Ukendt status", controlCenterOverallLabel("future-state"))
    }

    @Test
    fun componentLabelsKeepStaleUnknownAndDisabledDistinct() {
        assertEquals("Klar", controlCenterStateLabel("healthy"))
        assertEquals("Forældet", controlCenterStateLabel("stale"))
        assertEquals("Ukendt", controlCenterStateLabel("unknown"))
        assertEquals("Slået fra", controlCenterStateLabel("disabled"))
        assertEquals("Fallback", controlCenterStateLabel("fallback"))
        assertEquals("Utilgængelig", controlCenterStateLabel("unavailable"))
        assertEquals("Ukendt", controlCenterStateLabel("synthetic-green"))
    }

    @Test
    fun componentNamesAreHumanReadable() {
        assertEquals("Backend", controlCenterComponentTitle("backend"))
        assertEquals("Worker", controlCenterComponentTitle("worker"))
        assertEquals("Modeller", controlCenterComponentTitle("models"))
        assertEquals("Agent 3", controlCenterComponentTitle("agent3"))
        assertEquals("custom", controlCenterComponentTitle("custom"))
    }

    @Test
    fun ageLabelsAreBoundedAndNeverInventInvalidFreshness() {
        assertEquals("målt nu", controlCenterAgeLabel(0.0))
        assertEquals("målt for 12 sek. siden", controlCenterAgeLabel(12.0))
        assertEquals("målt for 2 min. siden", controlCenterAgeLabel(125.0))
        assertNull(controlCenterAgeLabel(null))
        assertNull(controlCenterAgeLabel(-1.0))
        assertNull(controlCenterAgeLabel(Double.NaN))
        assertNull(controlCenterAgeLabel(Double.POSITIVE_INFINITY))
    }

    @Test
    fun capabilityLabelsDescribeAuthorityWithoutInventingHealth() {
        assertEquals("læse", controlCenterAccessLabel("read"))
        assertEquals("skrive", controlCenterAccessLabel("write"))
        assertEquals("desktop", controlCenterAccessLabel("desktop"))
        assertEquals("future-access", controlCenterAccessLabel("future-access"))
        assertEquals("ikke direkte afbrydelig", controlCenterTerminationLabel("none"))
        assertEquals("kooperativ stop", controlCenterTerminationLabel("cooperative"))
        assertEquals("runtime-stop", controlCenterTerminationLabel("forceable"))
        assertEquals("future-stop", controlCenterTerminationLabel("future-stop"))
    }

    @Test
    fun schedulerRuntimeLabelDoesNotTurnConfigurationIntoExecutionSuccess() {
        assertEquals("Kører", controlCenterSchedulerRuntimeLabel(runtime(configured = true, running = true)))
        assertEquals(
            "Stoppet · ressourcer åbne",
            controlCenterSchedulerRuntimeLabel(runtime(configured = true, running = false, resourcesOpen = true)),
        )
        assertEquals(
            "Konfigureret · ikke startet",
            controlCenterSchedulerRuntimeLabel(runtime(configured = true, running = false)),
        )
        assertEquals("Slået fra", controlCenterSchedulerRuntimeLabel(runtime(configured = false, running = false)))
    }

    @Test
    fun grantLabelDescribesGrantOnlyAndNeverInventsOutcome() {
        assertEquals("Grant gyldig", controlCenterScheduleGrantLabel(grant()))
        assertEquals("Pauset", controlCenterScheduleGrantLabel(grant(enabled = false, eligible = false)))
        assertEquals("Udløbet", controlCenterScheduleGrantLabel(grant(expired = true, eligible = false)))
        assertEquals(
            "Budget brugt",
            controlCenterScheduleGrantLabel(grant(budgetExhausted = true, eligible = false)),
        )
        assertEquals("Blokeret", controlCenterScheduleGrantLabel(grant(eligible = false)))
    }

    private fun runtime(
        configured: Boolean,
        running: Boolean,
        resourcesOpen: Boolean = false,
    ) = ControlCenterScheduleRuntime(
        configured = configured,
        running = running,
        resourcesOpen = resourcesOpen,
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
        eligible: Boolean = true,
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
        maxRuns = if (budgetExhausted) 2 else 5,
        runsUsed = 2,
        budgetExhausted = budgetExhausted,
        dueAt = 1_900_000_000.0,
        missed = 0,
        enabled = enabled,
        structurallyEligible = eligible,
        blockedReason = if (eligible) null else "blocked",
    )
}

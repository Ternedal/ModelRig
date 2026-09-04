package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ControlCenterHistorySource
import dk.ternedal.modelrig.desktop.net.ControlCenterObservedJob
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleOccurrence
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertNull

class ControlCenterScheduleHistorySectionTest {
    @Test
    fun occurrenceLabelsKeepOutcomeAuthorityOnOccurrenceLedger() {
        val releasedWithCompletedJob = occurrence(
            occurrenceStatus = "released",
            inFlight = false,
            terminalOutcome = "not_run",
            job = ControlCenterObservedJob(
                status = "completed",
                kind = "schedule_tool_call",
                progressCompleted = 1,
                progressTotal = 1,
                createdAt = 100.0,
                updatedAt = 101.0,
            ),
        )

        assertEquals("Ikke kørt", desktopControlCenterOccurrenceLabel(releasedWithCompletedJob))
        assertEquals("ikke kørt", desktopControlCenterTerminalOutcomeLabel(releasedWithCompletedJob.terminalOutcome))
        assertEquals("completed", releasedWithCompletedJob.job?.status)
    }

    @Test
    fun pendingAndFutureStatesNeverBecomeTerminalSuccess() {
        assertEquals(
            "Reserveret · i gang",
            desktopControlCenterOccurrenceLabel(
                occurrence("reserved", true, null),
            ),
        )
        assertEquals(
            "Venter på execution-slot",
            desktopControlCenterOccurrenceLabel(
                occurrence("reserved_noslot", true, null),
            ),
        )
        assertEquals(
            "Ukendt · nyere serverstatus",
            desktopControlCenterOccurrenceLabel(
                occurrence("unknown_schema_value", null, "unknown"),
            ),
        )
        assertNull(desktopControlCenterTerminalOutcomeLabel(null))
        assertEquals("ukendt", desktopControlCenterTerminalOutcomeLabel("future-outcome"))
    }

    @Test
    fun sourceLabelsPreserveUnavailableAndNotRequiredStates() {
        assertEquals(
            "tilgængelig",
            desktopControlCenterHistorySourceLabel(ControlCenterHistorySource("ready", null)),
        )
        assertEquals(
            "utilgængelig",
            desktopControlCenterHistorySourceLabel(
                ControlCenterHistorySource("unavailable", "database_missing"),
            ),
        )
        assertEquals(
            "ikke nødvendig",
            desktopControlCenterHistorySourceLabel(ControlCenterHistorySource("not_required", null)),
        )
        assertEquals(
            "ukendt",
            desktopControlCenterHistorySourceLabel(ControlCenterHistorySource("future", null)),
        )
    }

    @Test
    fun timeLabelsDoNotInventInvalidTimestamps() {
        assertEquals("ukendt tidspunkt", desktopControlCenterHistoryTimeLabel(-1.0))
        assertEquals("ukendt tidspunkt", desktopControlCenterHistoryTimeLabel(Double.NaN))
        assertEquals("ukendt tidspunkt", desktopControlCenterHistoryTimeLabel(Double.POSITIVE_INFINITY))
        assertNotEquals("ukendt tidspunkt", desktopControlCenterHistoryTimeLabel(1_900_000_000.0))
    }

    @Test
    fun historyErrorsRemainNeutralAndBounded() {
        assertEquals(
            "Execution-historikken er ikke tilgængelig fra riggen lige nu.",
            desktopControlCenterScheduleHistoryError("schedule history failed (502): unavailable"),
        )
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopControlCenterScheduleHistoryError("failed (401)"),
        )
        assertEquals(
            "Execution-historikken kunne ikke hentes.",
            desktopControlCenterScheduleHistoryError(null),
        )
    }

    private fun occurrence(
        occurrenceStatus: String,
        inFlight: Boolean?,
        terminalOutcome: String?,
        job: ControlCenterObservedJob? = null,
    ) = ControlCenterScheduleOccurrence(
        occurrenceId = "occ-1",
        scheduleId = "schedule-1",
        tool = "note_append",
        dueAt = 1_900_000_000.0,
        occurrenceStatus = occurrenceStatus,
        inFlight = inFlight,
        terminalOutcome = terminalOutcome,
        createdAt = 1_899_999_900.0,
        resolvedAt = null,
        jobId = job?.let { "job-1" },
        job = job,
    )
}

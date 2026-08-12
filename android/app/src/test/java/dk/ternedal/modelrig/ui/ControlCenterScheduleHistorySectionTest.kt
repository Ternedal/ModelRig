package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ControlCenterHistorySource
import dk.ternedal.modelrig.net.ControlCenterObservedJob
import dk.ternedal.modelrig.net.ControlCenterScheduleOccurrence
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ControlCenterScheduleHistorySectionTest {
    @Test
    fun occurrenceLabelFollowsLedgerStateNotJobObservation() {
        val released = occurrence(
            status = "released",
            inFlight = false,
            outcome = "not_run",
            job = completedJob(),
        )
        assertEquals("Ikke kørt", controlCenterOccurrenceLabel(released))
        assertEquals("ikke kørt", controlCenterTerminalOutcomeLabel(released.terminalOutcome))

        val executed = occurrence(
            status = "executed",
            inFlight = false,
            outcome = "executed",
            job = completedJob(),
        )
        assertEquals("Udført", controlCenterOccurrenceLabel(executed))
        assertEquals("udført", controlCenterTerminalOutcomeLabel(executed.terminalOutcome))
    }

    @Test
    fun pendingAndFutureStatesStayDistinctFromTerminalSuccess() {
        assertEquals(
            "Reserveret · i gang",
            controlCenterOccurrenceLabel(occurrence("reserved", true, null)),
        )
        assertEquals(
            "Venter på execution-slot",
            controlCenterOccurrenceLabel(occurrence("reserved_noslot", true, null)),
        )
        assertEquals(
            "Ukendt · nyere serverstatus",
            controlCenterOccurrenceLabel(occurrence("unknown_schema_value", null, "unknown")),
        )
        assertNull(controlCenterTerminalOutcomeLabel(null))
        assertEquals("ukendt", controlCenterTerminalOutcomeLabel("unknown"))
        assertEquals("ukendt", controlCenterTerminalOutcomeLabel("future-value"))
    }

    @Test
    fun sourceLabelsNeverTurnUnavailableIntoReady() {
        assertEquals(
            "tilgængelig",
            controlCenterHistorySourceLabel(ControlCenterHistorySource("ready", null)),
        )
        assertEquals(
            "utilgængelig",
            controlCenterHistorySourceLabel(ControlCenterHistorySource("unavailable", "database_missing")),
        )
        assertEquals(
            "ikke nødvendig",
            controlCenterHistorySourceLabel(ControlCenterHistorySource("not_required", null)),
        )
        assertEquals(
            "ukendt",
            controlCenterHistorySourceLabel(ControlCenterHistorySource("future", null)),
        )
    }

    @Test
    fun invalidHistoryTimeNeverInventsTimestamp() {
        assertEquals("ukendt tidspunkt", controlCenterHistoryTimeLabel(-1.0))
        assertEquals("ukendt tidspunkt", controlCenterHistoryTimeLabel(Double.NaN))
        assertEquals("ukendt tidspunkt", controlCenterHistoryTimeLabel(Double.POSITIVE_INFINITY))
    }

    private fun occurrence(
        status: String,
        inFlight: Boolean?,
        outcome: String?,
        job: ControlCenterObservedJob? = null,
    ) = ControlCenterScheduleOccurrence(
        occurrenceId = "claim-1",
        scheduleId = "0a1b2c3d4e5f",
        tool = "note_append",
        dueAt = 1_900_000_000.0,
        occurrenceStatus = status,
        inFlight = inFlight,
        terminalOutcome = outcome,
        createdAt = 1_899_999_990.0,
        resolvedAt = if (outcome == null) null else 1_900_000_010.0,
        jobId = if (job == null) null else "job-1",
        job = job,
    )

    private fun completedJob() = ControlCenterObservedJob(
        status = "completed",
        kind = "schedule_tool_call",
        progressCompleted = 1,
        progressTotal = 1,
        createdAt = 1_899_999_991.0,
        updatedAt = 1_900_000_009.0,
    )
}

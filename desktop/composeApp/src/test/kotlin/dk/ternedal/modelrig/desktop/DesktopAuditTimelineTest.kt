package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.AuditEntry
import java.time.LocalDate
import java.time.ZoneId
import kotlin.test.Test
import kotlin.test.assertEquals

class DesktopAuditTimelineTest {
    private val copenhagen = ZoneId.of("Europe/Copenhagen")
    private val today = LocalDate.of(2026, 9, 12)

    @Test
    fun groupsTodayYesterdayAndOlderWithoutChangingServerOrder() {
        val rows = listOf(
            audit("2026-09-12T08:30:00", "rig_status", "executed"),
            audit("2026-09-11T08:30:00", "note_append", "denied"),
            // Deliberately surprising server order: today appears again after
            // yesterday. Presentation must not sort an audit trail to look tidy.
            audit("2026-09-12T09:00:00", "list_models", "executed"),
            audit("2026-09-09T08:30:00", "job_status", "error"),
        )

        val groups = desktopAuditTimelineGroups(rows, today, copenhagen)

        assertEquals(listOf("I DAG", "I GÅR", "I DAG", "9. SEPTEMBER 2026"), groups.map { it.label })
        assertEquals(
            listOf("rig_status", "note_append", "list_models", "job_status"),
            groups.flatMap { it.rows }.map { it.entry.tool },
        )
    }

    @Test
    fun utcWireTimestampIsShownInOperatorsLocalZone() {
        // Worker writes gmtime without a trailing Z. 22:30 UTC on the 11th is
        // 00:30 on the 12th in Copenhagen (CEST), therefore I DAG.
        val groups = desktopAuditTimelineGroups(
            listOf(audit("2026-09-11T22:30:00", "rig_status", "executed")),
            today,
            copenhagen,
        )

        assertEquals("I DAG", groups.single().label)
        assertEquals("00:30", groups.single().rows.single().timeLabel)
        assertEquals("00:30 · Læsning · Lokalt", groups.single().rows.single().metadataLabel)
    }

    @Test
    fun knownMachineCodesBecomeOperatorLabels() {
        val row = desktopAuditTimelineGroups(
            listOf(
                AuditEntry(
                    ts = "2026-09-12T08:30:00",
                    tool = "desktop_action_preview",
                    risk = "desktop",
                    outcome = "blocked",
                    origin = "schedule",
                    rawResultSummary = "Handling blev stoppet.",
                ),
            ),
            today,
            copenhagen,
        ).single().rows.single()

        assertEquals("Computerhandling", row.toolLabel)
        assertEquals("Blokeret", row.outcomeLabel)
        assertEquals(DesktopAuditTone.Warning, row.tone)
        assertEquals("10:30 · Computerstyring · Planlagt", row.metadataLabel)
        assertEquals("Handling blev stoppet.", row.summary)
    }

    @Test
    fun unknownValuesStayVisibleAndAreNotInventedIntoKnownMeaning() {
        val row = desktopAuditTimelineGroups(
            listOf(
                AuditEntry(
                    ts = "2026-09-12T08:30:00",
                    tool = "future_tool_v9",
                    risk = "metered",
                    outcome = "paused_by_peer",
                    origin = "remote_lab",
                    rawResultSummary = "future result",
                ),
            ),
            today,
            copenhagen,
        ).single().rows.single()

        assertEquals("Værktøj: future_tool_v9", row.toolLabel)
        assertEquals("paused_by_peer", row.outcomeLabel)
        assertEquals(DesktopAuditTone.Neutral, row.tone)
        assertEquals("10:30 · Risiko: metered · Kilde: remote_lab", row.metadataLabel)
    }

    @Test
    fun invalidTimestampFailsClosedIntoUnknownDateGroup() {
        val groups = desktopAuditTimelineGroups(
            listOf(audit("not-a-timestamp", "rig_status", "executed")),
            today,
            copenhagen,
        )

        assertEquals("UKENDT DATO", groups.single().label)
        assertEquals("not-a-timestamp", groups.single().rows.single().timeLabel)
    }

    @Test
    fun outcomePaletteIsDeterministic() {
        assertEquals("Udført" to DesktopAuditTone.Success, auditOutcome("executed"))
        assertEquals("Afvist" to DesktopAuditTone.Warning, auditOutcome("denied"))
        assertEquals("Blokeret" to DesktopAuditTone.Warning, auditOutcome("blocked"))
        assertEquals("Udløbet" to DesktopAuditTone.Warning, auditOutcome("expired"))
        assertEquals("Fejl" to DesktopAuditTone.Error, auditOutcome("error"))
        assertEquals("future" to DesktopAuditTone.Neutral, auditOutcome("future"))
    }

    private fun audit(ts: String, tool: String, outcome: String) = AuditEntry(
        ts = ts,
        tool = tool,
        risk = "read",
        outcome = outcome,
        origin = "local",
        rawResultSummary = "summary",
    )
}

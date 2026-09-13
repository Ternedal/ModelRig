package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.AuditEntry
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZoneOffset
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException
import java.util.Locale

internal enum class DesktopAuditTone { Success, Warning, Error, Neutral }

internal data class DesktopAuditTimelineRow(
    val entry: AuditEntry,
    val timeLabel: String,
    val toolLabel: String,
    val outcomeLabel: String,
    val tone: DesktopAuditTone,
    val metadataLabel: String,
    val summary: String,
)

internal data class DesktopAuditTimelineGroup(
    val label: String,
    val rows: List<DesktopAuditTimelineRow>,
)

/**
 * Presentation-only view of the append-only audit trail.
 *
 * Worker timestamps are UTC (`time.gmtime`) but intentionally omit a trailing
 * Z. We interpret the documented wire value as UTC and convert it to the
 * operator's system zone for day grouping and clock display. Invalid/future
 * timestamps fail closed into an honest "UKENDT DATO" group instead of being
 * guessed.
 *
 * Groups are built CONTIGUOUSLY in server order. We deliberately do not sort:
 * if a future server returns surprising timestamps, the UI must not rewrite
 * the audit sequence just to make it look tidy.
 */
internal fun desktopAuditTimelineGroups(
    entries: List<AuditEntry>,
    today: LocalDate = LocalDate.now(),
    zone: ZoneId = ZoneId.systemDefault(),
): List<DesktopAuditTimelineGroup> {
    val groups = mutableListOf<DesktopAuditTimelineGroup>()
    var currentKey: LocalDate? = null
    var currentUnknown = false
    var currentLabel: String? = null
    var currentRows = mutableListOf<DesktopAuditTimelineRow>()

    fun flush() {
        val label = currentLabel ?: return
        groups += DesktopAuditTimelineGroup(label, currentRows.toList())
        currentRows = mutableListOf()
    }

    entries.forEach { entry ->
        val local = parseAuditTimestamp(entry.ts, zone)
        val date = local?.toLocalDate()
        val unknown = local == null
        val label = when {
            date == null -> "UKENDT DATO"
            date == today -> "I DAG"
            date == today.minusDays(1) -> "I GÅR"
            else -> date.format(DANISH_DATE).uppercase(DANISH)
        }

        if (currentLabel != null && (date != currentKey || unknown != currentUnknown)) {
            flush()
        }
        if (currentLabel == null || date != currentKey || unknown != currentUnknown) {
            currentKey = date
            currentUnknown = unknown
            currentLabel = label
        }

        val (outcomeLabel, tone) = auditOutcome(entry.outcome)
        val time = local?.format(TIME) ?: entry.ts.trim().take(19).replace('T', ' ').ifBlank { "Tid ukendt" }
        val metadata = listOf(time, auditRiskLabel(entry.risk), auditOriginLabel(entry.origin))
            .joinToString(" · ")

        currentRows += DesktopAuditTimelineRow(
            entry = entry,
            timeLabel = time,
            toolLabel = auditToolLabel(entry.tool),
            outcomeLabel = outcomeLabel,
            tone = tone,
            metadataLabel = metadata,
            summary = entry.result_summary.trim(),
        )
    }
    flush()
    return groups
}

internal fun auditToolLabel(tool: String): String = when (tool.trim().lowercase()) {
    "rig_status" -> "Rigstatus"
    "note_append" -> "Notat"
    "list_models" -> "Installerede modeller"
    "list_documents" -> "Dokumenter"
    "current_datetime" -> "Dato og tid"
    "job_status" -> "Jobstatus"
    "cancel_job" -> "Annuller job"
    "pull_model" -> "Hent model"
    "delete_model" -> "Slet model"
    "desktop_screenshot" -> "Skærmbillede"
    "desktop_action_preview" -> "Computerhandling"
    "web_research" -> "Webresearch"
    "github_read" -> "GitHub-læsning"
    "" -> "Ukendt værktøj"
    else -> "Værktøj: ${tool.trim()}"
}

internal fun auditOutcome(outcome: String): Pair<String, DesktopAuditTone> = when (outcome.trim().lowercase()) {
    "executed" -> "Udført" to DesktopAuditTone.Success
    "denied" -> "Afvist" to DesktopAuditTone.Warning
    "blocked" -> "Blokeret" to DesktopAuditTone.Warning
    "expired" -> "Udløbet" to DesktopAuditTone.Warning
    "error", "failed" -> "Fejl" to DesktopAuditTone.Error
    "" -> "Ukendt status" to DesktopAuditTone.Neutral
    else -> outcome.trim() to DesktopAuditTone.Neutral
}

internal fun auditRiskLabel(risk: String): String = when (risk.trim().lowercase()) {
    "read" -> "Læsning"
    "write" -> "Ændring"
    "desktop" -> "Computerstyring"
    "destructive" -> "Destruktiv"
    "admin" -> "Administration"
    "" -> "Risiko ukendt"
    else -> "Risiko: ${risk.trim()}"
}

internal fun auditOriginLabel(origin: String): String = when (origin.trim().lowercase()) {
    "local" -> "Lokalt"
    "cloud" -> "Cloud-forslag"
    "schedule" -> "Planlagt"
    "agent", "agent_v2" -> "Agent"
    "agent3", "agent_3" -> "Agent 3"
    "" -> "Kilde ukendt"
    else -> "Kilde: ${origin.trim()}"
}

private fun parseAuditTimestamp(ts: String, zone: ZoneId): ZonedDateTime? {
    val raw = ts.trim()
    if (raw.length < 19) return null
    return try {
        LocalDateTime.parse(raw.take(19), DateTimeFormatter.ISO_LOCAL_DATE_TIME)
            .atOffset(ZoneOffset.UTC)
            .atZoneSameInstant(zone)
    } catch (_: DateTimeParseException) {
        null
    }
}

@Composable
internal fun DesktopAuditDialog(
    rows: List<AuditEntry>,
    error: String?,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Handlingslog", fontWeight = FontWeight.SemiBold) },
        text = {
            DesktopAuditTimeline(
                rows = rows,
                error = error,
                modifier = Modifier.height(420.dp),
            )
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text("Luk") } },
    )
}

@Composable
private fun DesktopAuditTimeline(
    rows: List<AuditEntry>,
    error: String?,
    modifier: Modifier = Modifier,
) {
    Column(modifier.verticalScroll(rememberScrollState()).fillMaxWidth()) {
        error?.let {
            Text(it, color = KalivTheme.colors.Danger, fontSize = 12.sp)
            Spacer(Modifier.height(8.dp))
        }
        if (rows.isEmpty() && error == null) {
            Text("Ingen handlinger endnu", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
            return@Column
        }

        val groups = desktopAuditTimelineGroups(rows)
        groups.forEachIndexed { groupIndex, group ->
            if (groupIndex > 0) Spacer(Modifier.height(14.dp))
            Text(
                group.label,
                color = KalivTheme.colors.Signal,
                fontSize = 11.sp,
                fontWeight = FontWeight.Bold,
            )
            Spacer(Modifier.height(7.dp))
            group.rows.forEachIndexed { rowIndex, row ->
                DesktopAuditTimelineItem(
                    row = row,
                    drawLine = rowIndex < group.rows.lastIndex,
                )
            }
        }
    }
}

@Composable
private fun DesktopAuditTimelineItem(row: DesktopAuditTimelineRow, drawLine: Boolean) {
    val toneColor: Color = when (row.tone) {
        DesktopAuditTone.Success -> KalivTheme.colors.Success
        DesktopAuditTone.Warning -> KalivTheme.colors.Warning
        DesktopAuditTone.Error -> KalivTheme.colors.Danger
        DesktopAuditTone.Neutral -> KalivTheme.colors.TextMuted
    }

    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.Top) {
        Column(
            modifier = Modifier.width(18.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Spacer(Modifier.height(5.dp))
            Box(Modifier.size(8.dp).background(toneColor, CircleShape))
            if (drawLine) {
                Box(Modifier.width(1.dp).height(48.dp).background(KalivTheme.colors.Border))
            }
        }
        Spacer(Modifier.width(8.dp))
        Column(Modifier.fillMaxWidth().padding(bottom = if (drawLine) 5.dp else 0.dp)) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    row.toolLabel,
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    row.outcomeLabel,
                    color = toneColor,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Text(row.metadataLabel, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            if (row.summary.isNotBlank()) {
                Spacer(Modifier.height(3.dp))
                Text(
                    row.summary,
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 12.sp,
                    lineHeight = 17.sp,
                )
            }
        }
    }
}

private val DANISH = Locale("da", "DK")
private val DANISH_DATE = DateTimeFormatter.ofPattern("d. MMMM yyyy", DANISH)
private val TIME = DateTimeFormatter.ofPattern("HH:mm")

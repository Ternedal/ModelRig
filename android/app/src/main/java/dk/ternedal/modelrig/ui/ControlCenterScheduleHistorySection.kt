package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.ControlCenterHistorySource
import dk.ternedal.modelrig.net.ControlCenterScheduleHistory
import dk.ternedal.modelrig.net.ControlCenterScheduleOccurrence
import dk.ternedal.modelrig.ui.theme.KalivTheme
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToLong

internal fun controlCenterOccurrenceLabel(occurrence: ControlCenterScheduleOccurrence): String = when (
    occurrence.occurrenceStatus
) {
    "reserved" -> "Reserveret · i gang"
    "reserved_noslot" -> "Venter på execution-slot"
    "executed" -> "Udført"
    "released" -> "Ikke kørt"
    "abandoned" -> "Forladt"
    "unknown" -> "Ukendt udfald"
    "unknown_schema_value" -> "Ukendt · nyere serverstatus"
    else -> "Ukendt udfald"
}

internal fun controlCenterTerminalOutcomeLabel(outcome: String?): String? = when (outcome) {
    null -> null
    "executed" -> "udført"
    "not_run" -> "ikke kørt"
    "abandoned" -> "forladt"
    "unknown" -> "ukendt"
    else -> "ukendt"
}

internal fun controlCenterHistorySourceLabel(source: ControlCenterHistorySource): String = when (source.state) {
    "ready" -> "tilgængelig"
    "not_required" -> "ikke nødvendig"
    "unavailable" -> "utilgængelig"
    else -> "ukendt"
}

internal fun controlCenterHistoryTimeLabel(epochSeconds: Double): String {
    if (!epochSeconds.isFinite() || epochSeconds < 0.0) return "ukendt tidspunkt"
    return runCatching {
        val formatter = SimpleDateFormat("dd.MM.yyyy HH:mm:ss", Locale.getDefault())
        formatter.format(Date((epochSeconds * 1000.0).roundToLong()))
    }.getOrDefault("ukendt tidspunkt")
}

@Composable
internal fun ControlCenterScheduleHistorySection(
    history: ControlCenterScheduleHistory?,
    error: String?,
) {
    Column(Modifier.padding(top = 10.dp)) {
        Text(
            "Execution-historik",
            color = KalivTheme.colors.textHigh,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Occurrence-ledger = outcome-authority · JobStore = separat observation · kun læsning",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Spacer(Modifier.height(8.dp))

        if (error != null) {
            HistoryNeutralCard {
                Text(
                    "Execution-historik ikke tilgængelig",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(error, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text(
                    "Manglende history-evidens bliver ikke fortolket som succes eller som tom historik.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }
            Spacer(Modifier.height(8.dp))
        }

        if (history != null) {
            HistorySourcesCard(history)
            Spacer(Modifier.height(8.dp))
            if (history.items.isEmpty()) {
                HistoryNeutralCard {
                    Text(
                        if (history.occurrenceSource.state == "ready") {
                            "Ingen registrerede occurrences i den aktuelle history-projektion."
                        } else {
                            "Occurrence-ledgeren kan ikke aflæses."
                        },
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                history.items.forEach { occurrence ->
                    HistoryOccurrenceCard(occurrence)
                    Spacer(Modifier.height(8.dp))
                }
            }
        }
    }
}

@Composable
private fun HistorySourcesCard(history: ControlCenterScheduleHistory) {
    HistoryNeutralCard {
        Text(
            "Datakilder",
            color = KalivTheme.colors.textHigh,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
        )
        HistorySourceLine("Occurrence-ledger", history.occurrenceSource)
        HistorySourceLine("JobStore", history.jobsSource)
        Text(
            "Genereret: ${controlCenterHistoryTimeLabel(history.generatedAt)}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        Text(
            "Production activation: nej",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun HistorySourceLine(label: String, source: ControlCenterHistorySource) {
    Text(
        "$label: ${controlCenterHistorySourceLabel(source)}" +
            (source.reason?.let { " · $it" } ?: ""),
        color = KalivTheme.colors.textMuted,
        fontSize = 11.sp,
    )
}

@Composable
private fun HistoryOccurrenceCard(occurrence: ControlCenterScheduleOccurrence) {
    HistoryNeutralCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    occurrence.tool ?: "Ukendt tool",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Schedule ${occurrence.scheduleId}",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }
            Text(
                controlCenterOccurrenceLabel(occurrence),
                color = KalivTheme.colors.textHigh,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(5.dp))
        Text(
            "Forfald: ${controlCenterHistoryTimeLabel(occurrence.dueAt)}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Occurrence: ${occurrence.occurrenceId}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        controlCenterTerminalOutcomeLabel(occurrence.terminalOutcome)?.let { outcome ->
            Text(
                "Terminalt outcome: $outcome",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
        }
        when (occurrence.inFlight) {
            true -> Text("In-flight: ja", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
            false -> Text("In-flight: nej", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
            null -> Text("In-flight: ukendt", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        }
        occurrence.resolvedAt?.let {
            Text(
                "Afsluttet: ${controlCenterHistoryTimeLabel(it)}",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
        }
        occurrence.job?.let { job ->
            Spacer(Modifier.height(5.dp))
            Text(
                "Job-observation: ${job.status} · ${job.kind}",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            Text(
                if (job.progressTotal > 0) {
                    "Job-progress: ${job.progressCompleted}/${job.progressTotal}"
                } else {
                    "Job-progress: ${job.progressCompleted} · total ikke angivet"
                },
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
        }
        Text(
            "Outcome ovenfor kommer kun fra occurrence-ledgeren; JobStore-status ændrer det ikke.",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun HistoryNeutralCard(content: @Composable () -> Unit) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) { content() }
    }
}

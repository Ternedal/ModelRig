package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterHistorySource
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleHistory
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleHistoryClient
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleOccurrence
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.roundToLong

internal fun desktopControlCenterOccurrenceLabel(
    occurrence: ControlCenterScheduleOccurrence,
): String = when (occurrence.occurrenceStatus) {
    "reserved" -> "Reserveret · i gang"
    "reserved_noslot" -> "Venter på execution-slot"
    "executed" -> "Udført"
    "released" -> "Ikke kørt"
    "abandoned" -> "Forladt"
    "unknown" -> "Ukendt udfald"
    "unknown_schema_value" -> "Ukendt · nyere serverstatus"
    else -> "Ukendt udfald"
}

internal fun desktopControlCenterTerminalOutcomeLabel(outcome: String?): String? = when (outcome) {
    null -> null
    "executed" -> "udført"
    "not_run" -> "ikke kørt"
    "abandoned" -> "forladt"
    "unknown" -> "ukendt"
    else -> "ukendt"
}

internal fun desktopControlCenterHistorySourceLabel(source: ControlCenterHistorySource): String = when (source.state) {
    "ready" -> "tilgængelig"
    "not_required" -> "ikke nødvendig"
    "unavailable" -> "utilgængelig"
    else -> "ukendt"
}

internal fun desktopControlCenterHistoryTimeLabel(epochSeconds: Double): String {
    if (!epochSeconds.isFinite() || epochSeconds < 0.0) return "ukendt tidspunkt"
    return runCatching {
        val formatter = SimpleDateFormat("dd.MM.yyyy HH:mm:ss", Locale.getDefault())
        formatter.format(Date((epochSeconds * 1000.0).roundToLong()))
    }.getOrDefault("ukendt tidspunkt")
}

internal fun desktopControlCenterScheduleHistoryError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(502)") ->
            "Execution-historikken er ikke tilgængelig fra riggen lige nu."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "History-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen for execution-historik."
        message.isBlank() -> "Execution-historikken kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun DesktopControlCenterScheduleHistorySection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var loading by remember { mutableStateOf(false) }
    var history by remember { mutableStateOf<ControlCenterScheduleHistory?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            history = null
            error = null
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterScheduleHistoryClient(baseUrl, token).history() }
        }
        result.onSuccess {
            history = it
            error = null
        }.onFailure {
            history = null
            error = desktopControlCenterScheduleHistoryError(it.message)
        }
        loading = false
    }

    Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        DesktopControlCenterSchedulesSection(
            baseUrl = baseUrl,
            token = token,
            refreshGeneration = refreshGeneration,
        )
        Spacer(Modifier.height(4.dp))

        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    "Execution-historik",
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Occurrence-ledger = outcome-authority · JobStore = separat observation · kun læsning",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
            }
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.height(18.dp),
                    strokeWidth = 2.dp,
                    color = KalivTheme.colors.Signal,
                )
            }
        }

        error?.let {
            DesktopHistoryNeutralCard {
                Text(
                    "Execution-historik ikke tilgængelig",
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                Text(
                    "Manglende history-evidens bliver ikke fortolket som succes eller som tom historik.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
            }
        }

        history?.let { current ->
            DesktopHistorySourcesCard(current)
            if (current.items.isEmpty()) {
                DesktopHistoryNeutralCard {
                    Text(
                        if (current.occurrenceSource.state == "ready") {
                            "Ingen registrerede occurrences i den aktuelle history-projektion."
                        } else {
                            "Occurrence-ledgeren kan ikke aflæses."
                        },
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                current.items.forEach { occurrence ->
                    DesktopHistoryOccurrenceCard(occurrence)
                }
            }
        }

        Spacer(Modifier.height(4.dp))
        DesktopControlCenterAuditSection(
            baseUrl = baseUrl,
            token = token,
            refreshGeneration = refreshGeneration,
        )
    }
}

@Composable
private fun DesktopHistorySourcesCard(history: ControlCenterScheduleHistory) {
    DesktopHistoryNeutralCard {
        Text(
            "Datakilder",
            color = KalivTheme.colors.TextHigh,
            fontWeight = FontWeight.SemiBold,
        )
        DesktopHistorySourceLine("Occurrence-ledger", history.occurrenceSource)
        DesktopHistorySourceLine("JobStore", history.jobsSource)
        Text(
            "Genereret: ${desktopControlCenterHistoryTimeLabel(history.generatedAt)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Production activation: nej",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopHistorySourceLine(label: String, source: ControlCenterHistorySource) {
    Text(
        "$label: ${desktopControlCenterHistorySourceLabel(source)}" +
            (source.reason?.let { " · $it" } ?: ""),
        color = KalivTheme.colors.TextMuted,
        fontSize = 11.sp,
    )
}

@Composable
private fun DesktopHistoryOccurrenceCard(occurrence: ControlCenterScheduleOccurrence) {
    DesktopHistoryNeutralCard {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    occurrence.tool ?: "Ukendt tool",
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Schedule ${occurrence.scheduleId}",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
            }
            Text(
                desktopControlCenterOccurrenceLabel(occurrence),
                color = KalivTheme.colors.TextHigh,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text(
            "Forfald: ${desktopControlCenterHistoryTimeLabel(occurrence.dueAt)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Occurrence: ${occurrence.occurrenceId}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        desktopControlCenterTerminalOutcomeLabel(occurrence.terminalOutcome)?.let { outcome ->
            Text(
                "Terminalt outcome: $outcome",
                color = KalivTheme.colors.TextMuted,
                fontSize = 11.sp,
            )
        }
        Text(
            when (occurrence.inFlight) {
                true -> "In-flight: ja"
                false -> "In-flight: nej"
                null -> "In-flight: ukendt"
            },
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        occurrence.resolvedAt?.let {
            Text(
                "Afsluttet: ${desktopControlCenterHistoryTimeLabel(it)}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }
        occurrence.job?.let { job ->
            Spacer(Modifier.height(4.dp))
            Text(
                "Job-observation: ${job.status} · ${job.kind}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 11.sp,
            )
            Text(
                if (job.progressTotal > 0) {
                    "Job-progress: ${job.progressCompleted}/${job.progressTotal}"
                } else {
                    "Job-progress: ${job.progressCompleted} · total ikke angivet"
                },
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }
        Text(
            "Outcome ovenfor kommer kun fra occurrence-ledgeren; JobStore-status ændrer det ikke.",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopHistoryNeutralCard(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.Surface, RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        content()
    }
}

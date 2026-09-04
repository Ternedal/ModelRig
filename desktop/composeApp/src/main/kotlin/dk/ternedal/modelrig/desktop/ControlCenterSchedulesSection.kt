package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
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
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleGrant
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleRuntime
import dk.ternedal.modelrig.desktop.net.ControlCenterScheduleSnapshot
import dk.ternedal.modelrig.desktop.net.ControlCenterSchedulesClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal fun desktopScheduleRuntimeLabel(runtime: ControlCenterScheduleRuntime): String = when {
    runtime.running -> "Scheduler kører"
    runtime.configured -> "Konfigureret · stoppet"
    else -> "Ikke konfigureret"
}

internal fun desktopScheduleGrantStateLabel(grant: ControlCenterScheduleGrant): String = when {
    !grant.enabled -> "Deaktiveret"
    grant.expired -> "Udløbet"
    grant.budgetExhausted -> "Budget opbrugt"
    grant.structurallyEligible -> "Strukturelt klar"
    else -> "Blokeret"
}

internal fun desktopScheduleBudgetLabel(grant: ControlCenterScheduleGrant): String =
    if (grant.maxRuns == 0) {
        "${grant.runsUsed} kørsler · intet run-loft"
    } else {
        "${grant.runsUsed}/${grant.maxRuns} kørsler"
    }

internal fun desktopControlCenterSchedulesError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(404)") ->
            "Scheduler-status er ikke eksponeret på denne rig."
        message.contains("(502)") ->
            "Scheduler-status er midlertidigt utilgængelig fra riggen."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "Scheduler-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen for scheduler-status."
        message.isBlank() -> "Scheduler-status kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun DesktopControlCenterSchedulesSection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<ControlCenterScheduleSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            snapshot = null
            error = null
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterSchedulesClient(baseUrl, token).snapshot() }
        }
        result.onSuccess {
            snapshot = it
            error = null
        }.onFailure {
            snapshot = null
            error = desktopControlCenterSchedulesError(it.message)
        }
        loading = false
    }

    Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    "Planer",
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    "Scheduler runtime + standing grants · kun læsning",
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
            DesktopScheduleNeutralCard {
                Text(
                    "Planer-status ikke tilgængelig",
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                Text(
                    "Manglende scheduler-evidens bliver ikke fortolket som klar eller som en tom grant-liste.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
            }
        }

        snapshot?.let { current ->
            DesktopScheduleRuntimeCard(current.runtime)
            if (current.schedules.isEmpty()) {
                DesktopScheduleNeutralCard {
                    Text(
                        "Ingen standing grants er registreret i scheduler-listen.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                current.schedules.forEach { grant -> DesktopScheduleGrantCard(grant) }
            }
        }
    }
}

@Composable
private fun DesktopScheduleRuntimeCard(runtime: ControlCenterScheduleRuntime) {
    DesktopScheduleNeutralCard {
        Text(
            desktopScheduleRuntimeLabel(runtime),
            color = KalivTheme.colors.TextHigh,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Ressourcer: ${if (runtime.resourcesOpen) "åbne" else "lukkede"} · aktive executions: " +
                "${runtime.activeExecutions}/${runtime.maxConcurrency}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Queue-kapacitet: ${runtime.queueCapacity} · accepterede ticks: ${runtime.acceptedTicks} · " +
                "overlap-afvisninger: ${runtime.overlapRejections}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        runtime.lastError?.let {
            Text("Seneste scheduler-fejl: $it", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
    }
}

@Composable
private fun DesktopScheduleGrantCard(grant: ControlCenterScheduleGrant) {
    DesktopScheduleNeutralCard {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    grant.tool,
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text("Schedule ${grant.id}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
            }
            Text(
                desktopScheduleGrantStateLabel(grant),
                color = KalivTheme.colors.TextHigh,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text(
            "Næste planlagte run: ${grant.dueAtLocal}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
        Text(
            "Cadence: ${grant.cadence} · timezone: ${grant.timezone} · misfire: ${grant.misfirePolicy}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Budget: ${desktopScheduleBudgetLabel(grant)} · missed: ${grant.missed}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Risk: ${grant.risk} · sensitivity: ${grant.sensitivity}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        grant.blockedReason?.let {
            Text("Blokeret: $it", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        Text(
            "Grant-status er ikke et execution-outcome. Runtime ToolGate kontrolleres først ved execution; " +
                "terminalt resultat kommer fra occurrence-ledgeren nedenfor.",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopScheduleNeutralCard(content: @Composable () -> Unit) {
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

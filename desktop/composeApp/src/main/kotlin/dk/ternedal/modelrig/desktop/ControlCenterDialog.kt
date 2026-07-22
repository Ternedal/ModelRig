package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterClient
import dk.ternedal.modelrig.desktop.net.ControlCenterComponent
import dk.ternedal.modelrig.desktop.net.ControlCenterRouting
import dk.ternedal.modelrig.desktop.net.ControlCenterStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

private val DESKTOP_CONTROL_CENTER_ORDER = listOf("backend", "worker", "models", "agent3")

internal fun desktopControlCenterOverallLabel(state: String): String = when (state) {
    "healthy" -> "Alt ser godt ud"
    "attention" -> "Kræver opmærksomhed"
    "unavailable" -> "Utilgængelig"
    "unknown" -> "Status er ukendt"
    else -> "Ukendt status"
}

internal fun desktopControlCenterStateLabel(state: String): String = when (state) {
    "healthy" -> "Klar"
    "unavailable" -> "Utilgængelig"
    "unknown" -> "Ukendt"
    "stale" -> "Forældet"
    "disabled" -> "Slået fra"
    "fallback" -> "Fallback"
    else -> "Ukendt"
}

internal fun desktopControlCenterTitle(name: String): String = when (name) {
    "backend" -> "Backend"
    "worker" -> "Worker"
    "models" -> "Modeller"
    "agent3" -> "Agent 3"
    else -> name
}

internal fun desktopControlCenterAge(ageSeconds: Double?): String? {
    if (ageSeconds == null || !ageSeconds.isFinite() || ageSeconds < 0.0) return null
    val seconds = ageSeconds.roundToInt()
    return when {
        seconds < 2 -> "målt nu"
        seconds < 60 -> "målt for $seconds sek. siden"
        else -> "målt for ${seconds / 60} min. siden"
    }
}

@Composable
fun DesktopControlCenterDialog(
    baseUrl: String,
    token: String,
    onDismiss: () -> Unit,
) {
    var refreshGeneration by remember { mutableStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<ControlCenterStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            status = null
            error = "Rig-adgangen mangler. Par desktop-appen med ModelRig i Indstillinger først."
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterClient(baseUrl, token).status() }
        }
        result.onSuccess {
            status = it
            error = null
        }.onFailure {
            status = null
            error = apiErrorHint(it.message)
        }
        loading = false
    }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Column {
                Text("Control Center", fontWeight = FontWeight.SemiBold)
                Text(
                    "Serverens aktuelle driftssandhed",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 12.sp,
                )
            }
        },
        text = {
            Column(
                modifier = Modifier
                    .height(480.dp)
                    .verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Button(
                        onClick = { refreshGeneration += 1 },
                        enabled = !loading && baseUrl.isNotBlank() && token.isNotBlank(),
                    ) {
                        Text(if (loading) "Henter…" else "Opdatér")
                    }
                    Spacer(Modifier.weight(1f))
                    if (loading) {
                        CircularProgressIndicator(
                            modifier = Modifier.height(22.dp),
                            strokeWidth = 2.dp,
                            color = KalivTheme.colors.Signal,
                        )
                    }
                    Text(
                        "Ingen automatisk polling",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 10.sp,
                        modifier = Modifier.padding(start = 8.dp),
                    )
                }

                error?.let {
                    DesktopControlCenterCard(
                        title = "Status kunne ikke hentes",
                        state = "unavailable",
                    ) {
                        Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                    }
                }

                status?.let { current ->
                    DesktopControlCenterCard(
                        title = desktopControlCenterOverallLabel(current.overall),
                        state = current.overall,
                    ) {
                        Text(
                            when (current.overall) {
                                "healthy" -> "Alle påkrævede kilder er friske og klar."
                                "attention" -> "Riggen svarer, men en valgfri del eller routing kræver opmærksomhed."
                                "unavailable" -> "Mindst én påkrævet del rapporterer utilgængelig."
                                else -> "Der mangler frisk eller entydig serverevidens."
                            },
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 12.sp,
                        )
                        Text(
                            "Friskhedsgrænse: ${current.freshnessSeconds.roundToInt()} sek.",
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 10.sp,
                        )
                    }

                    DESKTOP_CONTROL_CENTER_ORDER
                        .mapNotNull { current.components[it] }
                        .forEach { component -> DesktopControlCenterComponentCard(component) }

                    DesktopControlCenterRoutingCard(current.routing)

                    if (current.requiredFailures.isNotEmpty()) {
                        DesktopControlCenterCard("Påkrævede fejl", "unavailable") {
                            Text(
                                current.requiredFailures.joinToString {
                                    desktopControlCenterTitle(it)
                                },
                                color = KalivTheme.colors.TextMuted,
                                fontSize = 12.sp,
                            )
                        }
                    }
                }
            }
        },
        confirmButton = {
            OutlinedButton(onClick = onDismiss) { Text("Luk") }
        },
    )
}

@Composable
private fun DesktopControlCenterComponentCard(component: ControlCenterComponent) {
    DesktopControlCenterCard(
        title = desktopControlCenterTitle(component.name),
        state = component.state,
        badgeSuffix = if (component.required) " · påkrævet" else " · valgfri",
    ) {
        desktopControlCenterAge(component.ageSeconds)?.let {
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        component.detail?.let {
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
        }
        component.reason?.let {
            Text(
                "Årsag: $it",
                color = desktopControlCenterStateColor(component.state),
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun DesktopControlCenterRoutingCard(routing: ControlCenterRouting) {
    DesktopControlCenterCard("Routing", routing.state) {
        Text(
            "Konfigureret: ${routing.configuredSurface ?: "ukendt"}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 12.sp,
        )
        Text(
            "Aktiv: ${routing.activeSurface ?: "ukendt"}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 12.sp,
        )
        desktopControlCenterAge(routing.ageSeconds)?.let {
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        routing.fallbackReason?.let {
            Text(
                "Serverens fallback-årsag: $it",
                color = KalivTheme.colors.TextHigh,
                fontSize = 11.sp,
            )
        }
        routing.reason?.let {
            Text(
                "Årsag: $it",
                color = desktopControlCenterStateColor(routing.state),
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun DesktopControlCenterCard(
    title: String,
    state: String,
    badgeSuffix: String = "",
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.Surface, RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                title,
                color = KalivTheme.colors.TextHigh,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            Text(
                desktopControlCenterStateLabel(state) + badgeSuffix,
                color = desktopControlCenterStateColor(state),
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        content()
    }
}

@Composable
private fun desktopControlCenterStateColor(state: String): Color = when (state) {
    "healthy" -> KalivTheme.colors.Signal
    "unavailable" -> KalivTheme.colors.Danger
    "attention", "fallback" -> KalivTheme.colors.TextHigh
    else -> KalivTheme.colors.TextMuted
}

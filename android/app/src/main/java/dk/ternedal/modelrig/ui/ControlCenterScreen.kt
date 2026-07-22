package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ControlCenterClient
import dk.ternedal.modelrig.net.ControlCenterComponent
import dk.ternedal.modelrig.net.ControlCenterRouting
import dk.ternedal.modelrig.net.ControlCenterStatus
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

private val CONTROL_CENTER_COMPONENT_ORDER = listOf("backend", "worker", "models", "agent3")

internal fun controlCenterOverallLabel(state: String): String = when (state) {
    "healthy" -> "Alt ser godt ud"
    "attention" -> "Kræver opmærksomhed"
    "unavailable" -> "Utilgængelig"
    "unknown" -> "Status er ukendt"
    else -> "Ukendt status"
}

internal fun controlCenterStateLabel(state: String): String = when (state) {
    "healthy" -> "Klar"
    "unavailable" -> "Utilgængelig"
    "unknown" -> "Ukendt"
    "stale" -> "Forældet"
    "disabled" -> "Slået fra"
    "fallback" -> "Fallback"
    else -> "Ukendt"
}

internal fun controlCenterComponentTitle(name: String): String = when (name) {
    "backend" -> "Backend"
    "worker" -> "Worker"
    "models" -> "Modeller"
    "agent3" -> "Agent 3"
    else -> name
}

internal fun controlCenterAgeLabel(ageSeconds: Double?): String? {
    if (ageSeconds == null || !ageSeconds.isFinite() || ageSeconds < 0.0) return null
    val seconds = ageSeconds.roundToInt()
    return when {
        seconds < 2 -> "målt nu"
        seconds < 60 -> "målt for $seconds sek. siden"
        else -> "målt for ${seconds / 60} min. siden"
    }
}

@Composable
fun ControlCenterScreen(
    store: TokenStore,
    onClose: () -> Unit,
) {
    val baseUrl = store.baseUrl?.trim().orEmpty()
    val token = store.token?.trim().orEmpty()
    var refreshGeneration by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<ControlCenterStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            status = null
            error = "Rig-adgangen mangler. Par appen med ModelRig i Indstillinger først."
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
            error = it.message ?: "Kontrolcenter-status kunne ikke hentes."
        }
        loading = false
    }

    Surface(
        color = KalivTheme.colors.background,
        modifier = Modifier.fillMaxSize(),
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(20.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Control Center",
                        color = KalivTheme.colors.textHigh,
                        fontSize = 26.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Serverens aktuelle driftssandhed",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 13.sp,
                    )
                }
                OutlinedButton(onClick = onClose) { Text("Luk") }
            }
            Spacer(Modifier.height(14.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Button(
                    onClick = { refreshGeneration += 1 },
                    enabled = !loading && baseUrl.isNotBlank() && token.isNotBlank(),
                ) {
                    Text(if (loading) "Henter…" else "Opdatér")
                }
                if (loading) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(24.dp),
                        strokeWidth = 2.dp,
                        color = KalivTheme.colors.signal,
                    )
                }
                Text(
                    "Ingen automatisk polling",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
            }
            Spacer(Modifier.height(14.dp))

            val current = status
            LazyColumn(
                modifier = Modifier.fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                if (error != null) {
                    item {
                        MessageCard(
                            title = "Status kunne ikke hentes",
                            body = error.orEmpty(),
                            state = "unavailable",
                        )
                    }
                }
                if (current != null) {
                    item { OverallCard(current) }
                    items(
                        CONTROL_CENTER_COMPONENT_ORDER.mapNotNull { current.components[it] },
                        key = { it.name },
                    ) { component ->
                        ComponentCard(component)
                    }
                    item { RoutingCard(current.routing) }
                    if (current.requiredFailures.isNotEmpty()) {
                        item {
                            MessageCard(
                                title = "Påkrævede fejl",
                                body = current.requiredFailures
                                    .joinToString { controlCenterComponentTitle(it) },
                                state = "unavailable",
                            )
                        }
                    }
                }
                item { Spacer(Modifier.height(16.dp)) }
            }
        }
    }
}

@Composable
private fun OverallCard(status: ControlCenterStatus) {
    StatusCard(
        title = controlCenterOverallLabel(status.overall),
        state = status.overall,
    ) {
        Text(
            when (status.overall) {
                "healthy" -> "Alle påkrævede kilder er friske og klar."
                "attention" -> "Riggen svarer, men mindst én valgfri del eller routing kræver opmærksomhed."
                "unavailable" -> "Mindst én påkrævet del rapporterer utilgængelig."
                else -> "Der mangler frisk eller entydig serverevidens."
            },
            color = KalivTheme.colors.textMuted,
            fontSize = 13.sp,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            "Friskhedsgrænse: ${status.freshnessSeconds.roundToInt()} sek.",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun ComponentCard(component: ControlCenterComponent) {
    StatusCard(
        title = controlCenterComponentTitle(component.name),
        state = component.state,
        badgeSuffix = if (component.required) " · påkrævet" else " · valgfri",
    ) {
        controlCenterAgeLabel(component.ageSeconds)?.let {
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        }
        component.detail?.let {
            Spacer(Modifier.height(4.dp))
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 13.sp)
        }
        component.reason?.let {
            Spacer(Modifier.height(4.dp))
            Text(
                "Årsag: $it",
                color = stateColor(component.state),
                fontSize = 12.sp,
            )
        }
    }
}

@Composable
private fun RoutingCard(routing: ControlCenterRouting) {
    StatusCard(
        title = "Routing",
        state = routing.state,
    ) {
        Text(
            "Konfigureret: ${routing.configuredSurface ?: "ukendt"}",
            color = KalivTheme.colors.textMuted,
            fontSize = 13.sp,
        )
        Text(
            "Aktiv: ${routing.activeSurface ?: "ukendt"}",
            color = KalivTheme.colors.textMuted,
            fontSize = 13.sp,
        )
        controlCenterAgeLabel(routing.ageSeconds)?.let {
            Spacer(Modifier.height(4.dp))
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        }
        routing.fallbackReason?.let {
            Spacer(Modifier.height(4.dp))
            Text("Serverens fallback-årsag: $it", color = KalivTheme.colors.textHigh, fontSize = 12.sp)
        }
        routing.reason?.let {
            Spacer(Modifier.height(4.dp))
            Text("Årsag: $it", color = stateColor(routing.state), fontSize = 12.sp)
        }
    }
}

@Composable
private fun MessageCard(title: String, body: String, state: String) {
    StatusCard(title = title, state = state) {
        Text(body, color = KalivTheme.colors.textMuted, fontSize = 13.sp)
    }
}

@Composable
private fun StatusCard(
    title: String,
    state: String,
    badgeSuffix: String = "",
    content: @Composable () -> Unit,
) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    title,
                    color = KalivTheme.colors.textHigh,
                    fontSize = 17.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    controlCenterStateLabel(state) + badgeSuffix,
                    color = stateColor(state),
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Spacer(Modifier.height(8.dp))
            content()
        }
    }
}

@Composable
private fun stateColor(state: String): Color = when (state) {
    "healthy" -> KalivTheme.colors.signal
    "unavailable" -> KalivTheme.colors.danger
    "attention", "fallback" -> KalivTheme.colors.textHigh
    else -> KalivTheme.colors.textMuted
}

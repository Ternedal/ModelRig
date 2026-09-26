package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionClient
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionSensor
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal fun desktopVisionPresenceLabel(value: String): String = when (value) {
    "online" -> "Online"
    "stale" -> "Forældet"
    "offline" -> "Offline"
    else -> "Ukendt"
}

internal fun desktopVisionConvergenceLabel(value: String): String = when (value) {
    "converged" -> "Anvendt"
    "pending" -> "Afventer enheden"
    else -> "Ikke bekræftet"
}

internal fun desktopVisionError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(404)") ->
            "VisionRig Control Center-ruten findes ikke på denne rig endnu."
        message.contains("(502)") || message.contains("(503)") ->
            "VisionRig kan ikke nås fra riggen lige nu."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "VisionRig-kaldet fik tidsudløb."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå ModelRig-backenden for VisionRig-status."
        message.isBlank() -> "VisionRig-status kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun DesktopControlCenterVisionSection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var localGeneration by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<ControlCenterVisionSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var mutationError by remember { mutableStateOf<String?>(null) }
    var mutatingSource by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    LaunchedEffect(baseUrl, token, refreshGeneration, localGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            snapshot = null
            error = null
            loading = false
            return@LaunchedEffect
        }
        loading = true
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterVisionClient(baseUrl, token).snapshot() }
        }
        result.onSuccess {
            snapshot = it
            error = null
        }.onFailure {
            snapshot = null
            error = desktopVisionError(it.message)
        }
        loading = false
    }

    Column(
        modifier = Modifier.padding(top = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "VisionRig · sensorer",
            color = KalivTheme.colors.TextHigh,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Discovery · liveness · ønsket/faktisk capture · fjernstyring",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )

        if (loading) {
            CircularProgressIndicator(strokeWidth = 2.dp, color = KalivTheme.colors.Signal)
        }

        error?.let {
            VisionCard {
                Text(
                    "VisionRig-status kunne ikke verificeres",
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            }
        }

        mutationError?.let {
            VisionCard {
                Text(
                    "Sensorændringen blev ikke gennemført",
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Text(
                    "UI'et ændrer først ønsket state efter serverbekræftelse.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }
        }

        snapshot?.let { current ->
            if (!current.available) {
                VisionCard {
                    Text(
                        "VisionRig er ikke tilgængelig",
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        current.reason ?: "Ingen verificeret VisionRig-evidens.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
            } else if (current.sensors.isEmpty()) {
                VisionCard {
                    Text(
                        "Ingen sensorer er registreret endnu.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
            } else {
                val online = current.sensors.count { it.presence == "online" }
                val pending = current.sensors.count { it.convergence == "pending" }
                VisionCard {
                    Text(
                        "${current.sensors.size} kendte sensorer · $online online",
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        if (pending == 0) "Alle kendte kontrolstates er afklaret eller ukendte."
                        else "$pending sensor(er) afventer fysisk convergence.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 10.sp,
                    )
                }

                current.sensors.forEach { sensor ->
                    VisionSensorCard(
                        sensor = sensor,
                        mutating = mutatingSource == sensor.sourceId,
                        mutationBusy = mutatingSource != null,
                        onEnabledChange = { enabled ->
                            if (mutatingSource == null) {
                                mutatingSource = sensor.sourceId
                                mutationError = null
                                scope.launch {
                                    val result = withContext(Dispatchers.IO) {
                                        runCatching {
                                            ControlCenterVisionClient(baseUrl, token)
                                                .setEnabled(sensor.sourceId, enabled)
                                        }
                                    }
                                    result.onSuccess {
                                        mutationError = null
                                        localGeneration += 1
                                    }.onFailure {
                                        mutationError = desktopVisionError(it.message)
                                    }
                                    mutatingSource = null
                                }
                            }
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun VisionSensorCard(
    sensor: ControlCenterVisionSensor,
    mutating: Boolean,
    mutationBusy: Boolean,
    onEnabledChange: (Boolean) -> Unit,
) {
    VisionCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    sensor.title,
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                if (sensor.displayName != null) {
                    Text(sensor.sourceId, color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
                }
            }
            Text(
                desktopVisionPresenceLabel(sensor.presence),
                color = if (sensor.presence == "online") {
                    KalivTheme.colors.Signal
                } else {
                    KalivTheme.colors.TextMuted
                },
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Spacer(Modifier.width(10.dp))
            Switch(
                checked = sensor.desiredEnabled,
                enabled = !mutationBusy,
                onCheckedChange = onEnabledChange,
            )
        }

        val descriptor = buildList {
            add(sensor.sourceType)
            sensor.device?.let { add(it) }
            sensor.location?.let { add(it) }
            sensor.role?.let { add(it) }
        }.joinToString(" · ")
        Text(descriptor, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)

        if (sensor.capabilities.isNotEmpty()) {
            Text(
                "Capabilities: ${sensor.capabilities.joinToString()}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }

        val effective = when (sensor.effectiveCaptureActive) {
            true -> "capture aktiv"
            false -> "capture lukket"
            null -> "faktisk capture ukendt"
        }
        Text(
            "Ønsket: ${if (sensor.desiredEnabled) "aktiv" else "slået fra"} · " +
                "$effective · ${desktopVisionConvergenceLabel(sensor.convergence)}",
            color = if (sensor.convergence == "pending") {
                KalivTheme.colors.Amber
            } else {
                KalivTheme.colors.TextMuted
            },
            fontSize = 10.sp,
        )

        if (mutating) {
            Text(
                "Gemmer ønsket sensorstate…",
                color = KalivTheme.colors.Signal,
                fontSize = 9.sp,
            )
        }

        sensor.lastSeenUtc?.let {
            Text(
                "Sidst set: $it · observationer: ${sensor.observationCount}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
            )
        }
        sensor.firstSeenUtc?.let {
            Text("Først set: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        }
    }
}

@Composable
private fun VisionCard(content: @Composable () -> Unit) {
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

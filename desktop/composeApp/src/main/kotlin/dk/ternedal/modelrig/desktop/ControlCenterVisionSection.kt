package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionClient
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionSensor
import dk.ternedal.modelrig.desktop.net.ControlCenterVisionSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun DesktopControlCenterVisionSection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<ControlCenterVisionSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
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
            error = "VisionRig-status kunne ikke verificeres."
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
            "Read-only drift · liveness · convergence · transport",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        if (loading) {
            CircularProgressIndicator(strokeWidth = 2.dp, color = KalivTheme.colors.Cognition)
        }
        error?.let { message ->
            VisionReadCard {
                Text(message, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            }
        }
        snapshot?.let { current ->
            if (!current.available) {
                VisionReadCard {
                    Text("VisionRig er utilgængelig", color = KalivTheme.colors.TextHigh)
                    Text(
                        current.reason ?: "Ingen verificeret VisionRig-evidens.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 10.sp,
                    )
                }
            } else {
                VisionReadCard {
                    val online = current.sensors.count { it.presence == "online" }
                    val pending = current.sensors.count { it.convergence == "pending" }
                    val pressure = current.sensors.count {
                        it.transportStatus == "warning" || it.transportStatus == "critical"
                    }
                    Text(
                        if (current.sensorsTruncated) {
                            "${current.sensorsReturned} af ${current.total} sensorer · $online online · $pending pending"
                        } else {
                            "${current.sensors.size} sensorer · $online online · $pending pending"
                        },
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        "State rev ${current.sensorStateRevision ?: 0} · ${current.consistency} · ${current.attentionTotal} attention",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 10.sp,
                    )
                    Text(
                        if (pressure == 0) "Ingen kendt packet-pressure." else "$pressure sensor(er) med packet-pressure.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 10.sp,
                    )
                }
                current.sensors.forEach { VisionSensorReadCard(it) }
            }
        }
    }
}

@Composable
private fun VisionSensorReadCard(sensor: ControlCenterVisionSensor) {
    VisionReadCard {
        Row(Modifier.fillMaxWidth()) {
            Text(
                sensor.title,
                color = KalivTheme.colors.TextHigh,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            Text(
                sensor.presence,
                color = if (sensor.presence == "online") KalivTheme.colors.Signal else KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }
        if (sensor.displayName != null) {
            Text(sensor.sourceId, color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        }
        val descriptor = listOfNotNull(sensor.sourceType, sensor.device, sensor.location, sensor.role)
            .joinToString(" · ")
        Text(descriptor, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        if (sensor.capabilities.isNotEmpty()) {
            Text(
                "Capabilities: ${sensor.capabilities.joinToString()}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
            )
        }
        val effective = when (sensor.effectiveCaptureActive) {
            true -> "aktiv"
            false -> "lukket"
            null -> "ukendt"
        }
        Text(
            "Ønsket ${if (sensor.desiredEnabled) "aktiv" else "slukket"} · faktisk $effective · ${sensor.convergence}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Transport ${sensor.transportStatus} · negotiation ${sensor.capabilityRefreshStatus}" +
                (sensor.payloadUtilization?.let { " · payload ${(it * 100).toInt()}%" } ?: ""),
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        sensor.negotiatedMaxPayloadBytes?.let { bytes ->
            Text(
                "Budget ${bytes / 1024 / 1024} MiB · compression ${sensor.negotiatedPacketCompression ?: "ukendt"}" +
                    (sensor.negotiatedPacketTargetUtilization?.let { " · mål ${(it * 100).toInt()}%" } ?: ""),
                color = KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
            )
        }
        sensor.lastSeenUtc?.let {
            Text("Sidst set: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        }
    }
}

@Composable
private fun VisionReadCard(content: @Composable () -> Unit) {
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

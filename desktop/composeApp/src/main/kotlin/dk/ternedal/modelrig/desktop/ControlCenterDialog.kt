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
import dk.ternedal.modelrig.desktop.net.ControlCenterCapabilitiesClient
import dk.ternedal.modelrig.desktop.net.ControlCenterCapability
import dk.ternedal.modelrig.desktop.net.ControlCenterCapabilityInventory
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

internal fun desktopControlCenterReasonLabel(raw: String?): String? {
    val reason = raw?.trim().orEmpty()
    if (reason.isEmpty()) return null
    return when (reason) {
        "missing_source" -> "Ingen statuskilde har rapporteret endnu."
        "missing_or_invalid_observed_at" -> "Måletidspunktet mangler eller er ugyldigt."
        "observation_from_future" -> "Måletidspunktet ligger foran riggens ur."
        "observation_too_old" -> "Statusmålingen er for gammel."
        "disabled_by_configuration" -> "Slået fra i riggens konfiguration."
        "source_reported_unavailable" -> "Kilden rapporterer utilgængelig."
        "missing_boolean_verdict" -> "Kilden leverede ikke en entydig status."
        "agent3_disabled_by_configuration" -> "Agent 3 er slået fra i riggens konfiguration."
        "unknown_surface" -> "Routing bruger en ukendt surface."
        "fallback_reason_missing" -> "Fallback mangler serverens begrundelse."
        "server_selected_fallback" -> "Serveren valgte fallback."
        "unsupported_route_transition" -> "Routingovergangen understøttes ikke."
        else -> "Teknisk årsag ukendt."
    }
}

internal fun desktopControlCenterSurfaceLabel(raw: String?): String {
    val surface = raw?.trim().orEmpty()
    return when (surface) {
        "agent_v2" -> "Agent 2"
        "agent3_developer" -> "Agent 3 · udvikler"
        "disabled" -> "Slået fra"
        "" -> "Ikke oplyst"
        else -> "Ukendt surface"
    }
}

internal fun desktopControlCenterTechnicalDetail(raw: String?): String? =
    raw?.trim()?.takeIf { it.isNotEmpty() }?.let { "Teknisk detalje: $it" }

internal fun desktopControlCenterFallbackEvidence(raw: String?): String? =
    raw?.trim()?.takeIf { it.isNotEmpty() }?.let { "Serverens fallbackkode: $it" }

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

internal fun desktopControlCenterAccessLabel(access: String): String = when (access) {
    "read" -> "læse"
    "write" -> "skrive"
    "desktop" -> "desktop"
    else -> access
}

internal fun desktopControlCenterTerminationLabel(mode: String): String = when (mode) {
    "none" -> "ikke direkte afbrydelig"
    "cooperative" -> "kooperativ stop"
    "forceable" -> "runtime-stop"
    else -> mode
}

internal fun desktopControlCenterError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(502)") || message.contains("status unavailable") ->
            "Riggen kunne ikke levere Control Center-status. Tjek at backend og worker kører."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "Statuskaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen. Tjek URL og at serveren kører."
        message.isBlank() -> "Control Center-status kunne ikke hentes."
        else -> "Control Center-status kunne ikke hentes på grund af en ukendt klientfejl."
    }
}

internal fun desktopControlCenterCapabilityError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "Capability-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen for capability-metadata."
        message.isBlank() -> "Capabilities kunne ikke hentes."
        else -> "Capabilities kunne ikke hentes på grund af en ukendt klientfejl."
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
    var capabilityInventory by remember { mutableStateOf<ControlCenterCapabilityInventory?>(null) }
    var capabilityError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            status = null
            capabilityInventory = null
            error = "Rig-adgangen mangler. Par desktop-appen med ModelRig i Indstillinger først."
            capabilityError = null
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        capabilityError = null
        val results = withContext(Dispatchers.IO) {
            val statusResult = runCatching { ControlCenterClient(baseUrl, token).status() }
            val capabilityResult = runCatching {
                ControlCenterCapabilitiesClient(baseUrl, token).inventory()
            }
            statusResult to capabilityResult
        }
        results.first.onSuccess {
            status = it
            error = null
        }.onFailure {
            status = null
            error = desktopControlCenterError(it.message)
        }
        results.second.onSuccess {
            capabilityInventory = it
            capabilityError = null
        }.onFailure {
            capabilityInventory = null
            capabilityError = desktopControlCenterCapabilityError(it.message)
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
                        // Name the culprits: a status card that says "attention"
                        // without saying WHAT is unreadable (#779 item 7).
                        val notHealthy = current.components.values
                            .filter { it.state != "healthy" }
                            .joinToString { desktopControlCenterTitle(it.name) }
                        Text(
                            when (current.overall) {
                                "healthy" -> "Alle påkrævede kilder er friske og klar."
                                "attention" ->
                                    if (notHealthy.isNotBlank()) "Riggen svarer, men kræver opmærksomhed: $notHealthy."
                                    else "Riggen svarer, men en valgfri del eller routing kræver opmærksomhed."
                                "unavailable" ->
                                    if (notHealthy.isNotBlank()) "Utilgængelig eller degraderet: $notHealthy."
                                    else "Mindst én påkrævet del rapporterer utilgængelig."
                                else ->
                                    if (notHealthy.isNotBlank()) "Mangler frisk eller entydig evidens fra: $notHealthy."
                                    else "Der mangler frisk eller entydig serverevidens."
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

                DesktopControlCenterSectionHeading(
                    "Capabilities",
                    "Canonical T-030 metadata · kun læsning",
                )
                capabilityError?.let {
                    DesktopControlCenterCard("Capabilities kunne ikke hentes", "unavailable") {
                        Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                    }
                }
                capabilityInventory?.let { inventory ->
                    DesktopCapabilityLayerCard(inventory)
                    inventory.capabilities.forEach { capability ->
                        DesktopCapabilityCard(capability)
                    }
                }

                DesktopControlCenterScheduleHistorySection(
                    baseUrl = baseUrl,
                    token = token,
                    refreshGeneration = refreshGeneration,
                )
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
        desktopControlCenterTechnicalDetail(component.detail)?.let { detail ->
            Text(detail, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        desktopControlCenterReasonLabel(component.reason)?.let { reason ->
            Text(
                "Årsag: $reason",
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
            "Konfigureret: ${desktopControlCenterSurfaceLabel(routing.configuredSurface)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 12.sp,
        )
        Text(
            "Aktiv: ${desktopControlCenterSurfaceLabel(routing.activeSurface)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 12.sp,
        )
        desktopControlCenterAge(routing.ageSeconds)?.let {
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        desktopControlCenterFallbackEvidence(routing.fallbackReason)?.let { evidence ->
            Text(
                evidence,
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }
        desktopControlCenterReasonLabel(routing.reason)?.let { reason ->
            Text(
                "Årsag: $reason",
                color = desktopControlCenterStateColor(routing.state),
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun DesktopControlCenterSectionHeading(title: String, subtitle: String) {
    Column(Modifier.padding(top = 8.dp, bottom = 2.dp)) {
        Text(title, color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Text(subtitle, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
    }
}

@Composable
private fun DesktopCapabilityLayerCard(inventory: ControlCenterCapabilityInventory) {
    DesktopControlCenterNeutralCard {
        Text(
            "Tool-lag: ${if (inventory.toolLayerEnabled) "aktiveret" else "slået fra"}",
            color = KalivTheme.colors.TextHigh,
            fontSize = 13.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "${inventory.capabilities.size} capabilities · runtime-status er adskilt fra descriptoren",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Denne visning kan ikke ændre ToolGate eller aktivere en capability.",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopCapabilityCard(capability: ControlCenterCapability) {
    DesktopControlCenterNeutralCard {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(
                    capability.name,
                    color = KalivTheme.colors.TextHigh,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(capability.capabilityId, color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
            }
            Text(
                if (capability.enabled) "runtime: aktiveret" else "runtime: slået fra",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
        }
        Text(capability.description, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(
            "Adgang: ${desktopControlCenterAccessLabel(capability.access)} · konsekvens: ${capability.impact} · data: ${capability.dataClass}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Isolation: ${capability.isolationMode} · stop: ${desktopControlCenterTerminationLabel(capability.terminationMode)}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Scheduling: ${if (capability.schedulable) "tilladt" else "ikke tilladt"}" +
                (capability.schedulingReason?.let { " · $it" } ?: ""),
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Confirmation: ${capability.confirmationMode} · replay: ${if (capability.idempotent) "idempotent" else "ikke idempotent"}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Netværk: ${capability.networkMode}" +
                (if (capability.networkDestinations.isEmpty()) "" else " · ${capability.networkDestinations.joinToString()}"),
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopControlCenterNeutralCard(content: @Composable () -> Unit) {
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

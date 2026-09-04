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
import dk.ternedal.modelrig.net.ControlCenterCapabilitiesClient
import dk.ternedal.modelrig.net.ControlCenterCapability
import dk.ternedal.modelrig.net.ControlCenterCapabilityInventory
import dk.ternedal.modelrig.net.ControlCenterClient
import dk.ternedal.modelrig.net.ControlCenterComponent
import dk.ternedal.modelrig.net.ControlCenterRouting
import dk.ternedal.modelrig.net.ControlCenterScheduleGrant
import dk.ternedal.modelrig.net.ControlCenterScheduleRuntime
import dk.ternedal.modelrig.net.ControlCenterScheduleSnapshot
import dk.ternedal.modelrig.net.ControlCenterSchedulesClient
import dk.ternedal.modelrig.net.ControlCenterStatus
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

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

internal fun controlCenterAccessLabel(access: String): String = when (access) {
    "read" -> "læse"
    "write" -> "skrive"
    "desktop" -> "desktop"
    else -> access
}

internal fun controlCenterTerminationLabel(mode: String): String = when (mode) {
    "none" -> "ikke direkte afbrydelig"
    "cooperative" -> "kooperativ stop"
    "forceable" -> "runtime-stop"
    else -> mode
}

internal fun controlCenterSchedulerRuntimeLabel(runtime: ControlCenterScheduleRuntime): String = when {
    runtime.running -> "Kører"
    runtime.configured && runtime.resourcesOpen -> "Stoppet · ressourcer åbne"
    runtime.configured -> "Konfigureret · ikke startet"
    else -> "Slået fra"
}

internal fun controlCenterScheduleGrantLabel(grant: ControlCenterScheduleGrant): String = when {
    !grant.enabled -> "Pauset"
    grant.expired -> "Udløbet"
    grant.budgetExhausted -> "Budget brugt"
    grant.structurallyEligible -> "Grant gyldig"
    else -> "Blokeret"
}

@Composable
fun ControlCenterScreen(
    store: TokenStore,
    onClose: () -> Unit,
) {
    var showAgent4 by remember { mutableStateOf(false) }
    if (showAgent4) {
        Agent4OperatorScreen(
            store = store,
            onClose = { showAgent4 = false },
        )
        return
    }

    val baseUrl = store.baseUrl?.trim().orEmpty()
    val token = store.token?.trim().orEmpty()
    var refreshGeneration by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<ControlCenterStatus?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var capabilityInventory by remember { mutableStateOf<ControlCenterCapabilityInventory?>(null) }
    var capabilityError by remember { mutableStateOf<String?>(null) }
    var scheduleSnapshot by remember { mutableStateOf<ControlCenterScheduleSnapshot?>(null) }
    var scheduleError by remember { mutableStateOf<String?>(null) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            status = null
            capabilityInventory = null
            scheduleSnapshot = null
            error = "Rig-adgangen mangler. Par appen med ModelRig i Indstillinger først."
            capabilityError = null
            scheduleError = null
            loading = false
            return@LaunchedEffect
        }
        loading = true
        error = null
        capabilityError = null
        scheduleError = null
        val results = withContext(Dispatchers.IO) {
            Triple(
                runCatching { ControlCenterClient(baseUrl, token).status() },
                runCatching { ControlCenterCapabilitiesClient(baseUrl, token).inventory() },
                runCatching { ControlCenterSchedulesClient(baseUrl, token).snapshot() },
            )
        }
        results.first.onSuccess {
            status = it
            error = null
        }.onFailure {
            status = null
            error = it.message ?: "Kontrolcenter-status kunne ikke hentes."
        }
        results.second.onSuccess {
            capabilityInventory = it
            capabilityError = null
        }.onFailure {
            capabilityInventory = null
            capabilityError = it.message ?: "Capability-listen kunne ikke hentes."
        }
        results.third.onSuccess {
            scheduleSnapshot = it
            scheduleError = null
        }.onFailure {
            scheduleSnapshot = null
            scheduleError = it.message ?: "Planstatus kunne ikke hentes."
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
                .kalivScreenInsets()
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
                OutlinedButton(
                    onClick = { showAgent4 = true },
                    enabled = baseUrl.isNotBlank() && token.isNotBlank(),
                ) {
                    Text("Agent 4 · read-only")
                }
                if (loading) {
                    CircularProgressIndicator(
                        modifier = Modifier.height(24.dp),
                        strokeWidth = 2.dp,
                        color = KalivTheme.colors.signal,
                    )
                }
            }
            Text(
                "Ingen automatisk polling",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            Spacer(Modifier.height(14.dp))

            val current = status
            val currentCapabilities = capabilityInventory
            val currentSchedules = scheduleSnapshot
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

                item { SectionHeading("Capabilities", "Canonical T-030 metadata · kun læsning") }
                if (capabilityError != null) {
                    item {
                        MessageCard(
                            title = "Capabilities kunne ikke hentes",
                            body = capabilityError.orEmpty(),
                            state = "unavailable",
                        )
                    }
                }
                if (currentCapabilities != null) {
                    item { CapabilityLayerCard(currentCapabilities) }
                    items(
                        currentCapabilities.capabilities,
                        key = { it.capabilityId },
                    ) { capability ->
                        CapabilityCard(capability)
                    }
                }

                item { SectionHeading("Planer", "Scheduler-runtime + standing grants · kun læsning") }
                if (scheduleError != null) {
                    item {
                        MessageCard(
                            title = "Planstatus ikke tilgængelig",
                            body = scheduleError.orEmpty(),
                            state = "unknown",
                        )
                    }
                }
                if (currentSchedules != null) {
                    item { SchedulerRuntimeCard(currentSchedules.runtime, currentSchedules.schedules.size) }
                    items(currentSchedules.schedules, key = { it.id }) { grant ->
                        ScheduleGrantCard(grant)
                    }
                }
                item {
                    ControlCenterScheduleHistoryLoader(
                        baseUrl = baseUrl,
                        token = token,
                        refreshGeneration = refreshGeneration,
                    )
                }
                item {
                    ControlCenterAuditLoader(
                        baseUrl = baseUrl,
                        token = token,
                        refreshGeneration = refreshGeneration,
                    )
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
private fun SectionHeading(title: String, subtitle: String) {
    Column(Modifier.padding(top = 10.dp, bottom = 2.dp)) {
        Text(
            title,
            color = KalivTheme.colors.textHigh,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(subtitle, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
    }
}

@Composable
private fun CapabilityLayerCard(inventory: ControlCenterCapabilityInventory) {
    NeutralCard {
        Text(
            "Tool-lag: ${if (inventory.toolLayerEnabled) "aktiveret" else "slået fra"}",
            color = KalivTheme.colors.textHigh,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "${inventory.capabilities.size} capabilities · runtime-status er adskilt fra descriptoren",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Denne visning kan ikke ændre ToolGate eller aktivere en capability.",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun CapabilityCard(capability: ControlCenterCapability) {
    NeutralCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    capability.name,
                    color = KalivTheme.colors.textHigh,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(capability.capabilityId, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            Text(
                if (capability.enabled) "runtime: aktiveret" else "runtime: slået fra",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(capability.description, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
        Spacer(Modifier.height(6.dp))
        Text(
            "Adgang: ${controlCenterAccessLabel(capability.access)} · konsekvens: ${capability.impact} · data: ${capability.dataClass}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Isolation: ${capability.isolationMode} · stop: ${controlCenterTerminationLabel(capability.terminationMode)}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Scheduling: ${if (capability.schedulable) "tilladt" else "ikke tilladt"}" +
                (capability.schedulingReason?.let { " · $it" } ?: ""),
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Confirmation: ${capability.confirmationMode} · replay: ${if (capability.idempotent) "idempotent" else "ikke idempotent"}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Netværk: ${capability.networkMode}" +
                (if (capability.networkDestinations.isEmpty()) "" else " · ${capability.networkDestinations.joinToString()}"),
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun SchedulerRuntimeCard(runtime: ControlCenterScheduleRuntime, scheduleCount: Int) {
    NeutralCard {
        Text(
            "Scheduler: ${controlCenterSchedulerRuntimeLabel(runtime)}",
            color = KalivTheme.colors.textHigh,
            fontSize = 14.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "$scheduleCount grants · aktive executions: ${runtime.activeExecutions}/${runtime.maxConcurrency} · køkapacitet: ${runtime.queueCapacity}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Accepterede ticks: ${runtime.acceptedTicks} · overlap-afvisninger: ${runtime.overlapRejections}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        runtime.lastError?.let {
            Text("Runtime-fejl: $it", color = KalivTheme.colors.danger, fontSize = 11.sp)
        }
    }
}

@Composable
private fun ScheduleGrantCard(grant: ControlCenterScheduleGrant) {
    NeutralCard {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(grant.tool, color = KalivTheme.colors.textHigh, fontSize = 15.sp, fontWeight = FontWeight.Bold)
                Text(grant.id, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            Text(
                controlCenterScheduleGrantLabel(grant),
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Text("Næste forfald: ${grant.dueAtLocal}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(
            "Kadence: ${grant.cadence} · zone: ${grant.timezone} · misfire: ${grant.misfirePolicy}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            if (grant.maxRuns == 0) "Budget: ${grant.runsUsed} brugt · kun TTL begrænser"
            else "Budget: ${grant.runsUsed}/${grant.maxRuns} brugt",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Missed: ${grant.missed} · risk: ${grant.risk} · data: ${grant.sensitivity}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        grant.blockedReason?.let {
            Text("Blokeret: $it", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        }
        Text(
            "Live ToolGate og execution-outcome er ikke afgjort af denne grant-liste.",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun NeutralCard(content: @Composable () -> Unit) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) { content() }
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

package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3ReadonlyTaskClient
import dk.ternedal.modelrig.desktop.net.Agent3ReadonlyTaskPreview
import dk.ternedal.modelrig.desktop.net.Agent3ReadonlyTaskSnapshot
import dk.ternedal.modelrig.desktop.net.Agent3ReadonlyTaskStep
import dk.ternedal.modelrig.desktop.net.Agent3TaskCapabilityReceipt
import dk.ternedal.modelrig.desktop.net.Agent3TaskEvidenceBinding
import dk.ternedal.modelrig.desktop.net.Agent3TaskReadiness
import dk.ternedal.modelrig.desktop.net.Agent3TaskReadinessClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Human-facing, server-routed read-only task surface for desktop. */
@Composable
fun Agent3TaskApp(onUseAgent2: () -> Unit) {
    val db = remember { DesktopChatDb() }
    fun setting(key: String, env: String?, default: String): String =
        System.getenv(env ?: "")?.takeIf { it.isNotBlank() }
            ?: db.getSetting(key) ?: default

    var darkMode by remember { mutableStateOf(db.getSetting("darkMode") != "false") }
    KalivTheme(dark = darkMode) {
        val scope = rememberCoroutineScope()
        val baseUrl = remember {
            System.getenv("MODELRIG_AGENT3_URL")?.takeIf { it.isNotBlank() }
                ?: setting("localUrl", "MODELRIG_LOCAL_URL", "http://127.0.0.1:8080")
        }
        val token = remember { setting("deviceToken", "MODELRIG_TOKEN", "") }
        var readiness by remember { mutableStateOf<Agent3TaskReadiness?>(null) }
        var message by remember { mutableStateOf("") }
        var preview by remember { mutableStateOf<Agent3ReadonlyTaskPreview?>(null) }
        var snapshot by remember { mutableStateOf<Agent3ReadonlyTaskSnapshot?>(null) }
        var busy by remember { mutableStateOf(DesktopTaskBusy.READINESS) }
        var error by remember { mutableStateOf<String?>(null) }

        fun requireConnection(): Pair<String, String> {
            if (baseUrl.isBlank()) kotlin.error("Ingen ModelRig backend-URL er gemt")
            if (token.isBlank()) kotlin.error("Ingen device-token er gemt")
            return baseUrl.trim() to token.trim()
        }

        fun refreshReadiness() {
            if (busy != DesktopTaskBusy.NONE && busy != DesktopTaskBusy.READINESS) return
            busy = DesktopTaskBusy.READINESS
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3TaskReadinessClient(base, bearer).readiness()
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { value ->
                    readiness = value
                    if (!value.agent3ReadonlySelected && snapshot == null) preview = null
                }.onFailure {
                    readiness = null
                    if (snapshot == null) preview = null
                    error = it.message ?: "Task-readiness kunne ikke hentes"
                }
            }
        }

        fun requestPreview() {
            if (!Agent3TaskUiPolicy.canPreview(
                    readiness?.selectedSurface,
                    message,
                    busy != DesktopTaskBusy.NONE,
                    snapshot != null,
                )
            ) return
            busy = DesktopTaskBusy.PREVIEW
            error = null
            preview = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).preview(message.trim())
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { preview = it }
                    .onFailure { error = it.message ?: "Plan-preview fejlede" }
            }
        }

        fun startTask() {
            val plan = preview ?: return
            val planId = plan.planId ?: return
            if (!Agent3TaskUiPolicy.canStart(
                    readiness?.selectedSurface,
                    plan.canStart,
                    busy != DesktopTaskBusy.NONE,
                    snapshot != null,
                )
            ) return
            busy = DesktopTaskBusy.START
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).start(planId)
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { snapshot = it }
                    .onFailure { error = it.message ?: "Opgaven kunne ikke startes" }
            }
        }

        fun refreshRun() {
            val runId = snapshot?.run?.id ?: return
            if (busy != DesktopTaskBusy.NONE) return
            busy = DesktopTaskBusy.STATUS
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).status(runId)
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { snapshot = it }
                    .onFailure { error = it.message ?: "Task-status kunne ikke hentes" }
            }
        }

        fun stopPlan() {
            val current = snapshot ?: return
            if (!Agent3TaskUiPolicy.canStopPlan(
                    current.termination.plan.canRequest,
                    busy != DesktopTaskBusy.NONE,
                )
            ) return
            busy = DesktopTaskBusy.STOP_PLAN
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).cancel(current.run.id)
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { snapshot = it }
                    .onFailure { error = it.message ?: "Planen kunne ikke stoppes" }
            }
        }

        LaunchedEffect(Unit) { refreshReadiness() }

        // Window-owned polling is cancelled when --tasks is closed or falls back
        // to App(). Cancelling the plan does not imply that a synchronous tool
        // stopped, so the receipt keeps polling alive until tool truth is terminal.
        LaunchedEffect(
            snapshot?.run?.id,
            snapshot?.terminal,
            snapshot?.termination?.activeTool?.state,
            snapshot?.termination?.activeTool?.requestState,
        ) {
            val runId = snapshot?.run?.id ?: return@LaunchedEffect
            while (
                isActive && Agent3TaskUiPolicy.shouldPoll(
                    runTerminal = snapshot?.terminal,
                    activeToolState = snapshot?.termination?.activeTool?.state,
                    activeToolRequestState = snapshot?.termination?.activeTool?.requestState,
                )
            ) {
                delay(1_000)
                if (busy != DesktopTaskBusy.NONE) continue
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).status(runId)
                    }
                }
                if (result.isSuccess) {
                    snapshot = result.getOrThrow()
                } else {
                    error = result.exceptionOrNull()?.message ?: "Automatisk task-status fejlede"
                    return@LaunchedEffect
                }
            }
        }

        val surface = Agent3TaskUiPolicy.normalizedSurface(readiness?.selectedSurface)
        val isBusy = busy != DesktopTaskBusy.NONE
        val hasRun = snapshot != null

        Column(
            Modifier
                .fillMaxSize()
                .background(KalivTheme.colors.Graphite)
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Kaliv Opgaver",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Serverstyret read-only taskflade · normal chat er urørt",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                OutlinedButton(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
                Spacer(Modifier.height(1.dp))
                OutlinedButton(onClick = onUseAgent2) { Text("Normal chat") }
            }

            Spacer(Modifier.height(14.dp))
            DesktopTaskCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            if (surface == Agent3TaskUiPolicy.AGENT3_READONLY) {
                                "Agent 3 read-only valgt af serveren"
                            } else {
                                "Agent 2 fallback"
                            },
                            color = if (surface == Agent3TaskUiPolicy.AGENT3_READONLY) {
                                KalivTheme.colors.Success
                            } else {
                                KalivTheme.colors.Amber
                            },
                            fontSize = 19.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            readiness?.reason ?: "readiness_unavailable",
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 11.sp,
                        )
                    }
                    if (busy == DesktopTaskBusy.READINESS) CircularProgressIndicator()
                }
                Spacer(Modifier.height(8.dp))
                DesktopValueRow("Backend", baseUrl)
                DesktopValueRow("Device-token", if (token.isBlank()) "mangler" else "gemt")
                DesktopValueRow("Aktiv surface", surface)
                DesktopValueRow("Fallback", readiness?.fallbackSurface ?: Agent3TaskUiPolicy.AGENT2)
                DesktopValueRow("Routing", readiness?.uiContract?.routeSource ?: "fail_closed")
                DesktopValueRow(
                    "Pilot",
                    readiness?.pilot?.successes?.let { "$it/${readiness?.pilot?.tasks ?: "?"}" } ?: "ukendt",
                )
                DesktopValueRow("Replans", readiness?.pilot?.replans?.toString() ?: "ukendt")
                DesktopValueRow("Retry-events", readiness?.pilot?.retryEvents?.toString() ?: "ukendt")
                readiness?.reasons?.distinct()?.forEach {
                    Text("• $it", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(enabled = !isBusy, onClick = ::refreshReadiness) {
                    Text("Opdatér routing")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text("Fejl", color = KalivTheme.colors.Danger, fontWeight = FontWeight.Bold)
                    Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                }
            }

            if (surface == Agent3TaskUiPolicy.AGENT2 && !hasRun) {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text(
                        "Opgaven går via den eksisterende Agent 2-chat",
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Ingen preview- eller start-request sendes til Agent 3, når serveren ikke har valgt read-only surface.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = onUseAgent2) { Text("Åbn normal chat") }
                }
            } else if (!hasRun) {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text("Ny read-only opgave", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = { message = it; preview = null },
                        enabled = !isBusy,
                        label = { Text("Hvad skal Kaliv undersøge?") },
                        supportingText = { Text("Kun lokale, idempotente read-tools kan startes.") },
                        minLines = 3,
                        maxLines = 7,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3TaskUiPolicy.canPreview(
                            readiness?.selectedSurface,
                            message,
                            isBusy,
                            hasRun = false,
                        ),
                        onClick = ::requestPreview,
                    ) {
                        Text(if (busy == DesktopTaskBusy.PREVIEW) "Bygger preview…" else "Lav plan-preview")
                    }
                }

                preview?.let { value ->
                    Spacer(Modifier.height(12.dp))
                    DesktopPlanReview(
                        value,
                        canStart = Agent3TaskUiPolicy.canStart(
                            readiness?.selectedSurface,
                            value.canStart,
                            isBusy,
                            hasRun = false,
                        ),
                        starting = busy == DesktopTaskBusy.START,
                        onStart = ::startTask,
                    )
                }
            }

            snapshot?.let { value ->
                Spacer(Modifier.height(12.dp))
                DesktopRunCard(
                    value,
                    busy,
                    onRefresh = ::refreshRun,
                    onStopPlan = ::stopPlan,
                )
            }

            Spacer(Modifier.height(22.dp))
            Text(
                "Denne surface kan kun stoppe planen, når serverens receipt tillader det. Den kan ikke opfinde tool-/stream-kontrol, bekræfte writes, genoptage generiske Agent 3-runs eller ændre routing.",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun DesktopPlanReview(
    value: Agent3ReadonlyTaskPreview,
    canStart: Boolean,
    starting: Boolean,
    onStart: () -> Unit,
) {
    DesktopTaskCard {
        Text("Plan og review", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text("Preview har ikke kørt et tool.", color = KalivTheme.colors.Success, fontSize = 11.sp)
        if (value.rationale.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(value.rationale, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
        }
        Spacer(Modifier.height(10.dp))
        value.plan.forEachIndexed { index, step ->
            DesktopStepCard(index + 1, step)
            if (index != value.plan.lastIndex) Spacer(Modifier.height(7.dp))
        }
        Spacer(Modifier.height(10.dp))
        DesktopReceipt(value.capabilityReceipt)
        Spacer(Modifier.height(8.dp))
        DesktopEvidence(value.evidence)
        Spacer(Modifier.height(12.dp))
        Button(enabled = canStart, onClick = onStart) {
            Text(if (starting) "Starter…" else "Start read-only opgave")
        }
    }
}

@Composable
private fun DesktopRunCard(
    value: Agent3ReadonlyTaskSnapshot,
    busy: DesktopTaskBusy,
    onRefresh: () -> Unit,
    onStopPlan: () -> Unit,
) {
    val activeTool = value.termination.activeTool
    val polling = Agent3TaskUiPolicy.shouldPoll(
        runTerminal = value.terminal,
        activeToolState = activeTool?.state,
        activeToolRequestState = activeTool?.requestState,
    )
    DesktopTaskCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Task-run", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(value.run.id, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
            }
            Text(
                value.run.state,
                color = desktopRunColor(value.run.state),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        if (polling) {
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
        DesktopValueRow("Route", value.run.route.kind)
        DesktopValueRow("Step", "${value.run.currentStep}/${value.run.steps.size}")
        DesktopValueRow("Plan terminal", if (value.terminal) "ja" else "nej")
        DesktopValueRow("Statuspolling", if (polling) "aktiv" else "afsluttet")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(enabled = busy == DesktopTaskBusy.NONE, onClick = onRefresh) {
                Text(if (busy == DesktopTaskBusy.STATUS) "Henter…" else "Opdatér")
            }
            if (value.termination.plan.canRequest) {
                Button(
                    enabled = Agent3TaskUiPolicy.canStopPlan(
                        value.termination.plan.canRequest,
                        busy != DesktopTaskBusy.NONE,
                    ),
                    onClick = onStopPlan,
                ) {
                    Text(if (busy == DesktopTaskBusy.STOP_PLAN) "Stopper plan…" else "Stop plan")
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        DesktopTerminationScopes(value)

        value.run.answer?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text("Outcome", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
        }
        value.run.error?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text("Fejl/outcome", color = KalivTheme.colors.Danger, fontWeight = FontWeight.SemiBold)
            Text(it, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
        }
        Spacer(Modifier.height(12.dp))
        Text("Tool-status", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
        value.run.steps.forEachIndexed { index, step ->
            Spacer(Modifier.height(6.dp))
            DesktopStepCard(index + 1, step)
        }
        Spacer(Modifier.height(12.dp))
        DesktopReceipt(value.capabilityReceipt)
        Spacer(Modifier.height(8.dp))
        DesktopEvidence(value.evidence)
        Spacer(Modifier.height(12.dp))
        Text("Events og replans", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
        if (value.events.isEmpty()) {
            Text("Ingen events returneret endnu", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        } else {
            value.events.takeLast(20).forEach { event ->
                Spacer(Modifier.height(5.dp))
                Text(event.kind, color = KalivTheme.colors.Signal, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                event.payload?.toString()?.takeIf { it.isNotBlank() }?.let {
                    Text(it.take(420), color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun DesktopTerminationScopes(value: Agent3ReadonlyTaskSnapshot) {
    val termination = value.termination
    Text("Termination scopes", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(6.dp))

    Text("Plan", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    DesktopValueRow("State", termination.plan.state)
    DesktopValueRow("Kan anmodes", if (termination.plan.canRequest) "ja" else "nej")
    DesktopValueRow("Scope", termination.plan.requestScope)
    DesktopValueRow("Effekt", termination.plan.effect)
    Text(termination.plan.reason, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
    if (termination.plan.effect == "prevent_future_steps_active_tool_continues") {
        Text(
            "Stop af planen forhindrer fremtidige steps; det aktive tool fortsætter.",
            color = KalivTheme.colors.Amber,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }

    Spacer(Modifier.height(9.dp))
    Text("Modelstream", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    DesktopValueRow("State", termination.modelStream.state)
    DesktopValueRow("Aktiv", if (termination.modelStream.active) "ja" else "nej")
    DesktopValueRow("Handle", if (termination.modelStream.handlePresent) "til stede" else "mangler")
    DesktopValueRow("Kan anmodes", if (termination.modelStream.canRequest) "ja" else "nej")
    Text(termination.modelStream.reason, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)

    Spacer(Modifier.height(9.dp))
    Text("Aktivt tool", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    termination.activeTool?.let { active ->
        DesktopValueRow("Tool", active.tool)
        DesktopValueRow("Step", active.stepId)
        DesktopValueRow("State", active.state)
        DesktopValueRow("Semantik", active.semantics ?: "ukendt")
        DesktopValueRow("Handle", if (active.handlePresent) "til stede" else "mangler")
        DesktopValueRow("Request state", active.requestState)
        DesktopValueRow("Kan anmodes", if (active.canRequest) "ja" else "nej")
        Text(active.reason, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        if (active.canRequest) {
            Text(
                "Serveren rapporterer en tool-kontrol, men normal task-surface har ingen tool-cancel-route; ingen request sendes.",
                color = KalivTheme.colors.Amber,
                fontSize = 10.sp,
            )
        }
    } ?: Text("Intet aktivt tool", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
}

@Composable
private fun DesktopStepCard(index: Int, step: Agent3ReadonlyTaskStep) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(10.dp))
            .background(KalivTheme.colors.SurfaceHigh)
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "$index. ${step.summary.ifBlank { step.tool }}",
                color = KalivTheme.colors.TextHigh,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            step.state?.let {
                Text(it, color = desktopRunColor(it), fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
            }
        }
        Text("tool: ${step.tool}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        Text(
            "risk=${step.risk} · egress=${step.egress} · idempotent=${step.idempotent}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        if (step.args.isNotEmpty()) {
            Text("args: ${step.args.toString().take(420)}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        step.error?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = KalivTheme.colors.Danger, fontSize = 10.sp)
        }
    }
}

@Composable
private fun DesktopReceipt(value: Agent3TaskCapabilityReceipt?) {
    Text("Capability receipt", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
    if (value == null) {
        Text("Ingen receipt returneret", color = KalivTheme.colors.Amber, fontSize = 11.sp)
        return
    }
    DesktopValueRow("Tilladt", if (value.allowed) "ja" else "nej")
    DesktopValueRow("Route", value.route)
    DesktopValueRow("Graph", value.graphSha256.shortDesktopHash())
    DesktopValueRow("Plan", value.planSha256.shortDesktopHash())
    value.blockers.forEach {
        Text(
            "• ${it.capabilityId}: ${it.state} — ${it.reason}",
            color = KalivTheme.colors.Danger,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun DesktopEvidence(value: Agent3TaskEvidenceBinding) {
    Text("Versionsbundet evidens", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
    DesktopValueRow("Pilotrapport", value.pilotReportSha256.shortDesktopHash())
    DesktopValueRow("Kandidat", value.pilotCandidateGitSha.shortDesktopHash())
    DesktopValueRow("Rig-validation", value.rigValidationReportSha256.shortDesktopHash())
}

@Composable
private fun DesktopTaskCard(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(KalivTheme.colors.Surface)
            .padding(14.dp),
        content = content,
    )
}

@Composable
private fun DesktopValueRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.TextHigh, fontSize = 11.sp)
    }
}

@Composable
private fun desktopRunColor(state: String): Color = when (state) {
    "completed", "succeeded" -> KalivTheme.colors.Success
    "failed", "blocked" -> KalivTheme.colors.Danger
    "cancelled", "completed_after_cancel" -> KalivTheme.colors.Amber
    else -> KalivTheme.colors.Signal
}

private fun String.shortDesktopHash(): String = if (length <= 14) this else take(12) + "…"

private enum class DesktopTaskBusy {
    NONE,
    READINESS,
    PREVIEW,
    START,
    STATUS,
    STOP_PLAN,
}

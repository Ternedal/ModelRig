package dk.ternedal.modelrig.ui

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
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.logic.Agent3TaskUiPolicy
import dk.ternedal.modelrig.net.Agent3ReadonlyTaskClient
import dk.ternedal.modelrig.net.Agent3TaskReadinessClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Human-facing, server-routed read-only task surface.
 *
 * This screen never chooses Agent 3 itself. It reads the authoritative readiness
 * contract first. Missing, stale or unknown readiness is shown as Agent 2
 * fallback, while status and Stop remain available for a run that was already
 * persisted before readiness changed.
 */
@Composable
fun Agent3TaskScreen(
    store: TokenStore,
    onClose: () -> Unit,
    onUseAgent2: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    var readiness by remember { mutableStateOf<Agent3TaskReadinessClient.Readiness?>(null) }
    var message by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3ReadonlyTaskClient.Preview?>(null) }
    var snapshot by remember { mutableStateOf<Agent3ReadonlyTaskClient.Started?>(null) }
    var busy by remember { mutableStateOf(TaskBusy.READINESS) }
    var error by remember { mutableStateOf<String?>(null) }

    fun connection(): Pair<String, String> {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: kotlin.error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: kotlin.error("Ingen device-token er gemt")
        return base to token
    }

    fun refreshReadiness() {
        if (busy != TaskBusy.NONE && busy != TaskBusy.READINESS) return
        busy = TaskBusy.READINESS
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3TaskReadinessClient(base, token).readiness()
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { value ->
                readiness = value
                if (!value.agent3ReadonlySelected && snapshot == null) preview = null
            }.onFailure {
                // Unknown/unreadable readiness is Agent 2, not an optimistic guess.
                readiness = null
                if (snapshot == null) preview = null
                error = it.message ?: "Task-readiness kunne ikke hentes"
            }
        }
    }

    fun requestPreview() {
        if (!Agent3TaskUiPolicy.canPreview(
                serverSurface = readiness?.selectedSurface,
                message = message,
                busy = busy != TaskBusy.NONE,
                hasRun = snapshot != null,
            )
        ) return
        busy = TaskBusy.PREVIEW
        error = null
        preview = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).preview(message.trim())
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { preview = it }
                .onFailure { error = it.message ?: "Plan-preview fejlede" }
        }
    }

    fun startTask() {
        val plan = preview ?: return
        val planId = plan.planId ?: return
        if (!Agent3TaskUiPolicy.canStart(
                serverSurface = readiness?.selectedSurface,
                previewCanStart = plan.canStart,
                busy = busy != TaskBusy.NONE,
                hasRun = snapshot != null,
            )
        ) return
        busy = TaskBusy.START
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).start(planId)
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { snapshot = it }
                .onFailure { error = it.message ?: "Opgaven kunne ikke startes" }
        }
    }

    fun refreshRun() {
        val runId = snapshot?.run?.id ?: return
        if (busy != TaskBusy.NONE) return
        busy = TaskBusy.STATUS
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).status(runId)
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { snapshot = it }
                .onFailure { error = it.message ?: "Task-status kunne ikke hentes" }
        }
    }

    fun stopTask() {
        val runId = snapshot?.run?.id ?: return
        if (!Agent3TaskUiPolicy.canStop(snapshot?.terminal, busy != TaskBusy.NONE)) return
        busy = TaskBusy.STOP
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).cancel(runId)
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { snapshot = it }
                .onFailure { error = it.message ?: "Opgaven kunne ikke stoppes" }
        }
    }

    LaunchedEffect(Unit) { refreshReadiness() }

    // The screen owns phone-side polling. Leaving it cancels this coroutine, but
    // never pretends that cancelling the HTTP poll stopped the persisted rig run.
    LaunchedEffect(snapshot?.run?.id, snapshot?.terminal) {
        val runId = snapshot?.run?.id ?: return@LaunchedEffect
        while (isActive && Agent3TaskUiPolicy.shouldPoll(snapshot?.terminal)) {
            delay(1_000)
            if (busy != TaskBusy.NONE) continue
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).status(runId)
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
    val hasRun = snapshot != null
    val isBusy = busy != TaskBusy.NONE

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 18.dp, vertical = 14.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Kaliv Opgaver",
                        color = KalivTheme.colors.textHigh,
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Serverstyret read-only taskflade",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(12.dp))
            SurfaceCard {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(
                            if (surface == Agent3TaskUiPolicy.AGENT3_READONLY) {
                                "Agent 3 read-only valgt af serveren"
                            } else {
                                "Agent 2 fallback"
                            },
                            color = if (surface == Agent3TaskUiPolicy.AGENT3_READONLY) {
                                KalivTheme.colors.success
                            } else {
                                KalivTheme.colors.amber
                            },
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            readiness?.reason ?: "readiness_unavailable",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 11.sp,
                        )
                    }
                    if (busy == TaskBusy.READINESS) CircularProgressIndicator()
                }
                Spacer(Modifier.height(8.dp))
                MetaRow("Aktiv surface", surface)
                MetaRow("Fallback", readiness?.fallbackSurface ?: Agent3TaskUiPolicy.AGENT2)
                MetaRow("Routing", readiness?.uiContract?.routeSource ?: "fail_closed")
                MetaRow(
                    "Pilot",
                    readiness?.pilot?.successes?.let { "$it/${readiness?.pilot?.tasks ?: "?"}" } ?: "ukendt",
                )
                MetaRow("Replans", readiness?.pilot?.replans?.toString() ?: "ukendt")
                MetaRow("Retry-events", readiness?.pilot?.retryEvents?.toString() ?: "ukendt")
                readiness?.reasons?.distinct()?.forEach {
                    Text("• $it", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(enabled = !isBusy, onClick = { refreshReadiness() }) {
                    Text("Opdatér routing")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                SurfaceCard {
                    Text("Fejl", color = KalivTheme.colors.danger, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(4.dp))
                    Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                }
            }

            if (surface == Agent3TaskUiPolicy.AGENT2 && !hasRun) {
                Spacer(Modifier.height(12.dp))
                SurfaceCard {
                    Text(
                        "Denne opgave går via den eksisterende Agent 2-chat",
                        color = KalivTheme.colors.textHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Read-only taskfladen er ikke valgt af serveren. Ingen preview- eller start-request sendes til Agent 3.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(12.dp))
                    Button(onClick = onUseAgent2) { Text("Åbn normal chat") }
                }
            } else if (!hasRun) {
                Spacer(Modifier.height(12.dp))
                SurfaceCard {
                    Text("Ny read-only opgave", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = {
                            message = it
                            preview = null
                        },
                        enabled = !isBusy,
                        label = { Text("Hvad skal Kaliv undersøge?") },
                        supportingText = {
                            Text("Kun lokale, idempotente read-tools kan godkendes af serveren.")
                        },
                        minLines = 3,
                        maxLines = 7,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3TaskUiPolicy.canPreview(
                            serverSurface = readiness?.selectedSurface,
                            message = message,
                            busy = isBusy,
                            hasRun = false,
                        ),
                        onClick = { requestPreview() },
                    ) {
                        Text(if (busy == TaskBusy.PREVIEW) "Bygger preview…" else "Lav plan-preview")
                    }
                }

                preview?.let { plan ->
                    Spacer(Modifier.height(12.dp))
                    PlanReviewCard(
                        preview = plan,
                        canStart = Agent3TaskUiPolicy.canStart(
                            serverSurface = readiness?.selectedSurface,
                            previewCanStart = plan.canStart,
                            busy = isBusy,
                            hasRun = false,
                        ),
                        starting = busy == TaskBusy.START,
                        onStart = { startTask() },
                    )
                }
            }

            snapshot?.let { run ->
                Spacer(Modifier.height(12.dp))
                TaskRunCard(
                    snapshot = run,
                    busy = busy,
                    onRefresh = { refreshRun() },
                    onStop = { stopTask() },
                )
            }

            Spacer(Modifier.height(24.dp))
            Text(
                "Normal chat er urørt. Denne skærm kan ikke bekræfte writes, genoptage generiske Agent 3-runs eller ændre routing.",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            Spacer(Modifier.height(16.dp))
        }
    }
}

@Composable
private fun PlanReviewCard(
    preview: Agent3ReadonlyTaskClient.Preview,
    canStart: Boolean,
    starting: Boolean,
    onStart: () -> Unit,
) {
    SurfaceCard {
        Text("Plan og review", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(
            "Preview har ikke kørt et tool.",
            color = KalivTheme.colors.success,
            fontSize = 11.sp,
        )
        if (preview.rationale.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(preview.rationale, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
        }
        Spacer(Modifier.height(10.dp))
        preview.steps.forEachIndexed { index, step ->
            StepCard(index + 1, step)
            if (index != preview.steps.lastIndex) Spacer(Modifier.height(7.dp))
        }
        Spacer(Modifier.height(10.dp))
        ReceiptCard(preview.capabilityReceipt)
        Spacer(Modifier.height(8.dp))
        EvidenceCard(preview.evidence)
        Spacer(Modifier.height(12.dp))
        Button(enabled = canStart, onClick = onStart) {
            Text(if (starting) "Starter…" else "Start read-only opgave")
        }
    }
}

@Composable
private fun TaskRunCard(
    snapshot: Agent3ReadonlyTaskClient.Started,
    busy: TaskBusy,
    onRefresh: () -> Unit,
    onStop: () -> Unit,
) {
    val run = snapshot.run
    SurfaceCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Task-run", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(run.id, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            Text(
                run.state,
                color = runStateColor(run.state),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(Modifier.height(8.dp))
        if (!snapshot.terminal) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        MetaRow("Route", run.routeKind)
        MetaRow("Step", "${run.currentStep}/${run.steps.size}")
        MetaRow("Terminal", if (snapshot.terminal) "ja" else "nej")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(enabled = busy == TaskBusy.NONE, onClick = onRefresh) {
                Text(if (busy == TaskBusy.STATUS) "Henter…" else "Opdatér")
            }
            Button(
                enabled = Agent3TaskUiPolicy.canStop(snapshot.terminal, busy != TaskBusy.NONE),
                onClick = onStop,
            ) {
                Text(if (busy == TaskBusy.STOP) "Stopper…" else "Stop")
            }
        }

        run.answer?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text("Outcome", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
        }
        run.error?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text("Fejl/outcome", color = KalivTheme.colors.danger, fontWeight = FontWeight.SemiBold)
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
        }

        Spacer(Modifier.height(12.dp))
        Text("Tool-status", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(6.dp))
        run.steps.forEachIndexed { index, step ->
            StepCard(index + 1, step)
            if (index != run.steps.lastIndex) Spacer(Modifier.height(7.dp))
        }

        Spacer(Modifier.height(12.dp))
        ReceiptCard(snapshot.capabilityReceipt)
        Spacer(Modifier.height(8.dp))
        EvidenceCard(snapshot.evidence)

        Spacer(Modifier.height(12.dp))
        Text("Events og replans", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
        if (snapshot.events.isEmpty()) {
            Text("Ingen events returneret endnu", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        } else {
            snapshot.events.takeLast(20).forEach { event ->
                Spacer(Modifier.height(5.dp))
                Text(event.kind, color = KalivTheme.colors.signal, fontSize = 11.sp, fontWeight = FontWeight.SemiBold)
                if (event.payload.isNotBlank()) {
                    Text(event.payload.take(320), color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun StepCard(index: Int, step: Agent3ReadonlyTaskClient.Step) {
    Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "$index. ${step.summary.ifBlank { step.tool }}",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                step.state?.let {
                    Text(it, color = runStateColor(it), fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
                }
            }
            Text("tool: ${step.tool}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            Text(
                "risk=${step.risk} · egress=${step.egress} · idempotent=${step.idempotent}",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            if (step.args != "{}") {
                Text("args: ${step.args.take(300)}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            step.error?.takeIf { it.isNotBlank() }?.let {
                Text(it, color = KalivTheme.colors.danger, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun ReceiptCard(receipt: Agent3ReadonlyTaskClient.CapabilityReceipt?) {
    Text("Capability receipt", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
    if (receipt == null) {
        Text("Ingen receipt returneret", color = KalivTheme.colors.amber, fontSize = 11.sp)
        return
    }
    MetaRow("Tilladt", if (receipt.allowed) "ja" else "nej")
    MetaRow("Route", receipt.route)
    MetaRow("Graph", receipt.graphSha256.shortHash())
    MetaRow("Plan", receipt.planSha256.shortHash())
    receipt.blockers.forEach {
        Text(
            "• ${it.capabilityId}: ${it.state} — ${it.reason}",
            color = KalivTheme.colors.danger,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun EvidenceCard(evidence: Agent3ReadonlyTaskClient.EvidenceBinding) {
    Text("Versionsbundet evidens", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
    MetaRow("Pilotrapport", evidence.pilotReportSha256.shortHash())
    MetaRow("Kandidat", evidence.pilotCandidateGitSha.shortHash())
    MetaRow("Rig-validation", evidence.rigValidationReportSha256.shortHash())
}

@Composable
private fun SurfaceCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), content = content)
    }
}

@Composable
private fun MetaRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp)
    }
}

@Composable
private fun runStateColor(state: String): Color = when (state) {
    "completed", "succeeded" -> KalivTheme.colors.success
    "failed", "blocked" -> KalivTheme.colors.danger
    "cancelled", "completed_after_cancel" -> KalivTheme.colors.amber
    else -> KalivTheme.colors.signal
}

private fun String.shortHash(): String = if (length <= 14) this else take(12) + "…"

private enum class TaskBusy {
    NONE,
    READINESS,
    PREVIEW,
    START,
    STATUS,
    STOP,
}

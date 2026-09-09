package dk.ternedal.modelrig.ui

import android.os.SystemClock
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.Agent3TaskRunReferenceStore
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
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

/**
 * Human-facing, server-routed read-only task surface.
 *
 * This screen never chooses Agent 3 itself. It reads the authoritative readiness
 * contract first. Missing, stale or unknown readiness is shown as Agent 2
 * fallback, while status and the server-authorized plan Stop remain available
 * for a run that was already persisted before readiness changed. Plan, model
 * stream and active-tool termination are always shown as separate scopes.
 */
@Composable
fun Agent3TaskScreen(
    store: TokenStore,
    onClose: () -> Unit,
    onUseAgent2: () -> Unit,
) {
    val scope = rememberCoroutineScope()
    val context = LocalContext.current.applicationContext
    val runReferenceStore = remember { Agent3TaskRunReferenceStore(context) }
    var readiness by remember { mutableStateOf<Agent3TaskReadinessClient.Readiness?>(null) }
    var message by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3ReadonlyTaskClient.Preview?>(null) }
    var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
    var previewExpired by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<Agent3ReadonlyTaskClient.Started?>(null) }
    var retainedRunId by remember { mutableStateOf(runReferenceStore.read()) }
    var initialRecoveryPending by remember { mutableStateOf(retainedRunId != null) }
    var busy by remember { mutableStateOf(TaskBusy.READINESS) }
    var error by remember { mutableStateOf<String?>(null) }
    var publicationEpoch by remember { mutableStateOf(0L) }

    fun connection(): Pair<String, String> {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: kotlin.error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: kotlin.error("Ingen device-token er gemt")
        return base to token
    }

    fun publishSnapshot(value: Agent3ReadonlyTaskClient.Started) {
        snapshot = value
        val retained = Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(value.run.id, value.terminal)
        retainedRunId = retained
        if (!runReferenceStore.write(retained)) {
            error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.LOCAL_REFERENCE, null)
        }
    }

    fun recoverRun() {
        val runId = retainedRunId ?: return
        if (!Agent3TaskUiPolicy.canRecoverRun(runId, busy != TaskBusy.NONE)) return
        publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
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
            result.onSuccess(::publishSnapshot)
                .onFailure {
                    error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.STATUS, it.message)
                }
        }
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
                error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.READINESS, it.message)
            }
            if (initialRecoveryPending) {
                initialRecoveryPending = false
                recoverRun()
            }
        }
    }

    fun requestPreview() {
        if (!Agent3TaskUiPolicy.canPreview(
                serverSurface = readiness?.selectedSurface,
                message = message,
                busy = busy != TaskBusy.NONE,
                hasRun = Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId),
            )
        ) return
        busy = TaskBusy.PREVIEW
        error = null
        preview = null
        previewDeadlineMillis = null
        previewExpired = false
        val requestStartedAtMillis = SystemClock.elapsedRealtime()
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).preview(message.trim())
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess { value ->
                preview = value
                val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(
                    requestStartedAtMillis,
                    value.expiresInSeconds,
                )
                previewDeadlineMillis = deadline
                previewExpired = Agent3TaskUiPolicy.isPreviewExpired(
                    deadline,
                    SystemClock.elapsedRealtime(),
                )
            }.onFailure {
                    error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.PREVIEW, it.message)
                }
        }
    }

    fun startTask() {
        val plan = preview ?: return
        val planId = plan.planId ?: return
        val nowMillis = SystemClock.elapsedRealtime()
        val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(previewDeadlineMillis, nowMillis)
        if (Agent3TaskUiPolicy.isPreviewExpired(previewDeadlineMillis, nowMillis)) {
            previewExpired = true
        }
        if (!Agent3TaskUiPolicy.canStart(
                serverSurface = readiness?.selectedSurface,
                previewCanStart = plan.canStart,
                previewFresh = previewFresh,
                busy = busy != TaskBusy.NONE,
                hasRun = Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId),
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
            result.onSuccess(::publishSnapshot)
                .onFailure {
                    error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.START, it.message)
                }
        }
    }

    fun refreshRun() {
        val runId = snapshot?.run?.id ?: return
        if (busy != TaskBusy.NONE) return
        publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
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
            result.onSuccess(::publishSnapshot)
                .onFailure {
                    error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.STATUS, it.message)
                }
        }
    }

    fun stopPlan() {
        val current = snapshot ?: return
        val runId = current.run.id
        if (!Agent3TaskUiPolicy.canStopPlan(
                planCanRequest = current.termination.plan.canRequest,
                busy = busy != TaskBusy.NONE,
            )
        ) return
        publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
        busy = TaskBusy.STOP_PLAN
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).cancel(runId)
                }
            }
            busy = TaskBusy.NONE
            result.onSuccess(::publishSnapshot)
                .onFailure {
                    error = presentAgent3TaskScreenError(Agent3TaskFailureOperation.STOP_PLAN, it.message)
                }
        }
    }

    fun resetTerminalHistory() {
        val current = snapshot ?: return
        val activeTool = current.termination.activeTool
        if (!Agent3TaskUiPolicy.canResetTerminalHistory(
                runTerminal = current.terminal,
                activeToolState = activeTool?.state,
                activeToolRequestState = activeTool?.requestState,
                busy = busy != TaskBusy.NONE,
            )
        ) return
        publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
        snapshot = null
        preview = null
        previewDeadlineMillis = null
        previewExpired = false
        message = ""
        error = null
    }

    LaunchedEffect(Unit) { refreshReadiness() }

    // The screen owns phone-side polling. Leaving it cancels this coroutine, but
    // never pretends that cancelling the HTTP poll stopped the persisted rig run.
    // A cancelled plan may still have a synchronous tool executing, so the tool
    // receipt — not only run.terminal — decides when polling may stop.
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
            if (busy != TaskBusy.NONE) continue
            val requestEpoch = publicationEpoch
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ReadonlyTaskClient(base, token).status(runId)
                }
            }
            if (!Agent3TaskUiPolicy.canPublish(requestEpoch, publicationEpoch)) continue
            if (result.isSuccess) {
                publishSnapshot(result.getOrThrow())
            } else {
                error = presentAgent3TaskScreenError(
                    Agent3TaskFailureOperation.AUTOMATIC_STATUS,
                    result.exceptionOrNull()?.message,
                )
                return@LaunchedEffect
            }
        }
    }

    LaunchedEffect(preview?.planId, previewDeadlineMillis) {
        val deadline = previewDeadlineMillis ?: return@LaunchedEffect
        val remaining = deadline - SystemClock.elapsedRealtime()
        if (remaining > 0L) delay(remaining)
        if (preview?.planId != null && Agent3TaskUiPolicy.isPreviewExpired(
                deadline,
                SystemClock.elapsedRealtime(),
            )
        ) {
            previewExpired = true
        }
    }

    val surface = Agent3TaskUiPolicy.normalizedSurface(readiness?.selectedSurface)
    val hasRun = Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId)
    val isBusy = busy != TaskBusy.NONE

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .kalivScreenInsets()
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
                            presentAgent3TaskReadinessHeadline(readiness?.selectedSurface),
                            color = if (readiness?.agent3ReadonlySelected == true) {
                                KalivTheme.colors.success
                            } else {
                                KalivTheme.colors.amber
                            },
                            fontSize = 17.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            presentAgent3TaskReadinessStatus(readiness?.selectedSurface, readiness?.reason),
                            color = KalivTheme.colors.textMuted,
                            fontSize = 11.sp,
                        )
                        presentAgent3TaskReadinessServerReason(readiness?.reason)?.let { evidence ->
                            Text(evidence, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                        }
                    }
                    if (busy == TaskBusy.READINESS) CircularProgressIndicator()
                }
                Spacer(Modifier.height(8.dp))
                MetaRow("Aktiv surface", presentAgent3TaskReadinessSurface(readiness?.selectedSurface))
                MetaRow("Fallback", presentAgent3TaskReadinessSurface(readiness?.fallbackSurface))
                MetaRow("Routing", presentAgent3TaskReadinessRouteSource(readiness?.uiContract?.routeSource))
                MetaRow(
                    "Pilot",
                    readiness?.pilot?.successes?.let { "$it/${readiness?.pilot?.tasks ?: "?"}" } ?: "ukendt",
                )
                MetaRow("Replans", readiness?.pilot?.replans?.toString() ?: "ukendt")
                MetaRow("Retry-events", readiness?.pilot?.retryEvents?.toString() ?: "ukendt")
                val readinessReasons = readiness?.reasons?.distinct().orEmpty()
                if (readinessReasons.isNotEmpty()) {
                    Text("Tekniske readiness-koder", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                    readinessReasons.forEach {
                        Text("• $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                    }
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

            if (snapshot == null && retainedRunId != null) {
                Spacer(Modifier.height(12.dp))
                SurfaceCard {
                    Text(
                        "Tidligere task skal genforbindes",
                        color = KalivTheme.colors.textHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Denne enhed har en gemt reference til en read-only task. En ny task er låst, indtil riggen har bekræftet den eksisterende status.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3TaskUiPolicy.canRecoverRun(retainedRunId, isBusy),
                        onClick = { recoverRun() },
                    ) {
                        Text(if (busy == TaskBusy.STATUS) "Henter status…" else "Prøv igen")
                    }
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
                            previewDeadlineMillis = null
                            previewExpired = false
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
                    val nowMillis = SystemClock.elapsedRealtime()
                    val expired = previewExpired || Agent3TaskUiPolicy.isPreviewExpired(
                        previewDeadlineMillis,
                        nowMillis,
                    )
                    val previewFresh = !expired && Agent3TaskUiPolicy.isPreviewFresh(
                        previewDeadlineMillis,
                        nowMillis,
                    )
                    PlanReviewCard(
                        preview = plan,
                        canStart = Agent3TaskUiPolicy.canStart(
                            serverSurface = readiness?.selectedSurface,
                            previewCanStart = plan.canStart,
                            previewFresh = previewFresh,
                            busy = isBusy,
                            hasRun = false,
                        ),
                        expired = expired,
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
                    onStopPlan = { stopPlan() },
                )
                val activeTool = run.termination.activeTool
                if (Agent3TaskUiPolicy.canResetTerminalHistory(
                        runTerminal = run.terminal,
                        activeToolState = activeTool?.state,
                        activeToolRequestState = activeTool?.requestState,
                        busy = isBusy,
                    )
                ) {
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = { resetTerminalHistory() }) {
                        Text("Ny opgave")
                    }
                }
            }

            Spacer(Modifier.height(24.dp))
            Text(
                "Normal chat er urørt. Denne skærm kan stoppe fremtidige plan-steps, men viser ingen direkte tool-kontrol uden et serverbundet runtime-handle.",
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
    expired: Boolean,
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
        if (expired) {
            Spacer(Modifier.height(5.dp))
            Text(
                "Plan-previewet er udløbet. Lav et nyt preview før start.",
                color = KalivTheme.colors.danger,
                fontSize = 11.sp,
            )
        }
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
    onStopPlan: () -> Unit,
) {
    val run = snapshot.run
    val activeTool = snapshot.termination.activeTool
    val shouldPoll = Agent3TaskUiPolicy.shouldPoll(
        runTerminal = snapshot.terminal,
        activeToolState = activeTool?.state,
        activeToolRequestState = activeTool?.requestState,
    )
    SurfaceCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Task-run", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(run.id, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            Text(
                presentAgent3TaskRunState(run.state),
                color = runStateColor(run.state),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(Modifier.height(8.dp))
        if (shouldPoll) LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        MetaRow("Rute", presentAgent3TaskRunRoute(run.routeKind))
        MetaRow("Step", "${run.currentStep}/${run.steps.size}")
        MetaRow("Plan terminal", if (snapshot.terminal) "ja" else "nej")
        MetaRow("Statuspolling", if (shouldPoll) "aktiv" else "afsluttet")
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(enabled = busy == TaskBusy.NONE, onClick = onRefresh) {
                Text(if (busy == TaskBusy.STATUS) "Henter…" else "Opdatér")
            }
            if (snapshot.termination.plan.canRequest) {
                Button(
                    enabled = Agent3TaskUiPolicy.canStopPlan(
                        planCanRequest = snapshot.termination.plan.canRequest,
                        busy = busy != TaskBusy.NONE,
                    ),
                    onClick = onStopPlan,
                ) {
                    Text(if (busy == TaskBusy.STOP_PLAN) "Stopper plan…" else "Stop plan")
                }
            }
        }

        Spacer(Modifier.height(12.dp))
        TerminationCard(snapshot.termination)

        run.answer?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp))
            Text("Outcome", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
        }
        presentAgent3TaskRunError(run.state, run.error)?.let { message ->
            Spacer(Modifier.height(10.dp))
            Text("Kørselsproblem", color = KalivTheme.colors.danger, fontWeight = FontWeight.SemiBold)
            Text(message, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
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
                Text(
                    presentAgent3TaskEventKind(event.kind),
                    color = KalivTheme.colors.signal,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    presentAgent3TaskEventAuditCode(event.kind),
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                )
                presentAgent3TaskEventStructuredDetail(event.payload)?.let { detail ->
                    Text(detail, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun TerminationCard(receipt: Agent3ReadonlyTaskClient.TerminationReceipt) {
    val plan = receipt.plan
    val stream = receipt.modelStream
    val tool = receipt.activeTool

    Text("Afslutningsstatus", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(6.dp))
    Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Text("Plan", color = KalivTheme.colors.textHigh, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            MetaRow("Status", presentAgent3TerminationPlanState(plan.state))
            MetaRow("Stopomfang", presentAgent3TerminationPlanScope(plan.requestScope))
            MetaRow("Kan stoppes", if (plan.canRequest) "ja" else "nej")
            MetaRow("Effekt", presentAgent3TerminationPlanEffect(plan.effect))
            if (plan.effect == "prevent_future_steps_active_tool_continues") {
                Text(
                    "Plan-stop forhindrer nye steps, men det aktive tool fortsætter.",
                    color = KalivTheme.colors.amber,
                    fontSize = 10.sp,
                )
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "Teknisk kvittering · plan",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
                fontWeight = FontWeight.SemiBold,
            )
            agent3TerminationPlanEvidence(
                state = plan.state,
                canRequest = plan.canRequest,
                requestScope = plan.requestScope,
                effect = plan.effect,
                reason = plan.reason,
            ).forEach { field ->
                Text("${field.label}: ${field.value}", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
            }

            Spacer(Modifier.height(8.dp))
            Text("Modelstream", color = KalivTheme.colors.textHigh, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            MetaRow("Status", presentAgent3TerminationModelState(stream.state))
            MetaRow("Aktiv", if (stream.active) "ja" else "nej")
            MetaRow("Runtime-handle", if (stream.handlePresent) "ja" else "nej")
            MetaRow("Kan stoppes", if (stream.canRequest) "ja" else "nej")
            Spacer(Modifier.height(4.dp))
            Text(
                "Teknisk kvittering · modelstream",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
                fontWeight = FontWeight.SemiBold,
            )
            agent3TerminationModelEvidence(
                state = stream.state,
                active = stream.active,
                canRequest = stream.canRequest,
                handlePresent = stream.handlePresent,
                reason = stream.reason,
            ).forEach { field ->
                Text("${field.label}: ${field.value}", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
            }

            Spacer(Modifier.height(8.dp))
            Text("Aktivt tool", color = KalivTheme.colors.textHigh, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (tool == null) {
                Text("Intet aktivt tool", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            } else {
                MetaRow("Step-status", presentAgent3TaskStepState(tool.state) ?: "Status ukendt")
                MetaRow("Afbrydelse", presentAgent3TerminationSemantics(tool.semantics))
                MetaRow("Stopstatus", presentAgent3TerminationRequestState(tool.requestState))
                MetaRow("Runtime-handle", if (tool.handlePresent) "ja" else "nej")
                MetaRow("Kan stoppes", if (tool.canRequest) "ja" else "nej")
                MetaRow("Direkte kontrol", if (tool.canRequest && tool.handlePresent) "tilgængelig" else "ingen")
                Spacer(Modifier.height(4.dp))
                Text(
                    "Teknisk kvittering · aktivt tool",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                agent3TerminationActiveToolEvidence(
                    stepId = tool.stepId,
                    tool = tool.tool,
                    state = tool.state,
                    semantics = tool.semantics,
                    handlePresent = tool.handlePresent,
                    canRequest = tool.canRequest,
                    requestState = tool.requestState,
                    reason = tool.reason,
                ).forEach { field ->
                    Text("${field.label}: ${field.value}", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
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
                    "$index. ${presentAgent3TaskStepHeadline(step.summary)}",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                step.state?.let { rawState ->
                    presentAgent3TaskStepState(rawState)?.let { label ->
                        Text(label, color = runStateColor(rawState), fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
            Text(presentAgent3TaskStepToolAudit(step.tool), color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            Text(
                presentAgent3TaskStepReadOnlyMetadata(step.risk, step.egress, step.idempotent),
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            presentAgent3TaskStepStructuredDetail(step.args != "{}")?.let { detail ->
                Text(detail, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            presentAgent3TaskStepError(step.state, step.error)?.let { message ->
                Text(message, color = KalivTheme.colors.danger, fontSize = 10.sp)
            }
        }
    }
}

@Composable
private fun ReceiptCard(receipt: Agent3ReadonlyTaskClient.CapabilityReceipt?) {
    Text("Kapabilitetstjek", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
    if (receipt == null) {
        Text("Kapabilitetskvittering er ikke tilgængelig.", color = KalivTheme.colors.amber, fontSize = 11.sp)
        return
    }
    Text(
        presentAgent3CapabilityStatusMessage(receipt.allowed),
        color = if (receipt.allowed) KalivTheme.colors.success else KalivTheme.colors.danger,
        fontSize = 11.sp,
    )
    MetaRow("Rute", presentAgent3CapabilityRoute(receipt.route))
    MetaRow("Blokeringer", presentAgent3CapabilityBlockerCount(receipt.blockers.size))
    MetaRow("Graf-hash", receipt.graphSha256.shortHash())
    MetaRow("Plan-hash", receipt.planSha256.shortHash())
    if (receipt.blockers.isNotEmpty()) {
        Spacer(Modifier.height(4.dp))
        Text(
            "Teknisk kvittering · blokeringer",
            color = KalivTheme.colors.textMuted,
            fontSize = 9.sp,
            fontWeight = FontWeight.SemiBold,
        )
        receipt.blockers.forEachIndexed { index, blocker ->
            Text(
                "Blokering ${index + 1}",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
                fontWeight = FontWeight.SemiBold,
            )
            agent3CapabilityBlockerEvidence(
                blocker.capabilityId,
                blocker.state,
                blocker.reason,
            ).forEach { field ->
                Text(
                    "${field.label}: ${field.value}",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                )
            }
        }
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
    STOP_PLAN,
}

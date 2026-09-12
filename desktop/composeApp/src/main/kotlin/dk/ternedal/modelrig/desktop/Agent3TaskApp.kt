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
import dk.ternedal.modelrig.desktop.net.Agent3TaskHttpException
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
        var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
        var previewExpired by remember { mutableStateOf(false) }
        var snapshot by remember { mutableStateOf<Agent3ReadonlyTaskSnapshot?>(null) }
        var retainedRunId by remember {
            mutableStateOf(db.getSetting(ACTIVE_TASK_RUN_ID_SETTING)?.trim()?.takeIf { it.isNotEmpty() })
        }
        var retainedStartPlanId by remember {
            mutableStateOf(
                db.getSetting(ACTIVE_TASK_START_RECOVERY_PLAN_ID_SETTING)
                    ?.trim()
                    ?.takeIf { it.isNotEmpty() },
            )
        }
        var startRecoveryPending by remember {
            mutableStateOf(retainedRunId == null && retainedStartPlanId != null)
        }
        var initialRecoveryPending by remember { mutableStateOf(retainedRunId != null) }
        var busy by remember { mutableStateOf(DesktopTaskBusy.READINESS) }
        var error by remember { mutableStateOf<String?>(null) }
        var publicationEpoch by remember { mutableStateOf(0L) }

        fun requireConnection(): Pair<String, String> {
            if (baseUrl.isBlank()) kotlin.error("Ingen ModelRig backend-URL er gemt")
            if (token.isBlank()) kotlin.error("Ingen device-token er gemt")
            return baseUrl.trim() to token.trim()
        }

        fun writeRetainedRunId(runId: String?): Boolean = runCatching {
            db.putSetting(ACTIVE_TASK_RUN_ID_SETTING, runId.orEmpty())
        }.isSuccess

        fun writeRetainedStartPlanId(planId: String?): Boolean {
            val normalized = planId?.trim()?.takeIf { it.isNotEmpty() }
            val saved = runCatching {
                db.putSetting(ACTIVE_TASK_START_RECOVERY_PLAN_ID_SETTING, normalized.orEmpty())
            }.isSuccess
            if (saved) {
                retainedStartPlanId = normalized
                startRecoveryPending = normalized != null && retainedRunId == null && snapshot == null
            }
            return saved
        }

        fun publishSnapshot(value: Agent3ReadonlyTaskSnapshot) {
            snapshot = value
            val activeTool = value.termination.activeTool
            val retained = Agent3TaskUiPolicy.retainedRunIdAfterSnapshot(
                runId = value.run.id,
                terminal = value.terminal,
                activeToolState = activeTool?.state,
                activeToolRequestState = activeTool?.requestState,
            )
            retainedRunId = retained
            if (!writeRetainedRunId(retained)) {
                startRecoveryPending = retainedStartPlanId != null
                error = presentTaskRequestError(TaskRequestOperation.LOCAL_REFERENCE, null)
                return
            }
            if (retainedStartPlanId != null) writeRetainedStartPlanId(null)
            startRecoveryPending = false
        }

        fun recoverRun() {
            val runId = retainedRunId ?: return
            if (!Agent3TaskUiPolicy.canRecoverRun(runId, busy != DesktopTaskBusy.NONE)) return
            publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
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
                result.onSuccess(::publishSnapshot)
                    .onFailure { error = presentTaskRequestError(TaskRequestOperation.STATUS, it.message) }
            }
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
                    if (!value.agent3ReadonlySelected && snapshot == null && !startRecoveryPending) preview = null
                }.onFailure {
                    readiness = null
                    if (snapshot == null && !startRecoveryPending) preview = null
                    error = presentTaskRequestError(TaskRequestOperation.READINESS, it.message)
                }
                if (initialRecoveryPending) {
                    initialRecoveryPending = false
                    recoverRun()
                }
            }
        }

        fun requestPreview() {
            if (!Agent3TaskUiPolicy.canPreview(
                    readiness?.selectedSurface,
                    message,
                    busy != DesktopTaskBusy.NONE,
                    Agent3TaskUiPolicy.hasTaskAuthority(
                        snapshotPresent = snapshot != null,
                        retainedRunId = retainedRunId,
                        retainedStartPlanId = retainedStartPlanId,
                    ),
                )
            ) return
            busy = DesktopTaskBusy.PREVIEW
            error = null
            preview = null
            previewDeadlineMillis = null
            previewExpired = false
            startRecoveryPending = false
            scope.launch {
                val readinessResult = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3TaskReadinessClient(base, bearer).readiness()
                    }
                }
                val freshReadiness = readinessResult.getOrElse {
                    busy = DesktopTaskBusy.NONE
                    readiness = null
                    preview = null
                    error = presentTaskRequestError(TaskRequestOperation.READINESS, it.message)
                    return@launch
                }
                readiness = freshReadiness
                if (!freshReadiness.agent3ReadonlySelected) {
                    busy = DesktopTaskBusy.NONE
                    preview = null
                    previewDeadlineMillis = null
                    previewExpired = false
                    return@launch
                }
                val requestStartedAtMillis = System.nanoTime() / 1_000_000L
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).preview(message.trim())
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess { value ->
                    preview = value
                    val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(
                        requestStartedAtMillis,
                        value.expiresInSeconds,
                    )
                    previewDeadlineMillis = deadline
                    previewExpired = Agent3TaskUiPolicy.isPreviewExpired(
                        deadline,
                        System.nanoTime() / 1_000_000L,
                    )
                }.onFailure { error = presentTaskRequestError(TaskRequestOperation.PREVIEW, it.message) }
            }
        }

        fun publishStartFailure(failure: Throwable) {
            if (
                failure is Agent3TaskHttpException &&
                !Agent3TaskUiPolicy.shouldRetainStartRecovery(failure.reasonCode)
            ) {
                writeRetainedStartPlanId(null)
                if (failure.reasonCode == "task_start_refused") {
                    preview = null
                    previewDeadlineMillis = null
                    previewExpired = false
                    error = presentTaskRequestError(TaskRequestOperation.START_REFUSED, failure.message)
                } else {
                    error = presentTaskRequestError(TaskRequestOperation.START_NOT_ACCEPTED, failure.message)
                }
                return
            }
            startRecoveryPending = true
            error = presentTaskRequestError(TaskRequestOperation.START, failure.message)
        }

        fun recoverPendingStart() {
            val planId = retainedStartPlanId ?: return
            val hasRun = Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId)
            if (!Agent3TaskUiPolicy.canRecoverStart(
                    retainedStartPlanId = planId,
                    busy = busy != DesktopTaskBusy.NONE,
                    hasRun = hasRun,
                )
            ) return
            busy = DesktopTaskBusy.START
            error = null
            startRecoveryPending = true
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).start(planId)
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess(::publishSnapshot)
                    .onFailure(::publishStartFailure)
            }
        }

        fun startTask() {
            if (startRecoveryPending) {
                recoverPendingStart()
                return
            }
            val plan = preview ?: return
            val planId = plan.planId ?: return
            val nowMillis = System.nanoTime() / 1_000_000L
            val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(previewDeadlineMillis, nowMillis)
            if (Agent3TaskUiPolicy.isPreviewExpired(previewDeadlineMillis, nowMillis)) {
                previewExpired = true
            }
            if (!Agent3TaskUiPolicy.canStart(
                    readiness?.selectedSurface,
                    plan.canStart,
                    previewFresh,
                    busy != DesktopTaskBusy.NONE,
                    Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId),
                )
            ) return
            busy = DesktopTaskBusy.START
            error = null
            scope.launch {
                val readinessResult = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3TaskReadinessClient(base, bearer).readiness()
                    }
                }
                val freshReadiness = readinessResult.getOrElse {
                    busy = DesktopTaskBusy.NONE
                    readiness = null
                    preview = null
                    previewDeadlineMillis = null
                    previewExpired = false
                    error = presentTaskRequestError(TaskRequestOperation.READINESS, it.message)
                    return@launch
                }
                readiness = freshReadiness
                if (!freshReadiness.agent3ReadonlySelected) {
                    busy = DesktopTaskBusy.NONE
                    preview = null
                    previewDeadlineMillis = null
                    previewExpired = false
                    return@launch
                }
                if (!Agent3TaskUiPolicy.readinessBindingMatches(
                        currentPilotReportSha256 = freshReadiness.pilot.reportSha256,
                        currentPilotCandidateGitSha = freshReadiness.pilot.candidateGitSha,
                        currentRigValidationReportSha256 = freshReadiness.rigValidation.reportSha256,
                        previewPilotReportSha256 = plan.evidence.pilotReportSha256,
                        previewPilotCandidateGitSha = plan.evidence.pilotCandidateGitSha,
                        previewRigValidationReportSha256 = plan.evidence.rigValidationReportSha256,
                    )
                ) {
                    busy = DesktopTaskBusy.NONE
                    preview = null
                    previewDeadlineMillis = null
                    previewExpired = false
                    error = "Plan-previewet matcher ikke længere task-readiness. Lav et nyt preview."
                    return@launch
                }
                val startNowMillis = System.nanoTime() / 1_000_000L
                if (!Agent3TaskUiPolicy.isPreviewFresh(previewDeadlineMillis, startNowMillis)) {
                    busy = DesktopTaskBusy.NONE
                    if (Agent3TaskUiPolicy.isPreviewExpired(previewDeadlineMillis, startNowMillis)) {
                        previewExpired = true
                    }
                    return@launch
                }
                if (!writeRetainedStartPlanId(planId)) {
                    busy = DesktopTaskBusy.NONE
                    error = presentTaskRequestError(TaskRequestOperation.START_RECOVERY_REFERENCE, null)
                    return@launch
                }
                startRecoveryPending = true
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).start(planId)
                    }
                }
                busy = DesktopTaskBusy.NONE
                result.onSuccess(::publishSnapshot)
                    .onFailure(::publishStartFailure)
            }
        }

        fun refreshRun() {
            val runId = snapshot?.run?.id ?: return
            if (busy != DesktopTaskBusy.NONE) return
            publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
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
                result.onSuccess(::publishSnapshot)
                    .onFailure { error = presentTaskRequestError(TaskRequestOperation.STATUS, it.message) }
            }
        }

        fun stopPlan() {
            val current = snapshot ?: return
            if (!Agent3TaskUiPolicy.canStopPlan(
                    current.termination.plan.canRequest,
                    busy != DesktopTaskBusy.NONE,
                )
            ) return
            publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
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
                result.onSuccess(::publishSnapshot)
                    .onFailure { error = presentTaskRequestError(TaskRequestOperation.STOP_PLAN, it.message) }
            }
        }

        fun resetTerminalHistory() {
            val current = snapshot ?: return
            val activeTool = current.termination.activeTool
            if (!Agent3TaskUiPolicy.canResetTerminalHistory(
                    runTerminal = current.terminal,
                    activeToolState = activeTool?.state,
                    activeToolRequestState = activeTool?.requestState,
                    busy = busy != DesktopTaskBusy.NONE,
                )
            ) return
            publicationEpoch = Agent3TaskUiPolicy.nextPublicationEpoch(publicationEpoch)
            snapshot = null
            preview = null
            previewDeadlineMillis = null
            previewExpired = false
            startRecoveryPending = retainedStartPlanId != null && retainedRunId == null
            message = ""
            error = null
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
                val requestEpoch = publicationEpoch
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val (base, bearer) = requireConnection()
                        Agent3ReadonlyTaskClient(base, bearer).status(runId)
                    }
                }
                if (!Agent3TaskUiPolicy.canPublish(requestEpoch, publicationEpoch)) continue
                if (result.isSuccess) {
                    publishSnapshot(result.getOrThrow())
                } else {
                    error = presentTaskRequestError(TaskRequestOperation.POLLING, result.exceptionOrNull()?.message)
                    return@LaunchedEffect
                }
            }
        }

        LaunchedEffect(preview?.planId, previewDeadlineMillis) {
            val deadline = previewDeadlineMillis ?: return@LaunchedEffect
            val remaining = deadline - (System.nanoTime() / 1_000_000L)
            if (remaining > 0L) delay(remaining)
            if (preview?.planId != null && Agent3TaskUiPolicy.isPreviewExpired(
                    deadline,
                    System.nanoTime() / 1_000_000L,
                )
            ) {
                previewExpired = true
            }
        }

        val surface = Agent3TaskUiPolicy.normalizedSurface(readiness?.selectedSurface)
        val isBusy = busy != DesktopTaskBusy.NONE
        val hasRun = Agent3TaskUiPolicy.hasRunAuthority(snapshot != null, retainedRunId)
        val hasTaskAuthority = Agent3TaskUiPolicy.hasTaskAuthority(
            snapshotPresent = snapshot != null,
            retainedRunId = retainedRunId,
            retainedStartPlanId = retainedStartPlanId,
        )

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
                            presentTaskReadinessHeadline(readiness?.selectedSurface),
                            color = if (readiness?.agent3ReadonlySelected == true) {
                                KalivTheme.colors.Success
                            } else {
                                KalivTheme.colors.Amber
                            },
                            fontSize = 19.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        Text(
                            presentTaskReadinessStatus(readiness?.selectedSurface, readiness?.reason),
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 11.sp,
                        )
                        presentTaskReadinessServerReason(readiness?.reason)?.let { evidence ->
                            Text(evidence, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                        }
                    }
                    if (busy == DesktopTaskBusy.READINESS) CircularProgressIndicator()
                }
                Spacer(Modifier.height(8.dp))
                DesktopValueRow("Backend", baseUrl)
                DesktopValueRow("Device-token", if (token.isBlank()) "mangler" else "gemt")
                DesktopValueRow("Aktiv surface", presentTaskReadinessSurface(readiness?.selectedSurface))
                DesktopValueRow("Fallback", presentTaskReadinessSurface(readiness?.fallbackSurface))
                DesktopValueRow("Routing", presentTaskReadinessRouteSource(readiness?.uiContract?.routeSource))
                DesktopValueRow(
                    "Pilot",
                    readiness?.pilot?.successes?.let { "$it/${readiness?.pilot?.tasks ?: "?"}" } ?: "ukendt",
                )
                DesktopValueRow("Replans", readiness?.pilot?.replans?.toString() ?: "ukendt")
                DesktopValueRow("Retry-events", readiness?.pilot?.retryEvents?.toString() ?: "ukendt")
                val readinessReasons = readiness?.reasons?.distinct().orEmpty()
                if (readinessReasons.isNotEmpty()) {
                    Text("Tekniske readiness-koder", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                    readinessReasons.forEach {
                        Text("• $it", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                    }
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

            if (snapshot == null && retainedRunId != null) {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text(
                        "Tidligere task skal genforbindes",
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Denne klient har en gemt reference til en read-only task. En ny task er låst, indtil riggen har bekræftet den eksisterende status.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3TaskUiPolicy.canRecoverRun(retainedRunId, isBusy),
                        onClick = ::recoverRun,
                    ) {
                        Text(if (busy == DesktopTaskBusy.STATUS) "Henter status…" else "Prøv igen")
                    }
                }
            }

            if (snapshot == null && retainedRunId == null && retainedStartPlanId != null && preview == null) {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text(
                        "Startstatus skal afklares",
                        color = KalivTheme.colors.TextHigh,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Denne klient har gemt den samme plan-reference fra en Start, der ikke fik et entydigt svar. Ingen ny opgave kan startes, før riggen har afklaret den Start.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3TaskUiPolicy.canRecoverStart(
                            retainedStartPlanId = retainedStartPlanId,
                            busy = isBusy,
                            hasRun = hasRun,
                        ),
                        onClick = ::recoverPendingStart,
                    ) {
                        Text(if (busy == DesktopTaskBusy.START) "Henter startstatus…" else "Hent startstatus")
                    }
                }
            }

            if (surface == Agent3TaskUiPolicy.AGENT2 && !hasTaskAuthority) {
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
            } else if (!hasRun && (retainedStartPlanId == null || preview != null)) {
                Spacer(Modifier.height(12.dp))
                DesktopTaskCard {
                    Text("Ny read-only opgave", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = {
                            message = it
                            preview = null
                            previewDeadlineMillis = null
                            previewExpired = false
                        },
                        enabled = !isBusy && !hasTaskAuthority,
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
                            hasRun = hasTaskAuthority,
                        ),
                        onClick = ::requestPreview,
                    ) {
                        Text(if (busy == DesktopTaskBusy.PREVIEW) "Bygger preview…" else "Lav plan-preview")
                    }
                }

                preview?.let { value ->
                    Spacer(Modifier.height(12.dp))
                    val nowMillis = System.nanoTime() / 1_000_000L
                    val expired = previewExpired || Agent3TaskUiPolicy.isPreviewExpired(
                        previewDeadlineMillis,
                        nowMillis,
                    )
                    val previewFresh = !expired && Agent3TaskUiPolicy.isPreviewFresh(
                        previewDeadlineMillis,
                        nowMillis,
                    )
                    DesktopPlanReview(
                        value,
                        canStart = if (retainedStartPlanId != null) {
                            Agent3TaskUiPolicy.canRecoverStart(
                                retainedStartPlanId = retainedStartPlanId,
                                busy = isBusy,
                                hasRun = hasRun,
                            )
                        } else {
                            Agent3TaskUiPolicy.canStart(
                                readiness?.selectedSurface,
                                value.canStart,
                                previewFresh,
                                isBusy,
                                hasRun = false,
                            )
                        },
                        expired = expired,
                        recoveryPending = retainedStartPlanId != null,
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
                val activeTool = value.termination.activeTool
                if (Agent3TaskUiPolicy.canResetTerminalHistory(
                        runTerminal = value.terminal,
                        activeToolState = activeTool?.state,
                        activeToolRequestState = activeTool?.requestState,
                        busy = isBusy,
                    )
                ) {
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = ::resetTerminalHistory) {
                        Text("Ny opgave")
                    }
                }
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
    expired: Boolean,
    recoveryPending: Boolean,
    starting: Boolean,
    onStart: () -> Unit,
) {
    DesktopTaskCard {
        Text("Plan og review", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text("Preview har ikke kørt et tool.", color = KalivTheme.colors.Success, fontSize = 11.sp)
        if (recoveryPending) {
            Spacer(Modifier.height(5.dp))
            Text(
                "Start blev sendt, men udfaldet er ikke bekræftet. Samme Start bruges kun til at hente det allerede accepterede run eller et serverafslag.",
                color = KalivTheme.colors.Amber,
                fontSize = 11.sp,
            )
        } else if (expired) {
            Spacer(Modifier.height(5.dp))
            Text(
                "Plan-previewet er udløbet. Lav et nyt preview før start.",
                color = KalivTheme.colors.Danger,
                fontSize = 11.sp,
            )
        }
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
            Text(
                if (starting) "Henter startstatus…"
                else if (recoveryPending) "Hent startstatus"
                else "Start read-only opgave"
            )
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
                presentTaskRunState(value.run.state),
                color = desktopRunColor(value.run.state),
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        if (polling) {
            Spacer(Modifier.height(8.dp))
            LinearProgressIndicator(modifier = Modifier.fillMaxWidth())
        }
        DesktopValueRow("Route", presentTaskRunRoute(value.run.route.kind))
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
        presentTaskRunError(value.run.state, value.run.error)?.let { message ->
            Spacer(Modifier.height(10.dp))
            Text("Problem med kørslen", color = KalivTheme.colors.Danger, fontWeight = FontWeight.SemiBold)
            Text(message, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
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
                Text(
                    presentTaskEventKind(event.kind),
                    color = KalivTheme.colors.Signal,
                    fontSize = 11.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    presentTaskEventAuditCode(event.kind),
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
                presentTaskEventStructuredDetail(event.payload != null)?.let { detail ->
                    Text(detail, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                }
            }
        }
    }
}

@Composable
private fun DesktopTerminationScopes(value: Agent3ReadonlyTaskSnapshot) {
    val termination = value.termination
    Text("Stop og afbrydelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
    Spacer(Modifier.height(6.dp))

    Text("Plan", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    DesktopValueRow("Planstatus", presentTerminationPlanState(termination.plan.state))
    DesktopValueRow("Stopmulighed", if (termination.plan.canRequest) "Kan anmodes" else "Ikke tilgængelig")
    DesktopValueRow("Omfang", presentTerminationPlanScope(termination.plan.requestScope))
    DesktopValueRow("Stopeffekt", presentTerminationPlanEffect(termination.plan.effect))
    if (termination.plan.effect == "prevent_future_steps_active_tool_continues") {
        Text(
            "Stop af planen forhindrer kommende trin, men det aktive værktøj kan fortsætte.",
            color = KalivTheme.colors.Amber,
            fontSize = 10.sp,
        )
    }
    DesktopTechnicalReceipt("Plan", terminationPlanEvidence(termination.plan))

    Spacer(Modifier.height(8.dp))
    Text("Modelstream", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    DesktopValueRow("Modelstream-status", presentTerminationModelState(termination.modelStream.state))
    DesktopValueRow("Stopmulighed", if (termination.modelStream.canRequest) "Kan anmodes" else "Ikke tilgængelig")
    DesktopValueRow("Runtime-handle", if (termination.modelStream.handlePresent) "Til stede" else "Ikke tilgængeligt")
    DesktopTechnicalReceipt("Modelstream", terminationModelEvidence(termination.modelStream))

    Spacer(Modifier.height(8.dp))
    Text("Aktivt værktøj", color = KalivTheme.colors.Signal, fontWeight = FontWeight.SemiBold, fontSize = 12.sp)
    termination.activeTool?.let { active ->
        DesktopValueRow("Værktøj", active.tool)
        DesktopValueRow("Trin-id", active.stepId)
        DesktopValueRow("Værktøjsstatus", presentTaskStepState(active.state) ?: "Status ukendt")
        DesktopValueRow("Afbrydelse", presentTerminationSemantics(active.semantics))
        DesktopValueRow("Stopstatus", presentTerminationRequestState(active.requestState))
        DesktopValueRow("Runtime-handle", if (active.handlePresent) "Til stede" else "Ikke tilgængeligt")
        DesktopValueRow("Direkte stop", if (active.canRequest) "Kan anmodes" else "Ikke tilgængeligt")
        DesktopTechnicalReceipt("Aktivt værktøj", terminationActiveToolEvidence(active))
    } ?: Text("Intet aktivt værktøj", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
}

@Composable
private fun DesktopTechnicalReceipt(title: String, fields: List<TaskTerminationEvidence>) {
    Spacer(Modifier.height(4.dp))
    Text(
        "Teknisk kvittering · $title",
        color = KalivTheme.colors.TextMuted,
        fontSize = 9.sp,
        fontWeight = FontWeight.SemiBold,
    )
    fields.forEach { field ->
        Text(
            "${field.label}: ${field.value}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 9.sp,
        )
    }
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
                "$index. ${presentTaskStepHeadline(step.summary)}",
                color = KalivTheme.colors.TextHigh,
                fontSize = 12.sp,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            step.state?.let { rawState ->
                presentTaskStepState(rawState)?.let { label ->
                    Text(
                        label,
                        color = desktopRunColor(rawState),
                        fontSize = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
            }
        }
        Text(presentTaskStepToolAudit(step.tool), color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        Text(
            presentTaskStepReadOnlyMetadata(step.risk, step.egress, step.idempotent),
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        presentTaskStepStructuredDetail(step.args.isNotEmpty())?.let { detail ->
            Text(detail, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        presentTaskStepError(step.state, step.error)?.let { message ->
            Text(message, color = KalivTheme.colors.Danger, fontSize = 10.sp)
        }
    }
}

@Composable
private fun DesktopReceipt(value: Agent3TaskCapabilityReceipt?) {
    Text("Kapabilitetstjek", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
    if (value == null) {
        Text(
            presentTaskCapabilityStatus(null),
            color = KalivTheme.colors.Amber,
            fontSize = 11.sp,
        )
        return
    }
    Text(
        presentTaskCapabilityStatus(value.allowed),
        color = if (value.allowed) KalivTheme.colors.Success else KalivTheme.colors.Danger,
        fontSize = 11.sp,
    )
    DesktopValueRow("Rute", presentTaskCapabilityRoute(value.route))
    DesktopValueRow("Blokeringer", presentTaskCapabilityBlockerCount(value.blockers.size))
    DesktopValueRow("Graf-hash", value.graphSha256.shortDesktopHash())
    DesktopValueRow("Plan-hash", value.planSha256.shortDesktopHash())
    if (value.blockers.isNotEmpty()) {
        Spacer(Modifier.height(4.dp))
        Text(
            "Teknisk kvittering · blokeringer",
            color = KalivTheme.colors.TextMuted,
            fontSize = 9.sp,
            fontWeight = FontWeight.SemiBold,
        )
        value.blockers.forEachIndexed { index, blocker ->
            Text(
                "Blokering ${index + 1}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
                fontWeight = FontWeight.SemiBold,
            )
            taskCapabilityBlockerEvidence(
                blocker.capabilityId,
                blocker.state,
                blocker.reason,
            ).forEach { field ->
                Text(
                    "${field.label}: ${field.value}",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }
        }
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

private const val ACTIVE_TASK_RUN_ID_SETTING = "agent3TaskActiveRunId"
private const val ACTIVE_TASK_START_RECOVERY_PLAN_ID_SETTING = "agent3TaskPendingStartPlanId"

private enum class DesktopTaskBusy {
    NONE,
    READINESS,
    PREVIEW,
    START,
    STATUS,
    STOP_PLAN,
}

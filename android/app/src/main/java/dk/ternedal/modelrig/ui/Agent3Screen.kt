package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.logic.Agent3ConfirmationAuthority
import dk.ternedal.modelrig.logic.Agent3PreviewAuthorityPolicy
import dk.ternedal.modelrig.logic.Agent3PreviewConnection
import dk.ternedal.modelrig.logic.Agent3PreviewIntent
import dk.ternedal.modelrig.logic.Agent3TaskUiPolicy
import dk.ternedal.modelrig.logic.isAgent3ConfirmationAuthorityConsumed
import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.ui.components.kalivScreenInsets
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun Agent3Screen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var message by remember { mutableStateOf("") }
    var useMemory by remember { mutableStateOf(false) }
    var memorySubjects by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3Client.PlanPreview?>(null) }
    var previewConnection by remember { mutableStateOf<Agent3PreviewConnection?>(null) }
    var previewIntent by remember { mutableStateOf<Agent3PreviewIntent?>(null) }
    var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
    var previewExpired by remember { mutableStateOf(false) }
    var run by remember { mutableStateOf<Agent3Client.Run?>(null) }
    var runConnection by remember { mutableStateOf<Agent3PreviewConnection?>(null) }
    var consumedConfirmation by remember { mutableStateOf<Agent3ConfirmationAuthority?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun currentConnection(): Agent3PreviewConnection =
        requireNotNull(Agent3PreviewConnection.capture(store.baseUrl, store.token)) {
            "Forbindelsen er ugyldig"
        }

    fun client(connection: Agent3PreviewConnection): Agent3Client =
        Agent3Client(connection.baseUrl, connection.token)

    fun currentIntent(): Agent3PreviewIntent? =
        Agent3PreviewIntent.capture(message, useMemory, memorySubjects)

    fun clearPreviewAuthority() {
        preview = null
        previewConnection = null
        previewIntent = null
        previewDeadlineMillis = null
        previewExpired = false
    }

    fun previewPlan() {
        val requestIntent = currentIntent() ?: return
        if (busy) return
        val connection = runCatching { currentConnection() }
            .getOrElse {
                error = it.message ?: "Forbindelsen er ugyldig"
                return
            }
        val requestStartedAtMillis = System.nanoTime() / 1_000_000L
        busy = true
        error = null
        run = null
        runConnection = null
        clearPreviewAuthority()
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    client(connection).previewPlan(
                        message = requestIntent.message,
                        mode = "rig",
                        useMemory = requestIntent.useMemory,
                        memorySubjects = requestIntent.memorySubjects,
                    )
                }
            }
            busy = false
            result.onSuccess { planned ->
                if (!Agent3PreviewAuthorityPolicy.canPublish(requestIntent, currentIntent())) {
                    error = "Preview blev forældet, fordi opgaven eller memory-valget ændrede sig"
                    return@onSuccess
                }
                val deadline = Agent3TaskUiPolicy.previewDeadlineMillis(
                    requestStartedAtMillis,
                    planned.expiresInSeconds,
                )
                preview = planned
                previewConnection = connection
                previewIntent = requestIntent
                previewDeadlineMillis = deadline
                previewExpired = !Agent3TaskUiPolicy.isPreviewFresh(
                    deadline,
                    System.nanoTime() / 1_000_000L,
                )
            }.onFailure { error = it.message ?: "Planlægning fejlede" }
        }
    }

    fun startPlan() {
        val current = preview ?: return
        val currentConnection = Agent3PreviewConnection.capture(store.baseUrl, store.token)
        val currentIntent = currentIntent()
        val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
            previewDeadlineMillis,
            System.nanoTime() / 1_000_000L,
        )
        if (!previewFresh) previewExpired = true
        if (!Agent3PreviewAuthorityPolicy.canStart(
                planId = current.planId,
                hasSteps = current.steps.isNotEmpty(),
                capabilityAllowed = current.capabilityReceipt?.allowed,
                previewFresh = previewFresh,
                busy = busy,
                hasRun = run != null,
                currentConnection = currentConnection,
                previewConnection = previewConnection,
                currentIntent = currentIntent,
                previewIntent = previewIntent,
            )
        ) return
        val id = current.planId ?: return
        val connection = previewConnection ?: return
        busy = true
        error = null
        clearPreviewAuthority()
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client(connection).startPlan(id) }
            }
            busy = false
            result.onSuccess { started ->
                run = started
                runConnection = connection
            }.onFailure {
                val detail = it.message ?: "Kunne ikke starte planen"
                error = "$detail. Plan-preview-authority er forbrugt lokalt; lav et nyt preview før nyt forsøg."
            }
        }
    }

    fun refreshRun() {
        val id = run?.id ?: return
        val connection = runConnection
        if (connection == null) {
            error = "Run-forbindelsen mangler; opdatering er afvist lokalt"
            return
        }
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client(connection).getRun(id) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure { error = it.message ?: "Kunne ikke hente run-status" }
        }
    }

    fun decide(approve: Boolean) {
        val current = run ?: return
        val step = current.steps.getOrNull(current.currentStep) ?: return
        val stepId = step.id ?: return
        val digest = step.confirmationDigest ?: return
        val authority = Agent3ConfirmationAuthority.capture(current.id, stepId, digest) ?: return
        val connection = runConnection
        if (connection == null) {
            error = "Run-forbindelsen mangler; godkendelsen er afvist lokalt"
            return
        }
        if (busy || isAgent3ConfirmationAuthorityConsumed(authority, consumedConfirmation)) return
        busy = true
        error = null
        consumedConfirmation = authority
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client(connection).confirm(current.id, stepId, digest, approve) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure {
                    val detail = it.message ?: "Godkendelsen fejlede"
                    error = "$detail. Beslutningen kan allerede være gennemført på serveren; den gamle godkendelse genbruges ikke. Opdatér run-status."
                }
        }
    }

    fun stopPlan() {
        val id = run?.id ?: return
        val connection = runConnection
        if (connection == null) {
            error = "Run-forbindelsen mangler; stop er afvist lokalt"
            return
        }
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client(connection).cancel(id) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure { error = it.message ?: "Kunne ikke stoppe planen" }
        }
    }

    LaunchedEffect(preview?.planId, previewDeadlineMillis) {
        val planId = preview?.planId ?: return@LaunchedEffect
        val deadline = previewDeadlineMillis
        if (deadline == null) {
            previewExpired = true
            return@LaunchedEffect
        }
        val remaining = deadline - (System.nanoTime() / 1_000_000L)
        if (remaining > 0L) delay(remaining)
        if (
            preview?.planId == planId &&
            previewDeadlineMillis == deadline &&
            Agent3TaskUiPolicy.isPreviewExpired(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
        ) {
            previewExpired = true
        }
    }

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
                        "Agent 3.0",
                        fontSize = 26.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Eksperimentel plan- og run-visning",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(14.dp)) {
                    Text(
                        "Forespørgsel",
                        fontWeight = FontWeight.SemiBold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = { message = it; clearPreviewAuthority() },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 8,
                        label = { Text("Hvad skal agenten planlægge?") },
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (useMemory) {
                            Button(onClick = { useMemory = false; memorySubjects = ""; clearPreviewAuthority() }) {
                                Text("Memory: til")
                            }
                        } else {
                            OutlinedButton(onClick = { useMemory = true; clearPreviewAuthority() }) {
                                Text("Memory: fra")
                            }
                        }
                    }
                    Text(
                        if (useMemory) "Kun bekræftede records sendes til den lokale planner."
                        else "Planner-memory er opt-in og slukket.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 11.sp,
                    )
                    if (useMemory) {
                        Spacer(Modifier.height(8.dp))
                        OutlinedTextField(
                            value = memorySubjects,
                            onValueChange = { memorySubjects = it; clearPreviewAuthority() },
                            label = { Text("Valgfrit subject-filter, kommasepareret") },
                            supportingText = { Text("Tomt felt bruger alle eligible memories inden for serverens budget.") },
                            singleLine = true,
                            modifier = Modifier.fillMaxWidth(),
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = !busy && message.isNotBlank(),
                        onClick = { previewPlan() },
                    ) {
                        Text(if (busy) "Arbejder…" else "Lav plan-preview")
                    }
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(12.dp)) {
                    Text(
                        it,
                        color = KalivTheme.colors.danger,
                        modifier = Modifier.fillMaxWidth().padding(12.dp),
                        fontSize = 13.sp,
                    )
                }
            }

            preview?.let { p ->
                val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                    previewDeadlineMillis,
                    System.nanoTime() / 1_000_000L,
                )
                val startEnabled = Agent3PreviewAuthorityPolicy.canStart(
                    planId = p.planId,
                    hasSteps = p.steps.isNotEmpty(),
                    capabilityAllowed = p.capabilityReceipt?.allowed,
                    previewFresh = previewFresh,
                    busy = busy,
                    hasRun = run != null,
                    currentConnection = Agent3PreviewConnection.capture(store.baseUrl, store.token),
                    previewConnection = previewConnection,
                    currentIntent = currentIntent(),
                    previewIntent = previewIntent,
                )
                Spacer(Modifier.height(14.dp))
                Agent3PlanCard(
                    preview = p,
                    startEnabled = startEnabled,
                    expiredForDisplay = previewExpired || !previewFresh,
                    onStart = { startPlan() },
                )
            }

            run?.let { r ->
                Spacer(Modifier.height(14.dp))
                Agent3RunCard(
                    run = r,
                    busy = busy,
                    consumedConfirmation = consumedConfirmation,
                    onRefresh = { refreshRun() },
                    onApprove = { decide(true) },
                    onDeny = { decide(false) },
                    onStopPlan = { stopPlan() },
                )
            }

            Spacer(Modifier.height(30.dp))
        }
    }
}

@Composable
private fun Agent3PlanCard(
    preview: Agent3Client.PlanPreview,
    startEnabled: Boolean,
    expiredForDisplay: Boolean,
    onStart: () -> Unit,
) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text("Plan-preview", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
            Text(
                "Route: ${preview.routeKind.ifBlank { "ukendt" }}",
                fontSize = 12.sp,
                color = KalivTheme.colors.textMuted,
            )
            if (preview.rationale.isNotBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(preview.rationale, fontSize = 13.sp, color = KalivTheme.colors.textHigh)
            }
            if (preview.memoryContext.requested) {
                Spacer(Modifier.height(10.dp))
                Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
                    Column(Modifier.fillMaxWidth().padding(10.dp)) {
                        Text("Memory receipt", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                        Text(
                            if (preview.memoryContext.sentToModel) {
                                "Sendt til planner · ${preview.memoryContext.target}"
                            } else {
                                "Anmodet, men ingen eligible memory blev sendt"
                            },
                            color = if (preview.memoryContext.sentToModel) KalivTheme.colors.success else KalivTheme.colors.textMuted,
                            fontSize = 11.sp,
                        )
                        Text(
                            "inkluderet=${preview.memoryContext.includedIds.size} · udelukket=${preview.memoryContext.excludedIds.size} · tegn=${preview.memoryContext.characterCount}",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 10.sp,
                        )
                        if (preview.memoryContext.includedIds.isNotEmpty()) {
                            Text(
                                "ids: ${preview.memoryContext.includedIds.joinToString(", ")}",
                                color = KalivTheme.colors.textMuted,
                                fontSize = 9.sp,
                            )
                        }
                        preview.memoryContext.sha256?.let {
                            Text("sha256: $it", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
                        }
                    }
                }
            }
            preview.capabilityReceipt?.let {
                Spacer(Modifier.height(10.dp))
                Agent3CapabilityReceiptCard(it)
            }
            Spacer(Modifier.height(10.dp))
            if (preview.steps.isEmpty()) {
                Text("Planen indeholder ingen tool-steps.", color = KalivTheme.colors.textMuted)
            } else {
                preview.steps.forEachIndexed { index, step ->
                    Agent3StepCard(index + 1, step)
                    if (index != preview.steps.lastIndex) Spacer(Modifier.height(8.dp))
                }
            }
            Spacer(Modifier.height(12.dp))
            Button(
                enabled = startEnabled,
                onClick = onStart,
            ) {
                Text("Start den viste plan")
            }
            if (expiredForDisplay) {
                Spacer(Modifier.height(4.dp))
                Text(
                    "Plan-previewet er udløbet eller mangler gyldig TTL. Lav et nyt preview.",
                    fontSize = 11.sp,
                    color = KalivTheme.colors.danger,
                )
            } else {
                preview.expiresInSeconds?.let {
                    Spacer(Modifier.height(4.dp))
                    Text("Plan-id udløber om ca. $it sek.", fontSize = 11.sp, color = KalivTheme.colors.textMuted)
                }
            }
        }
    }
}

@Composable
private fun Agent3RunCard(
    run: Agent3Client.Run,
    busy: Boolean,
    consumedConfirmation: Agent3ConfirmationAuthority?,
    onRefresh: () -> Unit,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    onStopPlan: () -> Unit,
) {
    val current = run.steps.getOrNull(run.currentStep)
    val waiting = run.state == "waiting_confirmation" && current?.confirmationDigest != null && current.id != null
    val currentAuthority = Agent3ConfirmationAuthority.capture(run.id, current?.id, current?.confirmationDigest)
    val confirmationConsumed = isAgent3ConfirmationAuthorityConsumed(currentAuthority, consumedConfirmation)
    val termination = run.termination
    val canStopPlan = termination?.plan?.canRequest == true

    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Run", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Text(run.id, fontSize = 10.sp, color = KalivTheme.colors.textMuted)
                }
                Text(run.state, fontSize = 12.sp, color = KalivTheme.colors.signal)
            }
            Spacer(Modifier.height(8.dp))
            run.steps.forEachIndexed { index, step ->
                Agent3StepCard(index + 1, step, active = index == run.currentStep)
                if (index != run.steps.lastIndex) Spacer(Modifier.height(8.dp))
            }

            run.answer?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(10.dp))
                HorizontalDivider()
                Spacer(Modifier.height(8.dp))
                Text(it, color = KalivTheme.colors.textHigh)
            }
            run.error?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp)
            }

            if (waiting) {
                Spacer(Modifier.height(12.dp))
                Text(
                    current?.summary ?: "Dette step kræver godkendelse.",
                    color = KalivTheme.colors.amber,
                    fontWeight = FontWeight.SemiBold,
                )
                Spacer(Modifier.height(8.dp))
                if (confirmationConsumed) {
                    Text(
                        "Beslutningen er allerede sendt. Samme godkendelse genbruges ikke; opdatér run-status for serverens aktuelle sandhed.",
                        color = KalivTheme.colors.danger,
                        fontSize = 11.sp,
                    )
                } else {
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !busy, onClick = onApprove) { Text("Godkend") }
                        OutlinedButton(enabled = !busy, onClick = onDeny) { Text("Afvis") }
                    }
                }
            }

            Spacer(Modifier.height(10.dp))
            Agent3TerminationCard(termination, run.state)

            Spacer(Modifier.height(12.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(enabled = !busy, onClick = onRefresh) { Text("Opdatér") }
                if (canStopPlan) {
                    Button(
                        enabled = !busy,
                        onClick = onStopPlan,
                        colors = ButtonDefaults.buttonColors(containerColor = KalivTheme.colors.danger),
                    ) {
                        Text("Stop plan")
                    }
                }
            }
        }
    }
}

@Composable
private fun Agent3TerminationCard(
    receipt: Agent3Client.TerminationReceipt?,
    runState: String,
) {
    Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Text("Stopstatus", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            if (receipt == null) {
                Text(
                    if (runState in setOf("completed", "failed", "cancelled")) {
                        "Run er afsluttet."
                    } else {
                        "Serveren sendte ingen verificeret stopstatus. Ingen stopkontrol vises."
                    },
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                return@Column
            }
            Text(
                when (receipt.plan.effect) {
                    "prevent_future_steps_active_tool_continues" ->
                        "Stop plan forhindrer kommende trin. Det aktive tool fortsætter uden et bundet stop-handle."
                    else -> "Stop plan forhindrer kommende trin."
                },
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            receipt.activeTool?.let { active ->
                Spacer(Modifier.height(4.dp))
                Text(
                    if (active.canRequest && active.handlePresent) {
                        "Aktivt tool: ${active.tool} · direkte stop er tilgængeligt."
                    } else {
                        "Aktivt tool: ${active.tool} · direkte tool-stop er ikke tilgængeligt (${active.reason})."
                    },
                    color = if (active.canRequest && active.handlePresent) {
                        KalivTheme.colors.amber
                    } else {
                        KalivTheme.colors.textMuted
                    },
                    fontSize = 10.sp,
                )
            }
        }
    }
}

@Composable
private fun Agent3StepCard(
    number: Int,
    step: Agent3Client.Step,
    active: Boolean = false,
) {
    Surface(
        color = if (active) KalivTheme.colors.background else KalivTheme.colors.surface,
        shape = RoundedCornerShape(10.dp),
        tonalElevation = if (active) 2.dp else 0.dp,
    ) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "$number. ${step.tool}",
                    fontWeight = FontWeight.SemiBold,
                    color = KalivTheme.colors.textHigh,
                    modifier = Modifier.weight(1f),
                )
                Text(step.state ?: step.risk, fontSize = 11.sp, color = KalivTheme.colors.textMuted)
            }
            if (step.summary.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(step.summary, fontSize = 12.sp, color = KalivTheme.colors.textHigh)
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "risiko=${step.risk} · følsomhed=${step.sensitivity} · egress=${step.egress}",
                fontSize = 10.sp,
                color = KalivTheme.colors.textMuted,
            )
            if (step.args != "{}") {
                Spacer(Modifier.height(3.dp))
                Text(step.args, fontSize = 10.sp, color = KalivTheme.colors.textMuted)
            }
            step.error?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(4.dp))
                Text(it, fontSize = 11.sp, color = KalivTheme.colors.danger)
            }
        }
    }
}

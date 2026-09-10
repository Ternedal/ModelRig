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
import dk.ternedal.modelrig.logic.Agent3ReplanPreviewIntent
import dk.ternedal.modelrig.logic.Agent3ReplanPreviewPolicy
import dk.ternedal.modelrig.logic.Agent3ReviewConnectionBinding
import dk.ternedal.modelrig.logic.Agent3TaskUiPolicy
import dk.ternedal.modelrig.net.Agent3ReplanClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

/** Developer-only reviewed read-replan UI. Normal AppUi is untouched. */
@Composable
fun Agent3ReplanScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var runId by remember { mutableStateOf("") }
    var plannerModel by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3ReplanClient.Preview?>(null) }
    var previewConnection by remember { mutableStateOf<Agent3ReviewConnectionBinding?>(null) }
    var previewIntent by remember { mutableStateOf<Agent3ReplanPreviewIntent?>(null) }
    var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
    var previewExpired by remember { mutableStateOf(false) }
    var applied by remember { mutableStateOf<Agent3ReplanClient.ApplyResult?>(null) }
    var applyArmed by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun currentConnection(): Agent3ReviewConnectionBinding =
        requireNotNull(Agent3ReviewConnectionBinding.capture(store.baseUrl, store.token)) {
            "Rig-forbindelsen mangler eller er ugyldig"
        }

    fun client(connection: Agent3ReviewConnectionBinding): Agent3ReplanClient =
        Agent3ReplanClient(connection.baseUrl, connection.token)

    fun clearPreviewAuthority() {
        preview = null
        previewConnection = null
        previewIntent = null
        previewDeadlineMillis = null
        previewExpired = false
        applyArmed = false
    }

    fun loadPreview() {
        val requestIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel) ?: return
        if (busy) return
        val connection = runCatching { currentConnection() }
            .getOrElse {
                error = it.message ?: "Rig-forbindelsen er ugyldig"
                return
            }
        val requestStartedAtMillis = System.nanoTime() / 1_000_000L
        busy = true
        error = null
        clearPreviewAuthority()
        applied = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    client(connection).preview(
                        requestIntent.runId,
                        requestIntent.plannerModel,
                    )
                }
            }
            busy = false
            result.onSuccess { planned ->
                val currentIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel)
                if (!Agent3ReplanPreviewPolicy.canPublish(
                        requestIntent = requestIntent,
                        currentIntent = currentIntent,
                        responseRunId = planned.runId,
                    )
                ) {
                    error = if (planned.runId != requestIntent.runId) {
                        "Replan-preview blev afvist, fordi serverens run-id ikke matcher den reviewede kørsel"
                    } else {
                        "Replan-preview blev forældet, fordi run-id eller replanner-model ændrede sig"
                    }
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
            }.onFailure { error = it.message ?: "Replan-preview fejlede" }
        }
    }

    fun applyPreview() {
        val current = preview ?: return
        val boundConnection = previewConnection
        val currentConnection = Agent3ReviewConnectionBinding.capture(store.baseUrl, store.token)
        val currentIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel)
        val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
            previewDeadlineMillis,
            System.nanoTime() / 1_000_000L,
        )
        if (!previewFresh) {
            previewExpired = true
            applyArmed = false
        }
        if (!Agent3ReplanPreviewPolicy.canApply(
                previewId = current.previewId,
                previewRunId = current.runId,
                previewFresh = previewFresh,
                busy = busy,
                currentIntent = currentIntent,
                previewIntent = previewIntent,
                currentConnection = currentConnection,
                previewConnection = boundConnection,
            )
        ) {
            applyArmed = false
            error = if (!previewFresh) {
                "Replan-previewet er udløbet. Lav et nyt preview."
            } else {
                "Replan-previewet matcher ikke længere den reviewede opgave eller forbindelse"
            }
            return
        }
        if (!applyArmed) {
            applyArmed = true
            return
        }
        val connection = boundConnection ?: return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client(connection).applyReviewed(current) }
            }
            busy = false
            result.onSuccess {
                clearPreviewAuthority()
                applied = it
            }.onFailure { error = it.message ?: "Replan kunne ikke anvendes" }
        }
    }

    LaunchedEffect(preview?.previewId, previewDeadlineMillis) {
        val previewId = preview?.previewId ?: return@LaunchedEffect
        val deadline = previewDeadlineMillis
        if (deadline == null) {
            previewExpired = true
            applyArmed = false
            return@LaunchedEffect
        }
        val remaining = deadline - (System.nanoTime() / 1_000_000L)
        if (remaining > 0L) delay(remaining)
        if (
            preview?.previewId == previewId &&
            previewDeadlineMillis == deadline &&
            Agent3TaskUiPolicy.isPreviewExpired(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
        ) {
            previewExpired = true
            applyArmed = false
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
                        "Agent 3.0 Read Replanner",
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Reviewed lokal read-replan · developer-only",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            ReplanSurface {
                Text("Sikkerhedsgrænse", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(6.dp))
                Text(
                    "Preview kalder kun den lokale read-replanner. Write-argumenter skjules, cloud-runs afvises, og apply kan kun bruge det viste single-use-token.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 12.sp,
                )
                store.baseUrl?.let {
                    Spacer(Modifier.height(6.dp))
                    Text("Rig: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                }
            }

            Spacer(Modifier.height(12.dp))
            ReplanSurface {
                Text("Run", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = runId,
                    onValueChange = {
                        runId = it
                        clearPreviewAuthority()
                        applied = null
                    },
                    label = { Text("AgentRun-id") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = plannerModel,
                    onValueChange = {
                        plannerModel = it
                        clearPreviewAuthority()
                    },
                    label = { Text("Lokal replanner-model, valgfri") },
                    supportingText = { Text("Tomt felt bruger workerens standardmodel.") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy && runId.isNotBlank(), onClick = { loadPreview() }) {
                    Text(if (busy) "Arbejder…" else "Lav read-replan-preview")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ReplanSurface { Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp) }
            }

            preview?.let { current ->
                val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                    previewDeadlineMillis,
                    System.nanoTime() / 1_000_000L,
                )
                val applyAllowed = Agent3ReplanPreviewPolicy.canApply(
                    previewId = current.previewId,
                    previewRunId = current.runId,
                    previewFresh = previewFresh,
                    busy = busy,
                    currentIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel),
                    previewIntent = previewIntent,
                    currentConnection = Agent3ReviewConnectionBinding.capture(store.baseUrl, store.token),
                    previewConnection = previewConnection,
                )
                Spacer(Modifier.height(12.dp))
                ReplanPreviewSurface(
                    current,
                    busy,
                    applyArmed,
                    applyAllowed,
                    previewExpired || !previewFresh,
                    onApply = { applyPreview() },
                    onDisarm = { applyArmed = false },
                )
            }

            applied?.let {
                Spacer(Modifier.height(12.dp))
                AppliedReplanSurface(it)
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun ReplanSurface(content: @Composable () -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) { content() }
    }
}

@Composable
private fun ReplanPreviewSurface(
    preview: Agent3ReplanClient.Preview,
    busy: Boolean,
    armed: Boolean,
    applyAllowed: Boolean,
    expired: Boolean,
    onApply: () -> Unit,
    onDisarm: () -> Unit,
) {
    ReplanSurface {
        Text("Reviewed replan-preview", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(7.dp))
        ReplanRow("Revision", "${preview.revision} · replan #${preview.replanCount + 1}")
        ReplanRow("Udløb", "${preview.expiresInSeconds} sekunder")
        ReplanRow("Observationer", "${preview.observationCharacters} tegn")
        ReplanRow("Read-window", "${preview.window.start}..<${preview.window.end}")
        ReplanRow("Fjernes", preview.window.removableStepIds.joinToString().ifBlank { "ingen" })
        ReplanRow("Immutable tail", preview.window.immutableTailIds.joinToString().ifBlank { "ingen" })
        ReplanRow("Prompt SHA-256", preview.promptSha256)
        Spacer(Modifier.height(8.dp))
        Text(preview.rationale, color = KalivTheme.colors.textHigh, fontSize = 13.sp)
        Spacer(Modifier.height(10.dp))
        if (preview.plan.isEmpty()) {
            Text("Forslaget fjerner alle resterende pending reads.", color = KalivTheme.colors.amber)
        } else {
            preview.plan.forEachIndexed { index, step ->
                Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
                    Column(Modifier.fillMaxWidth().padding(10.dp)) {
                        Text("${index + 1}. ${step.tool}", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                        Text(step.summary, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                        Text("risk=${step.risk} · egress=${step.egress}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                        Text("args=${step.args}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                    }
                }
                if (index != preview.plan.lastIndex) Spacer(Modifier.height(7.dp))
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = applyAllowed, onClick = onApply) {
                Text(if (armed) "Bekræft apply" else "Armér apply")
            }
            if (armed) {
                OutlinedButton(enabled = applyAllowed && !busy, onClick = onDisarm) { Text("Fortryd") }
            }
        }
        if (expired) {
            Text(
                "Previewet er udløbet eller har en ugyldig TTL. Lav et nyt preview før Apply.",
                color = KalivTheme.colors.danger,
                fontSize = 11.sp,
            )
        } else if (!applyAllowed) {
            Text(
                "Apply er låst, fordi previewets opgave eller forbindelse ikke længere matcher.",
                color = KalivTheme.colors.danger,
                fontSize = 11.sp,
            )
        } else if (armed) {
            Text(
                "Næste klik forbruger tokenet og erstatter kun det viste pending read-window. Runnet fortsættes ikke automatisk.",
                color = KalivTheme.colors.amber,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun AppliedReplanSurface(result: Agent3ReplanClient.ApplyResult) {
    ReplanSurface {
        Text("Replan anvendt", color = KalivTheme.colors.success, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        ReplanRow("Run", result.run.id)
        ReplanRow("Run-state", result.run.state)
        ReplanRow("Revision", "${result.replan.fromRevision} → ${result.replan.toRevision}")
        ReplanRow("Fjernede tools", result.replan.removedTools.joinToString().ifBlank { "ingen" })
        ReplanRow("Tilføjede tools", result.replan.addedTools.joinToString().ifBlank { "ingen" })
        ReplanRow("Prompt SHA-256", result.preview.promptSha256)
        Spacer(Modifier.height(7.dp))
        Text(
            "Revisionen er journalført. Skærmen genoptager ikke runnet automatisk.",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun ReplanRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp)
    }
}
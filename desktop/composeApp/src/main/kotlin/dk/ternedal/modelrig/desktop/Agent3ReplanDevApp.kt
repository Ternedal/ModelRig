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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3ReplanApplyResult
import dk.ternedal.modelrig.desktop.net.Agent3ReplanClient
import dk.ternedal.modelrig.desktop.net.Agent3ReplanPreview
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only reviewed read-replan UI. Normal App() is untouched. */
@Composable
fun Agent3ReplanDevApp() {
    val db = remember { DesktopChatDb() }
    fun setting(key: String, env: String?, default: String): String =
        System.getenv(env ?: "")?.takeIf { it.isNotBlank() }
            ?: db.getSetting(key) ?: default

    var darkMode by remember { mutableStateOf(db.getSetting("darkMode") != "false") }
    KalivTheme(dark = darkMode) {
        val scope = rememberCoroutineScope()
        var baseUrl by remember {
            mutableStateOf(
                System.getenv("MODELRIG_AGENT3_URL")?.takeIf { it.isNotBlank() }
                    ?: setting("localUrl", "MODELRIG_LOCAL_URL", "http://127.0.0.1:8080")
            )
        }
        var token by remember { mutableStateOf(setting("deviceToken", "MODELRIG_TOKEN", "")) }
        var runId by remember { mutableStateOf("") }
        var plannerModel by remember {
            mutableStateOf(System.getenv("KALIV_AGENT3_PLANNER_MODEL") ?: "")
        }
        var preview by remember { mutableStateOf<Agent3ReplanPreview?>(null) }
        var previewConnection by remember { mutableStateOf<Agent3DevConnectionBinding?>(null) }
        var previewIntent by remember { mutableStateOf<Agent3ReplanPreviewIntent?>(null) }
        var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
        var previewExpired by remember { mutableStateOf(false) }
        var applied by remember { mutableStateOf<Agent3ReplanApplyResult?>(null) }
        var applyArmed by remember { mutableStateOf(false) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun currentConnection(): Agent3DevConnectionBinding =
            requireNotNull(Agent3DevConnectionBinding.capture(baseUrl, token)) {
                "Forbindelsen mangler eller er ugyldig"
            }

        fun client(connection: Agent3DevConnectionBinding): Agent3ReplanClient =
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
                    error = it.message ?: "Forbindelsen er ugyldig"
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
                    val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                        deadline,
                        System.nanoTime() / 1_000_000L,
                    )
                    preview = planned
                    previewConnection = connection
                    previewIntent = requestIntent
                    previewDeadlineMillis = deadline
                    previewExpired = Agent3ReplanPreviewPolicy.shouldMarkExpired(
                        previewId = planned.previewId,
                        previewFresh = previewFresh,
                    )
                }.onFailure { error = it.message ?: "Replan-preview fejlede" }
            }
        }

        fun applyPreview() {
            val current = preview ?: return
            val boundConnection = previewConnection
            val currentConnection = Agent3DevConnectionBinding.capture(baseUrl, token)
            val currentIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel)
            val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                previewDeadlineMillis,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReplanPreviewPolicy.shouldMarkExpired(current.previewId, previewFresh)) {
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
                    "Replan-previewet er udløbet eller mangler gyldig TTL. Lav et nyt preview."
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
            // The server may consume/commit this single-use Preview before a
            // usable response reaches us. Never leave the old token retryable.
            clearPreviewAuthority()
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { client(connection).applyReviewed(current) }
                }
                busy = false
                result.onSuccess {
                    applied = it
                }.onFailure {
                    val detail = it.message ?: "Replan kunne ikke anvendes"
                    error = "$detail. Preview-authority er forbrugt lokalt; lav et nyt preview før nyt forsøg."
                }
            }
        }

        LaunchedEffect(preview?.previewId, previewDeadlineMillis, previewIntent, previewConnection) {
            val currentPreview = preview ?: return@LaunchedEffect
            val deadline = previewDeadlineMillis
            val currentFresh = Agent3TaskUiPolicy.isPreviewFresh(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReplanPreviewPolicy.shouldMarkExpired(currentPreview.previewId, currentFresh)) {
                previewExpired = true
                applyArmed = false
                return@LaunchedEffect
            }
            if (!currentFresh) return@LaunchedEffect
            val remaining = requireNotNull(deadline) - (System.nanoTime() / 1_000_000L)
            if (remaining > 0L) delay(remaining)
            val freshAfterDelay = Agent3TaskUiPolicy.isPreviewFresh(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReplanPreviewPolicy.shouldMarkExpired(currentPreview.previewId, freshAfterDelay)) {
                previewExpired = true
                applyArmed = false
            }
        }

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
                        "Agent 3.0 Read Replanner",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Reviewed local read-replan · --agent3-replan",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                OutlinedButton(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            ReplanCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it; clearPreviewAuthority() },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it; clearPreviewAuthority() },
                    label = { Text("Device-token") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))
            ReplanCard {
                Text("Run", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
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
                    supportingText = { Text("Cloud-runs afvises før modelkald.") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && runId.isNotBlank() && baseUrl.isNotBlank() && token.isNotBlank(),
                    onClick = ::loadPreview,
                ) {
                    Text(if (busy) "Arbejder…" else "Lav read-replan-preview")
                }
                Text(
                    "Preview ændrer ikke runnet. Modellen ser kun completed observations, read-tool-kataloget og en redigeret immutable tail.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ReplanCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }

            preview?.let { current ->
                val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                    previewDeadlineMillis,
                    System.nanoTime() / 1_000_000L,
                )
                val showExpired = previewExpired || Agent3ReplanPreviewPolicy.shouldMarkExpired(
                    previewId = current.previewId,
                    previewFresh = previewFresh,
                )
                val applyAllowed = Agent3ReplanPreviewPolicy.canApply(
                    previewId = current.previewId,
                    previewRunId = current.runId,
                    previewFresh = previewFresh,
                    busy = busy,
                    currentIntent = Agent3ReplanPreviewIntent.capture(runId, plannerModel),
                    previewIntent = previewIntent,
                    currentConnection = Agent3DevConnectionBinding.capture(baseUrl, token),
                    previewConnection = previewConnection,
                )
                Spacer(Modifier.height(12.dp))
                ReplanPreviewCard(
                    preview = current,
                    busy = busy,
                    armed = applyArmed,
                    applyAllowed = applyAllowed,
                    expired = showExpired,
                    onApply = ::applyPreview,
                    onDisarm = { applyArmed = false },
                )
            }

            applied?.let {
                Spacer(Modifier.height(12.dp))
                AppliedReplanCard(it)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ReplanCard(content: @Composable ColumnScope.() -> Unit) {
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
private fun ReplanPreviewCard(
    preview: Agent3ReplanPreview,
    busy: Boolean,
    armed: Boolean,
    applyAllowed: Boolean,
    expired: Boolean,
    onApply: () -> Unit,
    onDisarm: () -> Unit,
) {
    ReplanCard {
        Text("Reviewed replan-preview", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(6.dp))
        ReplanValue("Revision", "${preview.revision} · replan #${preview.replanCount + 1}")
        ReplanValue("Udløb", "${preview.expiresInSeconds} sekunder")
        ReplanValue("Observationer", "${preview.observationCharacters} tegn")
        ReplanValue("Prompt SHA-256", preview.promptSha256)
        ReplanValue("Read-window", "${preview.window.start}..<${preview.window.end}")
        ReplanValue("Fjernes", preview.window.removableStepIds.joinToString().ifBlank { "ingen" })
        ReplanValue("Immutable tail", preview.window.immutableTailIds.joinToString().ifBlank { "ingen" })
        Spacer(Modifier.height(8.dp))
        Text(preview.rationale, color = KalivTheme.colors.TextHigh, fontSize = 13.sp)
        Spacer(Modifier.height(10.dp))
        if (preview.plan.isEmpty()) {
            Text("Forslaget fjerner alle resterende pending reads.", color = KalivTheme.colors.Amber)
        } else {
            preview.plan.forEachIndexed { index, step ->
                Column(
                    Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(8.dp))
                        .background(KalivTheme.colors.SurfaceHigh)
                        .padding(10.dp),
                ) {
                    Text("${index + 1}. ${step.tool}", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                    Text(step.summary, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                    Text("risk=${step.risk} · egress=${step.egress}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                    Text("args=${step.args}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
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
        when {
            expired -> Text(
                "Replan-previewet er udløbet eller mangler gyldig TTL. Lav et nyt preview.",
                color = KalivTheme.colors.Danger,
                fontSize = 11.sp,
            )
            !applyAllowed -> Text(
                "Apply er låst, fordi previewets opgave eller forbindelse ikke længere matcher.",
                color = KalivTheme.colors.Danger,
                fontSize = 11.sp,
            )
            armed -> Text(
                "Næste klik forbruger single-use-tokenet og ændrer kun det viste pending read-window. Runnet fortsættes ikke automatisk.",
                color = KalivTheme.colors.Amber,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun AppliedReplanCard(result: Agent3ReplanApplyResult) {
    val review = result.readReview
    ReplanCard {
        Text("Replan anvendt", color = KalivTheme.colors.Signal, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        ReplanValue("Run", result.run.id)
        ReplanValue("Run-state", result.run.state)
        ReplanValue("Revision", "${result.replan.fromRevision} → ${result.replan.toRevision}")
        ReplanValue("Fjernede tools", result.replan.removedTools.joinToString().ifBlank { "ingen" })
        ReplanValue("Tilføjede tools", result.replan.addedTools.joinToString().ifBlank { "ingen" })
        ReplanValue("Prompt SHA-256", result.preview.promptSha256)
        ReplanValue(
            "Read review",
            when {
                review.waiting -> "venter · ${review.windowStart}..<${review.windowEnd}"
                review.enabled -> "aktiv · intet ventende checkpoint"
                else -> "deaktiveret"
            },
        )
        if (review.waiting) {
            ReplanValue("Checkpoint reads", review.removableStepIds.joinToString())
        }
        Text(
            if (review.waiting) {
                "Revisionen er journalført. Runnet er fortsat pauset ved det re-bundne Read review-checkpoint; denne skærm genoptager ikke automatisk."
            } else {
                "Revisionen er journalført. Denne skærm starter eller genoptager ikke runnet automatisk."
            },
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun ReplanValue(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.TextHigh, fontSize = 11.sp)
    }
}

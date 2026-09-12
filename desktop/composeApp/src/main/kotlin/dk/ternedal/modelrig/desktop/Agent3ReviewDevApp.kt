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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.Agent3ReviewedStartRecoveryStore
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3Client
import dk.ternedal.modelrig.desktop.net.Agent3PlanPreview
import dk.ternedal.modelrig.desktop.net.Agent3ReadReview
import dk.ternedal.modelrig.desktop.net.Agent3ReviewedStartRecoveryAuthority
import dk.ternedal.modelrig.desktop.net.Agent3Run
import dk.ternedal.modelrig.desktop.net.shouldRetainReviewedStartRecovery
import dk.ternedal.modelrig.desktop.net.startReviewedPlanEnvelope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Isolated developer UI for reviewed read execution.
 *
 * It never resumes, replans, confirms, or cancels a run automatically. The only
 * mutating action is starting the exact single-use plan shown in the preview.
 */
@Composable
fun Agent3ReviewDevApp() {
    val db = remember { DesktopChatDb() }
    val recoveryStore = remember { Agent3ReviewedStartRecoveryStore(db) }
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
        var message by remember { mutableStateOf("") }
        var reviewReads by remember { mutableStateOf(false) }
        var preview by remember { mutableStateOf<Agent3PlanPreview?>(null) }
        var previewConnection by remember { mutableStateOf<Agent3DevConnectionBinding?>(null) }
        var previewIntent by remember { mutableStateOf<Agent3ReviewPreviewIntent?>(null) }
        var previewDeadlineMillis by remember { mutableStateOf<Long?>(null) }
        var previewExpired by remember { mutableStateOf(false) }
        var run by remember { mutableStateOf<Agent3Run?>(null) }
        var review by remember { mutableStateOf(Agent3ReadReview()) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }
        var pendingStartRecovery by remember {
            mutableStateOf(
                Agent3ReviewedStartRecoveryAuthority.decode(recoveryStore.read(baseUrl))
            )
        }

        LaunchedEffect(baseUrl) {
            val raw = recoveryStore.read(baseUrl)
            val decoded = Agent3ReviewedStartRecoveryAuthority.decode(raw)
            if (raw != null && decoded == null) {
                recoveryStore.write(baseUrl, null)
                error = "En ugyldig lokal Start-recovery blev ryddet; lav et nyt preview."
            }
            pendingStartRecovery = decoded
        }

        fun currentConnection(): Agent3DevConnectionBinding {
            return requireNotNull(Agent3DevConnectionBinding.capture(baseUrl, token)) {
                "Forbindelsen er ugyldig"
            }
        }

        fun client(connection: Agent3DevConnectionBinding): Agent3Client =
            Agent3Client(connection.baseUrl, connection.token)

        fun clearPreviewAuthority() {
            preview = null
            previewConnection = null
            previewIntent = null
            previewDeadlineMillis = null
            previewExpired = false
        }

        fun createPreview() {
            if (pendingStartRecovery != null) {
                error = "Et tidligere Start har uklart udfald. Gendan samme Start før et nyt preview."
                return
            }
            val requestIntent = Agent3ReviewPreviewIntent.capture(message, reviewReads) ?: return
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
            review = Agent3ReadReview()
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        client(connection).previewPlan(
                            message = requestIntent.message,
                            mode = "rig",
                            reviewReads = requestIntent.reviewReads,
                        )
                    }
                }
                busy = false
                result.onSuccess { planned ->
                    val currentIntent = Agent3ReviewPreviewIntent.capture(message, reviewReads)
                    if (!Agent3ReviewPreviewPolicy.canPublish(requestIntent, currentIntent)) {
                        error = "Preview blev forældet, fordi opgaven eller Read review ændrede sig"
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
                    previewExpired = Agent3ReviewPreviewPolicy.shouldMarkExpired(
                        planId = planned.planId,
                        planSize = planned.plan.size,
                        previewFresh = previewFresh,
                    )
                }.onFailure { error = it.message ?: "Plan-preview fejlede" }
            }
        }

        fun publishReviewedStart(
            envelope: dk.ternedal.modelrig.desktop.net.Agent3RunEnvelope,
            connection: Agent3DevConnectionBinding,
            authority: Agent3ReviewedStartRecoveryAuthority,
        ) {
            run = envelope.run
            review = envelope.readReview
            if (recoveryStore.write(connection.baseUrl, null)) {
                pendingStartRecovery = null
            } else {
                pendingStartRecovery = authority
                error = "Run blev valideret, men den lokale Start-recovery kunne ikke ryddes. Samme plan kan sikkert gendannes igen."
            }
        }

        fun publishReviewedStartFailure(
            failure: Throwable,
            connection: Agent3DevConnectionBinding,
            authority: Agent3ReviewedStartRecoveryAuthority,
        ) {
            val detail = failure.message ?: "Planen kunne ikke startes"
            if (!shouldRetainReviewedStartRecovery(failure)) {
                val cleared = recoveryStore.write(connection.baseUrl, null)
                if (cleared) pendingStartRecovery = null
                error = if (cleared) {
                    "$detail. Serveren afviste Start definitivt; lav et nyt preview."
                } else {
                    "$detail. Serveren afviste Start definitivt, men lokal recovery kunne ikke ryddes."
                }
                return
            }
            pendingStartRecovery = authority
            error = "$detail. Start-resultatet er uklart; brug Gendan samme Start i stedet for at lave et nyt preview."
        }

        fun recoverPendingStart() {
            if (busy || run != null) return
            val connection = runCatching { currentConnection() }
                .getOrElse {
                    error = it.message ?: "Forbindelsen er ugyldig"
                    return
                }
            val raw = recoveryStore.read(connection.baseUrl)
            val authority = Agent3ReviewedStartRecoveryAuthority.decode(raw)
            if (authority == null) {
                if (raw != null) recoveryStore.write(connection.baseUrl, null)
                pendingStartRecovery = null
                error = "Der er ingen gyldig Start-recovery for denne rig."
                return
            }
            pendingStartRecovery = authority
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        client(connection).startReviewedPlanEnvelope(
                            planId = authority.planId,
                            expectedReviewReads = authority.expectedReviewReads,
                            expectedCapabilityReceipt = authority.expectedCapabilityReceipt,
                        )
                    }
                }
                busy = false
                result.onSuccess { publishReviewedStart(it, connection, authority) }
                    .onFailure { publishReviewedStartFailure(it, connection, authority) }
            }
        }

        fun startPreview() {
            val reviewedPreview = preview ?: return
            val boundConnection = previewConnection
            val currentConnection = Agent3DevConnectionBinding.capture(baseUrl, token)
            val currentIntent = Agent3ReviewPreviewIntent.capture(message, reviewReads)
            val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                previewDeadlineMillis,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReviewPreviewPolicy.shouldMarkExpired(
                    planId = reviewedPreview.planId,
                    planSize = reviewedPreview.plan.size,
                    previewFresh = previewFresh,
                )
            ) {
                previewExpired = true
            }
            if (!Agent3ReviewPreviewPolicy.canStart(
                    planId = reviewedPreview.planId,
                    planSize = reviewedPreview.plan.size,
                    previewFresh = previewFresh,
                    busy = busy,
                    currentConnection = currentConnection,
                    previewConnection = boundConnection,
                    currentIntent = currentIntent,
                    previewIntent = previewIntent,
                )
            ) return
            if (pendingStartRecovery != null) return
            val planId = reviewedPreview.planId ?: return
            val connection = boundConnection ?: return
            val authority = Agent3ReviewedStartRecoveryAuthority.capture(
                planId = planId,
                expectedReviewReads = reviewedPreview.reviewReads,
                expectedCapabilityReceipt = reviewedPreview.capabilityReceipt,
            ) ?: run {
                error = "Det reviewede preview kunne ikke bindes til en sikker Start-recovery."
                return
            }
            if (!recoveryStore.write(connection.baseUrl, authority.encode())) {
                error = "Start blev ikke sendt, fordi recovery-authority ikke kunne gemmes sikkert lokalt."
                return
            }
            pendingStartRecovery = authority
            busy = true
            error = null
            clearPreviewAuthority()
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        client(connection).startReviewedPlanEnvelope(
                            planId = authority.planId,
                            expectedReviewReads = authority.expectedReviewReads,
                            expectedCapabilityReceipt = authority.expectedCapabilityReceipt,
                        )
                    }
                }
                busy = false
                result.onSuccess { publishReviewedStart(it, connection, authority) }
                    .onFailure { publishReviewedStartFailure(it, connection, authority) }
            }
        }

        LaunchedEffect(preview?.planId, previewDeadlineMillis, previewIntent, previewConnection) {
            val currentPreview = preview ?: return@LaunchedEffect
            val deadline = previewDeadlineMillis
            val currentFresh = Agent3TaskUiPolicy.isPreviewFresh(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReviewPreviewPolicy.shouldMarkExpired(
                    planId = currentPreview.planId,
                    planSize = currentPreview.plan.size,
                    previewFresh = currentFresh,
                )
            ) {
                previewExpired = true
                return@LaunchedEffect
            }
            if (!currentFresh) return@LaunchedEffect
            val remaining = requireNotNull(deadline) - (System.nanoTime() / 1_000_000L)
            if (remaining > 0L) delay(remaining)
            val freshAfterDelay = Agent3TaskUiPolicy.isPreviewFresh(
                deadline,
                System.nanoTime() / 1_000_000L,
            )
            if (Agent3ReviewPreviewPolicy.shouldMarkExpired(
                    planId = currentPreview.planId,
                    planSize = currentPreview.plan.size,
                    previewFresh = freshAfterDelay,
                )
            ) {
                previewExpired = true
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
                        "Agent 3.0 · Read review",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 27.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Developer-only · --agent3-review · ingen automatisk resume",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                OutlinedButton(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            ReviewCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("Device-token") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))
            ReviewCard {
                Text("Plan", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it; clearPreviewAuthority() },
                    label = { Text("Forespørgsel") },
                    minLines = 3,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    if (reviewReads) {
                        Button(onClick = { reviewReads = false; clearPreviewAuthority() }) {
                            Text("Read review: til")
                        }
                    } else {
                        OutlinedButton(onClick = { reviewReads = true; clearPreviewAuthority() }) {
                            Text("Read review: fra")
                        }
                    }
                    Text(
                        if (reviewReads) "Run stopper mellem read-steps."
                        else "Standardflowet kører sammenhængende reads.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy && message.isNotBlank() && pendingStartRecovery == null, onClick = ::createPreview) {
                    Text(if (busy) "Arbejder…" else "Lav preview")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ReviewCard { Text(it, color = KalivTheme.colors.Danger) }
            }

            pendingStartRecovery?.let { authority ->
                Spacer(Modifier.height(12.dp))
                ReviewCard {
                    Text("Uafklaret Start", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Text(
                        "plan=${authority.planId} · review_reads=${authority.expectedReviewReads}",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                    Text(
                        "Kun samme plan-id gendannes. Serveren må ikke oprette et nyt run.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                    Spacer(Modifier.height(8.dp))
                    Button(enabled = !busy && run == null, onClick = ::recoverPendingStart) {
                        Text(if (busy) "Arbejder…" else "Gendan samme Start")
                    }
                }
            }

            preview?.let { plan ->
                val previewFresh = Agent3TaskUiPolicy.isPreviewFresh(
                    previewDeadlineMillis,
                    System.nanoTime() / 1_000_000L,
                )
                val showExpired = previewExpired || Agent3ReviewPreviewPolicy.shouldMarkExpired(
                    planId = plan.planId,
                    planSize = plan.plan.size,
                    previewFresh = previewFresh,
                )
                Spacer(Modifier.height(12.dp))
                ReviewCard {
                    Text("Server-preview", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Text(
                        "review_reads=${plan.reviewReads} · steps=${plan.plan.size}",
                        color = if (plan.reviewReads) KalivTheme.colors.Signal else KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    plan.plan.forEachIndexed { index, step ->
                        Spacer(Modifier.height(6.dp))
                        Text(
                            "${index + 1}. ${step.tool} · ${step.risk}",
                            color = KalivTheme.colors.TextHigh,
                            fontSize = 13.sp,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = Agent3ReviewPreviewPolicy.canStart(
                            planId = plan.planId,
                            planSize = plan.plan.size,
                            previewFresh = previewFresh,
                            busy = busy,
                            currentConnection = Agent3DevConnectionBinding.capture(baseUrl, token),
                            previewConnection = previewConnection,
                            currentIntent = Agent3ReviewPreviewIntent.capture(message, reviewReads),
                            previewIntent = previewIntent,
                        ),
                        onClick = ::startPreview,
                    ) { Text("Start den viste single-use plan") }
                    if (showExpired) {
                        Text(
                            "Plan-previewet er udløbet eller mangler gyldig TTL. Lav et nyt preview.",
                            color = KalivTheme.colors.Danger,
                            fontSize = 11.sp,
                        )
                    } else {
                        plan.expiresInSeconds?.let {
                            Text(
                                "Plan-id udløber om ca. $it sek.",
                                color = KalivTheme.colors.TextMuted,
                                fontSize = 11.sp,
                            )
                        }
                    }
                }
            }

            run?.let { current ->
                Spacer(Modifier.height(12.dp))
                ReviewCard {
                    Text("Run checkpoint", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.Bold)
                    Text(
                        "state=${current.state} · current_step=${current.currentStep}",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    Text(
                        "review enabled=${review.enabled} · waiting=${review.waiting}",
                        color = if (review.waiting) KalivTheme.colors.Amber else KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                    if (review.waiting) {
                        Text(
                            "completed=${review.completedTool ?: "ukendt"} · window=${review.windowStart}..${review.windowEnd}",
                            color = KalivTheme.colors.TextHigh,
                            fontSize = 12.sp,
                        )
                        Text(
                            "removable ids: ${review.removableStepIds.joinToString(", ")}",
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 10.sp,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Denne skærm genoptager eller replanner ikke automatisk. Brug den separate reviewed replanner til næste beslutning.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
            }

            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ReviewCard(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(KalivTheme.colors.Surface)
            .padding(14.dp),
        content = content,
    )
}

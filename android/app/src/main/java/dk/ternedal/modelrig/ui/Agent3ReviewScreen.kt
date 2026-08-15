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
import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

/** Developer-only reviewed-read UI. It never resumes or replans automatically. */
@Composable
fun Agent3ReviewScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var message by remember { mutableStateOf("") }
    var reviewReads by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<Agent3Client.PlanPreview?>(null) }
    var run by remember { mutableStateOf<Agent3Client.Run?>(null) }
    var review by remember { mutableStateOf<Agent3Client.ReadReview?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var resultBody by remember { mutableStateOf<String?>(null) }
    var replanPreview by remember { mutableStateOf<dk.ternedal.modelrig.net.Agent3ReplanClient.Preview?>(null) }

    fun client(): Agent3Client {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return Agent3Client(base, token)
    }

    fun createPreview() {
        val text = message.trim()
        if (text.isEmpty() || busy) return
        busy = true
        error = null
        run = null
        review = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    client().previewPlan(
                        message = text,
                        mode = "rig",
                        reviewReads = reviewReads,
                    )
                }
            }
            busy = false
            result.onSuccess { preview = it }
                .onFailure { error = it.message ?: "Plan-preview fejlede" }
        }
    }

    fun startPreview() {
        val planId = preview?.planId ?: return
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client().startPlanEnvelope(planId) }
            }
            busy = false
            result.onSuccess {
                run = it.run
                review = it.readReview
            }.onFailure { error = it.message ?: "Planen kunne ikke startes" }
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
                        "Agent 3.0 · Read review",
                        fontSize = 25.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Developer-only · ingen automatisk resume",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            ReviewSurface {
                Text("Plan", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it; preview = null },
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
                    if (reviewReads) {
                        Button(onClick = { reviewReads = false; preview = null }) {
                            Text("Read review: til")
                        }
                    } else {
                        OutlinedButton(onClick = { reviewReads = true; preview = null }) {
                            Text("Read review: fra")
                        }
                    }
                }
                Text(
                    if (reviewReads) "Run stopper mellem read-steps."
                    else "Standardflowet kører sammenhængende reads.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy && message.isNotBlank(), onClick = { createPreview() }) {
                    Text(if (busy) "Arbejder…" else "Lav preview")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ReviewSurface { Text(it, color = KalivTheme.colors.danger) }
            }

            preview?.let { plan ->
                Spacer(Modifier.height(12.dp))
                ReviewSurface {
                    Text("Server-preview", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                    Text(
                        "review_reads=${plan.reviewReads} · steps=${plan.steps.size}",
                        color = if (plan.reviewReads) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    plan.steps.forEachIndexed { index, step ->
                        Text(
                            "${index + 1}. ${step.tool} · ${step.risk}",
                            color = KalivTheme.colors.textHigh,
                            fontSize = 13.sp,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    Button(
                        enabled = !busy && plan.planId != null && plan.steps.isNotEmpty(),
                        onClick = { startPreview() },
                    ) { Text("Start den viste single-use plan") }
                }
            }

            run?.let { current ->
                val checkpoint = review
                Spacer(Modifier.height(16.dp))
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 2.dp, vertical = 2.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text(
                        "Agent 3 \u00b7 run",
                        color = KalivTheme.colors.textHigh,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 20.sp,
                        modifier = Modifier.weight(1f),
                    )
                    if (checkpoint?.enabled == true) {
                        dk.ternedal.modelrig.ui.chat.Agent3ReviewBadge()
                    }
                }
                Spacer(Modifier.height(10.dp))
                dk.ternedal.modelrig.ui.chat.Agent3RunHeader(
                    task = message.ifBlank { "Kørsel ${current.id}" },
                    waitingLine = when {
                        checkpoint?.waiting == true && checkpoint.completedTool != null ->
                            "Checkpoint efter ${checkpoint.completedTool} \u00b7 venter på dig"
                        checkpoint?.waiting == true -> "Checkpoint \u00b7 venter på dig"
                        else -> "Tilstand: ${current.state} \u00b7 trin ${current.currentStep}"
                    },
                    modifier = Modifier.padding(horizontal = 0.dp),
                )
                Spacer(Modifier.height(12.dp))
                current.steps.forEachIndexed { index, step ->
                    val stepNo = index + 1
                    val isWrite = step.risk.lowercase().contains("write") ||
                        step.tool.lowercase().startsWith("write") ||
                        step.egress.lowercase() == "write"
                    val done = step.state?.lowercase() in setOf("done", "completed", "succeeded")
                    val active = checkpoint?.waiting == true && step.id != null &&
                        step.id == checkpoint.completedStepId
                    val kind = when {
                        active || done -> dk.ternedal.modelrig.ui.chat.Agent3StepKind.Done
                        isWrite -> dk.ternedal.modelrig.ui.chat.Agent3StepKind.WriteLocked
                        stepNo == current.currentStep -> dk.ternedal.modelrig.ui.chat.Agent3StepKind.Active
                        else -> dk.ternedal.modelrig.ui.chat.Agent3StepKind.Pending
                    }
                    dk.ternedal.modelrig.ui.chat.Agent3StepRow(
                        kind = kind,
                        title = (if (isWrite) "Write \u00b7 " else "Read \u00b7 ") + step.tool,
                        sub = when {
                            active -> "Udført \u00b7 resultat klar til gennemsyn"
                            done -> "Udført"
                            isWrite -> "Immutabel write-tail \u00b7 kræver separat bekræftelse"
                            else -> "Pending"
                        },
                        removable = step.id != null && checkpoint?.removableStepIds?.contains(step.id) == true,
                    )
                }
                if (checkpoint?.waiting == true && checkpoint.windowStart != null && checkpoint.windowEnd != null) {
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Read-window \u00b7 trin ${checkpoint.windowStart}\u2013${checkpoint.windowEnd} \u00b7 runnet er pauset her",
                        color = KalivTheme.colors.caps,
                        fontSize = 13.sp,
                    )
                }
                resultBody?.let { body ->
                    Spacer(Modifier.height(13.dp))
                    dk.ternedal.modelrig.ui.chat.Agent3ResultCard(
                        toolCaps = (checkpoint?.completedTool ?: "read").uppercase(),
                        body = body,
                    )
                }
                replanPreview?.let { rp ->
                    Spacer(Modifier.height(13.dp))
                    dk.ternedal.modelrig.ui.chat.Agent3ResultCard(
                        toolCaps = "REPLAN-PREVIEW",
                        body = "${rp.plan.size} trin foreslået \u00b7 vindue ${rp.window.start}\u2013${rp.window.end} " +
                            "\u00b7 udløber om ${rp.expiresInSeconds}s\n${rp.rationale}\n" +
                            "Anvend sker på replan-skærmen \u2014 kræver separat bekræftelse.",
                    )
                }
                if (checkpoint?.waiting == true) {
                    Spacer(Modifier.height(14.dp))
                    dk.ternedal.modelrig.ui.chat.Agent3CheckpointActions(
                        busy = busy,
                        onContinue = {
                            busy = true
                            scope.launch {
                                val res = withContext(Dispatchers.IO) { runCatching { client().resume(current.id) } }
                                res.onSuccess {
                                    run = it
                                    resultBody = null
                                    replanPreview = null
                                    error = null
                                }.onFailure { error = it.message }
                                val fresh = withContext(Dispatchers.IO) { runCatching { client().getRun(current.id) } }
                                fresh.onSuccess { run = it }
                                busy = false
                            }
                        },
                        onReplan = {
                            busy = true
                            scope.launch {
                                val res = withContext(Dispatchers.IO) {
                                    runCatching {
                                        dk.ternedal.modelrig.net.Agent3ReplanClient(
                                            store.baseUrl.orEmpty(), store.token.orEmpty(),
                                        ).preview(current.id)
                                    }
                                }
                                res.onSuccess { replanPreview = it; error = null }
                                    .onFailure { error = it.message }
                                busy = false
                            }
                        },
                        onStop = {
                            busy = true
                            scope.launch {
                                val res = withContext(Dispatchers.IO) { runCatching { client().cancel(current.id) } }
                                res.onSuccess { run = it; error = null }.onFailure { error = it.message }
                                busy = false
                            }
                        },
                    )
                }
            }

            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ReviewSurface(content: @Composable () -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) { content() }
    }
}

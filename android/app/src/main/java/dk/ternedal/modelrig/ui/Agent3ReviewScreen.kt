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
                Spacer(Modifier.height(12.dp))
                ReviewSurface {
                    Text("Run checkpoint", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                    Text(
                        "state=${current.state} · current_step=${current.currentStep}",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    val checkpoint = review
                    Text(
                        "review enabled=${checkpoint?.enabled == true} · waiting=${checkpoint?.waiting == true}",
                        color = if (checkpoint?.waiting == true) KalivTheme.colors.amber else KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    if (checkpoint?.waiting == true) {
                        Text(
                            "completed=${checkpoint.completedTool ?: "ukendt"} · window=${checkpoint.windowStart}..${checkpoint.windowEnd}",
                            color = KalivTheme.colors.textHigh,
                            fontSize = 12.sp,
                        )
                        Text(
                            "removable ids: ${checkpoint.removableStepIds.joinToString(", ")}",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 10.sp,
                        )
                    }
                    Spacer(Modifier.height(8.dp))
                    Text(
                        "Skærmen genoptager eller replanner ikke automatisk.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 11.sp,
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

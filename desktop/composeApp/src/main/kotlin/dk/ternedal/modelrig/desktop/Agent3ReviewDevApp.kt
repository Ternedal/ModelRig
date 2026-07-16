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
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3Client
import dk.ternedal.modelrig.desktop.net.Agent3PlanPreview
import dk.ternedal.modelrig.desktop.net.Agent3ReadReview
import dk.ternedal.modelrig.desktop.net.Agent3Run
import kotlinx.coroutines.Dispatchers
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
        var run by remember { mutableStateOf<Agent3Run?>(null) }
        var review by remember { mutableStateOf(Agent3ReadReview()) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun client(): Agent3Client {
            require(baseUrl.isNotBlank()) { "Base-URL mangler" }
            require(token.isNotBlank()) { "Device-token mangler" }
            return Agent3Client(baseUrl.trim(), token.trim())
        }

        fun createPreview() {
            val text = message.trim()
            if (text.isEmpty() || busy) return
            busy = true
            error = null
            run = null
            review = Agent3ReadReview()
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
                    onValueChange = { message = it; preview = null },
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
                        Button(onClick = { reviewReads = false; preview = null }) {
                            Text("Read review: til")
                        }
                    } else {
                        OutlinedButton(onClick = { reviewReads = true; preview = null }) {
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
                Button(enabled = !busy && message.isNotBlank(), onClick = ::createPreview) {
                    Text(if (busy) "Arbejder…" else "Lav preview")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ReviewCard { Text(it, color = KalivTheme.colors.Danger) }
            }

            preview?.let { plan ->
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
                        enabled = !busy && plan.planId != null && plan.plan.isNotEmpty(),
                        onClick = ::startPreview,
                    ) { Text("Start den viste single-use plan") }
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

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
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3ReplanApplyResult
import dk.ternedal.modelrig.desktop.net.Agent3ReplanClient
import dk.ternedal.modelrig.desktop.net.Agent3ReplanPreview
import kotlinx.coroutines.Dispatchers
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
        var applied by remember { mutableStateOf<Agent3ReplanApplyResult?>(null) }
        var applyArmed by remember { mutableStateOf(false) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun client(): Agent3ReplanClient {
            require(baseUrl.isNotBlank()) { "Base-URL mangler" }
            require(token.isNotBlank()) { "Device-token mangler" }
            return Agent3ReplanClient(baseUrl.trim(), token.trim())
        }

        fun loadPreview() {
            val id = runId.trim()
            if (busy || id.isEmpty()) return
            busy = true
            error = null
            preview = null
            applied = null
            applyArmed = false
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        client().preview(
                            id,
                            plannerModel.trim().takeIf { it.isNotEmpty() },
                        )
                    }
                }
                busy = false
                result.onSuccess { preview = it }
                    .onFailure { error = it.message ?: "Replan-preview fejlede" }
            }
        }

        fun applyPreview() {
            val current = preview ?: return
            if (busy) return
            if (!applyArmed) {
                applyArmed = true
                return
            }
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { client().apply(current.previewId) }
                }
                busy = false
                applyArmed = false
                result.onSuccess {
                    applied = it
                    preview = null
                }.onFailure { error = it.message ?: "Replan kunne ikke anvendes" }
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
                    onValueChange = { baseUrl = it; preview = null; applyArmed = false },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it; preview = null; applyArmed = false },
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
                    onValueChange = { runId = it; preview = null; applied = null; applyArmed = false },
                    label = { Text("AgentRun-id") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = plannerModel,
                    onValueChange = { plannerModel = it; preview = null; applyArmed = false },
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
                Spacer(Modifier.height(12.dp))
                ReplanPreviewCard(current, busy, applyArmed, ::applyPreview) {
                    applyArmed = false
                }
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
            Button(enabled = !busy, onClick = onApply) {
                Text(if (armed) "Bekræft apply" else "Armér apply")
            }
            if (armed) {
                OutlinedButton(enabled = !busy, onClick = onDisarm) { Text("Fortryd") }
            }
        }
        if (armed) {
            Text(
                "Næste klik forbruger single-use-tokenet og ændrer kun det viste pending read-window. Runnet fortsættes ikke automatisk.",
                color = KalivTheme.colors.Amber,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun AppliedReplanCard(result: Agent3ReplanApplyResult) {
    ReplanCard {
        Text("Replan anvendt", color = KalivTheme.colors.Signal, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        ReplanValue("Run", result.run.id)
        ReplanValue("Run-state", result.run.state)
        ReplanValue("Revision", "${result.replan.fromRevision} → ${result.replan.toRevision}")
        ReplanValue("Fjernede tools", result.replan.removedTools.joinToString().ifBlank { "ingen" })
        ReplanValue("Tilføjede tools", result.replan.addedTools.joinToString().ifBlank { "ingen" })
        ReplanValue("Prompt SHA-256", result.preview.promptSha256)
        Text(
            "Revisionen er journalført. Denne skærm starter eller genoptager ikke runnet automatisk.",
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

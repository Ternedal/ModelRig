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
import dk.ternedal.modelrig.net.Agent3ReplanClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only reviewed read-replan UI. Normal AppUi is untouched. */
@Composable
fun Agent3ReplanScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var runId by remember { mutableStateOf("") }
    var plannerModel by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3ReplanClient.Preview?>(null) }
    var applied by remember { mutableStateOf<Agent3ReplanClient.ApplyResult?>(null) }
    var applyArmed by remember { mutableStateOf(false) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun client(): Agent3ReplanClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return Agent3ReplanClient(base, token)
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
                Spacer(Modifier.height(12.dp))
                ReplanPreviewSurface(
                    current,
                    busy,
                    applyArmed,
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
            Button(enabled = !busy, onClick = onApply) {
                Text(if (armed) "Bekræft apply" else "Armér apply")
            }
            if (armed) {
                OutlinedButton(enabled = !busy, onClick = onDisarm) { Text("Fortryd") }
            }
        }
        if (armed) {
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

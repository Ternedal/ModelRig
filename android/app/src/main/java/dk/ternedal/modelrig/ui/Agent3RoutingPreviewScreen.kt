package dk.ternedal.modelrig.ui

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
import androidx.compose.material3.Checkbox
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
import dk.ternedal.modelrig.net.Agent3RoutingPreviewClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only, read-only preview of future Agent 3.0 routing eligibility. */
@Composable
fun Agent3RoutingPreviewScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var message by remember { mutableStateOf("") }
    var mode by remember { mutableStateOf("rig") }
    var tools by remember { mutableStateOf(true) }
    var rag by remember { mutableStateOf(false) }
    var hasImage by remember { mutableStateOf(false) }
    var voice by remember { mutableStateOf(false) }
    var allowRagCloud by remember { mutableStateOf(false) }
    var autoCloudFallback by remember { mutableStateOf(false) }
    var preview by remember { mutableStateOf<Agent3RoutingPreviewClient.Preview?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun client(): Agent3RoutingPreviewClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return Agent3RoutingPreviewClient(base, token)
    }

    fun clearResult() {
        preview = null
        error = null
    }

    fun analyze() {
        if (busy || message.isBlank()) return
        busy = true
        error = null
        preview = null
        val request = Agent3RoutingPreviewClient.RequestInput(
            message = message,
            mode = mode,
            tools = tools,
            rag = rag,
            hasImage = hasImage,
            voice = voice,
            allowRagCloud = allowRagCloud,
            autoCloudFallback = autoCloudFallback,
        )
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client().preview(request) }
            }
            busy = false
            result.onSuccess { preview = it }
                .onFailure { error = it.message ?: "Routing-preview kunne ikke hentes" }
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
                        "Agent 3.0 Routing Preview",
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Read-only kandidatvurdering · ingen routingændring",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            RoutingPreviewSurface {
                Text("Turn", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it.take(20_000); clearResult() },
                    label = { Text("Besked") },
                    minLines = 3,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedButton(onClick = { mode = "rig"; clearResult() }) {
                        Text(if (mode == "rig") "✓ Rig" else "Rig")
                    }
                    OutlinedButton(onClick = { mode = "cloud"; clearResult() }) {
                        Text(if (mode == "cloud") "✓ Cloud" else "Cloud")
                    }
                }
                RoutingPreviewOption("Tools", tools) { tools = it; clearResult() }
                RoutingPreviewOption("RAG", rag) { rag = it; clearResult() }
                RoutingPreviewOption("Billede", hasImage) { hasImage = it; clearResult() }
                RoutingPreviewOption("Voice", voice) { voice = it; clearResult() }
                RoutingPreviewOption("Tillad cloud-RAG", allowRagCloud) {
                    allowRagCloud = it
                    clearResult()
                }
                RoutingPreviewOption("Automatisk cloud fallback", autoCloudFallback) {
                    autoCloudFallback = it
                    clearResult()
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "Serveren returnerer kun den mulige Agent 3.0-kandidat. Faktisk surface forbliver " +
                        "Agent v2, og kaldet planlægger eller eksekverer intet.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy && message.isNotBlank(), onClick = ::analyze) {
                    Text(if (busy) "Analyserer…" else "Analysér routing")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                RoutingPreviewSurface {
                    Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp)
                }
            }

            preview?.let {
                Spacer(Modifier.height(12.dp))
                RoutingPreviewResultCard(it)
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun RoutingPreviewSurface(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), content = content)
    }
}

@Composable
private fun RoutingPreviewOption(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(label, color = KalivTheme.colors.textHigh, fontSize = 12.sp)
    }
}

@Composable
private fun RoutingPreviewResultCard(preview: Agent3RoutingPreviewClient.Preview) {
    val eligible = preview.eligibleForAgent3Preview
    RoutingPreviewSurface {
        Text(
            if (eligible) "Agent 3.0 developer-preview kandidat" else "Forbliver på Agent v2",
            color = if (eligible) KalivTheme.colors.success else KalivTheme.colors.amber,
            fontSize = 18.sp,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(8.dp))
        RoutingPreviewValue("Faktisk surface", preview.selectedSurface)
        RoutingPreviewValue("Kandidat", preview.candidateSurface ?: "ingen")
        RoutingPreviewValue("Route", preview.route.kind)
        RoutingPreviewValue("Begrundelse", preview.route.reason)
        RoutingPreviewValue("Beskedtegn", preview.messageCharacters.toString())
        RoutingPreviewValue("Message SHA-256", preview.messageSha256)
        RoutingPreviewGate("Faktisk surface uændret", preview.proofs.actualSurfaceUnchanged)
        RoutingPreviewGate("Developer-evidens", preview.proofs.developerPreviewEvidence)
        RoutingPreviewGate("Ingen planlægning", !preview.planned)
        RoutingPreviewGate("Ingen eksekvering", !preview.executed)
        RoutingPreviewGate("Produktion låst", !preview.productionActivation)
    }

    if (preview.requiredCapabilities.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        RoutingPreviewSurface {
            Text("Påkrævede capabilities", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            preview.requiredCapabilities.forEach {
                Text("• $it", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
            }
        }
    }

    if (preview.blockers.isNotEmpty() || preview.warnings.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        RoutingPreviewSurface {
            Text("Blockers og advarsler", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            preview.blockers.distinct().forEach {
                Text("• $it", color = KalivTheme.colors.danger, fontSize = 11.sp)
            }
            preview.warnings.distinct().forEach {
                Text("• $it", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun RoutingPreviewValue(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp)
    }
}

@Composable
private fun RoutingPreviewGate(label: String, passed: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(
            if (passed) "OK" else "NEJ",
            color = if (passed) KalivTheme.colors.success else KalivTheme.colors.danger,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

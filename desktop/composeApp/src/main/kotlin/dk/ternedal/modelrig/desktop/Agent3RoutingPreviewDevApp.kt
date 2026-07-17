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
import androidx.compose.material3.Checkbox
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
import dk.ternedal.modelrig.desktop.net.Agent3RoutingPreview
import dk.ternedal.modelrig.desktop.net.Agent3RoutingPreviewClient
import dk.ternedal.modelrig.desktop.net.Agent3RoutingPreviewRequest
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only, read-only preview of future Agent 3.0 routing eligibility. */
@Composable
fun Agent3RoutingPreviewDevApp() {
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
        var mode by remember { mutableStateOf("rig") }
        var tools by remember { mutableStateOf(true) }
        var rag by remember { mutableStateOf(false) }
        var hasImage by remember { mutableStateOf(false) }
        var voice by remember { mutableStateOf(false) }
        var allowRagCloud by remember { mutableStateOf(false) }
        var autoCloudFallback by remember { mutableStateOf(false) }
        var preview by remember { mutableStateOf<Agent3RoutingPreview?>(null) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun clearResult() {
            preview = null
            error = null
        }

        fun analyze() {
            if (busy || baseUrl.isBlank() || token.isBlank() || message.isBlank()) return
            busy = true
            error = null
            preview = null
            val request = Agent3RoutingPreviewRequest(
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
                    runCatching {
                        Agent3RoutingPreviewClient(baseUrl.trim(), token.trim()).preview(request)
                    }
                }
                busy = false
                result.onSuccess { preview = it }
                    .onFailure { error = it.message ?: "Routing-preview kunne ikke hentes" }
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
                        "Agent 3.0 Routing Preview",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Read-only kandidatvurdering · --agent3-routing-preview",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                Button(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            RoutingPreviewCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it; clearResult() },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it; clearResult() },
                    label = { Text("Device-token") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            Spacer(Modifier.height(12.dp))
            RoutingPreviewCard {
                Text("Turn", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
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
                    Button(onClick = { mode = "rig"; clearResult() }) {
                        Text(if (mode == "rig") "✓ Rig" else "Rig")
                    }
                    Button(onClick = { mode = "cloud"; clearResult() }) {
                        Text(if (mode == "cloud") "✓ Cloud" else "Cloud")
                    }
                }
                RoutingOption("Tools", tools) { tools = it; clearResult() }
                RoutingOption("RAG", rag) { rag = it; clearResult() }
                RoutingOption("Billede", hasImage) { hasImage = it; clearResult() }
                RoutingOption("Voice", voice) { voice = it; clearResult() }
                RoutingOption("Tillad cloud-RAG", allowRagCloud) {
                    allowRagCloud = it
                    clearResult()
                }
                RoutingOption("Automatisk cloud fallback", autoCloudFallback) {
                    autoCloudFallback = it
                    clearResult()
                }
                Spacer(Modifier.height(8.dp))
                Text(
                    "Kaldet viser kun den serverautoritative kandidat. Det starter ikke planner, run eller tools, " +
                        "og faktisk surface forbliver Agent v2.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && baseUrl.isNotBlank() && token.isNotBlank() && message.isNotBlank(),
                    onClick = ::analyze,
                ) {
                    Text(if (busy) "Analyserer…" else "Analysér routing")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                RoutingPreviewCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }

            preview?.let {
                Spacer(Modifier.height(12.dp))
                RoutingPreviewResult(it)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun RoutingPreviewCard(content: @Composable ColumnScope.() -> Unit) {
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
private fun RoutingOption(label: String, checked: Boolean, onChange: (Boolean) -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Checkbox(checked = checked, onCheckedChange = onChange)
        Text(label, color = KalivTheme.colors.TextHigh, fontSize = 12.sp)
    }
}

@Composable
private fun RoutingPreviewResult(preview: Agent3RoutingPreview) {
    val eligible = preview.eligibleForAgent3Preview
    RoutingPreviewCard {
        Text(
            if (eligible) "Agent 3.0 developer-preview kandidat" else "Forbliver på Agent v2",
            color = if (eligible) KalivTheme.colors.Signal else KalivTheme.colors.Amber,
            fontSize = 19.sp,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(8.dp))
        RoutingValue("Faktisk surface", preview.selectedSurface)
        RoutingValue("Kandidat", preview.candidateSurface ?: "ingen")
        RoutingValue("Route", preview.route.kind)
        RoutingValue("Begrundelse", preview.route.reason)
        RoutingValue("Beskedtegn", preview.messageCharacters.toString())
        RoutingValue("Message SHA-256", preview.messageSha256)
        RoutingGate("Faktisk surface uændret", preview.proofs.actualSurfaceUnchanged)
        RoutingGate("Developer-evidens", preview.proofs.developerPreviewEvidence)
        RoutingGate("Ingen planlægning", !preview.planned)
        RoutingGate("Ingen eksekvering", !preview.executed)
        RoutingGate("Produktion låst", !preview.productionActivation)
    }

    if (preview.requiredCapabilities.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        RoutingPreviewCard {
            Text("Påkrævede capabilities", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
            preview.requiredCapabilities.forEach {
                Text("• $it", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            }
        }
    }

    if (preview.blockers.isNotEmpty() || preview.warnings.isNotEmpty()) {
        Spacer(Modifier.height(12.dp))
        RoutingPreviewCard {
            Text("Blockers og advarsler", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
            preview.blockers.distinct().forEach {
                Text("• $it", color = KalivTheme.colors.Danger, fontSize = 11.sp)
            }
            preview.warnings.distinct().forEach {
                Text("• $it", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun RoutingValue(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.TextHigh, fontSize = 11.sp)
    }
}

@Composable
private fun RoutingGate(label: String, passed: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(
            if (passed) "OK" else "NEJ",
            color = if (passed) KalivTheme.colors.Signal else KalivTheme.colors.Danger,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

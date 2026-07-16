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
import dk.ternedal.modelrig.desktop.net.Agent3CapabilityClient
import dk.ternedal.modelrig.desktop.net.Agent3CapabilityGraph
import dk.ternedal.modelrig.desktop.net.Agent3CapabilityNode
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only, read-only view of the server-authoritative Capability Graph. */
@Composable
fun Agent3CapabilityDevApp() {
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
        var graph by remember { mutableStateOf<Agent3CapabilityGraph?>(null) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun refresh() {
            if (busy || baseUrl.isBlank() || token.isBlank()) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { Agent3CapabilityClient(baseUrl.trim(), token.trim()).graph() }
                }
                busy = false
                result.onSuccess { graph = it }
                    .onFailure { error = it.message ?: "Capability Graph kunne ikke hentes" }
            }
        }

        LaunchedEffect(Unit) {
            if (baseUrl.isNotBlank() && token.isNotBlank()) refresh()
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
                        "Agent 3.0 Capability Graph",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Read-only runtimekort · --agent3-capabilities",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                Button(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            CapabilityCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it; graph = null },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it; graph = null },
                    label = { Text("Device-token") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Skærmen udfører kun GET /api/v1/experimental/agent3/capabilities. " +
                        "Grafen kan ikke route, aktivere tools eller promovere Agent 3.0.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && baseUrl.isNotBlank() && token.isNotBlank(),
                    onClick = ::refresh,
                ) {
                    Text(if (busy) "Henter…" else "Opdatér graf")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                CapabilityCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }

            graph?.let { value ->
                Spacer(Modifier.height(12.dp))
                CapabilitySummary(value)
                value.nodes.groupBy { it.kind }.toSortedMap().forEach { (kind, nodes) ->
                    Spacer(Modifier.height(12.dp))
                    CapabilityGroup(kind, nodes)
                }
                Spacer(Modifier.height(12.dp))
                CapabilityCard {
                    Text("Afhængigheder", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(8.dp))
                    value.edges.forEach { edge ->
                        Text(
                            "${edge.source} → ${edge.target} (${edge.relation})",
                            color = KalivTheme.colors.TextMuted,
                            fontSize = 10.sp,
                        )
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun CapabilitySummary(graph: Agent3CapabilityGraph) {
    val ready = graph.nodes.count { it.state == "ready" }
    val blocked = graph.nodes.count { it.state == "blocked" }
    val disabled = graph.nodes.count { it.state == "disabled" || it.state == "unavailable" }
    CapabilityCard {
        Text("Runtimeoversigt", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        CapabilityValueRow("Schema", graph.schema)
        CapabilityValueRow("Nodes", graph.nodes.size.toString())
        CapabilityValueRow("Edges", graph.edges.size.toString())
        CapabilityValueRow("Ready", ready.toString())
        CapabilityValueRow("Blokeret", blocked.toString())
        CapabilityValueRow("Deaktiveret/utilgængelig", disabled.toString())
        CapabilityValueRow("Produktionsaktivering", if (graph.productionActivation) "UGYLDIG" else "Låst")
    }
}

@Composable
private fun CapabilityGroup(kind: String, nodes: List<Agent3CapabilityNode>) {
    CapabilityCard {
        Text(kind, color = KalivTheme.colors.TextHigh, fontSize = 16.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        nodes.sortedBy { it.id }.forEach { node ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                Column(Modifier.weight(1f)) {
                    Text(node.id, color = KalivTheme.colors.TextHigh, fontSize = 12.sp)
                    Text(node.reason, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                    if (node.metadata.isNotEmpty()) {
                        Text(node.metadata.toString(), color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
                    }
                }
                Text(
                    node.state.uppercase(),
                    color = when (node.state) {
                        "ready" -> KalivTheme.colors.Signal
                        "blocked" -> KalivTheme.colors.Danger
                        else -> KalivTheme.colors.Amber
                    },
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            Spacer(Modifier.height(9.dp))
        }
    }
}

@Composable
private fun CapabilityCard(content: @Composable ColumnScope.() -> Unit) {
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
private fun CapabilityValueRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.TextHigh, fontSize = 11.sp)
    }
}

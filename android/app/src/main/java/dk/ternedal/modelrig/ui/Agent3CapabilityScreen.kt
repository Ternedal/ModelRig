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
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import dk.ternedal.modelrig.net.Agent3CapabilityClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Developer-only, read-only view of the server-authoritative Capability Graph. */
@Composable
fun Agent3CapabilityScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var graph by remember { mutableStateOf<Agent3CapabilityClient.Graph?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun client(): Agent3CapabilityClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return Agent3CapabilityClient(base, token)
    }

    fun refresh() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) { runCatching { client().graph() } }
            busy = false
            result.onSuccess { graph = it }
                .onFailure { error = it.message ?: "Capability Graph kunne ikke hentes" }
        }
    }

    LaunchedEffect(Unit) { refresh() }

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
                        "Agent 3.0 Capability Graph",
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Read-only runtimekort · ingen aktivering",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(14.dp)) {
                    Text(
                        "Sikkerhedslås",
                        fontWeight = FontWeight.SemiBold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Skærmen læser kun GET /api/v1/experimental/agent3/capabilities. " +
                            "Den kan ikke route, aktivere tools eller promovere Agent 3.0.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(enabled = !busy, onClick = { refresh() }) {
                        Text(if (busy) "Henter…" else "Opdatér graf")
                    }
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(12.dp)) {
                    Text(
                        it,
                        color = KalivTheme.colors.danger,
                        modifier = Modifier.fillMaxWidth().padding(12.dp),
                        fontSize = 13.sp,
                    )
                }
            }

            graph?.let { value ->
                Spacer(Modifier.height(12.dp))
                CapabilitySummaryCard(value)
                value.nodes.groupBy { it.kind }.toSortedMap().forEach { (kind, nodes) ->
                    Spacer(Modifier.height(12.dp))
                    CapabilityNodeCard(kind, nodes)
                }
                Spacer(Modifier.height(12.dp))
                Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
                    Column(Modifier.fillMaxWidth().padding(14.dp)) {
                        Text(
                            "Afhængigheder",
                            color = KalivTheme.colors.textHigh,
                            fontWeight = FontWeight.SemiBold,
                        )
                        Spacer(Modifier.height(8.dp))
                        value.edges.forEach { edge ->
                            Text(
                                "${edge.source} → ${edge.target} (${edge.relation})",
                                color = KalivTheme.colors.textMuted,
                                fontSize = 10.sp,
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun CapabilitySummaryCard(graph: Agent3CapabilityClient.Graph) {
    val ready = graph.nodes.count { it.state == "ready" }
    val blocked = graph.nodes.count { it.state == "blocked" }
    val disabled = graph.nodes.count { it.state == "disabled" || it.state == "unavailable" }
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text("Runtimeoversigt", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
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
}

@Composable
private fun CapabilityNodeCard(
    kind: String,
    nodes: List<Agent3CapabilityClient.Node>,
) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text(kind, color = KalivTheme.colors.textHigh, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            nodes.sortedBy { it.id }.forEach { node ->
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Column(Modifier.weight(1f)) {
                        Text(node.id, color = KalivTheme.colors.textHigh, fontSize = 12.sp)
                        Text(node.reason, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                        if (node.metadata != "{}") {
                            Text(node.metadata, color = KalivTheme.colors.textMuted, fontSize = 9.sp)
                        }
                    }
                    Text(
                        node.state.uppercase(),
                        color = when (node.state) {
                            "ready" -> KalivTheme.colors.success
                            "blocked" -> KalivTheme.colors.danger
                            else -> KalivTheme.colors.amber
                        },
                        fontSize = 10.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                }
                Spacer(Modifier.height(9.dp))
            }
        }
    }
}

@Composable
private fun CapabilityValueRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp)
    }
}

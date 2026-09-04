package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.background
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.chat.ConversationsTopBar
import dk.ternedal.modelrig.ui.chat.RigEndpointCard
import dk.ternedal.modelrig.ui.chat.RigLoadedModelRow
import dk.ternedal.modelrig.ui.chat.RigMeasurementNote
import dk.ternedal.modelrig.ui.chat.RigMeterRow
import dk.ternedal.modelrig.ui.chat.RigSectionCaps
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.util.Locale
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

/**
 * Rig-status (skærm 18) mod B3a-endpointet GET /api/v1/system/status.
 * Alt vist er målt: intet tal opdigtes, og felter riggen ikke kan måle
 * vises som "ukendt" med tomt spor. Ældre rigge kender ikke endpointet
 * (404) — så siger noten det i stedet for at skjule en fejl.
 */
@Composable
fun RigStatusScreen(store: TokenStore, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var online by remember { mutableStateOf<Boolean?>(null) }
    var sys by remember { mutableStateOf<ModelRigClient.SystemStatus?>(null) }
    var running by remember { mutableStateOf<List<ModelRigClient.RunningModel>>(emptyList()) }
    var sysFailed by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }
    var freeing by remember { mutableStateOf(false) }
    var confirmFree by remember { mutableStateOf(false) }
    var freeResult by remember { mutableStateOf<String?>(null) }

    fun load() {
        if (loading) return
        loading = true
        scope.launch {
            val base = store.baseUrl
            if (base.isNullOrEmpty()) {
                online = false
                loading = false
                return@launch
            }
            val client = ModelRigClient(base, store.token)
            val up = withContext(Dispatchers.IO) { runCatching { client.ping() }.getOrDefault(false) }
            online = up
            if (up) {
                val s = withContext(Dispatchers.IO) { runCatching { client.systemStatus() } }
                sys = s.getOrNull()
                sysFailed = s.isFailure
                val r = withContext(Dispatchers.IO) { runCatching { client.listRunningModels() } }
                running = r.getOrDefault(emptyList())
            }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    Column(
        Modifier
            .fillMaxSize()
            .background(KalivTheme.colors.background)
            .kalivScreenInsets()
            .verticalScroll(rememberScrollState()),
    ) {
        ConversationsTopBar(
            title = "Rig-status",
            onBack = onBack,
            onMenu = { load() },
            menuIcon = R.drawable.ic_kaliv_retry,
        )
        Column(Modifier.padding(horizontal = 15.dp)) {
            RigEndpointCard(
                host = store.baseUrl?.removePrefix("https://")?.removePrefix("http://")?.trimEnd('/')
                    ?: "Ingen rig parret",
                stateText = when {
                    loading && online == null -> "Tjekker forbindelsen …"
                    // Oppetiden er backendens egen levetid — derfor står den
                    // som "rig-oppetid", ikke som maskinens driftstid.
                    online == true && sys?.uptimeSeconds != null ->
                        "Forbundet · rig-oppetid " + dk.ternedal.modelrig.ui.chat.formatUptime(sys!!.uptimeSeconds!!)
                    online == true -> "Forbundet"
                    online == false -> "Svarer ikke"
                    else -> "Ukendt"
                },
                online = online,
            )
            Spacer(Modifier.height(19.dp))

            RigSectionCaps("BELASTNING")
            Spacer(Modifier.height(12.dp))
            val total = sys?.vramTotalMb
            val used = sys?.vramUsedMb
            RigMeterRow(
                label = "VRAM",
                value = if (total != null && used != null) {
                    String.format(Locale.US, "%.1f / %d GB", used / 1024f, total / 1024)
                } else {
                    "ukendt"
                },
                fraction = if (total != null && used != null && total > 0) used.toFloat() / total else null,
            )
            Spacer(Modifier.height(16.dp))
            val temp = sys?.gpuTempC
            RigMeterRow(
                label = "GPU-temperatur",
                value = temp?.let { "$it°" } ?: "ukendt",
                // Sporet skalerer mod 110 °C: referencen viser 61° som ~55 %.
                fraction = temp?.let { it / 110f },
            )
            Spacer(Modifier.height(16.dp))
            val cpu = sys?.cpuPct
            RigMeterRow(
                label = "CPU",
                value = cpu?.let { String.format(Locale.US, "%.0f %%", it) } ?: "ukendt",
                fraction = cpu?.let { (it / 100.0).toFloat() },
            )

            if (online == true) {
                Spacer(Modifier.height(16.dp))
                dk.ternedal.modelrig.ui.chat.RigFreeVramAction(
                    busy = freeing,
                    confirming = confirmFree,
                    resultLine = freeResult,
                    onAsk = { confirmFree = true; freeResult = null },
                    onCancel = { confirmFree = false },
                    onConfirm = {
                        val base = store.baseUrl
                        if (base.isNullOrEmpty()) return@RigFreeVramAction
                        freeing = true
                        scope.launch {
                            val client = ModelRigClient(base, store.token)
                            val res = withContext(Dispatchers.IO) { runCatching { client.unloadModels() } }
                            freeing = false
                            confirmFree = false
                            res.onSuccess { r ->
                                freeResult = dk.ternedal.modelrig.ui.chat.unloadResultLine(
                                    r.unloaded.size, r.freedBytes, r.failed.size,
                                )
                                load()
                            }.onFailure {
                                freeResult = "Kunne ikke frigøre VRAM \u2014 kræver rig-version 2.0.5"
                            }
                        }
                    },
                )
            }

            if (online == true && sysFailed) {
                Spacer(Modifier.height(14.dp))
                RigMeasurementNote(
                    text = "Din rig kender ikke måle-endpointet endnu. Det kom med rig-version 2.0.3 — opdatér riggen, så udfyldes tallene.",
                    onRetry = { load() },
                )
            }

            Spacer(Modifier.height(19.dp))
            RigSectionCaps("INDLÆST")
            Spacer(Modifier.height(4.dp))
            if (running.isEmpty()) {
                Text(
                    if (online == true) "Ingen modeller indlæst lige nu." else "Kræver forbindelse til riggen.",
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textMuted,
                    modifier = Modifier.padding(vertical = 10.dp),
                )
            }
            running.forEach { m ->
                RigLoadedModelRow(
                    name = m.name,
                    sizeLabel = if (m.sizeVramBytes > 0) {
                        String.format(Locale.US, "%.1f GB", m.sizeVramBytes / 1_073_741_824f)
                    } else {
                        "ukendt"
                    },
                )
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

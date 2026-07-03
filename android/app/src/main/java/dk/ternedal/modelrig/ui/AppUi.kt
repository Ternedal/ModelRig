package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.CloudClient
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private enum class Screen { Setup, Chat }

@Composable
fun AppUi() {
    ModelRigTheme {
        val context = LocalContext.current
        val store = remember { TokenStore(context) }
        var screen by remember {
            mutableStateOf(if (store.hasRig || store.hasCloud) Screen.Chat else Screen.Setup)
        }
        Surface(color = Graphite, modifier = Modifier.fillMaxSize()) {
            when (screen) {
                Screen.Setup -> SetupScreen(store, onDone = { screen = Screen.Chat })
                Screen.Chat -> ChatScreen(store, onOpenSettings = { screen = Screen.Setup })
            }
        }
    }
}

// ---- setup: cloud and/or rig ----
@Composable
private fun SetupScreen(store: TokenStore, onDone: () -> Unit) {
    var refresh by remember { mutableStateOf(0) } // bump to re-read store state
    val canChat = remember(refresh) { store.hasRig || store.hasCloud }

    Column(
        Modifier.fillMaxSize().padding(20.dp).verticalScroll(rememberScrollState()),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("ModelRig", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Spacer(Modifier.weight(1f))
            if (canChat) TextButton(onClick = onDone) { Text("Til chat →", color = Signal) }
        }
        Text("Vælg mindst én kilde", fontSize = 14.sp, color = TextMuted)
        Spacer(Modifier.height(16.dp))

        CloudCard(store) { refresh++; onDone() }
        Spacer(Modifier.height(16.dp))
        RigCard(store) { refresh++; onDone() }
    }
}

@Composable
private fun CloudCard(store: TokenStore, onSaved: () -> Unit) {
    var key by remember { mutableStateOf("") }
    var model by remember { mutableStateOf(store.cloudModel) }
    var configured by remember { mutableStateOf(store.hasCloud) }
    var msg by remember { mutableStateOf<String?>(null) }

    Surface(color = GraphiteSurface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Ollama Cloud", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Text("Chat uden at rig'en kører. Modeller i skyen.", fontSize = 12.sp, color = TextMuted)
            Spacer(Modifier.height(4.dp))
            if (configured) {
                Text("✓ konfigureret", color = Signal, fontSize = 13.sp)
            }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = key, onValueChange = { key = it },
                label = { Text(if (configured) "Ny API-nøgle (valgfri)" else "API-nøgle", fontSize = 12.sp) },
                singleLine = true,
                visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Text("Hentes på ollama.com/settings/keys", fontSize = 11.sp, color = TextMuted)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = model, onValueChange = { model = it },
                label = { Text("Model (fx gpt-oss:120b)", fontSize = 12.sp) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    enabled = configured || key.isNotBlank(),
                    onClick = {
                        runCatching {
                            if (key.isNotBlank()) store.cloudKey = key.trim()
                            store.cloudModel = model.trim().ifBlank { "gpt-oss:120b" }
                            store.chatMode = "cloud"
                        }.onSuccess {
                            key = ""; configured = true; msg = null; onSaved()
                        }.onFailure { msg = "Kunne ikke gemme nøgle: ${it.message}" }
                    },
                ) { Text("Gem & brug cloud") }
                if (configured) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { store.clearCloud(); configured = false; key = "" }) {
                        Text("Ryd", color = Danger)
                    }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = Danger, fontSize = 12.sp) }
        }
    }
}

@Composable
private fun RigCard(store: TokenStore, onConnected: () -> Unit) {
    var baseUrl by remember { mutableStateOf(store.baseUrl ?: "http://192.168.1.10:8080") }
    var code by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf(android.os.Build.MODEL ?: "android") }
    var connected by remember { mutableStateOf(store.hasRig) }
    var busy by remember { mutableStateOf(false) }
    var msg by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Surface(color = GraphiteSurface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Din rig (backend)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Text("Lokale modeller + RAG. Kræver at rig'en kører.", fontSize = 12.sp, color = TextMuted)
            Spacer(Modifier.height(4.dp))
            if (connected) Text("✓ forbundet", color = Signal, fontSize = 13.sp)
            Spacer(Modifier.height(8.dp))
            Field("Server-URL", baseUrl) { baseUrl = it }
            Field("Parringskode (XXXX-XXXX)", code) { code = it }
            Field("Enhedsnavn", deviceName) { deviceName = it }
            Text(
                "Serveren skal binde 0.0.0.0 / Tailscale-IP — ikke 127.0.0.1. Brug LAN-IP.",
                color = TextMuted, fontSize = 11.sp, lineHeight = 15.sp,
            )
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    enabled = !busy && code.isNotBlank() && baseUrl.isNotBlank(),
                    onClick = {
                        busy = true; msg = null
                        val url = baseUrl.trim(); val c = code.trim(); val n = deviceName.trim()
                        scope.launch {
                            val res = withContext(Dispatchers.IO) {
                                runCatching { ModelRigClient(url).claimPairing(n, c) }
                            }
                            res.onSuccess {
                                store.baseUrl = url; store.token = it; store.chatMode = "rig"
                                busy = false; connected = true; onConnected()
                            }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
                        }
                    },
                ) { Text(if (busy) "Forbinder…" else "Forbind") }
                if (connected) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { store.clearRig(); connected = false }) {
                        Text("Afbryd", color = Danger)
                    }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = Danger, fontSize = 12.sp) }
        }
    }
}

// ---- chat ----
private data class Msg(val role: String, val text: String, val streaming: Boolean = false)

@Composable
private fun ChatScreen(store: TokenStore, onOpenSettings: () -> Unit) {
    val hasRig = store.hasRig
    val hasCloud = store.hasCloud
    val initialMode = when {
        hasRig && hasCloud -> store.chatMode
        hasCloud -> "cloud"
        else -> "rig"
    }
    var mode by remember { mutableStateOf(initialMode) }

    val messages = remember { mutableStateListOf<Msg>() }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var currentModel by remember { mutableStateOf(store.model) }
    var models by remember { mutableStateOf(listOf<String>()) }
    var modelMenu by remember { mutableStateOf(false) }
    var overflow by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.size - 1)
    }

    Column(Modifier.fillMaxSize()) {
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("ModelRig", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                    Spacer(Modifier.weight(1f))
                    Box {
                        TextButton(onClick = { overflow = true }) { Text("⋮", color = TextHigh, fontSize = 20.sp) }
                        DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                            DropdownMenuItem(text = { Text("Ryd samtale") }, onClick = { overflow = false; messages.clear() })
                            DropdownMenuItem(text = { Text("Indstillinger") }, onClick = { overflow = false; onOpenSettings() })
                        }
                    }
                }
                Spacer(Modifier.height(6.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // source selector (only when both are configured)
                    if (hasRig && hasCloud) {
                        SourceChip("Rig", mode == "rig") { mode = "rig"; store.chatMode = "rig" }
                        Spacer(Modifier.width(6.dp))
                        SourceChip("Cloud", mode == "cloud") { mode = "cloud"; store.chatMode = "cloud" }
                        Spacer(Modifier.width(10.dp))
                    }
                    // model area
                    if (mode == "cloud") {
                        AssistChipLike("☁ ${store.cloudModel}") { onOpenSettings() }
                    } else {
                        Box {
                            OutlinedButton(
                                onClick = { modelMenu = true },
                                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp),
                            ) { Text("$currentModel  ▾", color = TextHigh, fontSize = 12.sp) }
                            DropdownMenu(expanded = modelMenu, onDismissRequest = { modelMenu = false }) {
                                DropdownMenuItem(
                                    text = { Text("↻  Genindlæs modeller", color = Signal) },
                                    onClick = {
                                        modelMenu = false
                                        scope.launch {
                                            val res = withContext(Dispatchers.IO) {
                                                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listModels() }
                                            }
                                            res.onSuccess { models = it }
                                        }
                                    },
                                )
                                if (models.isNotEmpty()) HorizontalDivider()
                                models.forEach { m ->
                                    DropdownMenuItem(text = { Text(m) }, onClick = {
                                        currentModel = m; store.model = m; modelMenu = false
                                    })
                                }
                            }
                        }
                    }
                }
            }
        }

        if (messages.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    if (mode == "cloud") "Cloud-tilstand · skriv en besked" else "Rig-tilstand · skriv en besked",
                    color = TextMuted, fontSize = 14.sp,
                )
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            ) { items(messages) { m -> Bubble(m) } }
        }

        Surface(color = GraphiteSurface, tonalElevation = 3.dp) {
            Row(Modifier.fillMaxWidth().padding(12.dp), verticalAlignment = Alignment.Bottom) {
                OutlinedTextField(
                    value = input, onValueChange = { input = it },
                    modifier = Modifier.weight(1f), enabled = !busy, maxLines = 5,
                    placeholder = { Text("Besked…") },
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = !busy && input.isNotBlank(),
                    modifier = Modifier.height(52.dp),
                    onClick = {
                        val t = input.trim()
                        if (t.isEmpty()) return@Button
                        messages.add(Msg("user", t)); input = ""; busy = true
                        val history = messages.map { it.role to it.text }
                        val idx = messages.size
                        messages.add(Msg("assistant", "", streaming = true))
                        val useCloud = mode == "cloud"
                        val rigModel = currentModel
                        scope.launch {
                            val err = withContext(Dispatchers.IO) {
                                runCatching {
                                    val onDelta: (String) -> Unit = { delta ->
                                        scope.launch {
                                            val cur = messages[idx]
                                            messages[idx] = cur.copy(text = cur.text + delta)
                                        }
                                    }
                                    if (useCloud) {
                                        val key = store.cloudKey ?: throw RuntimeException("ingen cloud-nøgle")
                                        CloudClient(key).chatStream(store.cloudModel, history, onDelta = onDelta)
                                    } else {
                                        ModelRigClient(store.baseUrl ?: "", store.token)
                                            .chatStream(rigModel, history, onDelta = onDelta)
                                    }
                                }.exceptionOrNull()
                            }
                            val cur = messages[idx]
                            messages[idx] = cur.copy(
                                streaming = false,
                                text = when {
                                    err == null -> cur.text
                                    cur.text.isEmpty() -> "⚠️ Fejl: ${err.message}"
                                    else -> cur.text + "\n\n_[afbrudt]_"
                                },
                            )
                            busy = false
                        }
                    },
                ) { Text(if (busy) "…" else "Send") }
            }
        }
    }
}

@Composable
private fun SourceChip(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        Button(onClick = onClick, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp)) {
            Text(label, fontSize = 12.sp)
        }
    } else {
        OutlinedButton(onClick = onClick, contentPadding = PaddingValues(horizontal = 12.dp, vertical = 2.dp)) {
            Text(label, color = TextMuted, fontSize = 12.sp)
        }
    }
}

@Composable
private fun AssistChipLike(label: String, onClick: () -> Unit) {
    OutlinedButton(onClick = onClick, contentPadding = PaddingValues(horizontal = 10.dp, vertical = 2.dp)) {
        Text(label, color = TextHigh, fontSize = 12.sp)
    }
}

@Composable
private fun Bubble(m: Msg) {
    val isUser = m.role == "user"
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (isUser) "dig" else "modelrig",
                color = if (isUser) TextMuted else Signal,
                fontSize = 11.sp, fontWeight = FontWeight.Medium,
            )
            if (m.streaming) {
                Spacer(Modifier.width(6.dp))
                CircularProgressIndicator(Modifier.size(11.dp), strokeWidth = 2.dp, color = Signal)
            }
        }
        Spacer(Modifier.height(3.dp))
        Surface(
            color = if (isUser) GraphiteSurfaceHigh else GraphiteSurface,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Box(Modifier.padding(12.dp)) {
                if (isUser || m.streaming) {
                    Text(m.text.ifEmpty { " " }, color = TextHigh, fontSize = 15.sp, lineHeight = 22.sp)
                } else {
                    MarkdownText(m.text, color = TextHigh)
                }
            }
        }
    }
}

@Composable
private fun Field(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value, onValueChange = onChange,
        label = { Text(label, fontSize = 12.sp) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    )
}

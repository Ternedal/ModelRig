package dk.ternedal.modelrig.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun AppUi() {
    ModelRigTheme {
        val context = LocalContext.current
        val store = remember { TokenStore(context) }
        var token by remember { mutableStateOf(store.token) }

        Surface(color = Graphite, modifier = Modifier.fillMaxSize()) {
            if (token == null) {
                PairScreen(store) { token = it }
            } else {
                ChatScreen(store) { store.clear(); token = null }
            }
        }
    }
}

// ---- pairing ----
@Composable
private fun PairScreen(store: TokenStore, onPaired: (String) -> Unit) {
    var baseUrl by remember { mutableStateOf(store.baseUrl ?: "http://192.168.1.10:8080") }
    var code by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf(android.os.Build.MODEL ?: "android") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(
        Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
    ) {
        Text("ModelRig", fontSize = 30.sp, fontWeight = FontWeight.Bold, color = TextHigh)
        Text("Forbind din enhed", fontSize = 15.sp, color = Signal)
        Spacer(Modifier.height(20.dp))
        Field("Server-URL", baseUrl) { baseUrl = it }
        Field("Parringskode (XXXX-XXXX)", code) { code = it }
        Field("Enhedsnavn", deviceName) { deviceName = it }
        Spacer(Modifier.height(8.dp))
        Text(
            "Serveren skal binde 0.0.0.0 eller en Tailscale-IP. En 127.0.0.1-server " +
                "kan ikke nås fra telefonen. Brug maskinens LAN-IP her.",
            color = TextMuted, fontSize = 12.sp, lineHeight = 17.sp,
        )
        Spacer(Modifier.height(16.dp))
        Button(
            enabled = !busy && code.isNotBlank() && baseUrl.isNotBlank(),
            modifier = Modifier.fillMaxWidth(),
            onClick = {
                busy = true; status = null
                val url = baseUrl.trim(); val c = code.trim(); val n = deviceName.trim()
                scope.launch {
                    val res = withContext(Dispatchers.IO) {
                        runCatching { ModelRigClient(url).claimPairing(n, c) }
                    }
                    res.onSuccess {
                        store.baseUrl = url; store.token = it
                        busy = false; onPaired(it)
                    }.onFailure {
                        status = it.message ?: "Kunne ikke forbinde"; busy = false
                    }
                }
            },
        ) { Text(if (busy) "Forbinder…" else "Forbind") }
        status?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = Danger, fontSize = 13.sp)
        }
    }
}

// ---- chat ----
private data class Msg(val role: String, val text: String, val streaming: Boolean = false)

@Composable
private fun ChatScreen(store: TokenStore, onUnpair: () -> Unit) {
    val messages = remember { mutableStateListOf<Msg>() }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var currentModel by remember { mutableStateOf(store.model) }
    var models by remember { mutableStateOf(listOf<String>()) }
    var modelMenu by remember { mutableStateOf(false) }
    var overflow by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val client = remember { ModelRigClient(store.baseUrl ?: "", store.token) }
    val listState = rememberLazyListState()

    fun loadModels() {
        scope.launch {
            val res = withContext(Dispatchers.IO) { runCatching { client.listModels() } }
            res.onSuccess { models = it }
        }
    }

    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.size - 1)
    }

    Column(Modifier.fillMaxSize()) {
        // top bar
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("ModelRig", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                Spacer(Modifier.width(12.dp))
                Box {
                    OutlinedButton(
                        onClick = { modelMenu = true },
                        contentPadding = PaddingValues(horizontal = 12.dp, vertical = 4.dp),
                    ) {
                        Text(currentModel, color = TextHigh, fontSize = 12.sp)
                        Text("  ▾", color = TextMuted, fontSize = 12.sp)
                    }
                    DropdownMenu(expanded = modelMenu, onDismissRequest = { modelMenu = false }) {
                        DropdownMenuItem(
                            text = { Text("↻  Genindlæs modeller", color = Signal) },
                            onClick = { modelMenu = false; loadModels() },
                        )
                        if (models.isNotEmpty()) HorizontalDivider()
                        models.forEach { m ->
                            DropdownMenuItem(text = { Text(m) }, onClick = {
                                currentModel = m; store.model = m; modelMenu = false
                            })
                        }
                    }
                }
                Spacer(Modifier.weight(1f))
                Box {
                    TextButton(onClick = { overflow = true }) {
                        Text("⋮", color = TextHigh, fontSize = 20.sp)
                    }
                    DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                        DropdownMenuItem(
                            text = { Text("Ryd samtale") },
                            onClick = { overflow = false; messages.clear() },
                        )
                        DropdownMenuItem(
                            text = { Text("Afbryd forbindelse", color = Danger) },
                            onClick = { overflow = false; onUnpair() },
                        )
                    }
                }
            }
        }

        // messages
        if (messages.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Skriv en besked for at starte", color = TextMuted, fontSize = 14.sp)
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            ) {
                items(messages) { m -> Bubble(m) }
            }
        }

        // input bar
        Surface(color = GraphiteSurface, tonalElevation = 3.dp) {
            Row(
                Modifier.fillMaxWidth().padding(12.dp),
                verticalAlignment = Alignment.Bottom,
            ) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    enabled = !busy,
                    maxLines = 5,
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
                        val model = currentModel
                        val idx = messages.size
                        messages.add(Msg("assistant", "", streaming = true))
                        scope.launch {
                            val err = withContext(Dispatchers.IO) {
                                runCatching {
                                    client.chatStream(model, history) { delta ->
                                        scope.launch {
                                            val cur = messages[idx]
                                            messages[idx] = cur.copy(text = cur.text + delta)
                                        }
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
private fun Bubble(m: Msg) {
    val isUser = m.role == "user"
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                if (isUser) "dig" else "modelrig",
                color = if (isUser) TextMuted else Signal,
                fontSize = 11.sp,
                fontWeight = FontWeight.Medium,
            )
            if (m.streaming) {
                Spacer(Modifier.width(6.dp))
                CircularProgressIndicator(
                    Modifier.size(11.dp),
                    strokeWidth = 2.dp,
                    color = Signal,
                )
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
        value = value,
        onValueChange = onChange,
        label = { Text(label, fontSize = 12.sp) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    )
}

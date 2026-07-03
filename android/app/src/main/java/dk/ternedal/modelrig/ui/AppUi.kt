package dk.ternedal.modelrig.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ModelRigClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private val Graphite = Color(0xFF0E1116)
private val Surface = Color(0xFF171B22)
private val SurfaceHigh = Color(0xFF1F242D)
private val Signal = Color(0xFF4C8DFF)
private val TextHigh = Color(0xFFE6E9EF)
private val TextMuted = Color(0xFF9AA4B2)
private val Danger = Color(0xFFF2555A)

private val Colors = darkColorScheme(
    primary = Signal,
    onPrimary = Graphite,
    background = Graphite,
    onBackground = TextHigh,
    surface = Surface,
    onSurface = TextHigh,
)

@Composable
fun AppUi() {
    MaterialTheme(colorScheme = Colors) {
        val context = LocalContext.current
        val store = remember { TokenStore(context) }
        var token by remember { mutableStateOf(store.token) }

        Box(Modifier.fillMaxSize().background(Graphite)) {
            if (token == null) {
                PairScreen(store) { token = it }
            } else {
                ChatScreen(store) { store.clear(); token = null }
            }
        }
    }
}

@Composable
private fun PairScreen(store: TokenStore, onPaired: (String) -> Unit) {
    var baseUrl by remember { mutableStateOf(store.baseUrl ?: "http://192.168.1.10:8080") }
    var code by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf(android.os.Build.MODEL ?: "android") }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()

    Column(Modifier.fillMaxSize().padding(20.dp)) {
        Text("Pair with ModelRig", color = TextHigh, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(4.dp))
        Text(
            "The server must bind 0.0.0.0 or a Tailscale IP — a 127.0.0.1 server is unreachable from the phone.",
            color = TextMuted, fontSize = 12.sp,
        )
        Spacer(Modifier.height(16.dp))
        Fld("Server base URL", baseUrl) { baseUrl = it }
        Fld("Pairing code (XXXX-XXXX)", code) { code = it }
        Fld("Device name", deviceName) { deviceName = it }
        Spacer(Modifier.height(12.dp))
        Button(
            enabled = !busy,
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
                        status = it.message; busy = false
                    }
                }
            },
        ) { Text(if (busy) "Pairing…" else "Pair") }
        status?.let {
            Spacer(Modifier.height(12.dp))
            Text(it, color = Danger, fontSize = 13.sp)
        }
    }
}

private data class Msg(val role: String, val text: String)

@Composable
private fun ChatScreen(store: TokenStore, onUnpair: () -> Unit) {
    val messages = remember { mutableStateListOf<Msg>() }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var currentModel by remember { mutableStateOf(store.model) }
    var models by remember { mutableStateOf(listOf<String>()) }
    var menuOpen by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val client = remember { ModelRigClient(store.baseUrl ?: "", store.token) }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            Text("ModelRig", color = TextHigh, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.weight(1f))
            TextButton(onClick = onUnpair) { Text("Unpair", color = Signal) }
        }

        Row(verticalAlignment = Alignment.CenterVertically) {
            Box {
                OutlinedButton(onClick = { menuOpen = true }) {
                    Text(currentModel, color = TextHigh, fontSize = 12.sp)
                }
                DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
                    if (models.isEmpty()) {
                        DropdownMenuItem(text = { Text("(load models)") }, onClick = { menuOpen = false })
                    } else {
                        models.forEach { m ->
                            DropdownMenuItem(text = { Text(m) }, onClick = {
                                currentModel = m; store.model = m; menuOpen = false
                            })
                        }
                    }
                }
            }
            Spacer(Modifier.width(8.dp))
            TextButton(onClick = {
                scope.launch {
                    val res = withContext(Dispatchers.IO) { runCatching { client.listModels() } }
                    res.onSuccess { models = it }
                }
            }) { Text("Load models", color = Signal, fontSize = 12.sp) }
        }

        Spacer(Modifier.height(8.dp))
        LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
            items(messages) { m -> Bubble(m) }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = input,
                onValueChange = { input = it },
                modifier = Modifier.weight(1f),
                enabled = !busy,
                singleLine = true,
                placeholder = { Text("Message…") },
            )
            Spacer(Modifier.width(8.dp))
            Button(
                enabled = !busy,
                onClick = {
                    val t = input.trim()
                    if (t.isEmpty()) return@Button
                    messages.add(Msg("user", t)); input = ""; busy = true
                    val history = messages.map { it.role to it.text }
                    val model = currentModel
                    val idx = messages.size
                    messages.add(Msg("assistant", ""))
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
                        if (err != null) {
                            val cur = messages[idx]
                            messages[idx] = cur.copy(
                                text = if (cur.text.isEmpty()) "Error: ${err.message}" else cur.text + "\n[afbrudt]"
                            )
                        }
                        busy = false
                    }
                },
            ) { Text(if (busy) "…" else "Send") }
        }
    }
}

@Composable
private fun Bubble(m: Msg) {
    val isUser = m.role == "user"
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(if (isUser) "you" else "modelrig", color = TextMuted, fontSize = 11.sp)
        Spacer(Modifier.height(2.dp))
        Box(
            Modifier.clip(RoundedCornerShape(10.dp))
                .background(if (isUser) SurfaceHigh else Surface)
                .fillMaxWidth()
                .padding(12.dp)
        ) {
            Text(m.text, color = TextHigh, fontSize = 14.sp)
        }
    }
}

@Composable
private fun Fld(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = onChange,
        label = { Text(label, fontSize = 12.sp) },
        singleLine = true,
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    )
}

package dk.ternedal.modelrig.desktop

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
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ChatMessage
import dk.ternedal.modelrig.desktop.net.ChatResult
import dk.ternedal.modelrig.desktop.net.ChatRouter
import dk.ternedal.modelrig.desktop.net.OllamaClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private data class UiMessage(val role: String, val text: String, val source: ChatResult.Source? = null)

@Composable
fun App() {
    MaterialTheme(colorScheme = Brand.Colors) {
        var localUrl by remember { mutableStateOf(System.getenv("MODELRIG_LOCAL_URL") ?: "http://localhost:11434") }
        var localPath by remember { mutableStateOf("/api/chat") }
        var localModel by remember { mutableStateOf("qwen2.5-coder:7b") }
        var deviceToken by remember { mutableStateOf(System.getenv("MODELRIG_TOKEN") ?: "") }
        var cloudKey by remember { mutableStateOf(System.getenv("OLLAMA_API_KEY") ?: "") }
        var cloudModel by remember { mutableStateOf("gpt-oss:120b-cloud") }
        var preferLocal by remember { mutableStateOf(true) }
        var showSettings by remember { mutableStateOf(true) }

        val messages = remember { mutableStateListOf<UiMessage>() }
        var input by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        var lastSource by remember { mutableStateOf<ChatResult.Source?>(null) }
        var models by remember { mutableStateOf(listOf<String>()) }
        var modelMenuOpen by remember { mutableStateOf(false) }
        var modelError by remember { mutableStateOf<String?>(null) }
        val scope = rememberCoroutineScope()

        fun loadModels() {
            scope.launch {
                val res = withContext(Dispatchers.IO) {
                    runCatching {
                        val path = if (localPath.contains("/api/v1/")) "/api/v1/models" else "/api/tags"
                        OllamaClient(baseUrl = localUrl, chatPath = localPath, bearer = deviceToken.ifBlank { null })
                            .listModels(path)
                    }
                }
                res.onSuccess { models = it; modelError = null }.onFailure { modelError = it.message }
            }
        }

        fun send() {
            val text = input.trim()
            if (text.isEmpty() || busy) return
            messages.add(UiMessage("user", text))
            input = ""
            busy = true
            val history = messages
                .filter { it.role == "user" || it.role == "assistant" }
                .map { ChatMessage(it.role, it.text) }
            val assistantIdx = messages.size
            messages.add(UiMessage("assistant", "", null))
            scope.launch {
                val err = withContext(Dispatchers.IO) {
                    runCatching {
                        val local = OllamaClient(baseUrl = localUrl, chatPath = localPath, bearer = deviceToken.ifBlank { null })
                        val cloud = if (cloudKey.isNotBlank())
                            OllamaClient(baseUrl = "https://ollama.com", chatPath = "/api/chat", bearer = cloudKey)
                        else null
                        ChatRouter(local, localModel, cloud, cloudModel, preferLocal).chatStream(history) { src, delta ->
                            scope.launch {
                                lastSource = src
                                val cur = messages[assistantIdx]
                                messages[assistantIdx] = cur.copy(text = cur.text + delta, source = src)
                            }
                        }
                    }.exceptionOrNull()
                }
                if (err != null) {
                    val cur = messages[assistantIdx]
                    val msg = if (cur.text.isEmpty()) "Error: ${err.message}" else cur.text + "\n[afbrudt: ${err.message}]"
                    messages[assistantIdx] = cur.copy(text = msg)
                }
                busy = false
            }
        }

        Column(Modifier.fillMaxSize().background(Brand.Graphite).padding(16.dp)) {
            Header(lastSource)
            Spacer(Modifier.height(12.dp))
            if (showSettings) {
                SettingsCard(
                    localUrl, { localUrl = it },
                    localPath, { localPath = it },
                    localModel, { localModel = it },
                    deviceToken, { deviceToken = it },
                    cloudKey, { cloudKey = it },
                    cloudModel, { cloudModel = it },
                    preferLocal, { preferLocal = it },
                )
                Spacer(Modifier.height(8.dp))
            }
            TextButton(onClick = { showSettings = !showSettings }) {
                Text(if (showSettings) "Hide settings" else "Show settings", color = Brand.Signal)
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    OutlinedButton(onClick = { modelMenuOpen = true }) {
                        Text("Model: $localModel", color = Brand.TextHigh)
                    }
                    DropdownMenu(expanded = modelMenuOpen, onDismissRequest = { modelMenuOpen = false }) {
                        if (models.isEmpty()) {
                            DropdownMenuItem(text = { Text("(load models first)") }, onClick = { modelMenuOpen = false })
                        } else {
                            models.forEach { m ->
                                DropdownMenuItem(text = { Text(m) }, onClick = { localModel = m; modelMenuOpen = false })
                            }
                        }
                    }
                }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { loadModels() }) { Text("Load models", color = Brand.Signal) }
            }
            modelError?.let { Text("Models: $it", color = Brand.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(8.dp))

            LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
                items(messages) { m -> MessageBubble(m) }
            }

            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("Ask ModelRig…") },
                    enabled = !busy,
                    singleLine = true,
                )
                Spacer(Modifier.width(8.dp))
                Button(onClick = { send() }, enabled = !busy) {
                    Text(if (busy) "…" else "Send")
                }
            }
        }
    }
}

@Composable
private fun Header(source: ChatResult.Source?) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("ModelRig", color = Brand.TextHigh, fontSize = 22.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.width(10.dp))
        val label: String
        val color = when (source) {
            ChatResult.Source.LOCAL -> { label = "LOCAL"; Brand.Signal }
            ChatResult.Source.CLOUD -> { label = "CLOUD"; Brand.Amber }
            null -> { label = "IDLE"; Brand.TextMuted }
        }
        Box(
            Modifier.clip(RoundedCornerShape(6.dp))
                .background(color.copy(alpha = 0.18f))
                .padding(horizontal = 8.dp, vertical = 3.dp)
        ) {
            Text(label, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        }
    }
}

@Composable
private fun MessageBubble(m: UiMessage) {
    val isUser = m.role == "user"
    val bg = if (isUser) Brand.SurfaceHigh else Brand.Surface
    val badge = when {
        isUser -> "you"
        m.source == ChatResult.Source.CLOUD -> "modelrig · cloud"
        m.source == ChatResult.Source.LOCAL -> "modelrig · local"
        else -> "modelrig"
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(badge, color = Brand.TextMuted, fontSize = 11.sp)
        Spacer(Modifier.height(2.dp))
        Box(Modifier.clip(RoundedCornerShape(10.dp)).background(bg).fillMaxWidth().padding(12.dp)) {
            Text(m.text, color = Brand.TextHigh, fontSize = 14.sp)
        }
    }
}

@Composable
private fun SettingsCard(
    localUrl: String, onLocalUrl: (String) -> Unit,
    localPath: String, onLocalPath: (String) -> Unit,
    localModel: String, onLocalModel: (String) -> Unit,
    token: String, onToken: (String) -> Unit,
    cloudKey: String, onCloudKey: (String) -> Unit,
    cloudModel: String, onCloudModel: (String) -> Unit,
    preferLocal: Boolean, onPreferLocal: (Boolean) -> Unit,
) {
    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(Brand.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Text("Connection", color = Brand.TextHigh, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("Local base URL (Ollama or ModelRig backend)", localUrl, onLocalUrl)
            Field("Local chat path (/api/chat direct · /api/v1/chat via backend)", localPath, onLocalPath)
            Field("Local model", localModel, onLocalModel)
            Field("Device token (only when going via ModelRig backend)", token, onToken)
            Spacer(Modifier.height(8.dp))
            Text("Ollama Cloud fallback", color = Brand.Amber, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("OLLAMA_API_KEY", cloudKey, onCloudKey)
            Field("Cloud model (e.g. gpt-oss:120b-cloud)", cloudModel, onCloudModel)
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = preferLocal, onCheckedChange = onPreferLocal)
                Spacer(Modifier.width(8.dp))
                Text("Prefer local, fall back to cloud", color = Brand.TextMuted, fontSize = 13.sp)
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
        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
    )
}

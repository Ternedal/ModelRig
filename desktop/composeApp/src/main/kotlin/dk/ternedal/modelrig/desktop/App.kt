package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
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
import androidx.compose.runtime.LaunchedEffect
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
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.ChatMessage
import dk.ternedal.modelrig.desktop.net.ChatResult
import dk.ternedal.modelrig.desktop.net.ChatRouter
import dk.ternedal.modelrig.desktop.net.OllamaClient
import dk.ternedal.modelrig.desktop.net.RagClient
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private data class UiMessage(
    val role: String,
    val text: String,
    val source: ChatResult.Source? = null,
    val streaming: Boolean = false,
    val ragSources: List<String> = emptyList(),
)

@Composable
fun App() {
    MaterialTheme(colorScheme = Brand.Colors) {
        var localUrl by remember { mutableStateOf(System.getenv("MODELRIG_LOCAL_URL") ?: "http://localhost:11434") }
        var localPath by remember { mutableStateOf("/api/chat") }
        var localModel by remember { mutableStateOf("qwen2.5-coder:7b") }
        var deviceToken by remember { mutableStateOf(System.getenv("MODELRIG_TOKEN") ?: "") }
        var cloudKey by remember { mutableStateOf(System.getenv("OLLAMA_API_KEY") ?: "") }
        var cloudModel by remember { mutableStateOf("gpt-oss:120b-cloud") }
        var localSystem by remember { mutableStateOf("") }
        var cloudSystem by remember { mutableStateOf("") }
        var preferLocal by remember { mutableStateOf(true) }
        var showSettings by remember { mutableStateOf(true) }

        val messages = remember { mutableStateListOf<UiMessage>() }
        var input by remember { mutableStateOf("") }
        var busy by remember { mutableStateOf(false) }
        var lastSource by remember { mutableStateOf<ChatResult.Source?>(null) }
        var models by remember { mutableStateOf(listOf<String>()) }
        var modelMenuOpen by remember { mutableStateOf(false) }
        var modelError by remember { mutableStateOf<String?>(null) }
        var ragMode by remember { mutableStateOf(false) }
        var ragSources by remember { mutableStateOf(listOf<String>()) }
        var ragSourceFilter by remember { mutableStateOf<String?>(null) }
        var ragSourceMenuOpen by remember { mutableStateOf(false) }
        var ragError by remember { mutableStateOf<String?>(null) }
        var showModels by remember { mutableStateOf(false) }
        var showConvos by remember { mutableStateOf(false) }
        val scope = rememberCoroutineScope()
        val db = remember { DesktopChatDb() }
        var convId by remember { mutableStateOf<Long?>(null) }

        // Silently resume the latest conversation on startup, if any. No
        // conversation *browser* yet (list/switch/delete) -- next increment.
        LaunchedEffect(Unit) {
            val latest = withContext(Dispatchers.IO) { db.latestConversationId() }
            if (latest != null) {
                val loaded = withContext(Dispatchers.IO) { db.loadMessages(latest) }
                messages.clear()
                loaded.forEach { (role, content) -> messages.add(UiMessage(role, content)) }
                convId = latest
            }
        }

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

        fun loadRagSources() {
            scope.launch {
                val res = withContext(Dispatchers.IO) {
                    runCatching { RagClient(localUrl, deviceToken.ifBlank { null }).listSources() }
                }
                res.onSuccess { ragSources = it; ragError = null }.onFailure { ragError = it.message }
            }
        }

        fun send() {
            val text = input.trim()
            if (text.isEmpty() || busy) return
            messages.add(UiMessage("user", text))
            input = ""
            busy = true
            // System prompt reflects the PREFERRED source (preferLocal), not
            // necessarily whichever one ends up answering after a fallback —
            // a known simplification since the router picks the actual source
            // only at call time. Fine for the common case; a mid-call switch
            // is the rare edge case (rig went down mid-session). Irrelevant in
            // RAG mode -- the worker sets its own system prompt.
            val sys = (if (preferLocal) localSystem else cloudSystem).trim()
            val history = buildList {
                if (sys.isNotEmpty()) add(ChatMessage("system", sys))
                addAll(
                    messages.filter { it.role == "user" || it.role == "assistant" }
                        .map { ChatMessage(it.role, it.text) },
                )
            }
            val useRag = ragMode
            val srcFilter = ragSourceFilter
            val assistantIdx = messages.size
            messages.add(UiMessage("assistant", "", null, streaming = true))
            scope.launch {
                // Best-effort source label for the DB row: since ChatRouter can
                // fall back dynamically, we label by the PREFERRED source
                // (preferLocal), same known simplification as the system prompt.
                val cid = withContext(Dispatchers.IO) {
                    val id = convId ?: db.newConversation(
                        source = if (useRag) "rag" else if (preferLocal) "rig" else "cloud",
                        model = if (preferLocal) localModel else cloudModel,
                        title = text,
                    )
                    db.addMessage(id, "user", text)
                    id
                }
                if (convId == null) convId = cid

                val err = withContext(Dispatchers.IO) {
                    runCatching {
                        if (useRag) {
                            // RAG only makes sense against the backend+worker --
                            // never local Ollama directly, never cloud.
                            val onSources: (List<String>) -> Unit = { srcs ->
                                scope.launch {
                                    val cur = messages[assistantIdx]
                                    messages[assistantIdx] = cur.copy(ragSources = srcs)
                                }
                            }
                            RagClient(localUrl, deviceToken.ifBlank { null })
                                .chatStream(text, localModel, srcFilter, onSources = onSources) { delta ->
                                    scope.launch {
                                        lastSource = ChatResult.Source.LOCAL
                                        val cur = messages[assistantIdx]
                                        messages[assistantIdx] = cur.copy(text = cur.text + delta, source = ChatResult.Source.LOCAL)
                                    }
                                }
                        } else {
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
                        }
                    }.exceptionOrNull()
                }
                val cur = messages[assistantIdx]
                val cancelled = err != null && cur.text.isNotEmpty()
                val msg = if (err == null) cur.text
                    else if (cur.text.isEmpty()) "Fejl: ${err.message}"
                    else cur.text + "\n[afbrudt: ${err.message}]"
                messages[assistantIdx] = cur.copy(text = msg, streaming = false)
                if (err == null || cancelled) {
                    val finalText = messages[assistantIdx].text
                    withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", finalText) }
                }
                busy = false
            }
        }

        Column(Modifier.fillMaxSize().background(Brand.Graphite).padding(16.dp)) {
            Header(lastSource)
            Spacer(Modifier.height(12.dp))
            // Panel toggles live ABOVE the panels and are never pushed out of
            // view. The original layout put the settings card first and its
            // close-button below it -- once the card grew taller than the
            // window (no scrolling existed), the close-button and everything
            // else became unreachable. Found by Anders on Windows (v0.20.9
            // jar, 980x720 default window): a genuine soft-lock this
            // session's headless smoke tests could never catch.
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = { showSettings = !showSettings }) {
                    Text(if (showSettings) "Skjul indstillinger" else "Indstillinger", color = Brand.Signal)
                }
                TextButton(onClick = { showConvos = !showConvos }) {
                    Text(if (showConvos) "Skjul samtaler" else "Samtaler", color = Brand.Signal)
                }
                TextButton(onClick = { showModels = !showModels }) {
                    Text(if (showModels) "Skjul modelstyring" else "Modelstyring", color = Brand.Signal)
                }
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    OutlinedButton(onClick = { modelMenuOpen = true }) {
                        Text("Model: $localModel", color = Brand.TextHigh)
                    }
                    DropdownMenu(expanded = modelMenuOpen, onDismissRequest = { modelMenuOpen = false }) {
                        if (models.isEmpty()) {
                            DropdownMenuItem(text = { Text("(genindlæs modeller først)") }, onClick = { modelMenuOpen = false })
                        } else {
                            models.forEach { m ->
                                DropdownMenuItem(text = { Text(m) }, onClick = { localModel = m; modelMenuOpen = false })
                            }
                        }
                    }
                }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { loadModels() }) { Text("Genindlæs modeller", color = Brand.Signal) }
            }
            modelError?.let { Text("Modeller: $it", color = Brand.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(6.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(
                    checked = ragMode,
                    onCheckedChange = { on -> ragMode = on; if (on) loadRagSources() },
                )
                Spacer(Modifier.width(6.dp))
                Text("RAG-tilstand (mod rig'en, ikke lokal Ollama direkte/cloud)", color = Brand.TextMuted, fontSize = 12.sp)
                if (ragMode) {
                    Spacer(Modifier.width(10.dp))
                    Box {
                        OutlinedButton(onClick = { ragSourceMenuOpen = true }) {
                            Text(ragSourceFilter?.let { "Kilde: $it" } ?: "Alle kilder", color = Brand.TextHigh)
                        }
                        DropdownMenu(expanded = ragSourceMenuOpen, onDismissRequest = { ragSourceMenuOpen = false }) {
                            DropdownMenuItem(text = { Text("Alle kilder") }, onClick = { ragSourceFilter = null; ragSourceMenuOpen = false })
                            if (ragSources.isNotEmpty()) {
                                ragSources.forEach { s ->
                                    DropdownMenuItem(text = { Text(s) }, onClick = { ragSourceFilter = s; ragSourceMenuOpen = false })
                                }
                            } else {
                                DropdownMenuItem(text = { Text("(ingen kilder ingesteret endnu)") }, onClick = { ragSourceMenuOpen = false })
                            }
                        }
                    }
                    Spacer(Modifier.width(6.dp))
                    TextButton(onClick = { loadRagSources() }) { Text("Genindlæs kilder", color = Brand.Signal, fontSize = 12.sp) }
                }
            }
            ragError?.let { Text("RAG-kilder: $it", color = Brand.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(8.dp))

            // Exactly one weighted child at a time: either the (scrollable)
            // panel area or the chat list. Panels can grow to any height at
            // any window size without pushing the input row or their own
            // close-buttons out of reach; verticalScroll never wraps the
            // LazyColumn, so there's no same-direction nested-scroll conflict.
            val panelsOpen = showSettings || showConvos || showModels
            if (panelsOpen) {
                Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState())) {
                    if (showConvos) {
                        ConversationsPanel(
                            db = db,
                            onOpen = { id ->
                                scope.launch {
                                    val loaded = withContext(Dispatchers.IO) { db.loadMessages(id) }
                                    messages.clear()
                                    loaded.forEach { (role, content) -> messages.add(UiMessage(role, content)) }
                                    convId = id
                                    showConvos = false
                                }
                            },
                            onNew = {
                                messages.clear()
                                convId = null
                                showConvos = false
                            },
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                    if (showSettings) {
                        SettingsCard(
                            localUrl, { localUrl = it },
                            localPath, { localPath = it },
                            localModel, { localModel = it },
                            deviceToken, { deviceToken = it },
                            localSystem, { localSystem = it },
                            cloudKey, { cloudKey = it },
                            cloudModel, { cloudModel = it },
                            cloudSystem, { cloudSystem = it },
                            preferLocal, { preferLocal = it },
                            db,
                        )
                        Spacer(Modifier.height(8.dp))
                    }
                    if (showModels) {
                        ModelsPanel(
                            baseUrl = localUrl,
                            isBackend = localPath.contains("/api/v1/"),
                            bearer = deviceToken.ifBlank { null },
                            onModelsChanged = { models = it },
                        )
                    }
                }
            } else {
                LazyColumn(Modifier.weight(1f).fillMaxWidth()) {
                    items(messages) { m -> MessageBubble(m) }
                }
            }

            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                OutlinedTextField(
                    value = input,
                    onValueChange = { input = it },
                    modifier = Modifier.weight(1f),
                    placeholder = { Text("Skriv til modellen…") },
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

/**
 * Conversation browser: list, open, start new, delete. Deliberately scoped to
 * ONLY this confirmed-safe feature set (matches Android's original 0.16.0
 * conversation list, not the newer 0.20.6 search/rename/share) -- that newer
 * feature hasn't been on-device confirmed yet, and copying an unconfirmed UI
 * pattern to a second client is exactly the mistake the preset saga taught
 * to avoid. Closes desktop's only remaining gap versus Android: previously
 * this client only silently resumed the latest conversation with no way to
 * browse, switch, or clean up older ones.
 */
@Composable
private fun ConversationsPanel(db: DesktopChatDb, onOpen: (Long) -> Unit, onNew: () -> Unit) {
    var convos by remember { mutableStateOf(runCatching { db.listConversations() }.getOrElse { emptyList() }) }
    var panelError by remember { mutableStateOf<String?>(null) }
    val fmt = remember { SimpleDateFormat("d/M HH:mm", Locale.getDefault()) }

    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(Brand.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Samtaler", color = Brand.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onNew) { Text("+ Ny", color = Brand.Signal, fontSize = 12.sp) }
            }
            panelError?.let { Spacer(Modifier.height(4.dp)); Text("Fejl: $it", color = Brand.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(8.dp))
            if (convos.isEmpty()) {
                Text("Ingen samtaler endnu", color = Brand.TextMuted, fontSize = 13.sp)
            } else {
                convos.forEach { c ->
                    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                        Column(
                            Modifier.weight(1f).clip(RoundedCornerShape(6.dp)).clickable { onOpen(c.id) }.padding(vertical = 4.dp),
                        ) {
                            Text(c.title.ifBlank { "(uden titel)" }, color = Brand.TextHigh, fontSize = 13.sp, maxLines = 1)
                            Text(
                                "${c.source} · ${fmt.format(Date(c.updatedAt))}",
                                color = Brand.TextMuted, fontSize = 11.sp,
                            )
                        }
                        TextButton(onClick = {
                            runCatching {
                                db.deleteConversation(c.id)
                                convos = db.listConversations()
                            }.onFailure { panelError = it.message }
                        }) { Text("Slet", color = Brand.Danger, fontSize = 12.sp) }
                    }
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
            ChatResult.Source.LOCAL -> { label = "RIG"; Brand.Signal }
            ChatResult.Source.CLOUD -> { label = "CLOUD"; Brand.Amber }
            null -> { label = "—"; Brand.TextMuted }
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
        isUser -> "dig"
        m.source == ChatResult.Source.CLOUD -> "modelrig · cloud"
        m.source == ChatResult.Source.LOCAL -> "modelrig · rig"
        else -> "modelrig"
    }
    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Text(badge, color = Brand.TextMuted, fontSize = 11.sp)
        Spacer(Modifier.height(2.dp))
        Box(Modifier.clip(RoundedCornerShape(10.dp)).background(bg).fillMaxWidth().padding(12.dp)) {
            Column {
                if (!isUser && m.ragSources.isNotEmpty()) {
                    Row(Modifier.padding(bottom = 6.dp)) {
                        m.ragSources.take(4).forEach { s ->
                            Box(
                                Modifier.clip(RoundedCornerShape(999.dp))
                                    .background(Brand.SurfaceHigh)
                                    .padding(horizontal = 8.dp, vertical = 3.dp),
                            ) {
                                Text(s, fontSize = 10.sp, color = Brand.TextMuted)
                            }
                            Spacer(Modifier.width(4.dp))
                        }
                    }
                }
                when {
                    isUser -> Text(m.text, color = Brand.TextHigh, fontSize = 14.sp)
                    m.streaming && m.text.isEmpty() -> Text("…", color = Brand.TextMuted, fontSize = 14.sp)
                    m.streaming -> Text(m.text + "▍", color = Brand.TextHigh, fontSize = 14.sp)
                    else -> MarkdownText(m.text, color = Brand.TextHigh)
                }
            }
        }
    }
}

@Composable
private fun SettingsCard(
    localUrl: String, onLocalUrl: (String) -> Unit,
    localPath: String, onLocalPath: (String) -> Unit,
    localModel: String, onLocalModel: (String) -> Unit,
    token: String, onToken: (String) -> Unit,
    localSystem: String, onLocalSystem: (String) -> Unit,
    cloudKey: String, onCloudKey: (String) -> Unit,
    cloudModel: String, onCloudModel: (String) -> Unit,
    cloudSystem: String, onCloudSystem: (String) -> Unit,
    preferLocal: Boolean, onPreferLocal: (Boolean) -> Unit,
    db: DesktopChatDb,
) {
    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(Brand.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Text("Forbindelse", color = Brand.TextHigh, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("Lokal base-URL (Ollama eller ModelRig-backend)", localUrl, onLocalUrl)
            Field("Lokal chat-sti (/api/chat direkte · /api/v1/chat via backend)", localPath, onLocalPath)
            Field("Lokal model", localModel, onLocalModel)
            Field("Enhedstoken (kun ved brug af ModelRig-backend)", token, onToken)
            Field("System-instruktion, lokal (valgfri)", localSystem, onLocalSystem)
            PresetRow(db, "rig", localSystem, onLocalSystem)
            Spacer(Modifier.height(8.dp))
            Text("Ollama Cloud-fallback", color = Brand.Amber, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("OLLAMA_API_KEY", cloudKey, onCloudKey)
            Field("Cloud-model (fx gpt-oss:120b-cloud)", cloudModel, onCloudModel)
            Field("System-instruktion, cloud (valgfri)", cloudSystem, onCloudSystem)
            PresetRow(db, "cloud", cloudSystem, onCloudSystem)
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = preferLocal, onCheckedChange = onPreferLocal)
                Spacer(Modifier.width(8.dp))
                Text("Foretræk lokal, brug cloud som fallback", color = Brand.TextMuted, fontSize = 13.sp)
            }
        }
    }
}

/**
 * Saved system-instruction presets for one source ("rig" or "cloud"), shown as
 * chips under the system-instruction field. Inline save flow (no dialog) --
 * the pattern Anders confirmed working on-device in Android 0.20.4, after the
 * original dialog-based flow (0.19.8/0.19.9) failed on-device with a root
 * cause that couldn't be pinned down remotely. Ported here for parity AFTER
 * that confirmation, not before.
 */
@Composable
private fun PresetRow(db: DesktopChatDb, source: String, currentPrompt: String, onApply: (String) -> Unit) {
    var presets by remember { mutableStateOf(runCatching { db.listPresets(source) }.getOrElse { emptyList() }) }
    var saving by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var presetError by remember { mutableStateOf<String?>(null) }

    Spacer(Modifier.height(4.dp))
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        presets.forEach { p ->
            Box(
                Modifier.clip(RoundedCornerShape(999.dp)).background(Brand.SurfaceHigh),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p.prompt) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = Brand.TextHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deletePreset(p.id)
                                presets = db.listPresets(source)
                            }.onFailure { presetError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = Brand.TextMuted, fontSize = 11.sp) }
                }
            }
            Spacer(Modifier.width(6.dp))
        }
        TextButton(
            enabled = currentPrompt.isNotBlank(),
            onClick = { saving = !saving; presetError = null },
            contentPadding = PaddingValues(horizontal = 8.dp),
        ) {
            Text(
                if (saving) "− Annullér" else "+ Gem som preset",
                color = if (currentPrompt.isNotBlank()) Brand.Signal else Brand.TextMuted,
                fontSize = 12.sp,
            )
        }
    }

    if (saving) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = newName, onValueChange = { newName = it },
                label = { Text("Preset-navn (fx \"Kort & teknisk\")", fontSize = 12.sp) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            TextButton(
                enabled = newName.isNotBlank(),
                onClick = {
                    runCatching {
                        db.savePreset(source, newName.trim(), currentPrompt)
                        presets = db.listPresets(source)
                        newName = ""; saving = false
                    }.onFailure { presetError = "Kunne ikke gemme: ${it.message}" }
                },
            ) { Text("Gem", color = if (newName.isNotBlank()) Brand.Signal else Brand.TextMuted, fontWeight = FontWeight.Bold) }
        }
    }
    presetError?.let { Text(it, color = Brand.Danger, fontSize = 11.sp) }
}

/**
 * Model administration panel: installed models (size + delete), running
 * models (VRAM), and pulling a new model with live progress. Works against
 * either local Ollama directly or the backend, using the same path-derivation
 * as loadModels() ("/api/v1/..." when going via the backend, "/api/..." when
 * talking to Ollama directly) -- same feature as Android's Modeller screen.
 */
@Composable
private fun ModelsPanel(baseUrl: String, isBackend: Boolean, bearer: String?, onModelsChanged: (List<String>) -> Unit) {
    val scope = rememberCoroutineScope()
    val runningPath = if (isBackend) "/api/v1/models/running" else "/api/ps"
    val pullPath = if (isBackend) "/api/v1/models/pull" else "/api/pull"
    val deletePath = if (isBackend) "/api/v1/models/delete" else "/api/delete"
    val tagsPath = if (isBackend) "/api/v1/models" else "/api/tags"

    var installed by remember { mutableStateOf<List<OllamaClient.ModelInfo>>(emptyList()) }
    var running by remember { mutableStateOf<List<OllamaClient.RunningModel>>(emptyList()) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var pullName by remember { mutableStateOf("") }
    var pulling by remember { mutableStateOf(false) }
    var pullStatus by remember { mutableStateOf<String?>(null) }
    var pullErr by remember { mutableStateOf<String?>(null) }
    var confirmDelete by remember { mutableStateOf<String?>(null) }

    fun refresh() {
        scope.launch {
            val client = OllamaClient(baseUrl = baseUrl, bearer = bearer)
            val res = withContext(Dispatchers.IO) {
                runCatching { client.listModelsDetailed(tagsPath) to client.listRunningModels(runningPath) }
            }
            res.onSuccess { (i, r) ->
                installed = i; running = r; loadError = null
                onModelsChanged(i.map { it.name })
            }.onFailure { loadError = it.message }
        }
    }
    LaunchedEffect(Unit) { refresh() }

    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(Brand.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Modelstyring", color = Brand.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { refresh() }) { Text("Genindlæs", color = Brand.Signal, fontSize = 12.sp) }
            }
            loadError?.let { Spacer(Modifier.height(4.dp)); Text("Fejl: $it", color = Brand.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(10.dp))

            Text("Hent ny model", color = Brand.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = pullName, onValueChange = { pullName = it },
                    placeholder = { Text("fx llama3.2:3b", fontSize = 12.sp) },
                    singleLine = true, enabled = !pulling,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = !pulling && pullName.isNotBlank(),
                    onClick = {
                        val name = pullName.trim()
                        pulling = true; pullErr = null; pullStatus = "Starter…"
                        scope.launch {
                            val client = OllamaClient(baseUrl = baseUrl, bearer = bearer)
                            val err = withContext(Dispatchers.IO) {
                                runCatching {
                                    client.pullModel(name, pullPath) { status, completed, total ->
                                        pullStatus = if (total > 0) {
                                            "$status (${completed * 100 / total}% — ${completed / 1_000_000}MB/${total / 1_000_000}MB)"
                                        } else status
                                    }
                                }.exceptionOrNull()
                            }
                            pulling = false
                            if (err != null) { pullErr = err.message; pullStatus = null }
                            else { pullStatus = "Færdig: $name"; pullName = ""; refresh() }
                        }
                    },
                ) { Text(if (pulling) "Henter…" else "Hent") }
            }
            pullStatus?.let { Text(it, color = Brand.Signal, fontSize = 11.sp) }
            pullErr?.let { Text("Fejl: $it", color = Brand.Danger, fontSize = 11.sp) }

            Spacer(Modifier.height(10.dp))
            Text("Kører nu", color = Brand.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (running.isEmpty()) {
                Text("Ingen modeller i hukommelsen", color = Brand.TextMuted, fontSize = 12.sp)
            } else {
                running.forEach { m ->
                    Text("${m.name} — ${m.sizeVramBytes / 1_000_000_000.0} GB VRAM", color = Brand.TextHigh, fontSize = 12.sp)
                }
            }

            Spacer(Modifier.height(10.dp))
            Text("Installeret", color = Brand.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            installed.forEach { m ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("${m.name} — ${m.sizeBytes / 1_000_000_000.0} GB", color = Brand.TextHigh, fontSize = 12.sp, modifier = Modifier.weight(1f))
                    TextButton(onClick = { confirmDelete = m.name }) { Text("Slet", color = Brand.Danger, fontSize = 11.sp) }
                }
            }
        }
    }

    confirmDelete?.let { name ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Slet $name?") },
            text = { Text("Kan ikke fortrydes — modellen skal hentes igen for at bruges.", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    scope.launch {
                        val client = OllamaClient(baseUrl = baseUrl, bearer = bearer)
                        val err = withContext(Dispatchers.IO) { runCatching { client.deleteModel(name, deletePath) }.exceptionOrNull() }
                        if (err == null) refresh() else loadError = err.message
                    }
                }) { Text("Slet", color = Brand.Danger) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Annullér", color = Brand.TextMuted) } },
        )
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

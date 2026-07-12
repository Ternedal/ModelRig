package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Spacer
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.ChatMessage
import dk.ternedal.modelrig.desktop.net.ChatResult
import dk.ternedal.modelrig.desktop.net.ChatRouter
import dk.ternedal.modelrig.desktop.net.OllamaClient
import dk.ternedal.modelrig.desktop.net.RagClient
import dk.ternedal.modelrig.desktop.net.ToolsClient
import dk.ternedal.modelrig.desktop.net.ToolTurn
import dk.ternedal.modelrig.desktop.net.AuditEntry
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
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


// Kaliv's default persona -- kept identical to the Android TokenStore.DEFAULT_SYSTEM.
// Without it, an untethered instruct model becomes the eager emoji-drenched
// hygge-bot. Both modules carry their own copy since they don't share code.
private const val DEFAULT_SYSTEM =
    "Du er Kaliv, en personlig AI-assistent der k\u00f8rer p\u00e5 Anders' egen maskine. " +
    "Du taler dansk, medmindre du bliver bedt om andet.\n\n" +
    "ABSOLUT VIGTIGST \u2014 tone:\n" +
    "- INGEN emojis. Slet ingen. Aldrig.\n" +
    "- Ingen udr\u00e5bstegn-begejstring. Ingen \"hyggeligt at h\u00f8re fra dig\", ingen " +
    "\"jeg er her for dig\", ingen \"jeg er altid klar til at assistere dig\".\n" +
    "- Svar KORT. Et \"hej\" besvares med \u00e9t \"Hej\" eller \"Hej \u2014 hvad s\u00e5?\", ikke mere.\n" +
    "- Skriv som en kompetent voksen kollega, ikke som en kundeservice-bot.\n\n" +
    "Eksempel p\u00e5 HVORDAN du IKKE svarer:\n" +
    "  Bruger: hej\n" +
    "  D\u00c5RLIGT: \"Hej! Det er s\u00e5 hyggeligt at h\u00f8re fra dig! Jeg er altid klar til at assistere dig!\"\n" +
    "  GODT: \"Hej. Hvad kan jeg hj\u00e6lpe med?\"\n\n" +
    "Indhold:\n" +
    "- V\u00e6r konkret og \u00e6rlig. Ved du ikke noget, s\u00e5 sig det. Find ikke p\u00e5.\n" +
    "- Du er en lokal assistent med v\u00e6rkt\u00f8jer (bl.a. l\u00e6se riggens status og " +
    "tilf\u00f8je noter) n\u00e5r de er sl\u00e5et til. Kald et v\u00e6rkt\u00f8j n\u00e5r det giver mening."

@Composable
fun App() {
    // The DB comes FIRST now: settings persist across launches (v1.35.0).
    // Before this, the desktop forgot everything -- URL, token, systems --
    // unless supplied via env vars every start. Env still wins as an
    // explicit override; the DB remembers what you typed.
    val db = remember { DesktopChatDb() }
    fun setting(key: String, env: String?, default: String): String =
        System.getenv(env ?: "")?.takeIf { it.isNotBlank() }
            ?: db.getSetting(key) ?: default

    var darkMode by remember { mutableStateOf(db.getSetting("darkMode") != "false") }
    KalivTheme(dark = darkMode) {
        var localUrl by remember { mutableStateOf(setting("localUrl", "MODELRIG_LOCAL_URL", "http://localhost:11434")) }
        var localPath by remember { mutableStateOf(setting("localPath", null, "/api/chat")) }
        var localModel by remember { mutableStateOf(setting("localModel", null, "hermes3:8b")) }
        var deviceToken by remember { mutableStateOf(setting("deviceToken", "MODELRIG_TOKEN", "")) }
        var cloudKey by remember { mutableStateOf(setting("cloudKey", "OLLAMA_API_KEY", "")) }
        var cloudModel by remember { mutableStateOf(setting("cloudModel", null, "gpt-oss:120b-cloud")) }
        var localSystem by remember { mutableStateOf(setting("localSystem", null, DEFAULT_SYSTEM).ifBlank { DEFAULT_SYSTEM }) }
        var cloudSystem by remember { mutableStateOf(setting("cloudSystem", null, DEFAULT_SYSTEM).ifBlank { DEFAULT_SYSTEM }) }
        var preferLocal by remember { mutableStateOf(db.getSetting("preferLocal") != "false") }
        var showSettings by remember { mutableStateOf(true) }
        var toolsMode by remember { mutableStateOf(db.getSetting("toolsMode") == "true") }
        var pendingCard by remember { mutableStateOf<ToolTurn?>(null) }
        var showAudit by remember { mutableStateOf(false) }
        var auditRows by remember { mutableStateOf(listOf<AuditEntry>()) }
        var auditError by remember { mutableStateOf<String?>(null) }
        var pairStatus by remember { mutableStateOf<String?>(null) }
        fun persist(key: String, value: String) {
            try { db.putSetting(key, value) } catch (_: Exception) {}
        }

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
                res.onSuccess { models = it; modelError = null }.onFailure { modelError = apiErrorHint(it.message) }
            }
        }

        fun loadRagSources() {
            scope.launch {
                val res = withContext(Dispatchers.IO) {
                    runCatching { RagClient(localUrl, deviceToken.ifBlank { null }).listSources() }
                }
                res.onSuccess { ragSources = it; ragError = null }.onFailure { ragError = apiErrorHint(it.message) }
            }
        }

        fun send() {
            val text = input.trim()
            if (text.isEmpty() || busy) return
            // History for the tools path: the turns BEFORE this message --
            // the worker gets the new message in its own field (Android parity).
            val priorPairs = messages
                .filter { it.role == "user" || it.role == "assistant" }
                .map { it.role to it.text }
            messages.add(UiMessage("user", text))
            input = ""
            busy = true
            if (toolsMode) {
                // V5 on the desktop: non-streaming by necessity (the worker
                // must see the whole response to detect a tool call), the
                // confirmation card enforced by the WORKER -- this client can
                // only render it, never bypass it.
                val sysT = localSystem.trim().takeIf { it.isNotEmpty() }
                val assistantIdxT = messages.size
                messages.add(UiMessage("assistant", "", null, streaming = true))
                scope.launch {
                    val cid = withContext(Dispatchers.IO) {
                        val id = convId ?: db.newConversation(source = "tools", model = localModel, title = text)
                        db.addMessage(id, "user", text)
                        id
                    }
                    if (convId == null) convId = cid
                    val res = withContext(Dispatchers.IO) {
                        runCatching {
                            ToolsClient(localUrl, deviceToken.ifBlank { null })
                                .toolsChat(text, localModel, priorPairs, sysT)
                        }
                    }
                    res.onSuccess { turn ->
                        when (turn.status) {
                            "confirmation_required" -> {
                                messages[assistantIdxT] = messages[assistantIdxT].copy(
                                    text = "⚙ Kaliv foreslår: ${turn.summary.ifBlank { turn.tool }}",
                                    streaming = false,
                                )
                                pendingCard = turn
                            }
                            else -> {
                                val ans = turn.answer.ifBlank { "(tomt svar, status: ${turn.status})" }
                                messages[assistantIdxT] = messages[assistantIdxT].copy(text = ans, streaming = false)
                                withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", ans) }
                            }
                        }
                    }.onFailure { e ->
                        messages[assistantIdxT] = messages[assistantIdxT].copy(
                            text = "Fejl: ${apiErrorHint(e.message)}", streaming = false,
                        )
                    }
                    busy = false
                }
                return
            }
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
                    else if (cur.text.isEmpty()) "Fejl: ${apiErrorHint(err.message)}"
                    else cur.text + "\n[afbrudt: ${err.message}]"
                messages[assistantIdx] = cur.copy(text = msg, streaming = false)
                if (err == null || cancelled) {
                    val finalText = messages[assistantIdx].text
                    withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", finalText) }
                }
                busy = false
            }
        }

        Column(Modifier.fillMaxSize().background(KalivTheme.colors.Graphite).padding(16.dp)) {
            Header(
                source = lastSource,
                dark = darkMode,
                onToggleDark = { darkMode = !darkMode; persist("darkMode", darkMode.toString()) },
                onAudit = { showAudit = true },
            )
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
                    Text(if (showSettings) "Skjul indstillinger" else "Indstillinger", color = KalivTheme.colors.Signal)
                }
                TextButton(onClick = { showConvos = !showConvos }) {
                    Text(if (showConvos) "Skjul samtaler" else "Samtaler", color = KalivTheme.colors.Signal)
                }
                TextButton(onClick = { showModels = !showModels }) {
                    Text(if (showModels) "Skjul modelstyring" else "Modelstyring", color = KalivTheme.colors.Signal)
                }
            }

            Row(verticalAlignment = Alignment.CenterVertically) {
                Box {
                    OutlinedButton(onClick = { modelMenuOpen = true }) {
                        Text("Model: $localModel", color = KalivTheme.colors.TextHigh)
                    }
                    DropdownMenu(expanded = modelMenuOpen, onDismissRequest = { modelMenuOpen = false }) {
                        if (models.isEmpty()) {
                            DropdownMenuItem(text = { Text("(genindlæs modeller først)") }, onClick = { modelMenuOpen = false })
                        } else {
                            models.forEach { m ->
                                DropdownMenuItem(text = { Text(m) }, onClick = { localModel = m; persist("localModel", m); modelMenuOpen = false })
                            }
                        }
                    }
                }
                Spacer(Modifier.width(8.dp))
                TextButton(onClick = { loadModels() }) { Text("Genindlæs modeller", color = KalivTheme.colors.Signal) }
            }
            modelError?.let { Text("Modeller: $it", color = KalivTheme.colors.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(6.dp))

            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(
                    checked = ragMode,
                    onCheckedChange = { on -> ragMode = on; if (on) loadRagSources() },
                )
                Spacer(Modifier.width(6.dp))
                Text("RAG-tilstand (mod rig'en, ikke lokal Ollama direkte/cloud)", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                if (ragMode) {
                    Spacer(Modifier.width(10.dp))
                    Box {
                        OutlinedButton(onClick = { ragSourceMenuOpen = true }) {
                            Text(ragSourceFilter?.let { "Kilde: $it" } ?: "Alle kilder", color = KalivTheme.colors.TextHigh)
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
                    TextButton(onClick = { loadRagSources() }) { Text("Genindlæs kilder", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
                }
            }
            ragError?.let { Text("RAG-kilder: $it", color = KalivTheme.colors.Danger, fontSize = 11.sp) }
            Row(verticalAlignment = Alignment.CenterVertically) {
                val toolsReady = localPath.contains("/api/v1/") && deviceToken.isNotBlank()
                Switch(
                    checked = toolsMode && toolsReady,
                    onCheckedChange = { on -> toolsMode = on; persist("toolsMode", on.toString()) },
                    enabled = toolsReady,
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    if (toolsReady) "Tools-tilstand (agent — hver skrivning kræver din godkendelse)"
                    else "Tools kræver backend-sti (/api/v1/…) og parring — se Indstillinger",
                    color = KalivTheme.colors.TextMuted, fontSize = 12.sp,
                )
            }
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
                            localUrl, { localUrl = it; persist("localUrl", it) },
                            localPath, { localPath = it; persist("localPath", it) },
                            localModel, { localModel = it; persist("localModel", it) },
                            deviceToken, { deviceToken = it; persist("deviceToken", it) },
                            localSystem, { localSystem = it; persist("localSystem", it) },
                            cloudKey, { cloudKey = it; persist("cloudKey", it) },
                            cloudModel, { cloudModel = it; persist("cloudModel", it) },
                            cloudSystem, { cloudSystem = it; persist("cloudSystem", it) },
                            preferLocal, { preferLocal = it; persist("preferLocal", it.toString()) },
                            db,
                            onPair = {
                                pairStatus = "parrer…"
                                scope.launch {
                                    val res = withContext(Dispatchers.IO) {
                                        runCatching { ToolsClient(localUrl, null).pair("Kaliv Desktop") }
                                    }
                                    res.onSuccess {
                                        deviceToken = it; persist("deviceToken", it)
                                        pairStatus = "Parret ✓ — token gemt"
                                    }.onFailure {
                                        pairStatus = "Parring fejlede: ${apiErrorHint(it.message)}"
                                    }
                                }
                            },
                            pairStatus = pairStatus,
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

        // The confirmation card -- V5's core promise, now on the desktop.
        // Rendering only: the gate lives in the worker, so a modified client
        // cannot skip it. Deny is a first-class action, not a dismiss.
        pendingCard?.let { card ->
            fun decide(approve: Boolean) {
                val id = card.confirmation_id
                pendingCard = null
                busy = true
                scope.launch {
                    val res = withContext(Dispatchers.IO) {
                        runCatching {
                            ToolsClient(localUrl, deviceToken.ifBlank { null })
                                .toolsConfirm(id, approve)
                        }
                    }
                    val text = res.fold(
                        onSuccess = { it.answer.ifBlank { if (approve) "Udført." else "Afvist." } },
                        onFailure = { "Fejl: ${apiErrorHint(it.message)}" },
                    )
                    messages.add(UiMessage("assistant", text))
                    val cid = convId
                    if (cid != null) withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", text) }
                    busy = false
                }
            }
            AlertDialog(
                onDismissRequest = { /* et kort lukkes med et VALG, ikke et klik udenfor */ },
                title = { Text("Kaliv vil bruge et værktøj", fontWeight = FontWeight.SemiBold) },
                text = { Text(card.summary.ifBlank { card.tool }) },
                confirmButton = { Button(onClick = { decide(true) }) { Text("Godkend") } },
                dismissButton = { OutlinedButton(onClick = { decide(false) }) { Text("Afvis") } },
            )
        }

        if (showAudit) {
            LaunchedEffect(Unit) {
                val res = withContext(Dispatchers.IO) {
                    runCatching { ToolsClient(localUrl, deviceToken.ifBlank { null }).toolsAudit(50) }
                }
                res.onSuccess { auditRows = it; auditError = null }
                    .onFailure { auditError = apiErrorHint(it.message) }
            }
            AlertDialog(
                onDismissRequest = { showAudit = false },
                title = { Text("Handlingslog", fontWeight = FontWeight.SemiBold) },
                text = {
                    Column(Modifier.verticalScroll(rememberScrollState()).height(360.dp)) {
                        auditError?.let { Text(it, color = KalivTheme.colors.Danger, fontSize = 12.sp) }
                        if (auditRows.isEmpty() && auditError == null)
                            Text("(ingen handlinger endnu)", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                        auditRows.forEach { e ->
                            Text(
                                "${e.ts.take(19).replace('T', ' ')}  ·  ${e.tool}  ·  ${e.outcome}" +
                                    (if (e.origin != "local") "  ·  ${e.origin}" else "") +
                                    (if (e.result_summary.isNotBlank()) "\n    ${e.result_summary}" else ""),
                                color = KalivTheme.colors.TextHigh, fontSize = 12.sp,
                                modifier = Modifier.padding(vertical = 4.dp),
                            )
                        }
                    }
                },
                confirmButton = { TextButton(onClick = { showAudit = false }) { Text("Luk") } },
            )
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
    var query by remember { mutableStateOf("") }
    var renamingId by remember { mutableStateOf<Long?>(null) }
    var renameText by remember { mutableStateOf("") }
    var copiedId by remember { mutableStateOf<Long?>(null) }
    val clipboard = LocalClipboardManager.current
    val fmt = remember { SimpleDateFormat("d/M HH:mm", Locale.getDefault()) }

    // Live title filter -- mirrors Android's conversation search (0.20.6).
    val shown = remember(convos, query) {
        if (query.isBlank()) convos
        else convos.filter { it.title.contains(query, ignoreCase = true) }
    }

    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(KalivTheme.colors.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Samtaler", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onNew) { Text("+ Ny", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
            }
            panelError?.let { Spacer(Modifier.height(4.dp)); Text("Fejl: $it", color = KalivTheme.colors.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = query, onValueChange = { query = it },
                placeholder = { Text("Søg i titler…", fontSize = 12.sp, color = KalivTheme.colors.TextMuted) },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            if (convos.isEmpty()) {
                Text("Ingen samtaler endnu", color = KalivTheme.colors.TextMuted, fontSize = 13.sp)
            } else if (shown.isEmpty()) {
                Text("Ingen match på \"$query\"", color = KalivTheme.colors.TextMuted, fontSize = 13.sp)
            } else {
                shown.forEach { c ->
                    if (renamingId == c.id) {
                        // Inline rename row -- same inline-field pattern as presets.
                        Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                            OutlinedTextField(
                                value = renameText, onValueChange = { renameText = it },
                                singleLine = true, modifier = Modifier.weight(1f),
                            )
                            TextButton(onClick = {
                                runCatching {
                                    db.renameConversation(c.id, renameText.trim())
                                    convos = db.listConversations()
                                }.onFailure { panelError = it.message }
                                renamingId = null
                            }) { Text("Gem", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
                            TextButton(onClick = { renamingId = null }) {
                                Text("Annullér", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                            }
                        }
                    } else {
                        Row(Modifier.fillMaxWidth().padding(vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(
                                Modifier.weight(1f).clip(RoundedCornerShape(6.dp)).clickable { onOpen(c.id) }.padding(vertical = 4.dp),
                            ) {
                                Text(c.title.ifBlank { "(uden titel)" }, color = KalivTheme.colors.TextHigh, fontSize = 13.sp, maxLines = 1)
                                Text(
                                    "${c.source} · ${fmt.format(Date(c.updatedAt))}",
                                    color = KalivTheme.colors.TextMuted, fontSize = 11.sp,
                                )
                            }
                            TextButton(onClick = { renamingId = c.id; renameText = c.title }) {
                                Text("✎", color = KalivTheme.colors.Signal, fontSize = 13.sp)
                            }
                            TextButton(onClick = {
                                runCatching {
                                    clipboard.setText(AnnotatedString(db.conversationAsMarkdown(c.id)))
                                    copiedId = c.id
                                }.onFailure { panelError = it.message }
                            }) {
                                Text(if (copiedId == c.id) "Kopieret" else "Kopiér", color = KalivTheme.colors.Signal, fontSize = 12.sp)
                            }
                            TextButton(onClick = {
                                runCatching {
                                    db.deleteConversation(c.id)
                                    convos = db.listConversations()
                                }.onFailure { panelError = it.message }
                            }) { Text("Slet", color = KalivTheme.colors.Danger, fontSize = 12.sp) }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun Header(
    source: ChatResult.Source?,
    dark: Boolean,
    onToggleDark: () -> Unit,
    onAudit: () -> Unit,
) {
    Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
        // Wordmark = the clean letter-spaced KALIV plus the ankh symbol. User-
        // facing is Kaliv; only the backend is ModelRig. (The textured wordmark
        // image read as clutter next to the text, so we use the ankh mark instead.)
        runCatching {
            painterResource(if (dark) "kaliv_symbol_dark.png" else "kaliv_symbol_light.png")
        }.getOrNull()?.let {
            Image(painter = it, contentDescription = null, modifier = Modifier.size(26.dp))
            Spacer(Modifier.width(8.dp))
        }
        Text("KALIV", color = KalivTheme.colors.Amber, fontSize = 22.sp,
             fontWeight = FontWeight.Bold, letterSpacing = 4.sp)
        Spacer(Modifier.width(12.dp))
        val srcLabel = when (source) {
            ChatResult.Source.LOCAL -> "svar: rig"
            ChatResult.Source.CLOUD -> "svar: cloud"
            null -> ""
        }
        if (srcLabel.isNotEmpty())
            Text(srcLabel, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
        Spacer(Modifier.weight(1f))
        TextButton(onClick = onAudit) { Text("Handlingslog", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
        TextButton(onClick = onToggleDark) {
            Text(if (dark) "Lys tilstand" else "Mørk tilstand", color = KalivTheme.colors.Signal, fontSize = 12.sp)
        }
    }
}

@Composable
private fun MessageBubble(m: UiMessage) {
    val isUser = m.role == "user"
    // Match the mobile app: the user's bubble is bronze with ivory ink (6.2:1,
    // measured), the assistant's is the raised surface. Bubbles are aligned
    // (user right, assistant left), constrained to ~82% width, with the ankh-tail
    // corner -- not full-width grey boxes stacked like a 90s form.
    val bg = if (isUser) KalivTheme.colors.Signal else KalivTheme.colors.SurfaceHigh
    val fg = if (isUser) Color(0xFFF3EFE6) else KalivTheme.colors.TextHigh
    val label = when {
        isUser -> null // the alignment already says who
        m.source == ChatResult.Source.CLOUD -> "☁ Kaliv · cloud"
        m.source == ChatResult.Source.LOCAL -> "◈ Kaliv · rig"
        else -> "Kaliv"
    }
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Column(
            Modifier.widthIn(max = 640.dp),
            horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
        ) {
            if (label != null) {
                Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Spacer(Modifier.height(3.dp))
            }
            Box(
                Modifier
                    .clip(
                        RoundedCornerShape(
                            topStart = 16.dp, topEnd = 16.dp,
                            bottomStart = if (isUser) 16.dp else 4.dp,
                            bottomEnd = if (isUser) 4.dp else 16.dp,
                        )
                    )
                    .background(bg)
                    .padding(horizontal = 14.dp, vertical = 10.dp),
            ) {
                Column {
                    if (!isUser && m.ragSources.isNotEmpty()) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            m.ragSources.distinct().take(4).forEach { s ->
                                Box(
                                    Modifier.clip(RoundedCornerShape(999.dp))
                                        .background(KalivTheme.colors.Surface)
                                        .padding(horizontal = 8.dp, vertical = 3.dp),
                                ) {
                                    Text(s, fontSize = 10.sp, color = KalivTheme.colors.TextMuted)
                                }
                                Spacer(Modifier.width(4.dp))
                            }
                        }
                    }
                    when {
                        isUser -> Text(m.text, color = fg, fontSize = 15.sp, lineHeight = 21.sp)
                        m.streaming && m.text.isEmpty() -> DesktopThinking()
                        m.streaming -> Text(m.text + "▍", color = fg, fontSize = 15.sp, lineHeight = 21.sp)
                        else -> MarkdownText(m.text, color = fg)
                    }
                }
            }
        }
    }
}

// The Kaliv thinking animation in the assistant bubble while the reply is still
// empty -- the desktop counterpart of the mobile ThinkingIndicator. The asset is
// an animated WebP; painterResource draws only the first frame, so on desktop we
// decode the frames and drive them with a small timer.
@Composable
private fun DesktopThinking() {
    val painter = runCatching { painterResource("kaliv_thinking.webp") }.getOrNull()
    if (painter != null) {
        Image(painter = painter, contentDescription = "tænker", modifier = Modifier.size(40.dp))
    } else {
        Text("…", color = KalivTheme.colors.TextMuted, fontSize = 15.sp, lineHeight = 21.sp)
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
    onPair: () -> Unit,
    pairStatus: String?,
) {
    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(KalivTheme.colors.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("Base-URL (Ollama direkte, eller rig'ens backend :8080)", localUrl, onLocalUrl)
            Field("Lokal chat-sti (/api/chat direkte · /api/v1/chat via backend)", localPath, onLocalPath)
            Field("Lokal model", localModel, onLocalModel)
            Field("Enhedstoken (kun ved brug af backenden)", token, onToken)
            Row(verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onPair) { Text("Par med rig (dev-mode)", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
                pairStatus?.let { Spacer(Modifier.width(8.dp)); Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.sp) }
            }
            Field("System-instruktion, lokal (valgfri)", localSystem, onLocalSystem)
            PresetRow(db, "rig", localSystem, onLocalSystem)
            Spacer(Modifier.height(8.dp))
            Text("Ollama Cloud-fallback", color = KalivTheme.colors.Amber, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Field("OLLAMA_API_KEY", cloudKey, onCloudKey)
            Field("Cloud-model (fx gpt-oss:120b-cloud)", cloudModel, onCloudModel)
            Field("System-instruktion, cloud (valgfri)", cloudSystem, onCloudSystem)
            PresetRow(db, "cloud", cloudSystem, onCloudSystem)
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Switch(checked = preferLocal, onCheckedChange = onPreferLocal)
                Spacer(Modifier.width(8.dp))
                Text("Foretræk lokal, brug cloud som fallback", color = KalivTheme.colors.TextMuted, fontSize = 13.sp)
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
                Modifier.clip(RoundedCornerShape(999.dp)).background(KalivTheme.colors.SurfaceHigh),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p.prompt) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = KalivTheme.colors.TextHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deletePreset(p.id)
                                presets = db.listPresets(source)
                            }.onFailure { presetError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = KalivTheme.colors.TextMuted, fontSize = 11.sp) }
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
                color = if (currentPrompt.isNotBlank()) KalivTheme.colors.Signal else KalivTheme.colors.TextMuted,
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
            ) { Text("Gem", color = if (newName.isNotBlank()) KalivTheme.colors.Signal else KalivTheme.colors.TextMuted, fontWeight = FontWeight.Bold) }
        }
    }
    presetError?.let { Text(it, color = KalivTheme.colors.Danger, fontSize = 11.sp) }
}

/**
 * Model administration panel: installed models (size + delete), running
 * models (VRAM), and pulling a new model with live progress. Works against
 * either local Ollama directly or the backend, using the same path-derivation
 * as loadModels() ("/api/v1/..." when going via the backend, "/api/..." when
 * talking to Ollama directly) -- same feature as Android's Modeller screen.
 */
/**
 * Decorates raw API error strings (e.g. "rag sources failed (401)") with a
 * one-line explanation of the two failure modes that actually bit during
 * on-device testing (6/7-2026): a missing/stale token (401 -- fresh server
 * data file, or the pairing CODE pasted where the claimed token belongs),
 * and pointing the client at raw Ollama while asking for backend-only
 * features (404 -- Ollama has no /rag or /api/v1 endpoints). The raw message
 * stays first so screenshots/logs still show the real status code.
 */
private fun apiErrorHint(raw: String?): String {
    val msg = raw.orEmpty()
    return when {
        // Ported from Android's friendlyError (v1.34.9): name the REAL cause.
        // "Tool layer disabled" masquerading as a timeout cost a whole hunt.
        msg.contains("tool layer is disabled") || msg.contains("(403)") ->
            "Tool-laget er slået fra på rig'en. Start workeren med KALIV_TOOLS_ENABLED=1."
        msg.contains("(401)") || msg.contains("401") ->
            "Ikke godkendt (401). Parringen mangler eller er udløbet — brug \"Par med rig\" under Indstillinger."
        msg.contains("(404)") ->
            "Ikke fundet (404). Tjek modelnavn og at stien er /api/v1/… mod backenden."
        msg.contains("(502)") || msg.contains("(503)") ->
            "Rig'en/Ollama svarer ikke (502/503). Tjek at stakken kører — start-kaliv.bat viser /health/full."
        msg.contains("timed out", ignoreCase = true) || msg.contains("HttpTimeout", ignoreCase = true) ->
            "Tidsudløb — modellen svarede ikke i tide. Første kolde load kan tage tid; prøv igen."
        msg.contains("Connection refused", ignoreCase = true) || msg.contains("ConnectException") ->
            "Kan ikke nå adressen. Kører serveren, og er URL'en rigtig (Tailscale-IP hvis WiFi er slået fra)?"
        msg.isEmpty() -> "ukendt fejl"
        else -> msg.take(300)
    }
}

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
            }.onFailure { loadError = apiErrorHint(it.message) }
        }
    }
    // Re-fetch when the connection settings change -- keyed on the actual
    // inputs instead of Unit, so a token pasted AFTER the panel was opened
    // clears the stale 401 by itself (bit Anders live 6/7-2026: the panel
    // kept showing its first, pre-token failure until a manual refresh).
    // The 400 ms delay is a debounce: these params change per KEYSTROKE
    // while typing in settings, and LaunchedEffect cancels the previous
    // block on every key change, so only the settled value fires a request.
    LaunchedEffect(baseUrl, isBackend, bearer) {
        delay(400)
        refresh()
    }

    Box(Modifier.clip(RoundedCornerShape(12.dp)).background(KalivTheme.colors.Surface).fillMaxWidth().padding(14.dp)) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Modelstyring", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { refresh() }) { Text("Genindlæs", color = KalivTheme.colors.Signal, fontSize = 12.sp) }
            }
            loadError?.let { Spacer(Modifier.height(4.dp)); Text("Fejl: $it", color = KalivTheme.colors.Danger, fontSize = 11.sp) }
            Spacer(Modifier.height(10.dp))

            Text("Hent ny model", color = KalivTheme.colors.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
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
            pullStatus?.let { Text(it, color = KalivTheme.colors.Signal, fontSize = 11.sp) }
            pullErr?.let { Text("Fejl: $it", color = KalivTheme.colors.Danger, fontSize = 11.sp) }

            Spacer(Modifier.height(10.dp))
            Text("Kører nu", color = KalivTheme.colors.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            if (running.isEmpty()) {
                Text("Ingen modeller i hukommelsen", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
            } else {
                running.forEach { m ->
                    Text("${m.name} — ${m.sizeVramBytes / 1_000_000_000.0} GB VRAM", color = KalivTheme.colors.TextHigh, fontSize = 12.sp)
                }
            }

            Spacer(Modifier.height(10.dp))
            Text("Installeret", color = KalivTheme.colors.TextMuted, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
            installed.forEach { m ->
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("${m.name} — ${m.sizeBytes / 1_000_000_000.0} GB", color = KalivTheme.colors.TextHigh, fontSize = 12.sp, modifier = Modifier.weight(1f))
                    TextButton(onClick = { confirmDelete = m.name }) { Text("Slet", color = KalivTheme.colors.Danger, fontSize = 11.sp) }
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
                        if (err == null) refresh() else loadError = apiErrorHint(err.message)
                    }
                }) { Text("Slet", color = KalivTheme.colors.Danger) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Annullér", color = KalivTheme.colors.TextMuted) } },
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

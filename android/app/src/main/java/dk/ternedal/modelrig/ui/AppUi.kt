package dk.ternedal.modelrig.ui

import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.platform.LocalConfiguration
import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.ChatDb
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.CloudClient
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class Screen { Setup, Chat, Convos, Models }

@Composable
fun AppUi() {
    ModelRigTheme {
        val context = LocalContext.current
        val store = remember { TokenStore(context) }
        val db = remember { ChatDb(context) }
        var screen by remember {
            mutableStateOf(if (store.hasRig || store.hasCloud) Screen.Chat else Screen.Setup)
        }
        // conversation to open in ChatScreen; null = start fresh / latest
        var openConvId by remember { mutableStateOf(db.latestConversationId()) }

        Surface(color = Graphite, modifier = Modifier.fillMaxSize()) {
            when (screen) {
                Screen.Setup -> SetupScreen(store, db, onDone = { screen = Screen.Chat })
                Screen.Chat -> ChatScreen(
                    store, db, openConvId,
                    onOpenSettings = { screen = Screen.Setup },
                    onOpenConversations = { screen = Screen.Convos },
                    onOpenModels = { screen = Screen.Models },
                    onConvChanged = { openConvId = it },
                )
                Screen.Convos -> ConversationsScreen(
                    db,
                    onOpen = { openConvId = it; screen = Screen.Chat },
                    onNew = { openConvId = null; screen = Screen.Chat },
                    onBack = { screen = Screen.Chat },
                )
                Screen.Models -> ModelsScreen(store, onBack = { screen = Screen.Chat })
            }
        }
    }
}

// ---- setup: cloud and/or rig ----
@Composable
private fun SetupScreen(store: TokenStore, db: ChatDb, onDone: () -> Unit) {
    var refresh by remember { mutableStateOf(0) }
    val canChat = remember(refresh) { store.hasRig || store.hasCloud }

    Column(
        Modifier
            .fillMaxSize()
            .windowInsetsPadding(WindowInsets.safeDrawing)
            .padding(20.dp)
            .verticalScroll(rememberScrollState()),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("ModelRig", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Spacer(Modifier.weight(1f))
            if (canChat) TextButton(onClick = onDone) { Text("Til chat →", color = Signal) }
        }
        Text("Vælg mindst én kilde", fontSize = 14.sp, color = TextMuted)
        Spacer(Modifier.height(16.dp))
        CloudCard(store, db) { refresh++; onDone() }
        Spacer(Modifier.height(16.dp))
        RigCard(store, db) { refresh++; onDone() }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun CloudCard(store: TokenStore, db: ChatDb, onSaved: () -> Unit) {
    var key by remember { mutableStateOf("") }
    var model by remember { mutableStateOf(store.cloudModel) }
    var system by remember { mutableStateOf(store.cloudSystem) }
    var configured by remember { mutableStateOf(store.hasCloud) }
    var msg by remember { mutableStateOf<String?>(null) }

    Surface(color = GraphiteSurface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Ollama Cloud", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Text("Chat uden at rig'en kører. Modeller i skyen.", fontSize = 12.sp, color = TextMuted)
            if (configured) { Spacer(Modifier.height(4.dp)); Text("✓ konfigureret", color = Signal, fontSize = 13.sp) }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = key, onValueChange = { key = it },
                label = { Text(if (configured) "Ny API-nøgle (valgfri)" else "API-nøgle", fontSize = 12.sp) },
                singleLine = true, visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Text("Hentes på ollama.com/settings/keys", fontSize = 11.sp, color = TextMuted)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = model, onValueChange = { model = it },
                label = { Text("Model (fx gpt-oss:120b)", fontSize = 12.sp) },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = system, onValueChange = { system = it; store.cloudSystem = it },
                label = { Text("System-instruktion (valgfri)", fontSize = 12.sp) },
                minLines = 2, maxLines = 5, modifier = Modifier.fillMaxWidth(),
            )
            Text("Rolle/baggrund modellen altid får. Fx: Du er en skarp dansk backend-udvikler. Svar kort.",
                fontSize = 11.sp, color = TextMuted, lineHeight = 15.sp)
            PresetRow(db, "cloud", system) { system = it; store.cloudSystem = it }
            Spacer(Modifier.height(12.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    enabled = configured || key.isNotBlank(),
                    onClick = {
                        runCatching {
                            if (key.isNotBlank()) store.cloudKey = key.trim()
                            store.cloudModel = model.trim().ifBlank { "gpt-oss:120b" }
                            store.chatMode = "cloud"
                        }.onSuccess { key = ""; configured = true; msg = null; onSaved() }
                            .onFailure { msg = "Kunne ikke gemme nøgle: ${it.message}" }
                    },
                ) { Text("Gem & brug cloud") }
                if (configured) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { store.clearCloud(); configured = false; key = "" }) { Text("Ryd", color = Danger) }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = Danger, fontSize = 12.sp) }
        }
    }
}

@Composable
private fun RigCard(store: TokenStore, db: ChatDb, onConnected: () -> Unit) {
    var baseUrl by remember { mutableStateOf(store.baseUrl ?: "http://192.168.1.10:8080") }
    var code by remember { mutableStateOf("") }
    var deviceName by remember { mutableStateOf(android.os.Build.MODEL ?: "android") }
    var connected by remember { mutableStateOf(store.hasRig) }
    var busy by remember { mutableStateOf(false) }
    var system by remember { mutableStateOf(store.rigSystem) }
    var msg by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    Surface(color = GraphiteSurface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Din rig (backend)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Text("Lokale modeller + RAG. Kræver at rig'en kører.", fontSize = 12.sp, color = TextMuted)
            if (connected) { Spacer(Modifier.height(4.dp)); Text("✓ forbundet", color = Signal, fontSize = 13.sp) }
            RigProfileRow(
                db = db,
                canSaveCurrent = connected,
                currentUrl = baseUrl,
                currentToken = store.token,
                onApply = { profile ->
                    store.baseUrl = profile.serverUrl
                    store.token = profile.deviceToken
                    store.chatMode = "rig"
                    baseUrl = profile.serverUrl
                    connected = true
                    onConnected()
                },
            )
            Spacer(Modifier.height(8.dp))
            Field("Server-URL", baseUrl) { baseUrl = it }
            Field("Parringskode (XXXX-XXXX)", code) { code = it }
            Field("Enhedsnavn", deviceName) { deviceName = it }
            Text("Serveren skal binde 0.0.0.0 / Tailscale-IP — ikke 127.0.0.1. Brug LAN-IP.",
                color = TextMuted, fontSize = 11.sp, lineHeight = 15.sp)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = system, onValueChange = { system = it; store.rigSystem = it },
                label = { Text("System-instruktion (valgfri)", fontSize = 12.sp) },
                minLines = 2, maxLines = 5, modifier = Modifier.fillMaxWidth(),
            )
            PresetRow(db, "rig", system) { system = it; store.rigSystem = it }
            Spacer(Modifier.height(10.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Button(
                    enabled = !busy && code.isNotBlank() && baseUrl.isNotBlank(),
                    onClick = {
                        busy = true; msg = null
                        val url = baseUrl.trim(); val c = code.trim(); val n = deviceName.trim()
                        scope.launch {
                            val res = withContext(Dispatchers.IO) { runCatching { ModelRigClient(url).claimPairing(n, c) } }
                            res.onSuccess { store.baseUrl = url; store.token = it; store.chatMode = "rig"; busy = false; connected = true; onConnected() }
                                .onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
                        }
                    },
                ) { Text(if (busy) "Forbinder…" else "Forbind") }
                if (connected) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { store.clearRig(); connected = false }) { Text("Afbryd", color = Danger) }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = Danger, fontSize = 12.sp) }
        }
    }
}

/**
 * Saved rig connection profiles (name + server-url + already-obtained device
 * token), for quick-switching between e.g. "Hjemme" and "Arbejde" without
 * re-pairing each time. A profile can only be saved once actually connected
 * (a valid token exists) -- the pairing code itself is single-use and never
 * stored. Tapping a chip applies the profile directly (bypasses pairing).
 * Same confirmed-safe inline pattern as PresetRow: no AlertDialog.
 */
@Composable
private fun RigProfileRow(
    db: ChatDb,
    canSaveCurrent: Boolean,
    currentUrl: String,
    currentToken: String?,
    onApply: (ChatDb.RigProfile) -> Unit,
) {
    var profiles by remember { mutableStateOf(runCatching { db.listRigProfiles() }.getOrElse { emptyList() }) }
    var saving by remember { mutableStateOf(false) }
    var newName by remember { mutableStateOf("") }
    var profileError by remember { mutableStateOf<String?>(null) }

    Spacer(Modifier.height(4.dp))
    Row(
        Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        profiles.forEach { p ->
            Surface(
                shape = RoundedCornerShape(999.dp),
                color = GraphiteSurfaceHigh,
                modifier = Modifier.padding(end = 6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = TextHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deleteRigProfile(p.id)
                                profiles = db.listRigProfiles()
                            }.onFailure { profileError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = TextMuted, fontSize = 11.sp) }
                }
            }
        }
        TextButton(
            enabled = canSaveCurrent,
            onClick = { saving = !saving; profileError = null },
            contentPadding = PaddingValues(horizontal = 8.dp),
        ) {
            Text(
                if (saving) "− Annullér" else "+ Gem denne rig",
                color = if (canSaveCurrent) Signal else TextMuted,
                fontSize = 12.sp,
            )
        }
    }

    if (saving) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = newName, onValueChange = { newName = it },
                label = { Text("Navn (fx \"Hjemme\", \"Arbejde\")", fontSize = 12.sp) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(8.dp))
            TextButton(
                enabled = newName.isNotBlank() && currentToken != null,
                onClick = {
                    val tok = currentToken
                    if (tok != null) {
                        runCatching {
                            db.saveRigProfile(newName.trim(), currentUrl, tok)
                            profiles = db.listRigProfiles()
                            newName = ""; saving = false
                        }.onFailure { profileError = "Kunne ikke gemme: ${it.message}" }
                    }
                },
            ) { Text("Gem", color = if (newName.isNotBlank() && currentToken != null) Signal else TextMuted, fontWeight = FontWeight.Bold) }
        }
    }
    profileError?.let { Text(it, color = Danger, fontSize = 11.sp) }
}

@Composable
private fun PresetRow(db: ChatDb, source: String, currentPrompt: String, onApply: (String) -> Unit) {
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
            Surface(
                shape = RoundedCornerShape(999.dp),
                color = GraphiteSurfaceHigh,
                modifier = Modifier.padding(end = 6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p.prompt) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = TextHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deletePreset(p.id)
                                presets = db.listPresets(source)
                            }.onFailure { presetError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = TextMuted, fontSize = 11.sp) }
                }
            }
        }
        TextButton(
            enabled = currentPrompt.isNotBlank(),
            onClick = { saving = !saving; presetError = null },
            contentPadding = PaddingValues(horizontal = 8.dp),
        ) {
            Text(
                if (saving) "− Annullér" else "+ Gem som preset",
                color = if (currentPrompt.isNotBlank()) Signal else TextMuted,
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
            ) { Text("Gem", color = if (newName.isNotBlank()) Signal else TextMuted, fontWeight = FontWeight.Bold) }
        }
    }
    presetError?.let { Text(it, color = Danger, fontSize = 11.sp) }
}
private data class Msg(
    val role: String,
    val text: String,
    val streaming: Boolean = false,
    val error: Boolean = false, // shown in UI, but never persisted or sent as history
    val sources: List<String> = emptyList(), // RAG source names, if this reply used RAG
)

/**
 * Bounds what's sent as chat history: last [maxMessages] messages, further
 * trimmed from the front if their combined length exceeds [maxChars]. Keeps the
 * system prompt (if any) first and untouched. Applies to both rig and cloud —
 * without this, a long conversation resends its entire text on every turn
 * (slow, and burns cloud quota for no benefit).
 */
private fun trimHistory(
    sys: String,
    convo: List<Pair<String, String>>,
    maxMessages: Int = 20,
    maxChars: Int = 24_000,
): List<Pair<String, String>> {
    val tail = if (convo.size > maxMessages) convo.takeLast(maxMessages) else convo
    val list = tail.toMutableList()
    var total = list.sumOf { it.second.length }
    while (list.size > 1 && total > maxChars) {
        total -= list.removeAt(0).second.length
    }
    return if (sys.isNotEmpty()) listOf("system" to sys) + list else list
}

/**
 * Maps a raised exception to a short, human Danish message. Network/auth/model
 * errors are common enough (rig asleep, phone off Tailscale, stale pairing,
 * typo'd model name) that a raw stack-trace-ish message isn't good enough for
 * daily use.
 */
private fun friendlyError(err: Throwable): String {
    val msg = err.message ?: ""
    return when {
        err is java.net.UnknownHostException || err is java.net.ConnectException ->
            "Kan ikke oprette forbindelse. Tjek at rig'en kører, og at telefonen er på samme netværk (eller Tailscale)."
        err is java.net.SocketTimeoutException ->
            "Tidsudløb — modellen svarede ikke i tide. Prøv igen, eller vælg en mindre model."
        msg.contains("ingen cloud-nøgle") ->
            "Ingen cloud-nøgle gemt. Tilføj en under Indstillinger."
        msg.contains("(401)") ->
            "Ikke godkendt. Parringen er nok udløbet — genpar enheden under Indstillinger."
        msg.contains("(404)") ->
            "Modellen eller endpointet blev ikke fundet. Tjek modelnavnet under Indstillinger."
        msg.contains("(502)") || msg.contains("(503)") ->
            "Rig'en/Ollama svarer ikke lige nu. Tjek at Ollama kører på maskinen."
        msg.startsWith("rag chat error:") ->
            "RAG-fejl: ${msg.removePrefix("rag chat error:").trim()}"
        msg.isEmpty() -> "Noget gik galt (ukendt fejl)."
        else -> "Noget gik galt: $msg"
    }
}

@Composable
private fun ChatScreen(
    store: TokenStore,
    db: ChatDb,
    openConvId: Long?,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
    onOpenModels: () -> Unit,
    onConvChanged: (Long?) -> Unit,
) {
    val hasRig = store.hasRig
    val hasCloud = store.hasCloud
    var mode by remember {
        mutableStateOf(
            when {
                hasRig && hasCloud -> store.chatMode
                hasCloud -> "cloud"
                else -> "rig"
            },
        )
    }

    val messages = remember { mutableStateListOf<Msg>() }
    var convId by remember { mutableStateOf<Long?>(null) }
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var activeCall by remember { mutableStateOf<okhttp3.Call?>(null) }
    var currentModel by remember { mutableStateOf(store.model) }
    var models by remember { mutableStateOf(listOf<String>()) }
    var modelMenu by remember { mutableStateOf(false) }
    var cloudModel by remember { mutableStateOf(store.cloudModel) }
    var cloudModels by remember { mutableStateOf(listOf<String>()) }
    var cloudMenu by remember { mutableStateOf(false) }
    var ragMode by remember { mutableStateOf(false) }
    var ragSources by remember { mutableStateOf(listOf<String>()) }
    var ragSourceFilter by remember { mutableStateOf<String?>(null) }
    var ragSourceMenu by remember { mutableStateOf(false) }
    var overflow by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    val context = LocalContext.current

    var ingesting by remember { mutableStateOf(false) }
    var ingestStatus by remember { mutableStateOf<String?>(null) }
    var ingestError by remember { mutableStateOf<String?>(null) }

    // Reads the picked document's text content + display name, then POSTs it
    // to the RAG index. txt/md only — no PDF/DOCX extraction (matches the
    // worker's plain-text ingest contract).
    val pickDocument = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        ingesting = true; ingestError = null; ingestStatus = "Læser fil…"
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val resolver = context.contentResolver
                    var name = uri.lastPathSegment ?: "dokument.txt"
                    resolver.query(uri, null, null, null, null)?.use { c ->
                        val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
                    }
                    val text = resolver.openInputStream(uri)?.use { it.readBytes().toString(Charsets.UTF_8) }
                        ?: throw RuntimeException("kunne ikke læse filen")
                    if (text.isBlank()) throw RuntimeException("filen er tom")
                    name to ModelRigClient(store.baseUrl ?: "", store.token).ingestText(name, text)
                }
            }
            ingesting = false
            result.onSuccess { (name, r) ->
                ingestStatus = "Ingesteret: $name (${r.chunksAdded} chunks)"
                val res2 = withContext(Dispatchers.IO) {
                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
                }
                res2.onSuccess { ragSources = it }
            }.onFailure { ingestError = it.message }
        }
    }

    // Load the requested conversation (or none). Restores source/model from its
    // metadata when that source is still configured.
    LaunchedEffect(openConvId) {
        messages.clear()
        convId = openConvId
        if (openConvId != null) {
            val loaded = withContext(Dispatchers.IO) {
                db.conversationMeta(openConvId) to db.loadMessages(openConvId)
            }
            val (meta, msgs) = loaded
            msgs.forEach { (role, content) -> messages.add(Msg(role, content)) }
            if (meta != null) {
                if (meta.source == "cloud" && hasCloud) { mode = "cloud"; ragMode = false; if (meta.model.isNotBlank()) { cloudModel = meta.model } }
                if (meta.source == "rag" && hasRig) { mode = "rig"; ragMode = true; if (meta.model.isNotBlank()) { currentModel = meta.model } }
                if (meta.source == "rig" && hasRig) { mode = "rig"; ragMode = false; if (meta.model.isNotBlank()) { currentModel = meta.model } }
            }
        }
    }

    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.size - 1)
    }

    val onSend: () -> Unit = onSend@{
        val t = input.trim()
        if (t.isEmpty() || busy) return@onSend
        messages.add(Msg("user", t)); input = ""; busy = true
        val useCloud = mode == "cloud"
        val useRag = mode == "rig" && ragMode
        val sys = (if (useCloud) store.cloudSystem else store.rigSystem).trim()
        val convo = messages.filter { !it.error }.map { it.role to it.text }
        val history = trimHistory(sys, convo)
        val idx = messages.size
        messages.add(Msg("assistant", "", streaming = true))
        val rigModel = currentModel
        val cModel = cloudModel
        val srcFilter = ragSourceFilter
        scope.launch {
            // persist: create conversation lazily, then the user message
            val cid = withContext(Dispatchers.IO) {
                val id = convId ?: db.newConversation(
                    source = if (useCloud) "cloud" else if (useRag) "rag" else "rig",
                    model = if (useCloud) cModel else rigModel,
                    title = t,
                )
                db.addMessage(id, "user", t)
                id
            }
            if (convId == null) { convId = cid; onConvChanged(cid) }

            val onDelta: (String) -> Unit = { delta ->
                scope.launch {
                    val cur = messages[idx]
                    messages[idx] = cur.copy(text = cur.text + delta)
                }
            }
            val onSources: (List<String>) -> Unit = { srcs ->
                scope.launch {
                    val cur = messages[idx]
                    messages[idx] = cur.copy(sources = srcs)
                }
            }
            val hook: (okhttp3.Call) -> Unit = { activeCall = it }

            val err = withContext(Dispatchers.IO) {
                runCatching {
                    when {
                        // RAG: single-shot retrieval over the current question, not the
                        // full conversation — that's how the worker's /rag/chat is built
                        // (one query in, sources + answer out). History still shows and
                        // persists locally; it isn't replayed as context to the model.
                        useRag -> ModelRigClient(store.baseUrl ?: "", store.token)
                            .ragChatStream(t, rigModel, srcFilter, registerCall = hook, onSources = onSources, onDelta = onDelta)
                        useCloud -> {
                            val key = store.cloudKey ?: throw RuntimeException("ingen cloud-nøgle")
                            CloudClient(key).chatStream(cModel, history, registerCall = hook, onDelta = onDelta)
                        }
                        else -> ModelRigClient(store.baseUrl ?: "", store.token)
                            .chatStream(rigModel, history, registerCall = hook, onDelta = onDelta)
                    }
                }.exceptionOrNull()
            }
            activeCall = null
            val cur = messages[idx]
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[idx] = when {
                err == null -> cur.copy(streaming = false)
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = friendlyError(err!!))
                else -> cur.copy(streaming = false, text = cur.text + "\n\n_[afbrudt]_")
            }
            // persist the assistant reply (full or partial-cancelled), never errors
            val finalText = messages[idx].text
            if (err == null || cancelled) {
                withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", finalText) }
            }
            busy = false
        }
    }

    // Retries the user message that precedes an errored assistant bubble at
    // index [i]. Re-runs generation in place — no duplicate user message, no
    // duplicate DB row. Uses the CURRENT mode/model/RAG settings, which is
    // usually what you want (you just hit retry right after the failure).
    val retry: (Int) -> Unit = retry@{ i ->
        if (busy) return@retry
        val errMsg = messages.getOrNull(i) ?: return@retry
        if (!errMsg.error) return@retry
        val userMsg = messages.getOrNull(i - 1) ?: return@retry
        if (userMsg.role != "user") return@retry
        val t = userMsg.text
        val useCloud = mode == "cloud"
        val useRag = mode == "rig" && ragMode
        val sys = (if (useCloud) store.cloudSystem else store.rigSystem).trim()
        val convo = messages.filterIndexed { idx2, mm -> idx2 != i && !mm.error }.map { it.role to it.text }
        val history = trimHistory(sys, convo)
        val rigModel = currentModel
        val cModel = cloudModel
        val srcFilter = ragSourceFilter
        val cidNow = convId
        messages[i] = Msg("assistant", "", streaming = true)
        busy = true
        scope.launch {
            val onDelta: (String) -> Unit = { delta ->
                scope.launch { val cur = messages[i]; messages[i] = cur.copy(text = cur.text + delta) }
            }
            val onSources: (List<String>) -> Unit = { srcs ->
                scope.launch { val cur = messages[i]; messages[i] = cur.copy(sources = srcs) }
            }
            val hook: (okhttp3.Call) -> Unit = { activeCall = it }
            val err = withContext(Dispatchers.IO) {
                runCatching {
                    when {
                        useRag -> ModelRigClient(store.baseUrl ?: "", store.token)
                            .ragChatStream(t, rigModel, srcFilter, registerCall = hook, onSources = onSources, onDelta = onDelta)
                        useCloud -> {
                            val key = store.cloudKey ?: throw RuntimeException("ingen cloud-nøgle")
                            CloudClient(key).chatStream(cModel, history, registerCall = hook, onDelta = onDelta)
                        }
                        else -> ModelRigClient(store.baseUrl ?: "", store.token)
                            .chatStream(rigModel, history, registerCall = hook, onDelta = onDelta)
                    }
                }.exceptionOrNull()
            }
            activeCall = null
            val cur = messages[i]
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[i] = when {
                err == null -> cur.copy(streaming = false)
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = friendlyError(err!!))
                else -> cur.copy(streaming = false, text = cur.text + "\n\n_[afbrudt]_")
            }
            val finalText = messages[i].text
            if (cidNow != null && (err == null || cancelled)) {
                withContext(Dispatchers.IO) { db.addMessage(cidNow, "assistant", finalText) }
            }
            busy = false
        }
    }

    Column(Modifier.fillMaxSize()) {
        // top bar
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Column {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (mode == "cloud") {
                    Box {
                        ModelChip("☁  $cloudModel  ▾", onClick = { cloudMenu = true })
                        DropdownMenu(expanded = cloudMenu, onDismissRequest = { cloudMenu = false }) {
                            DropdownMenuItem(
                                text = { Text("↻  Genindlæs modeller", color = Signal) },
                                onClick = {
                                    cloudMenu = false
                                    val key = store.cloudKey
                                    if (key != null) scope.launch {
                                        val res = withContext(Dispatchers.IO) { runCatching { CloudClient(key).listModels() } }
                                        res.onSuccess { cloudModels = it }
                                    }
                                },
                            )
                            if (cloudModels.isNotEmpty()) HorizontalDivider()
                            cloudModels.forEach { m ->
                                DropdownMenuItem(text = { Text(m) }, onClick = {
                                    cloudModel = m; store.cloudModel = m; cloudMenu = false
                                })
                            }
                            HorizontalDivider()
                            DropdownMenuItem(text = { Text("Indstillinger…", color = TextMuted) }, onClick = { cloudMenu = false; onOpenSettings() })
                        }
                    }
                } else {
                    Box {
                        ModelChip("$currentModel  ▾", onClick = { modelMenu = true })
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
                if (mode == "rig") {
                    Spacer(Modifier.width(6.dp))
                    RagToggle(ragMode) { on ->
                        ragMode = on
                        if (on) scope.launch {
                            val res = withContext(Dispatchers.IO) {
                                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
                            }
                            res.onSuccess { ragSources = it }
                        }
                    }
                    if (ragMode) {
                        Spacer(Modifier.width(6.dp))
                        Box {
                            ModelChip(ragSourceFilter?.let { "⌕ $it" } ?: "⌕ Alle kilder", onClick = { ragSourceMenu = true })
                            DropdownMenu(expanded = ragSourceMenu, onDismissRequest = { ragSourceMenu = false }) {
                                DropdownMenuItem(text = { Text("Alle kilder") }, onClick = { ragSourceFilter = null; ragSourceMenu = false })
                                if (ragSources.isNotEmpty()) HorizontalDivider()
                                ragSources.forEach { s ->
                                    DropdownMenuItem(text = { Text(s) }, onClick = { ragSourceFilter = s; ragSourceMenu = false })
                                }
                                if (ragSources.isEmpty()) {
                                    HorizontalDivider()
                                    DropdownMenuItem(text = { Text("Ingen kilder ingesteret endnu", color = TextMuted) }, onClick = { ragSourceMenu = false })
                                }
                                HorizontalDivider()
                                DropdownMenuItem(
                                    text = { Text("+ Tilføj dokument (txt/md)…", color = Signal) },
                                    onClick = { ragSourceMenu = false; pickDocument.launch(arrayOf("text/plain", "text/markdown", "application/octet-stream")) },
                                )
                            }
                        }
                    }
                }
                Spacer(Modifier.weight(1f))
                SourceBadge(mode)
                if (hasRig && hasCloud) {
                    TextButton(
                        onClick = { val m = if (mode == "cloud") "rig" else "cloud"; mode = m; store.chatMode = m; if (m == "cloud") ragMode = false },
                        contentPadding = PaddingValues(horizontal = 8.dp),
                    ) { Text("Skift", color = Signal, fontSize = 13.sp) }
                }
                Box {
                    TextButton(onClick = { overflow = true }, contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Text("⋮", color = TextHigh, fontSize = 20.sp)
                    }
                    DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                        DropdownMenuItem(text = { Text("Ny samtale") }, onClick = {
                            overflow = false; messages.clear(); convId = null; onConvChanged(null)
                        })
                        DropdownMenuItem(text = { Text("Samtaler") }, onClick = { overflow = false; onOpenConversations() })
                        DropdownMenuItem(text = { Text("Modeller") }, onClick = { overflow = false; onOpenModels() })
                        DropdownMenuItem(text = { Text("Indstillinger") }, onClick = { overflow = false; onOpenSettings() })
                    }
                }
            }
            if (ingesting || ingestStatus != null || ingestError != null) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
                    when {
                        ingesting -> Text("Ingesterer…", color = TextMuted, fontSize = 11.sp)
                        ingestError != null -> Text("Fejl: $ingestError", color = Danger, fontSize = 11.sp)
                        ingestStatus != null -> Text(ingestStatus!!, color = Signal, fontSize = 11.sp)
                    }
                }
            }
            }
        }

        // messages
        if (messages.isEmpty()) {
            Column(
                Modifier.weight(1f).fillMaxWidth().padding(32.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Text(if (mode == "cloud") "☁" else if (ragMode) "⌕" else "◉", fontSize = 40.sp, color = if (mode == "cloud") Amber else Signal)
                Spacer(Modifier.height(12.dp))
                Text(
                    when { mode == "cloud" -> "Cloud-tilstand"; ragMode -> "RAG-tilstand"; else -> "Rig-tilstand" },
                    color = TextHigh, fontSize = 16.sp, fontWeight = FontWeight.Medium,
                )
                Text(
                    if (ragMode) "Spørg om dine ingesterede dokumenter" else "Skriv en besked for at starte",
                    color = TextMuted, fontSize = 13.sp,
                )
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
            ) { itemsIndexed(messages) { i, m -> Bubble(m, onRetry = { retry(i) }) } }
        }

        // input bar — adjustResize + edge-to-edge: the keyboard arrives as the ime
        // inset, so ime.union(navigationBars) lifts the field above it (max per
        // side, no double-count).
        Surface(color = GraphiteSurface, tonalElevation = 3.dp) {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                OutlinedTextField(
                    value = input, onValueChange = { input = it },
                    modifier = Modifier.weight(1f), enabled = !busy, maxLines = 5,
                    placeholder = { Text("Skriv til modellen…") },
                    shape = RoundedCornerShape(24.dp),
                )
                Spacer(Modifier.width(6.dp))
                if (busy) {
                    Box(
                        Modifier.size(44.dp).clickable(onClick = { activeCall?.cancel() }),
                        contentAlignment = Alignment.Center,
                    ) { StopGlyph(color = Danger, modifier = Modifier.size(20.dp)) }
                } else {
                    val canSend = input.isNotBlank()
                    Box(
                        Modifier.size(44.dp).clickable(enabled = canSend, onClick = onSend),
                        contentAlignment = Alignment.Center,
                    ) { SendGlyph(color = if (canSend) Signal else TextMuted, modifier = Modifier.size(26.dp)) }
                }
            }
        }
    }
}

// ---- conversations list ----
@Composable
private fun ConversationsScreen(
    db: ChatDb,
    onOpen: (Long) -> Unit,
    onNew: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    var convos by remember { mutableStateOf(db.listConversations()) }
    var query by remember { mutableStateOf("") }
    var renamingId by remember { mutableStateOf<Long?>(null) }
    var renameText by remember { mutableStateOf("") }
    val fmt = remember { SimpleDateFormat("d/M HH:mm", Locale.getDefault()) }
    val visible = remember(convos, query) {
        if (query.isBlank()) convos else convos.filter { it.title.contains(query, ignoreCase = true) }
    }

    Column(Modifier.fillMaxSize()) {
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Column(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onBack) { Text("←", color = TextHigh, fontSize = 18.sp) }
                    Text("Samtaler", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = onNew) { Text("+ Ny", color = Signal) }
                }
                OutlinedTextField(
                    value = query, onValueChange = { query = it },
                    placeholder = { Text("Søg i titler…", fontSize = 13.sp) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                )
            }
        }
        if (visible.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    if (convos.isEmpty()) "Ingen samtaler endnu" else "Ingen match på \"$query\"",
                    color = TextMuted, fontSize = 14.sp,
                )
            }
        } else {
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
            ) {
                items(visible, key = { it.id }) { c ->
                    Surface(
                        color = GraphiteSurface,
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
                    ) {
                        Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
                            if (renamingId == c.id) {
                                Row(verticalAlignment = Alignment.CenterVertically) {
                                    OutlinedTextField(
                                        value = renameText, onValueChange = { renameText = it },
                                        singleLine = true, modifier = Modifier.weight(1f),
                                    )
                                    TextButton(
                                        enabled = renameText.isNotBlank(),
                                        onClick = {
                                            db.renameConversation(c.id, renameText.trim())
                                            convos = db.listConversations()
                                            renamingId = null
                                        },
                                    ) { Text("Gem", color = if (renameText.isNotBlank()) Signal else TextMuted) }
                                    TextButton(onClick = { renamingId = null }) { Text("✕", color = TextMuted) }
                                }
                            } else {
                                Row(
                                    Modifier.fillMaxWidth().clickable { onOpen(c.id) },
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Text(
                                            c.title.ifBlank { "(uden titel)" },
                                            color = TextHigh, fontSize = 14.sp,
                                            maxLines = 1,
                                        )
                                        Spacer(Modifier.height(2.dp))
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            SourceBadge(c.source)
                                            Spacer(Modifier.width(8.dp))
                                            Text(fmt.format(Date(c.updatedAt)), color = TextMuted, fontSize = 11.sp)
                                        }
                                    }
                                }
                                Row {
                                    TextButton(onClick = {
                                        renamingId = c.id
                                        renameText = c.title
                                    }) { Text("✎", color = TextMuted, fontSize = 13.sp) }
                                    TextButton(onClick = {
                                        val md = buildString {
                                            appendLine("# ${c.title.ifBlank { "ModelRig-samtale" }}")
                                            appendLine()
                                            db.loadMessages(c.id).forEach { (role, content) ->
                                                appendLine(if (role == "user") "**Du:**" else "**Assistent:**")
                                                appendLine(content)
                                                appendLine()
                                            }
                                        }
                                        val intent = Intent(Intent.ACTION_SEND).apply {
                                            type = "text/plain"
                                            putExtra(Intent.EXTRA_SUBJECT, c.title.ifBlank { "ModelRig-samtale" })
                                            putExtra(Intent.EXTRA_TEXT, md)
                                        }
                                        context.startActivity(Intent.createChooser(intent, "Del samtale"))
                                    }) { Text("Del", color = Signal, fontSize = 12.sp) }
                                    TextButton(onClick = {
                                        db.deleteConversation(c.id)
                                        convos = db.listConversations()
                                    }) { Text("Slet", color = Danger, fontSize = 12.sp) }
                                }
                            }
                        }
                    }
                }
            }
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
    }
}

/**
 * Model administration: installed models (with size + delete), currently
 * running models (VRAM usage), and pulling a new model with live progress.
 * Only meaningful against the rig — Ollama Cloud doesn't expose these
 * management endpoints, and this screen isn't shown as a cloud-mode option.
 */
@Composable
private fun ModelsScreen(store: TokenStore, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    val client = remember { ModelRigClient(store.baseUrl ?: "", store.token) }

    var installed by remember { mutableStateOf<List<ModelRigClient.ModelInfo>>(emptyList()) }
    var running by remember { mutableStateOf<List<ModelRigClient.RunningModel>>(emptyList()) }
    var loadError by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(false) }

    var pullName by remember { mutableStateOf("") }
    var pulling by remember { mutableStateOf(false) }
    var pullStatus by remember { mutableStateOf<String?>(null) }
    var pullError by remember { mutableStateOf<String?>(null) }

    var confirmDelete by remember { mutableStateOf<String?>(null) }

    fun refresh() {
        loading = true; loadError = null
        scope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching { client.listModelsDetailed() to client.listRunningModels() }
            }
            res.onSuccess { (i, r) -> installed = i; running = r }
                .onFailure { loadError = it.message }
            loading = false
        }
    }
    LaunchedEffect(Unit) { refresh() }

    Column(Modifier.fillMaxSize()) {
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onBack) { Text("←", color = TextHigh, fontSize = 18.sp) }
                Text("Modeller", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { refresh() }) { Text(if (loading) "…" else "Genindlæs", color = Signal) }
            }
        }

        if (!store.hasRig) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Kræver rig-forbindelse", color = TextMuted, fontSize = 14.sp)
            }
            return@Column
        }

        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp)) {
            // ---- pull new model ----
            Text("Hent ny model", color = TextHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(8.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(
                    value = pullName, onValueChange = { pullName = it },
                    placeholder = { Text("fx llama3.2:3b", fontSize = 13.sp) },
                    singleLine = true, enabled = !pulling,
                    modifier = Modifier.weight(1f),
                )
                Spacer(Modifier.width(8.dp))
                Button(
                    enabled = !pulling && pullName.isNotBlank(),
                    onClick = {
                        val name = pullName.trim()
                        pulling = true; pullError = null; pullStatus = "Starter…"
                        scope.launch {
                            val err = withContext(Dispatchers.IO) {
                                runCatching {
                                    client.pullModel(name) { status, completed, total ->
                                        scope.launch {
                                            pullStatus = if (total > 0) {
                                                val pct = (completed * 100 / total)
                                                "$status ($pct% — ${completed / 1_000_000}MB/${total / 1_000_000}MB)"
                                            } else status
                                        }
                                    }
                                }.exceptionOrNull()
                            }
                            pulling = false
                            if (err != null) {
                                pullError = err.message; pullStatus = null
                            } else {
                                pullStatus = "Færdig: $name"; pullName = ""
                                refresh()
                            }
                        }
                    },
                ) { Text(if (pulling) "Henter…" else "Hent") }
            }
            pullStatus?.let { Spacer(Modifier.height(6.dp)); Text(it, color = Signal, fontSize = 12.sp) }
            pullError?.let { Spacer(Modifier.height(6.dp)); Text("Fejl: $it", color = Danger, fontSize = 12.sp) }

            Spacer(Modifier.height(20.dp))

            // ---- running now ----
            Text("Kører nu", color = TextHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(8.dp))
            if (running.isEmpty()) {
                Text("Ingen modeller indlæst i hukommelsen lige nu", color = TextMuted, fontSize = 13.sp)
            } else {
                running.forEach { m ->
                    Surface(
                        color = GraphiteSurface, shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(m.name, color = TextHigh, fontSize = 13.sp)
                                Text(
                                    "${m.sizeVramBytes / 1_000_000_000.0} GB VRAM",
                                    color = TextMuted, fontSize = 11.sp,
                                )
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(20.dp))

            // ---- installed ----
            Text("Installeret", color = TextHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(8.dp))
            loadError?.let { Text("Fejl: $it", color = Danger, fontSize = 12.sp); Spacer(Modifier.height(6.dp)) }
            installed.forEach { m ->
                Surface(
                    color = GraphiteSurface, shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                ) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(m.name, color = TextHigh, fontSize = 13.sp)
                            Text("${m.sizeBytes / 1_000_000_000.0} GB", color = TextMuted, fontSize = 11.sp)
                        }
                        TextButton(onClick = { confirmDelete = m.name }) { Text("Slet", color = Danger, fontSize = 12.sp) }
                    }
                }
            }
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
    }

    confirmDelete?.let { name ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Slet $name?") },
            text = { Text("Dette kan ikke fortrydes — modellen skal hentes igen for at bruges.", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    scope.launch {
                        val err = withContext(Dispatchers.IO) { runCatching { client.deleteModel(name) }.exceptionOrNull() }
                        if (err == null) refresh() else loadError = err.message
                    }
                }) { Text("Slet", color = Danger) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Annullér", color = TextMuted) } },
        )
    }
}
@Composable
private fun ModelChip(label: String, onClick: () -> Unit) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = GraphiteSurfaceHigh,
        modifier = Modifier.clickable(onClick = onClick),
    ) {
        Text(label, color = TextHigh, fontSize = 13.sp, modifier = Modifier.padding(horizontal = 12.dp, vertical = 6.dp))
    }
}

@Composable
private fun SourceBadge(mode: String) {
    val (label, color, onColor) = when (mode) {
        "cloud" -> Triple("☁ Cloud", Amber, Graphite)
        "rag" -> Triple("⌕ RAG", Signal, Color.White)
        else -> Triple("◈ Rig", Signal, Color.White)
    }
    Surface(shape = RoundedCornerShape(999.dp), color = color) {
        Text(
            label, color = onColor,
            fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
        )
    }
}

@Composable
private fun RagToggle(active: Boolean, onToggle: (Boolean) -> Unit) {
    Surface(
        shape = RoundedCornerShape(20.dp),
        color = if (active) Signal else GraphiteSurfaceHigh,
        modifier = Modifier.clickable { onToggle(!active) },
    ) {
        Text(
            "⌕ RAG",
            color = if (active) Color.White else TextMuted,
            fontSize = 12.sp, fontWeight = FontWeight.Medium,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 6.dp),
        )
    }
}

@Composable
private fun SendGlyph(color: Color, modifier: Modifier) {
    Canvas(modifier) {
        val w = size.width; val h = size.height
        val p = Path().apply {
            moveTo(w * 0.08f, h * 0.12f)
            lineTo(w * 0.92f, h * 0.5f)
            lineTo(w * 0.08f, h * 0.88f)
            lineTo(w * 0.30f, h * 0.5f)
            close()
        }
        drawPath(p, color)
    }
}

@Composable
private fun StopGlyph(color: Color, modifier: Modifier) {
    Canvas(modifier) {
        drawRoundRect(color = color, cornerRadius = androidx.compose.ui.geometry.CornerRadius(size.width * 0.18f))
    }
}

@Composable
private fun Bubble(m: Msg, onRetry: (() -> Unit)? = null) {
    val isUser = m.role == "user"
    val maxW = (LocalConfiguration.current.screenWidthDp * 0.82f).dp
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp),
        horizontalArrangement = if (isUser) Arrangement.End else Arrangement.Start,
    ) {
        Surface(
            color = if (isUser) Signal else GraphiteSurfaceHigh,
            shape = RoundedCornerShape(
                topStart = 16.dp, topEnd = 16.dp,
                bottomStart = if (isUser) 16.dp else 4.dp,
                bottomEnd = if (isUser) 4.dp else 16.dp,
            ),
            modifier = Modifier.widthIn(max = maxW),
        ) {
            Box(Modifier.padding(horizontal = 14.dp, vertical = 10.dp)) {
                Column {
                    if (!isUser && m.sources.isNotEmpty()) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            m.sources.take(4).forEach { s ->
                                Surface(
                                    shape = RoundedCornerShape(999.dp),
                                    color = GraphiteSurfaceHigh,
                                    modifier = Modifier.padding(end = 4.dp),
                                ) {
                                    Text(
                                        s, fontSize = 10.sp, color = TextMuted,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                    )
                                }
                            }
                        }
                    }
                    when {
                        isUser -> Text(m.text, color = Color.White, fontSize = 15.sp, lineHeight = 21.sp)
                        m.error -> Text(m.text, color = Danger, fontSize = 14.sp, lineHeight = 20.sp)
                        m.streaming && m.text.isEmpty() -> Text("…", color = TextMuted, fontSize = 15.sp, lineHeight = 21.sp)
                        m.streaming -> Text(m.text + "▍", color = TextHigh, fontSize = 15.sp, lineHeight = 21.sp)
                        else -> MarkdownText(m.text, color = TextHigh)
                    }
                    if (m.error && onRetry != null) {
                        Spacer(Modifier.height(6.dp))
                        TextButton(onClick = onRetry, contentPadding = PaddingValues(0.dp)) {
                            Text("↻ Prøv igen", color = Signal, fontSize = 12.sp)
                        }
                    }
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
        singleLine = true, modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    )
}

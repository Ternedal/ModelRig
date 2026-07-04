package dk.ternedal.modelrig.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.clickable
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.platform.LocalConfiguration
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

private enum class Screen { Setup, Chat, Convos }

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
                Screen.Setup -> SetupScreen(store, onDone = { screen = Screen.Chat })
                Screen.Chat -> ChatScreen(
                    store, db, openConvId,
                    onOpenSettings = { screen = Screen.Setup },
                    onOpenConversations = { screen = Screen.Convos },
                    onConvChanged = { openConvId = it },
                )
                Screen.Convos -> ConversationsScreen(
                    db,
                    onOpen = { openConvId = it; screen = Screen.Chat },
                    onNew = { openConvId = null; screen = Screen.Chat },
                    onBack = { screen = Screen.Chat },
                )
            }
        }
    }
}

// ---- setup: cloud and/or rig ----
@Composable
private fun SetupScreen(store: TokenStore, onDone: () -> Unit) {
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
        CloudCard(store) { refresh++; onDone() }
        Spacer(Modifier.height(16.dp))
        RigCard(store) { refresh++; onDone() }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun CloudCard(store: TokenStore, onSaved: () -> Unit) {
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
private fun RigCard(store: TokenStore, onConnected: () -> Unit) {
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

// ---- chat ----
private data class Msg(
    val role: String,
    val text: String,
    val streaming: Boolean = false,
    val error: Boolean = false, // shown in UI, but never persisted or sent as history
)

@Composable
private fun ChatScreen(
    store: TokenStore,
    db: ChatDb,
    openConvId: Long?,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
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
    var overflow by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()

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
                if (meta.source == "cloud" && hasCloud) { mode = "cloud"; if (meta.model.isNotBlank()) { cloudModel = meta.model } }
                if (meta.source == "rig" && hasRig) { mode = "rig"; if (meta.model.isNotBlank()) { currentModel = meta.model } }
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
        val sys = (if (useCloud) store.cloudSystem else store.rigSystem).trim()
        val convo = messages.filter { !it.error }.map { it.role to it.text }
        val history = if (sys.isNotEmpty()) listOf("system" to sys) + convo else convo
        val idx = messages.size
        messages.add(Msg("assistant", "", streaming = true))
        val rigModel = currentModel
        val cModel = cloudModel
        scope.launch {
            // persist: create conversation lazily, then the user message
            val cid = withContext(Dispatchers.IO) {
                val id = convId ?: db.newConversation(
                    source = if (useCloud) "cloud" else "rig",
                    model = if (useCloud) cModel else rigModel,
                    title = t,
                )
                db.addMessage(id, "user", t)
                id
            }
            if (convId == null) { convId = cid; onConvChanged(cid) }

            val err = withContext(Dispatchers.IO) {
                runCatching {
                    val onDelta: (String) -> Unit = { delta ->
                        scope.launch {
                            val cur = messages[idx]
                            messages[idx] = cur.copy(text = cur.text + delta)
                        }
                    }
                    val hook: (okhttp3.Call) -> Unit = { activeCall = it }
                    if (useCloud) {
                        val key = store.cloudKey ?: throw RuntimeException("ingen cloud-nøgle")
                        CloudClient(key).chatStream(cModel, history, registerCall = hook, onDelta = onDelta)
                    } else {
                        ModelRigClient(store.baseUrl ?: "", store.token)
                            .chatStream(rigModel, history, registerCall = hook, onDelta = onDelta)
                    }
                }.exceptionOrNull()
            }
            activeCall = null
            val cur = messages[idx]
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[idx] = when {
                err == null -> cur.copy(streaming = false)
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = "Fejl: ${err.message}")
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

    Column(Modifier.fillMaxSize()) {
        // top bar
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
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
                Spacer(Modifier.weight(1f))
                SourceBadge(mode)
                if (hasRig && hasCloud) {
                    TextButton(
                        onClick = { val m = if (mode == "cloud") "rig" else "cloud"; mode = m; store.chatMode = m },
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
                        DropdownMenuItem(text = { Text("Indstillinger") }, onClick = { overflow = false; onOpenSettings() })
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
                Text(if (mode == "cloud") "☁" else "◉", fontSize = 40.sp, color = if (mode == "cloud") Amber else Signal)
                Spacer(Modifier.height(12.dp))
                Text(if (mode == "cloud") "Cloud-tilstand" else "Rig-tilstand", color = TextHigh, fontSize = 16.sp, fontWeight = FontWeight.Medium)
                Text("Skriv en besked for at starte", color = TextMuted, fontSize = 13.sp)
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
            ) { items(messages) { m -> Bubble(m) } }
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
    var convos by remember { mutableStateOf(db.listConversations()) }
    val fmt = remember { SimpleDateFormat("d/M HH:mm", Locale.getDefault()) }

    Column(Modifier.fillMaxSize()) {
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onBack) { Text("←", color = TextHigh, fontSize = 18.sp) }
                Text("Samtaler", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = onNew) { Text("+ Ny", color = Signal) }
            }
        }
        if (convos.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Ingen samtaler endnu", color = TextMuted, fontSize = 14.sp)
            }
        } else {
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
            ) {
                items(convos, key = { it.id }) { c ->
                    Surface(
                        color = GraphiteSurface,
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(vertical = 4.dp)
                            .clickable { onOpen(c.id) },
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 10.dp),
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
                            TextButton(onClick = {
                                db.deleteConversation(c.id)
                                convos = db.listConversations()
                            }) { Text("Slet", color = Danger, fontSize = 12.sp) }
                        }
                    }
                }
            }
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
    }
}

// ---- small components ----
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
    val isCloud = mode == "cloud"
    Surface(shape = RoundedCornerShape(999.dp), color = if (isCloud) Amber else Signal) {
        Text(
            if (isCloud) "☁ Cloud" else "◈ Rig",
            color = if (isCloud) Graphite else Color.White,
            fontSize = 11.sp, fontWeight = FontWeight.SemiBold,
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 4.dp),
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
private fun Bubble(m: Msg) {
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
                when {
                    isUser -> Text(m.text, color = Color.White, fontSize = 15.sp, lineHeight = 21.sp)
                    m.error -> Text(m.text, color = Danger, fontSize = 14.sp, lineHeight = 20.sp)
                    m.streaming -> Text(m.text + "▍", color = TextHigh, fontSize = 15.sp, lineHeight = 21.sp)
                    else -> MarkdownText(m.text, color = TextHigh)
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

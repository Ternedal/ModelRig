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

private enum class Screen { Setup, Chat, Convos, Models, CloudPicker }

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
        // bumped when the cloud model is changed elsewhere (picker), so
        // ChatScreen re-reads store.cloudModel when it comes back into view.
        var cloudModelTick by remember { mutableStateOf(0) }

        Surface(color = Graphite, modifier = Modifier.fillMaxSize()) {
            when (screen) {
                Screen.Setup -> SetupScreen(store, db, onDone = { screen = Screen.Chat })
                Screen.Chat -> ChatScreen(
                    store, db, openConvId, cloudModelTick,
                    onOpenSettings = { screen = Screen.Setup },
                    onOpenConversations = { screen = Screen.Convos },
                    onOpenModels = { screen = Screen.Models },
                    onOpenCloudPicker = { screen = Screen.CloudPicker },
                    onConvChanged = { openConvId = it },
                )
                Screen.Convos -> ConversationsScreen(
                    db,
                    onOpen = { openConvId = it; screen = Screen.Chat },
                    onNew = { openConvId = null; screen = Screen.Chat },
                    onBack = { screen = Screen.Chat },
                )
                Screen.Models -> ModelsScreen(store, onBack = { screen = Screen.Chat })
                Screen.CloudPicker -> CloudModelPickerScreen(
                    store,
                    onPicked = { cloudModelTick++; screen = Screen.Chat },
                    onBack = { cloudModelTick++; screen = Screen.Chat },
                )
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
            Text("Alva", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = TextHigh)
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
                label = { Text("Standardmodel (fx gpt-oss:120b)", fontSize = 12.sp) },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )
            Text("Modellen der bruges som standard. Du kan også vælge fra din cloud-kontos liste via ☁-menuen øverst i chatten.",
                fontSize = 11.sp, color = TextMuted, lineHeight = 15.sp)
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
    // "connected" = a pairing is stored. That is NOT the same as the rig being
    // reachable -- Anders' rig changed IP and the app still claimed "forbundet"
    // while every message fell back to cloud. So we also ping the rig and show
    // its real state. null = not checked yet.
    var connected by remember { mutableStateOf(store.hasRig) }
    var reachable by remember { mutableStateOf<Boolean?>(null) }
    var busy by remember { mutableStateOf(false) }
    var system by remember { mutableStateOf(store.rigSystem) }
    var msg by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()

    // Check reachability whenever we have a stored pairing (on entry, and after
    // the URL changes), so the status line tells the truth.
    LaunchedEffect(store.hasRig, baseUrl) {
        if (!store.hasRig || baseUrl.isBlank()) { reachable = null; return@LaunchedEffect }
        reachable = null
        reachable = withContext(Dispatchers.IO) {
            runCatching { ModelRigClient(baseUrl.trim(), store.token).ping() }.getOrDefault(false)
        }
    }

    Surface(color = GraphiteSurface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Din rig (backend)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
            Text("Lokale modeller + RAG. Kræver at rig'en kører.", fontSize = 12.sp, color = TextMuted)
            if (connected) {
                Spacer(Modifier.height(4.dp))
                when (reachable) {
                    true -> Text("✓ forbundet", color = Signal, fontSize = 13.sp)
                    false -> Text(
                        "⚠ parret, men rig'en svarer ikke — tjek IP og at serveren kører",
                        color = Danger, fontSize = 13.sp,
                    )
                    null -> Text("… tjekker forbindelsen", color = TextMuted, fontSize = 13.sp)
                }
            }
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
                // A pairing code is only needed for a FIRST pairing. If a token
                // is already stored (e.g. the rig just changed IP), the user
                // should be able to update the URL and reconnect without
                // re-pairing -- the token isn't tied to the address. Anders hit
                // this on 2026-07-09: the button stayed disabled with an empty
                // code, forcing an unnecessary re-pair.
                val hasToken = store.token != null
                Button(
                    enabled = !busy && baseUrl.isNotBlank() && (code.isNotBlank() || hasToken),
                    onClick = {
                        busy = true; msg = null
                        val url = baseUrl.trim(); val c = code.trim(); val n = deviceName.trim()
                        scope.launch {
                            if (c.isBlank() && hasToken) {
                                // Reconnect with the existing token: save the new
                                // URL, then verify the rig actually answers there.
                                val ok = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(url, store.token).ping() }.getOrDefault(false)
                                }
                                busy = false
                                if (ok) {
                                    store.baseUrl = url; store.chatMode = "rig"
                                    connected = true; reachable = true; onConnected()
                                } else {
                                    reachable = false
                                    msg = "Rig'en svarer ikke på $url. Tjek IP'en og at serveren kører."
                                }
                            } else {
                                val res = withContext(Dispatchers.IO) { runCatching { ModelRigClient(url).claimPairing(n, c) } }
                                res.onSuccess {
                                    store.baseUrl = url; store.token = it; store.chatMode = "rig"
                                    busy = false; connected = true; reachable = true; onConnected()
                                }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
                            }
                        }
                    },
                ) { Text(if (busy) "Forbinder…" else "Forbind") }
                if (connected) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(onClick = { store.clearRig(); connected = false; reachable = null }) { Text("Afbryd", color = Danger) }
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
    val fellBackToCloud: Boolean = false, // rig was unreachable -> answered via cloud
    // For a spoken turn: which model answered, and whether it was a cloud model.
    // Deliberately separate from fellBackToCloud -- using cloud for voice is a
    // deliberate choice, not a fallback, and conflating them would mislead.
    val voiceModel: String? = null,
    val voiceViaCloud: Boolean = false,
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
        else -> friendlyError(msg)
    }
}

/**
 * String overload: the model-management / ingest / pull panels hold a raw
 * error String (not a Throwable), and were showing it verbatim ("Fejl:
 * models failed (401)"). This routes them through the same status-code
 * explanations chat already used, so a 401 there also tells the user to
 * re-pair instead of leaving them to decode it (bit Anders live 6/7 --
 * Modelstyring showed a bare 401 until refreshed).
 */
private fun friendlyError(msg: String): String {
    return when {
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
    cloudModelTick: Int,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
    onOpenModels: () -> Unit,
    onOpenCloudPicker: () -> Unit,
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

    // Vision: an image picked to send with the next message, held as base64
    // (no data-URI prefix, as Ollama's images field expects). Cleared after
    // the message is sent. Only attached to the current user turn -- not
    // persisted, not resent with history (same scope as RAG document context).
    var pendingImageB64 by remember { mutableStateOf<String?>(null) }
    var pendingImageError by remember { mutableStateOf<String?>(null) }

    // Alva Voice: push-to-talk state. Voice runs on the rig (ASR/TTS live
    // there), so the mic button only shows in rig mode. recording = mic is
    // live; voiceBusy = uploaded audio is being transcribed/answered/spoken.
    val voiceCapture = remember { dk.ternedal.modelrig.voice.VoiceCapture() }
    var recording by remember { mutableStateOf(false) }
    var voiceBusy by remember { mutableStateOf(false) }
    var voiceError by remember { mutableStateOf<String?>(null) }
    // Model-list load failures used to be swallowed silently: "Genindlæs
    // modeller" looked dead when the rig was unreachable. Surface the reason.
    var modelError by remember { mutableStateOf<String?>(null) }

    // Voice always runs ASR + TTS on the rig, but the LLM step in the middle can
    // go to the cloud. That lets a spoken question be answered by a big model
    // (kimi-k2.6) instead of what fits in 12 GB of VRAM. Off by default: the
    // transcript would leave the house, and the local path is the private one.
    var voiceUsesCloud by remember { mutableStateOf(store.voiceUsesCloud) }

    // Barge-in: let the user cut Alva off by speaking while she talks. Needs
    // echo cancellation on speaker (the mic hears Alva otherwise); trivially
    // safe on a headset. Off by default until it's proven on a device.
    var bargeInEnabled by remember { mutableStateOf(store.bargeInEnabled) }
    var wasInterrupted by remember { mutableStateOf(false) }
    var hasMicPermission by remember {
        mutableStateOf(
            androidx.core.content.ContextCompat.checkSelfPermission(
                context, android.Manifest.permission.RECORD_AUDIO,
            ) == android.content.pm.PackageManager.PERMISSION_GRANTED,
        )
    }
    val micPermLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted -> hasMicPermission = granted; if (!granted) voiceError = "Mikrofon-adgang nægtet" }

    // One spoken turn: stop recording -> upload WAV -> rig runs ASR->LLM->TTS
    // -> show transcript + reply in chat -> play the reply audio. No cloud
    // fallback (voice needs the rig). Runs off the main thread.
    fun runVoiceTurn(wav: ByteArray) {
        voiceBusy = true; voiceError = null; wasInterrupted = false
        scope.launch {
            try {
                val result = withContext(Dispatchers.IO) {
                    val b64 = android.util.Base64.encodeToString(wav, android.util.Base64.NO_WRAP)
                    // Cloud answers the spoken question only if the toggle is on
                    // AND a cloud key exists. ASR/TTS always stay on the rig.
                    val key = if (voiceUsesCloud) store.cloudKey else null
                    ModelRigClient(store.baseUrl ?: "", store.token).voiceConverse(
                        b64,
                        language = "da",
                        model = if (key != null) store.cloudModel else null,
                        cloudBaseUrl = if (key != null) "https://ollama.com" else null,
                        cloudKey = key,
                    )
                }
                val transcript = result.optString("transcript").trim()
                val reply = result.optString("reply").trim()
                val audioB64 = result.optString("audio_base64")
                val usedModel = result.optString("model").ifBlank { null }
                val usedCloud = result.optBoolean("via_cloud", false)
                if (transcript.isNotEmpty()) messages.add(Msg("user", transcript))
                if (reply.isNotEmpty()) {
                    messages.add(Msg("assistant", reply, voiceModel = usedModel, voiceViaCloud = usedCloud))
                }
                // Persist like a normal rig turn.
                withContext(Dispatchers.IO) {
                    val cid = convId ?: db.newConversation("rig", currentModel, transcript.take(40))
                    if (convId == null) convId = cid
                    if (transcript.isNotEmpty()) db.addMessage(cid, "user", transcript)
                    if (reply.isNotEmpty()) db.addMessage(cid, "assistant", reply)
                }
                if (audioB64.isNotEmpty()) {
                    val cut = withContext(Dispatchers.IO) {
                        val bytes = android.util.Base64.decode(audioB64, android.util.Base64.DEFAULT)
                        val detector = if (bargeInEnabled && hasMicPermission) {
                            dk.ternedal.modelrig.voice.BargeInDetector()
                        } else null
                        dk.ternedal.modelrig.voice.VoiceCapture.playWav(bytes, detector)
                    }
                    wasInterrupted = cut
                }
            } catch (e: Exception) {
                voiceError = e.message ?: "stemme-fejl"
            } finally {
                voiceBusy = false
            }
        }
    }
    val pickImage = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        pendingImageError = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw RuntimeException("kunne ikke læse billedet")
                    // Cap at ~8 MB raw to avoid oversized base64 payloads / OOM.
                    if (bytes.size > 8 * 1024 * 1024) throw RuntimeException("billedet er for stort (max 8 MB)")
                    android.util.Base64.encodeToString(bytes, android.util.Base64.NO_WRAP)
                }
            }
            result.onSuccess { pendingImageB64 = it }
                .onFailure { pendingImageError = it.message }
        }
    }

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
                    var name = uri.lastPathSegment ?: "dokument"
                    resolver.query(uri, null, null, null, null)?.use { c ->
                        val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
                    }
                    val mime = resolver.getType(uri) ?: ""
                    val lower = name.lowercase()
                    val isPdf = mime == "application/pdf" || lower.endsWith(".pdf")
                    val isDocx = mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
                        lower.endsWith(".docx")
                    val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw RuntimeException("kunne ikke læse filen")
                    if (bytes.isEmpty()) throw RuntimeException("filen er tom")
                    val client = ModelRigClient(store.baseUrl ?: "", store.token)
                    when {
                        isPdf -> name to client.ingestPdf(name, bytes)
                        isDocx -> name to client.ingestDocx(name, bytes)
                        else -> {
                            // Plain text/markdown: send decoded text as before.
                            val text = bytes.toString(Charsets.UTF_8)
                            if (text.isBlank()) throw RuntimeException("filen er tom")
                            name to client.ingestText(name, text)
                        }
                    }
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
    // Re-read the persisted cloud model when the picker changed it.
    LaunchedEffect(cloudModelTick) { cloudModel = store.cloudModel }

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
                // NB: for cloud we deliberately do NOT restore the model from
                // the conversation's metadata. store.cloudModel (set in the
                // picker) is the single authority for which cloud model runs;
                // restoring per-conversation here fought the picker and left
                // the chip showing a stale model after a switch (Anders, 8/7).
                if (meta.source == "cloud" && hasCloud) { mode = "cloud"; ragMode = false }
                if (meta.source == "rag" && hasRig) { mode = "rig"; ragMode = true; if (meta.model.isNotBlank()) { currentModel = meta.model } }
                if (meta.source == "rig" && hasRig) { mode = "rig"; ragMode = false; if (meta.model.isNotBlank()) { currentModel = meta.model } }
            }
            // Cloud model always reflects the current default, even after
            // loading an old conversation.
            cloudModel = store.cloudModel
        }
    }

    LaunchedEffect(messages.size, messages.lastOrNull()?.text?.length) {
        if (messages.isNotEmpty()) listState.scrollToItem(messages.size - 1)
    }

    val onSend: () -> Unit = onSend@{
        val t = input.trim()
        // Allow an image-only turn (vision: "describe this" with no text).
        if ((t.isEmpty() && pendingImageB64 == null) || busy) return@onSend
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
        // Capture + clear the pending image now (this turn owns it). RAG is
        // text retrieval, not vision, so images are only sent on cloud/rig
        // chat, never the RAG branch.
        val imageB64 = if (useRag) null else pendingImageB64
        pendingImageB64 = null
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

            // Track whether the rig stream emitted anything, so we only fall
            // back to cloud on a clean pre-emit failure (never mid-stream --
            // that would double the visible output). Mirrors desktop's
            // ChatRouter.chatStream contract.
            var rigEmitted = 0
            var didFallback = false
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
                            CloudClient(key).chatStream(cModel, history, registerCall = hook, imageB64 = imageB64, onDelta = onDelta)
                        }
                        else -> {
                            // Rig chat, local-first with automatic cloud fallback:
                            // try the rig; if it fails BEFORE emitting anything and a
                            // cloud key is set, transparently answer via cloud instead
                            // (rig down / model not pulled / HTTP error). A mid-stream
                            // rig failure is surfaced, not retried.
                            val cloudKey = store.cloudKey
                            try {
                                ModelRigClient(store.baseUrl ?: "", store.token)
                                    .chatStream(rigModel, history, registerCall = hook, imageB64 = imageB64,
                                        onDelta = { d -> rigEmitted++; onDelta(d) })
                            } catch (e: Exception) {
                                if (rigEmitted == 0 && cloudKey != null) {
                                    didFallback = true
                                    CloudClient(cloudKey).chatStream(cModel, history, registerCall = hook, imageB64 = imageB64, onDelta = onDelta)
                                } else throw e
                            }
                        }
                    }
                }.exceptionOrNull()
            }
            activeCall = null
            val cur = messages[idx]
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[idx] = when {
                err == null -> cur.copy(streaming = false, fellBackToCloud = didFallback)
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
                        else -> {
                            // Same local-first cloud fallback as the main send
                            // path: retrying a rig message while the rig is down
                            // should still fall back to cloud (before any
                            // output), not just fail. A mid-stream failure is
                            // surfaced, not retried.
                            val cloudKey = store.cloudKey
                            var rigEmitted = 0
                            try {
                                ModelRigClient(store.baseUrl ?: "", store.token)
                                    .chatStream(rigModel, history, registerCall = hook,
                                        onDelta = { d -> rigEmitted++; onDelta(d) })
                            } catch (e: Exception) {
                                if (rigEmitted == 0 && cloudKey != null) {
                                    CloudClient(cloudKey).chatStream(cModel, history, registerCall = hook, onDelta = onDelta)
                                } else throw e
                            }
                        }
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
                    ModelChip("☁  $cloudModel  ▾", onClick = { onOpenCloudPicker() })
                } else {
                    Box {
                        ModelChip("$currentModel  ▾", onClick = { modelMenu = true })
                        DropdownMenu(expanded = modelMenu, onDismissRequest = { modelMenu = false }) {
                            // Voice: ASR/TTS always run on the rig, but the LLM
                            // step can go to a big cloud model. Only meaningful
                            // in rig mode with a cloud key configured.
                            if (mode == "rig" && store.cloudKey != null) {
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            (if (voiceUsesCloud) "☁ " else "◇ ") +
                                                "Stemme svarer via cloud (${store.cloudModel})",
                                            color = if (voiceUsesCloud) Signal else TextMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        voiceUsesCloud = !voiceUsesCloud
                                        store.voiceUsesCloud = voiceUsesCloud
                                        modelMenu = false
                                    },
                                )
                            }
                            // Barge-in: speak to cut Alva off mid-reply. Needs the
                            // mic while she talks, hence the permission check.
                            if (mode == "rig") {
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            (if (bargeInEnabled) "✋ " else "◇ ") +
                                                "Afbryd Alva ved at tale",
                                            color = if (bargeInEnabled) Signal else TextMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        bargeInEnabled = !bargeInEnabled
                                        store.bargeInEnabled = bargeInEnabled
                                        modelMenu = false
                                    },
                                )
                            }
                            if (mode == "rig") HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("↻  Genindlæs modeller", color = Signal) },
                                onClick = {
                                    modelMenu = false
                                    scope.launch {
                                        modelError = null
                                        val res = withContext(Dispatchers.IO) {
                                            runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listModels() }
                                        }
                                        res.onSuccess {
                                            models = it
                                            if (it.isEmpty()) modelError = "Rig'en svarede, men har ingen modeller"
                                        }.onFailure {
                                            // Don't fail silently -- the user just
                                            // sees a dead button otherwise.
                                            modelError = "Kan ikke hente modeller: rig'en svarer ikke"
                                        }
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
                                    text = { Text(if (ingesting) "Ingesterer…" else "+ Tilføj dokument (txt/md)…", color = if (ingesting) TextMuted else Signal) },
                                    enabled = !ingesting,
                                    onClick = { ragSourceMenu = false; pickDocument.launch(arrayOf("text/plain", "text/markdown", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/octet-stream")) },
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
                        ingestError != null -> Text("Fejl: ${friendlyError(ingestError!!)}", color = Danger, fontSize = 11.sp)
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
            Column(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.ime.union(WindowInsets.navigationBars))
                    .padding(horizontal = 12.dp, vertical = 10.dp),
            ) {
                // Pending image chip: shows an image is attached to the next
                // message, with an ✕ to remove it before sending.
                pendingImageB64?.let {
                    Row(
                        Modifier.fillMaxWidth().padding(bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("🖼 Billede vedhæftet", color = Signal, fontSize = 12.sp)
                        Spacer(Modifier.weight(1f))
                        TextButton(onClick = { pendingImageB64 = null }) {
                            Text("✕ Fjern", color = TextMuted, fontSize = 12.sp)
                        }
                    }
                }
                pendingImageError?.let {
                    Text("Billedfejl: $it", color = Danger, fontSize = 11.sp, modifier = Modifier.padding(bottom = 4.dp))
                }
                // Alva Voice status line (recording / working / error).
                if (recording || voiceBusy || voiceError != null) {
                    val vt = when {
                        recording -> "🎙 Optager… tryk igen for at sende"
                        voiceBusy -> "🔊 Alva lytter og svarer…"
                        else -> "Stemme-fejl: ${voiceError.orEmpty()}"
                    }
                    Text(
                        vt,
                        color = if (voiceError != null && !recording && !voiceBusy) Danger else Signal,
                        fontSize = 12.sp, modifier = Modifier.padding(bottom = 6.dp),
                    )
                }
                modelError?.let {
                    Text(it, color = Danger, fontSize = 12.sp, modifier = Modifier.padding(bottom = 6.dp))
                }
                if (wasInterrupted && !voiceBusy && !recording) {
                    Text(
                        "✋ Du afbrød Alva — tryk 🎙 for at sige noget",
                        color = TextMuted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 6.dp),
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // Vision is chat-only (cloud/rig), not RAG. Requires a
                    // vision-capable model; the button just attaches — the
                    // model choice is the user's.
                    if (mode != "rig" || !ragMode) {
                        Box(
                            Modifier.size(44.dp).clickable(enabled = !busy, onClick = {
                                pendingImageError = null
                                pickImage.launch(arrayOf("image/*"))
                            }),
                            contentAlignment = Alignment.Center,
                        ) { Text("📎", fontSize = 20.sp) }
                        Spacer(Modifier.width(2.dp))
                    }
                    // Alva Voice mic button: rig mode only (voice runs on the
                    // rig). Tap to start recording, tap again to send. Disabled
                    // while a voice turn is in flight.
                    if (mode == "rig") {
                        Box(
                            Modifier.size(44.dp).clickable(enabled = !busy && !voiceBusy, onClick = {
                                voiceError = null
                                if (!hasMicPermission) {
                                    micPermLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
                                } else if (recording) {
                                    recording = false
                                    val wav = voiceCapture.stopToWav()
                                    if (wav != null) runVoiceTurn(wav) else voiceError = "ingen lyd optaget"
                                } else {
                                    wasInterrupted = false
                                    try { voiceCapture.start(); recording = true }
                                    catch (e: Exception) { voiceError = e.message ?: "kunne ikke optage" }
                                }
                            }),
                            contentAlignment = Alignment.Center,
                        ) { Text(if (recording) "⏺" else "🎙", fontSize = 20.sp) }
                        Spacer(Modifier.width(2.dp))
                    }
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
                        // Can send with text OR just an image (vision prompts
                        // are often "what's in this?" with an image and no text).
                        val canSend = input.isNotBlank() || pendingImageB64 != null
                        Box(
                            Modifier.size(44.dp).clickable(enabled = canSend, onClick = onSend),
                            contentAlignment = Alignment.Center,
                        ) { SendGlyph(color = if (canSend) Signal else TextMuted, modifier = Modifier.size(26.dp)) }
                    }
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
                                            appendLine("# ${c.title.ifBlank { "Alva-samtale" }}")
                                            appendLine()
                                            db.loadMessages(c.id).forEach { (role, content) ->
                                                appendLine(if (role == "user") "**Du:**" else "**Assistent:**")
                                                appendLine(content)
                                                appendLine()
                                            }
                                        }
                                        val intent = Intent(Intent.ACTION_SEND).apply {
                                            type = "text/plain"
                                            putExtra(Intent.EXTRA_SUBJECT, c.title.ifBlank { "Alva-samtale" })
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
            pullError?.let { Spacer(Modifier.height(6.dp)); Text("Fejl: ${friendlyError(it)}", color = Danger, fontSize = 12.sp) }

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
            loadError?.let { Text("Fejl: ${friendlyError(it)}", color = Danger, fontSize = 12.sp); Spacer(Modifier.height(6.dp)) }
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

/**
 * Fullscreen cloud model picker -- replaces the old cramped dropdown that
 * couldn't scroll a 20+ model list. Same shape as ModelsScreen (top bar +
 * back). The currently-selected default is pinned at the top with a check;
 * the rest are listed alphabetically below a search field that filters as you
 * type. Picking one persists it as store.cloudModel (the default used on every
 * open) and returns to chat. Auto-loads the list on entry if empty.
 */
@Composable
private fun CloudModelPickerScreen(store: TokenStore, onPicked: () -> Unit, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var models by remember { mutableStateOf(listOf<String>()) }
    var query by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val selected = store.cloudModel

    fun reload() {
        val key = store.cloudKey ?: return
        loading = true; error = null
        scope.launch {
            val res = withContext(Dispatchers.IO) { runCatching { CloudClient(key).listModels() } }
            res.onSuccess { models = it.sorted(); loading = false }
                .onFailure { error = friendlyError(it); loading = false }
        }
    }
    LaunchedEffect(Unit) { if (models.isEmpty()) reload() }

    val shown = remember(models, query) {
        val others = models.filter { it != selected }
        (if (query.isBlank()) others else others.filter { it.contains(query, ignoreCase = true) })
    }

    Column(Modifier.fillMaxSize()) {
        Surface(color = GraphiteSurface, tonalElevation = 2.dp) {
            Column(
                Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onBack) { Text("←", color = TextHigh, fontSize = 18.sp) }
                    Text("Vælg cloud-model", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = TextHigh)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { reload() }) { Text("↻", color = Signal, fontSize = 16.sp) }
                }
                OutlinedTextField(
                    value = query, onValueChange = { query = it },
                    placeholder = { Text("Søg i modeller…", fontSize = 13.sp) },
                    singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                )
            }
        }
        error?.let { Text(it, color = Danger, fontSize = 12.sp, modifier = Modifier.padding(12.dp)) }
        if (loading && models.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Henter modeller…", color = TextMuted, fontSize = 14.sp)
            }
        } else {
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(vertical = 8.dp)) {
                // pinned selected/default
                item {
                    Text("Nuværende standard", color = TextMuted, fontSize = 11.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    Row(
                        Modifier.fillMaxWidth().clickable { onBack() }
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("✓", color = Signal, fontSize = 15.sp, modifier = Modifier.width(24.dp))
                        Text(selected, color = Signal, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    }
                    if (shown.isNotEmpty()) {
                        HorizontalDivider()
                        Text("Alle modeller", color = TextMuted, fontSize = 11.sp,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    }
                }
                items(shown, key = { it }) { m ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { store.cloudModel = m; onPicked() }
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Spacer(Modifier.width(24.dp))
                        Text(m, color = TextHigh, fontSize = 15.sp)
                    }
                }
                if (shown.isEmpty() && query.isNotBlank()) {
                    item {
                        Text("Ingen match på \"$query\"", color = TextMuted, fontSize = 14.sp,
                            modifier = Modifier.padding(16.dp))
                    }
                }
            }
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
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
                    // Spoken replies say which brain answered -- otherwise it's
                    // invisible whether the rig or a cloud model did the thinking.
                    if (!isUser && m.voiceModel != null) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            Surface(shape = RoundedCornerShape(999.dp), color = GraphiteSurfaceHigh) {
                                Text(
                                    (if (m.voiceViaCloud) "☁ " else "◈ ") + "🎙 ${m.voiceModel}",
                                    fontSize = 10.sp,
                                    color = if (m.voiceViaCloud) Signal else TextMuted,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                            }
                        }
                    }
                    if (!isUser && m.fellBackToCloud) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = GraphiteSurfaceHigh,
                            ) {
                                Text(
                                    "☁ via cloud (rig utilgængelig)",
                                    fontSize = 10.sp, color = TextMuted,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                            }
                        }
                    }
                    if (!isUser && m.sources.isNotEmpty()) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            // distinct(): a source split into several chunks is
                            // still one source -- the RAG answer returns one
                            // chip per matched chunk, so without this a single
                            // file cited twice showed as two identical chips
                            // (seen on-device 7/7: "test" appeared twice).
                            m.sources.distinct().take(4).forEach { s ->
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

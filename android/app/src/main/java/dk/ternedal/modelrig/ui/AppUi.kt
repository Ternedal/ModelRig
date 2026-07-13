package dk.ternedal.modelrig.ui


import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import android.graphics.ImageDecoder
import android.graphics.drawable.AnimatedImageDrawable
import android.os.Build
import android.widget.ImageView
import androidx.compose.ui.viewinterop.AndroidView
import androidx.compose.foundation.background
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
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import android.content.Intent
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.data.ChatDb
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.CloudClient
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.theme.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private enum class Screen { Splash, Setup, Chat, Convos, Models, Knowledge, CloudPicker, VoiceCloudPicker }

@Composable
fun AppUi() {
    val context = LocalContext.current
    val store = remember { TokenStore(context) }
    val db = remember { ChatDb(context) }
    // The chosen mode lives here, above the theme, so the in-app toggle can flip
    // it and the whole tree recomposes into the other palette live -- no restart.
    var darkMode by remember { mutableStateOf(store.darkMode) }
    ModelRigTheme(dark = darkMode) {
        // Launch on the textured splash (design guide: texture in hero/splash/
        // icon). The OS SplashScreen API only allows a solid colour + centred
        // icon, so the TEXTURE has to be an in-app splash drawn by Compose.
        var screen by remember { mutableStateOf(Screen.Splash) }
        // conversation to open in ChatScreen; null = start fresh / latest
        var openConvId by remember { mutableStateOf(db.latestConversationId()) }
        // bumped when the cloud model is changed elsewhere (picker), so
        // ChatScreen re-reads store.cloudModel when it comes back into view.
        var cloudModelTick by remember { mutableStateOf(0) }

        Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
            when (screen) {
                Screen.Splash -> SplashScreen(onDone = {
                    screen = if (store.hasRig || store.hasCloud) Screen.Chat else Screen.Setup
                })
                Screen.Setup -> SetupScreen(store, db, onDone = { screen = Screen.Chat })
                Screen.Chat -> ChatScreen(
                    store, db, openConvId, cloudModelTick,
                    darkMode = darkMode,
                    onToggleDark = { store.darkMode = it; darkMode = it },
                    onOpenSettings = { screen = Screen.Setup },
                    onOpenConversations = { screen = Screen.Convos },
                    onOpenModels = { screen = Screen.Models },
                    onOpenKnowledge = { screen = Screen.Knowledge },
                    onOpenCloudPicker = { screen = Screen.CloudPicker },
                    onOpenVoiceCloudPicker = { screen = Screen.VoiceCloudPicker },
                    onConvChanged = { openConvId = it },
                )
                Screen.Convos -> ConversationsScreen(
                    db,
                    activeConvId = openConvId,
                    onOpen = { openConvId = it; screen = Screen.Chat },
                    onNew = { openConvId = null; screen = Screen.Chat },
                    onActiveDeleted = { openConvId = null },
                    onBack = { screen = Screen.Chat },
                )
                Screen.Models -> ModelsScreen(store, onBack = { screen = Screen.Chat })
                Screen.Knowledge -> KnowledgeScreen(store, onBack = { screen = Screen.Chat })
                Screen.VoiceCloudPicker -> CloudModelPickerScreen(
                    store,
                    forVoice = true,
                    // The voice cloud picker is only reachable from rig mode (voice
                    // keeps ASR/TTS local). Force chatMode back to rig on return so
                    // ChatScreen -- which re-reads store.chatMode when it recomposes
                    // -- lands back on rig, not cloud. Without this it sprang to the
                    // cloud chat, which is not where the user came from.
                    onPicked = { store.chatMode = "rig"; cloudModelTick++; screen = Screen.Chat },
                    onBack = { store.chatMode = "rig"; cloudModelTick++; screen = Screen.Chat },
                )
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
            Text(
                "Kaliv",
                fontFamily = androidx.compose.ui.text.font.FontFamily.Serif,
                fontSize = 28.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh,
                letterSpacing = 2.sp,
            )
            Spacer(Modifier.weight(1f))
            if (canChat) TextButton(onClick = onDone) { Text("Til chat →", color = KalivTheme.colors.signal) }
        }
        Text("Vælg mindst én kilde", fontSize = 14.sp, color = KalivTheme.colors.textMuted)
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

    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Ollama Cloud", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
            Text("Chat uden at rig'en kører. Modeller i skyen.", fontSize = 12.sp, color = KalivTheme.colors.textMuted)
            if (configured) { Spacer(Modifier.height(4.dp)); Text("✓ konfigureret", color = KalivTheme.colors.signal, fontSize = 13.sp) }
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = key, onValueChange = { key = it },
                label = { Text(if (configured) "Ny API-nøgle (valgfri)" else "API-nøgle", fontSize = 12.sp) },
                singleLine = true, visualTransformation = PasswordVisualTransformation(),
                modifier = Modifier.fillMaxWidth(),
            )
            Text("Hentes på ollama.com/settings/keys", fontSize = 11.sp, color = KalivTheme.colors.textMuted)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = model, onValueChange = { model = it },
                label = { Text("Standardmodel (fx gpt-oss:120b)", fontSize = 12.sp) },
                singleLine = true, modifier = Modifier.fillMaxWidth(),
            )
            Text("Modellen der bruges som standard. Du kan også vælge fra din cloud-kontos liste via ☁-menuen øverst i chatten.",
                fontSize = 11.sp, color = KalivTheme.colors.textMuted, lineHeight = 15.sp)
            Spacer(Modifier.height(8.dp))
            OutlinedTextField(
                value = system, onValueChange = { system = it; store.cloudSystem = it },
                label = { Text("System-instruktion (valgfri)", fontSize = 12.sp) },
                minLines = 2, maxLines = 5, modifier = Modifier.fillMaxWidth(),
            )
            Text("Rolle/baggrund modellen altid får. Fx: Du er en skarp dansk backend-udvikler. Svar kort.",
                fontSize = 11.sp, color = KalivTheme.colors.textMuted, lineHeight = 15.sp)
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
                    TextButton(onClick = { store.clearCloud(); configured = false; key = "" }) { Text("Ryd", color = KalivTheme.colors.danger) }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp) }
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

    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(16.dp)) {
            Text("Din rig (backend)", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
            Text("Lokale modeller + RAG. Kræver at rig'en kører.", fontSize = 12.sp, color = KalivTheme.colors.textMuted)
            if (connected) {
                Spacer(Modifier.height(4.dp))
                when (reachable) {
                    true -> Text("✓ forbundet", color = KalivTheme.colors.signal, fontSize = 13.sp)
                    false -> Text(
                        "⚠ parret, men rig'en svarer ikke — tjek IP og at serveren kører",
                        color = KalivTheme.colors.danger, fontSize = 13.sp,
                    )
                    null -> Text("… tjekker forbindelsen", color = KalivTheme.colors.textMuted, fontSize = 13.sp)
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
                color = KalivTheme.colors.textMuted, fontSize = 11.sp, lineHeight = 15.sp)
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
                    TextButton(onClick = { store.clearRig(); connected = false; reachable = null }) { Text("Afbryd", color = KalivTheme.colors.danger) }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp) }
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
                color = KalivTheme.colors.surfaceHigh,
                modifier = Modifier.padding(end = 6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = KalivTheme.colors.textHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deleteRigProfile(p.id)
                                profiles = db.listRigProfiles()
                            }.onFailure { profileError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = KalivTheme.colors.textMuted, fontSize = 11.sp) }
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
                color = if (canSaveCurrent) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
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
            ) { Text("Gem", color = if (newName.isNotBlank() && currentToken != null) KalivTheme.colors.signal else KalivTheme.colors.textMuted, fontWeight = FontWeight.Bold) }
        }
    }
    profileError?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 11.sp) }
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
                color = KalivTheme.colors.surfaceHigh,
                modifier = Modifier.padding(end = 6.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(
                        onClick = { onApply(p.prompt) },
                        contentPadding = PaddingValues(start = 12.dp, end = 4.dp),
                    ) { Text(p.name, color = KalivTheme.colors.textHigh, fontSize = 12.sp) }
                    TextButton(
                        onClick = {
                            runCatching {
                                db.deletePreset(p.id)
                                presets = db.listPresets(source)
                            }.onFailure { presetError = "Kunne ikke slette: ${it.message}" }
                        },
                        contentPadding = PaddingValues(start = 4.dp, end = 12.dp),
                    ) { Text("✕", color = KalivTheme.colors.textMuted, fontSize = 11.sp) }
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
                color = if (currentPrompt.isNotBlank()) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
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
            ) { Text("Gem", color = if (newName.isNotBlank()) KalivTheme.colors.signal else KalivTheme.colors.textMuted, fontWeight = FontWeight.Bold) }
        }
    }
    presetError?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 11.sp) }
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
// Kaliv shouldn't emoji (the persona says so), but small local models keep doing
// it anyway no matter how firm the prompt is -- qwen3:14b still ended replies with
// 🌟✨ after "INGEN emojis. Aldrig.". Since the rig chat proxies straight to Ollama
// (no worker pass to clean it server-side), we strip emojis from the finished
// reply client-side. Deterministic: it doesn't matter whether the model obeyed.
// Covers the common pictographic ranges plus variation selectors and ZWJ; leaves
// ordinary text, Danish letters, and punctuation untouched.
private val EMOJI_REGEX = Regex(
    "[\uD83C-\uDBFF\uDC00-\uDFFF]" +          // surrogate pairs (most emoji)
    "|[\u2600-\u27BF]" +                          // misc symbols + dingbats (☀ ✨ ✋ etc.)
    "|[\u2190-\u21FF]" +                          // arrows sometimes rendered as emoji
    "|[\uFE00-\uFE0F]" +                          // variation selectors
    "|\u200D" +                                     // zero-width joiner
    "|[\u2B00-\u2BFF]"                            // extra symbols (⭐ etc.)
)

private fun stripEmojis(text: String): String {
    // Remove emojis, then tidy the whitespace they leave behind (trailing spaces
    // before newlines, doubled spaces, spaces before punctuation).
    var t = EMOJI_REGEX.replace(text, "")
    t = t.replace(Regex("[ \t]+([.,!?])"), "$1")
    t = t.replace(Regex("[ \t]{2,}"), " ")
    t = t.replace(Regex(" +\n"), "\n")
    t = t.replace(Regex("\n{3,}"), "\n\n")
    return t.trim()
}

private fun friendlyError(err: Throwable): String {
    val msg = err.message ?: ""
    return when {
        err is java.net.UnknownHostException || err is java.net.ConnectException ->
            "Kan ikke oprette forbindelse. Tjek at rig'en kører, og at telefonen er på samme netværk (eller Tailscale)."
        err is java.net.SocketTimeoutException ->
            "Tidsudløb — modellen svarede ikke i tide. I cloud-mode: tjek at modelnavnet findes på din konto (fx gpt-oss:120b) og at nøglen er gyldig. Ellers prøv igen eller vælg en mindre model."
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
        // Tool layer off on the rig (KALIV_TOOLS_ENABLED not set). This was
        // surfacing as a misleading "modellen svarede ikke i tide" -- name the
        // real cause so nobody chases a timeout that never existed.
        msg.contains("tool layer is disabled") || msg.contains("(403)") ->
            "Tool-laget er slået fra på rig'en. Start workeren med KALIV_TOOLS_ENABLED=1."
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
    darkMode: Boolean,
    onToggleDark: (Boolean) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
    onOpenModels: () -> Unit,
    onOpenKnowledge: () -> Unit,
    onOpenCloudPicker: () -> Unit,
    onOpenVoiceCloudPicker: () -> Unit,
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
    // D4 consent (per session, default off): may RAG document content be sent to
    // a CLOUD model? Off -> the rig keeps document content local (refuses RAG+cloud).
    var allowRagCloud by remember { mutableStateOf(false) }
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
    var imageIngestStatus by remember { mutableStateOf<String?>(null) }

    // Kaliv Voice: push-to-talk state. Voice runs on the rig (ASR/TTS live
    // there), so the mic button only shows in rig mode. recording = mic is
    // live; voiceBusy = uploaded audio is being transcribed/answered/spoken.
    val voiceCapture = remember { dk.ternedal.modelrig.voice.VoiceCapture() }
    var recording by remember { mutableStateOf(false) }
    var voiceBusy by remember { mutableStateOf(false) }
    var voiceError by remember { mutableStateOf<String?>(null) }
    // Tap-to-stop (v1.13.0). Until now a voice turn could not be interrupted
    // at all: barge-in is off by default and uncalibrated. Two mechanisms,
    // because a turn has two phases with different escape routes:
    //   voiceJob   -- cancels the coroutine (covers the rig round-trip)
    //   playbackStop -- a flag playWav's write loop checks between chunks;
    //                   cancelling a coroutine cannot interrupt the blocking
    //                   AudioTrack write, so the flag is what actually stops
    //                   the sound.
    var voiceJob by remember { mutableStateOf<Job?>(null) }
    val playbackStop = remember { java.util.concurrent.atomic.AtomicBoolean(false) }
    var speaking by remember { mutableStateOf(false) }
    // Model-list load failures used to be swallowed silently: "Genindlæs
    // modeller" looked dead when the rig was unreachable. Surface the reason.
    var modelError by remember { mutableStateOf<String?>(null) }

    // Voice always runs ASR + TTS on the rig, but the LLM step in the middle can
    // go to the cloud. That lets a spoken question be answered by a big model
    // (kimi-k2.6) instead of what fits in 12 GB of VRAM. Off by default: the
    // transcript would leave the house, and the local path is the private one.
    var voiceUsesCloud by remember { mutableStateOf(store.voiceUsesCloud) }

    // Barge-in: let the user cut Kaliv off by speaking while she talks. Needs
    // echo cancellation on speaker (the mic hears Kaliv otherwise); trivially
    // safe on a headset. Off by default until it's proven on a device.
    var bargeInEnabled by remember { mutableStateOf(store.bargeInEnabled) }
    var wasInterrupted by remember { mutableStateOf(false) }
    // Barge-in calibration (v1.15.0). The threshold used to be a hardcoded
    // guess with no way to check it. Now: the detector reports what it hears,
    // and the number is settable. Read the peak while speaking over Kaliv,
    // then set the threshold between the idle floor and that peak.
    var bargeInThreshold by remember { mutableStateOf(store.bargeInThreshold) }
    // Kaliv Tools: when on, a chat turn goes through the rig's tool layer and
    // the model may propose an action. A write proposal parks here until the
    // human decides -- nothing has run when this is non-null.
    var toolsMode by remember { mutableStateOf(store.toolsMode) }
    var pendingTool by remember { mutableStateOf<dk.ternedal.modelrig.net.ToolTurn?>(null) }
    var toolBusy by remember { mutableStateOf(false) }
    // Audit log viewer. An append-only log nobody can read is only half a
    // safeguard: the point is to SEE what was proposed, approved and refused.
    var showAudit by remember { mutableStateOf(false) }
    var auditRows by remember { mutableStateOf<List<dk.ternedal.modelrig.net.AuditEntry>>(emptyList()) }
    var auditError by remember { mutableStateOf<String?>(null) }
    // Rig-side tool control. The kill switch used to be an env var only, so
    // stopping a misbehaving tool meant restarting the worker. Now it is a tap.
    var showToolCtl by remember { mutableStateOf(false) }
    var registry by remember { mutableStateOf<dk.ternedal.modelrig.net.ToolRegistry?>(null) }
    var registryError by remember { mutableStateOf<String?>(null) }
    var registryBusy by remember { mutableStateOf(false) }

    fun loadRegistry() {
        registryBusy = true
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).toolsList() }
            }
            registryBusy = false
            registry = r.getOrNull()
            registryError = r.exceptionOrNull()?.let { friendlyError(it) }
        }
    }

    fun toggleTool(enabled: Boolean, tool: String?) {
        registryBusy = true
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    ModelRigClient(store.baseUrl ?: "", store.token).setToolsEnabled(enabled, tool)
                }
            }
            registryBusy = false
            r.getOrNull()?.let { registry = it }
            registryError = r.exceptionOrNull()?.let { friendlyError(it) }
        }
    }
    var liveRms by remember { mutableStateOf(0.0) }
    var peakRms by remember { mutableStateOf(0.0) }
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

    // One spoken turn, STREAMING: stop recording -> upload WAV -> the rig streams
    // back the transcript, then each sentence's audio as it's synthesized. We play
    // each chunk the moment it arrives (queued, in order), so Kaliv starts speaking
    // the first sentence while the rest is still generating -- instead of waiting
    // for the whole reply (the old buffered path felt slow with big cloud models).
    // ASR/TTS stay on the rig; only the LLM step may go to cloud. Off the main thread.
    fun runVoiceTurn(wav: ByteArray) {
        voiceBusy = true; voiceError = null; wasInterrupted = false
        speaking = false; playbackStop.set(false)
        voiceJob = scope.launch {
            // Audio chunks flow from the network reader (producer) to the player
            // (consumer) through this channel. Unlimited: sentences are small and
            // we never want the reader to block on a slow player.
            val audioChan = Channel<ByteArray>(Channel.UNLIMITED)
            var transcriptText = ""
            var transcriptShown = false
            var replyIdx = -1
            val replyBuilder = StringBuilder()
            var usedModel: String? = null
            var usedCloud = false
            var streamError: Pair<Int, String>? = null

            // Player: pull decoded WAVs and play each in order via playWav, which
            // blocks until that sentence finishes (or barge-in/stop cuts it).
            val detector = if (bargeInEnabled && hasMicPermission) {
                dk.ternedal.modelrig.voice.BargeInDetector(rmsThreshold = bargeInThreshold.toDouble())
            } else null
            val player = launch(Dispatchers.IO) {
                for (bytes in audioChan) {
                    if (playbackStop.get()) break
                    speaking = true
                    val cut = dk.ternedal.modelrig.voice.VoiceCapture.playWav(bytes, detector, playbackStop)
                    if (cut) { wasInterrupted = true; playbackStop.set(true); break }
                }
                speaking = false
            }
            // Poll the barge-in detector at 5 Hz to drive the on-screen RMS meter
            // (liveRms / peakRms). The streaming rewrite has to carry this over
            // explicitly -- without it the meter sits frozen at 0 for the whole
            // spoken turn even though barge-in detection still works.
            val meter = detector?.let {
                launch {
                    while (isActive) {
                        liveRms = it.lastRms; peakRms = it.peakRms
                        delay(200)
                    }
                }
            }

            try {
                withContext(Dispatchers.IO) {
                    val b64 = android.util.Base64.encodeToString(wav, android.util.Base64.NO_WRAP)
                    val key = if (voiceUsesCloud) store.cloudKey else null
                    ModelRigClient(store.baseUrl ?: "", store.token).voiceConverseStream(
                        b64,
                        language = "da",
                        model = if (key != null) store.voiceCloudModel else currentModel,
                        cloudBaseUrl = if (key != null) "https://ollama.com" else null,
                        cloudKey = key,
                        registerCall = { c -> activeCall = c },
                        onTranscript = { t ->
                            val tt = t.trim()
                            if (tt.isNotEmpty() && !transcriptShown) {
                                transcriptShown = true
                                transcriptText = tt
                                // messages is a SnapshotStateList -- safe to mutate
                                // from this IO thread; the recomposer picks it up.
                                // Set replyIdx synchronously (the callbacks run in
                                // order on the reader thread) so the first chunk
                                // can reference it.
                                messages.add(Msg("user", tt))
                                replyIdx = messages.size
                                messages.add(Msg("assistant", "", streaming = true))
                            }
                        },
                        onChunk = { _, text, chunkB64 ->
                            if (replyBuilder.isNotEmpty()) replyBuilder.append(" ")
                            replyBuilder.append(text.trim())
                            if (replyIdx in messages.indices) {
                                messages[replyIdx] = messages[replyIdx].copy(text = stripEmojis(replyBuilder.toString()))
                            }
                            if (chunkB64.isNotEmpty() && !playbackStop.get()) {
                                val bytes = android.util.Base64.decode(chunkB64, android.util.Base64.DEFAULT)
                                audioChan.trySend(bytes)
                            }
                        },
                        onDone = { reply, m, cloud ->
                            usedModel = m; usedCloud = cloud
                            val finalText = stripEmojis(reply.trim().ifEmpty { replyBuilder.toString() })
                            if (replyIdx in messages.indices) {
                                messages[replyIdx] = messages[replyIdx].copy(
                                    text = finalText,
                                    streaming = false, voiceModel = m, voiceViaCloud = cloud,
                                )
                            }
                        },
                        onError = { status, detail -> streamError = status to detail },
                    )
                }
                // The network stream is done; close the channel so the player
                // finishes the queued sentences, then wait for it.
                audioChan.close()
                player.join()

                streamError?.let { (status, detail) ->
                    voiceError = friendlyError(RuntimeException("voice ($status): $detail"))
                }

                // Persist the finished turn like a normal rig turn.
                // Persist the finished turn like a normal rig turn, using the
                // captured transcript (not a fragile read-back from the message
                // list). If the reply is empty (e.g. all-markup), still persist
                // the user turn but skip an empty assistant row, and drop the
                // empty bubble from the UI.
                val finalReply = replyBuilder.toString().trim()
                if (finalReply.isEmpty() && replyIdx in messages.indices &&
                    messages.getOrNull(replyIdx)?.text.isNullOrBlank()) {
                    messages.removeAt(replyIdx)
                }
                withContext(Dispatchers.IO) {
                    val cid = convId ?: db.newConversation("rig", currentModel, transcriptText.ifBlank { "tale" }.take(40))
                    if (convId == null) convId = cid
                    if (transcriptText.isNotBlank()) db.addMessage(cid, "user", transcriptText)
                    if (finalReply.isNotEmpty()) db.addMessage(cid, "assistant", finalReply)
                }
            } catch (e: CancellationException) {
                wasInterrupted = true
                playbackStop.set(true)
                audioChan.close()
                throw e
            } catch (e: Exception) {
                voiceError = e.message ?: "stemme-fejl"
                audioChan.close()
            } finally {
                activeCall = null
                player.cancel()
                meter?.cancel()
                // peakRms survives the turn: it's the measurement of the loudest
                // barge-in attempt. liveRms resets to 0 (nothing playing now).
                detector?.let { liveRms = 0.0; peakRms = it.peakRms }
                speaking = false
                voiceBusy = false
                voiceJob = null
            }
        }
    }

    /**
     * Cut the current voice turn short. Order matters: raise the flag first so
     * a blocking playWav write returns, then cancel the coroutine. Cancelling
     * first would leave the audio playing until the WAV ran out.
     */
    fun stopVoiceTurn() {
        playbackStop.set(true)
        voiceJob?.cancel()
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
                    val isPptx = mime == "application/vnd.openxmlformats-officedocument.presentationml.presentation" ||
                        lower.endsWith(".pptx")
                    // Extension first for HTML: providers report saved pages as
                    // text/html, but also sometimes as text/plain, and a page
                    // sent through ingestText would keep all its markup.
                    val isHtml = lower.endsWith(".html") || lower.endsWith(".htm") || mime == "text/html"
                    val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw RuntimeException("kunne ikke læse filen")
                    if (bytes.isEmpty()) throw RuntimeException("filen er tom")
                    val client = ModelRigClient(store.baseUrl ?: "", store.token)
                    when {
                        isPdf -> name to client.ingestPdf(name, bytes)
                        isDocx -> name to client.ingestDocx(name, bytes)
                        isPptx -> name to client.ingestPptx(name, bytes)
                        isHtml -> name to client.ingestHtml(name, bytes)
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
        // A pending confirmation belongs to the conversation that proposed it.
        // Leaving it on screen across a switch means approving an action in the
        // wrong context -- the confirmation_id still points at the old thread.
        // The rig would happily execute it: it parked the arguments, not the UI.
        pendingTool = null
        showAudit = false
        showToolCtl = false
        convId = openConvId
        if (openConvId != null) {
            val loaded = withContext(Dispatchers.IO) {
                db.conversationMeta(openConvId) to db.loadMessages(openConvId)
            }
            val (meta, msgs) = loaded
            // Strip emojis from OLD assistant replies on load too. The finalize-time
            // strip only cleans new replies; without this, opening a conversation
            // made before the persona/strip landed still shows the old 🌟✨ filler.
            msgs.forEach { (role, content) ->
                messages.add(Msg(role, if (role == "assistant") stripEmojis(content) else content))
            }
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
            // Tools work in cloud mode too -- but only by routing the cloud
            // model THROUGH the rig, because that is where the gate lives. The
            // app's direct CloudClient path has no tools at all: nothing to
            // bypass, since the tool layer simply isn't on that road.
            val useTools = toolsMode && (mode == "rig" || (mode == "cloud" && store.cloudKey != null))
            // RAG and Tools compose: documents ground the answer, and the model
            // may still propose an action about them. Retrieval runs against the
            // rig's index; sending those chunks to a CLOUD model is gated behind
            // the D4 consent toggle (allowRagCloud), off by default.
            val toolsWithRag = useTools && ragMode && (mode == "rig" || allowRagCloud)
            var proposal: dk.ternedal.modelrig.net.ToolTurn? = null
            val err = withContext(Dispatchers.IO) {
                runCatching {
                    when {
                        // Tools: not a stream. One turn in, either an answer or a
                        // proposal that has executed nothing. Checked before RAG and
                        // cloud because it is the most restrictive mode.
                        useTools -> {
                            val viaCloud = mode == "cloud"
                            // history minus the just-added user turn (the rig
                            // appends that itself; sending it twice makes the
                            // model answer its own echo) and minus the system
                            // prompt, which now travels in its own field.
                            val prior = history.dropLast(1).filter { it.first != "system" }
                            val turn = ModelRigClient(store.baseUrl ?: "", store.token)
                                .toolsChat(
                                    t,
                                    model = if (viaCloud) cModel else rigModel,
                                    cloudBaseUrl = if (viaCloud) "https://ollama.com" else null,
                                    cloudKey = if (viaCloud) store.cloudKey else null,
                                    history = prior,
                                    rag = toolsWithRag,
                                    ragSource = if (toolsWithRag) srcFilter else null,
                                    allowRagCloud = allowRagCloud,
                                    imageB64 = imageB64,
                                    system = sys,
                                )
                            if (turn.sources.isNotEmpty()) onSources(turn.sources)
                            if (turn.status == "confirmation_required") {
                                proposal = turn
                            } else {
                                onDelta(turn.answer)
                            }
                        }
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
                                // local-first: a rig failure does NOT auto-send to cloud
                                // unless the user opted in, and an attached image is
                                // never sent via fallback -- it stays on the device.
                                if (rigEmitted == 0 && cloudKey != null && store.autoCloudFallback) {
                                    didFallback = true
                                    CloudClient(cloudKey).chatStream(cModel, history, registerCall = hook, onDelta = onDelta)
                                } else throw e
                            }
                        }
                    }
                }.exceptionOrNull()
            }
            activeCall = null
            // A parked write proposal: surface the card. Nothing has executed.
            proposal?.let { pendingTool = it }
            val cur = messages[idx]
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[idx] = when {
                err == null -> cur.copy(streaming = false, text = stripEmojis(cur.text), fellBackToCloud = didFallback)
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = friendlyError(err!!))
                else -> cur.copy(streaming = false, text = stripEmojis(cur.text) + "\n\n_[afbrudt]_")
            }
            // persist the assistant reply (full or partial-cancelled), never errors
            val finalText = messages[idx].text
            // A pending tool proposal produces no answer yet: the card is on
            // screen and nothing has run. Persisting an empty assistant turn
            // would leave a blank bubble in the history forever.
            if ((err == null || cancelled) && finalText.isNotBlank()) {
                withContext(Dispatchers.IO) { db.addMessage(cid, "assistant", finalText) }
            }
            if (proposal != null) messages.removeAt(idx)
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
                                if (rigEmitted == 0 && cloudKey != null && store.autoCloudFallback) {
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
                err == null -> cur.copy(streaming = false, text = stripEmojis(cur.text))
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = friendlyError(err!!))
                else -> cur.copy(streaming = false, text = stripEmojis(cur.text) + "\n\n_[afbrudt]_")
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
        Surface(color = KalivTheme.colors.surface, tonalElevation = 2.dp) {
            Column {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 12.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // Kaliv wordmark in the header (design guide). Art swaps with the
                // palette so it reads on both backgrounds.
                Image(
                    painter = painterResource(
                        if (KalivTheme.colors.isDark) R.drawable.kaliv_wordmark_dark
                        else R.drawable.kaliv_wordmark_light,
                    ),
                    contentDescription = "Kaliv",
                    modifier = Modifier.height(26.dp).padding(end = 10.dp),
                )
                // The model + mode controls live in a weighted, horizontally
                // scrollable strip. Non-weighted siblings (source badge, Skift,
                // the overflow menu) are measured first, so this strip only gets
                // the LEFTOVER width and shrinks/scrolls -- it can never push the
                // overflow button (which holds Settings) off the right edge, the
                // way a plain Row of six items did on a phone-width screen.
                Row(
                    Modifier.weight(1f).horizontalScroll(rememberScrollState()),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                if (mode == "cloud") {
                    ModelChip("☁  $cloudModel  ▾", onClick = { onOpenCloudPicker() })
                } else {
                    Box {
                        ModelChip("$currentModel  ▾", onClick = { modelMenu = true })
                        // Auto-load the installed rig models the first time the menu
                        // opens (and whenever it reopens empty), so there's an actual
                        // list to pick from -- previously the list only appeared after
                        // tapping "Genindlæs modeller", so rig mode looked like it had
                        // no model switcher at all.
                        LaunchedEffect(modelMenu) {
                            if (modelMenu && models.isEmpty() && store.baseUrl != null) {
                                val res = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listModels() }
                                }
                                res.onSuccess { models = it }
                                    .onFailure { modelError = "Kan ikke hente modeller: rig'en svarer ikke" }
                            }
                        }
                        DropdownMenu(expanded = modelMenu, onDismissRequest = { modelMenu = false }) {
                            // The installed rig models, at the TOP where a model
                            // picker belongs. Tap one to switch the rig model.
                            if (models.isEmpty()) {
                                DropdownMenuItem(
                                    enabled = false,
                                    text = { Text("Henter modeller…", color = KalivTheme.colors.textMuted, fontSize = 13.sp) },
                                    onClick = {},
                                )
                            } else {
                                models.forEach { m ->
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                (if (m == currentModel) "◈  " else "     ") + m,
                                                color = if (m == currentModel) KalivTheme.colors.signal else KalivTheme.colors.textHigh,
                                                fontSize = 14.sp,
                                            )
                                        },
                                        onClick = { currentModel = m; store.model = m; modelMenu = false },
                                    )
                                }
                            }
                            HorizontalDivider()
                            // Voice: ASR/TTS always run on the rig, but the LLM
                            // step can go to a big cloud model. Only meaningful
                            // in rig mode with a cloud key configured.
                            if (mode == "rig" && store.cloudKey != null) {
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            (if (voiceUsesCloud) "☁ " else "◇ ") +
                                                "Stemme svarer via cloud",
                                            color = if (voiceUsesCloud) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        voiceUsesCloud = !voiceUsesCloud
                                        store.voiceUsesCloud = voiceUsesCloud
                                        modelMenu = false
                                    },
                                )
                                // Pick WHICH cloud model the voice chain uses --
                                // separate from the text cloud model, reachable from
                                // rig mode (where voice lives). Only useful when the
                                // toggle above is on.
                                if (voiceUsesCloud) {
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                "     ☁ Cloud-model til tale: ${store.voiceCloudModel}",
                                                color = KalivTheme.colors.amber,
                                                fontSize = 12.sp,
                                            )
                                        },
                                        onClick = { modelMenu = false; onOpenVoiceCloudPicker() },
                                    )
                                }
                            }
                            // Barge-in: speak to cut Kaliv off mid-reply. Needs the
                            // mic while she talks, hence the permission check.
                            if (mode == "rig") {
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            (if (bargeInEnabled) "✋ " else "◇ ") +
                                                "Afbryd Kaliv ved at tale",
                                            color = if (bargeInEnabled) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        bargeInEnabled = !bargeInEnabled
                                        store.bargeInEnabled = bargeInEnabled
                                        modelMenu = false
                                    },
                                )
                                // RAG: a capability toggle, grouped here with
                                // Tools and Voice (all "what can this model do")
                                // rather than crammed into the header, where it
                                // did not fit on a phone and got scrolled out of
                                // sight. Rig mode only -- cloud has no RAG.
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            if (ragMode) "⌕ RAG: til" else "⌕ RAG: fra",
                                            color = if (ragMode) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        val on = !ragMode
                                        ragMode = on
                                        if (on) scope.launch {
                                            val res = withContext(Dispatchers.IO) {
                                                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
                                            }
                                            res.onSuccess { ragSources = it }
                                        }
                                        modelMenu = false
                                    },
                                )
                                // D4 consent: allow RAG document content to reach a
                                // CLOUD model this session. Shown in cloud mode, where
                                // the choice applies; default is blocked (kept local).
                                if (mode == "cloud") {
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                if (allowRagCloud) "☁ RAG→cloud: tilladt" else "☁ RAG→cloud: blokeret",
                                                color = if (allowRagCloud) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                                fontSize = 13.sp,
                                            )
                                        },
                                        onClick = {
                                            allowRagCloud = !allowRagCloud
                                            modelMenu = false
                                        },
                                    )
                                }
                                // Source filter + add-document, shown only when RAG
                                // is on. Opens the same source menu the header chip
                                // used to.
                                if (ragMode) {
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                ragSourceFilter?.let { "⌕ Kilde: $it" } ?: "⌕ Kilder: alle",
                                                color = KalivTheme.colors.textMuted, fontSize = 13.sp,
                                            )
                                        },
                                        onClick = { modelMenu = false; ragSourceMenu = true },
                                    )
                                }
                                // Kaliv Tools. Off by default, and the rig has its
                                // own kill switch on top: two locks, both opt-in.
                                DropdownMenuItem(
                                    text = {
                                        Text(
                                            if (toolsMode) "🛠 Tools: til" else "🛠 Tools: fra",
                                            color = if (toolsMode) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                            fontSize = 13.sp,
                                        )
                                    },
                                    onClick = {
                                        toolsMode = !toolsMode
                                        store.toolsMode = toolsMode
                                        if (!toolsMode) pendingTool = null
                                        modelMenu = false
                                    },
                                )
                                // Audit log: readable whether or not tools mode is
                                // currently on -- past actions matter regardless.
                                DropdownMenuItem(
                                    text = { Text("⚙ Tool-styring", color = KalivTheme.colors.textMuted, fontSize = 13.sp) },
                                    onClick = {
                                        modelMenu = false
                                        registryError = null
                                        showToolCtl = true
                                        loadRegistry()
                                    },
                                )
                                DropdownMenuItem(
                                    text = { Text("📜 Handlingslog", color = KalivTheme.colors.textMuted, fontSize = 13.sp) },
                                    onClick = {
                                        modelMenu = false
                                        auditError = null
                                        showAudit = true
                                        scope.launch {
                                            val r = withContext(Dispatchers.IO) {
                                                runCatching {
                                                    ModelRigClient(store.baseUrl ?: "", store.token).toolsAudit(50)
                                                }
                                            }
                                            auditRows = r.getOrDefault(emptyList())
                                            auditError = r.exceptionOrNull()?.let { friendlyError(it) }
                                        }
                                    },
                                )
                                if (bargeInEnabled) {
                                    // Step through sensible thresholds rather than
                                    // a slider: this is a calibration dial used a
                                    // handful of times, not a daily control.
                                    DropdownMenuItem(
                                        text = {
                                            Text(
                                                "Barge-in følsomhed: $bargeInThreshold" +
                                                    if (peakRms > 0) "  (sidste top ${peakRms.toInt()})" else "",
                                                color = KalivTheme.colors.textMuted,
                                                fontSize = 13.sp,
                                            )
                                        },
                                        onClick = {
                                            val steps = listOf(500, 800, 1200, 1500, 2000, 3000, 4500)
                                            val next = steps.firstOrNull { it > bargeInThreshold } ?: steps.first()
                                            bargeInThreshold = next
                                            store.bargeInThreshold = next
                                        },
                                    )
                                }
                            }
                            if (mode == "rig") HorizontalDivider()
                            DropdownMenuItem(
                                text = { Text("↻  Genindlæs modeller", color = KalivTheme.colors.signal) },
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
                        }
                    }
                }
                // RAG moved into the model menu (above). The source menu still
                // needs an anchor in the tree; hang it off a zero-size Box here so
                // "Kilder" in the model menu can open it.
                Box {
                    DropdownMenu(expanded = ragSourceMenu, onDismissRequest = { ragSourceMenu = false }) {
                        DropdownMenuItem(text = { Text("Alle kilder") }, onClick = { ragSourceFilter = null; ragSourceMenu = false })
                        if (ragSources.isNotEmpty()) HorizontalDivider()
                        ragSources.forEach { src ->
                            DropdownMenuItem(text = { Text(src) }, onClick = { ragSourceFilter = src; ragSourceMenu = false })
                        }
                        if (ragSources.isEmpty()) {
                            HorizontalDivider()
                            DropdownMenuItem(text = { Text("Ingen kilder ingesteret endnu", color = KalivTheme.colors.textMuted) }, onClick = { ragSourceMenu = false })
                        }
                        HorizontalDivider()
                        DropdownMenuItem(
                            text = { Text(if (ingesting) "Ingesterer…" else "+ Tilføj dokument…", color = if (ingesting) KalivTheme.colors.textMuted else KalivTheme.colors.signal) },
                            enabled = !ingesting,
                            onClick = { ragSourceMenu = false; pickDocument.launch(arrayOf("text/plain", "text/markdown", "text/html", "application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "application/vnd.openxmlformats-officedocument.presentationml.presentation", "application/octet-stream")) },
                        )
                    }
                }
                }  // end scrollable model/mode strip
                Spacer(Modifier.width(8.dp))
                SourceBadge(mode)
                if (hasRig && hasCloud) {
                    TextButton(
                        onClick = { val m = if (mode == "cloud") "rig" else "cloud"; mode = m; store.chatMode = m; if (m == "cloud") ragMode = false },
                        contentPadding = PaddingValues(horizontal = 8.dp),
                    ) { Text("Skift", color = KalivTheme.colors.signal, fontSize = 13.sp) }
                }
                Box {
                    TextButton(onClick = { overflow = true }, contentPadding = PaddingValues(horizontal = 6.dp)) {
                        Text("⋮", color = KalivTheme.colors.textHigh, fontSize = 20.sp)
                    }
                    DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                        DropdownMenuItem(text = { Text("Ny samtale") }, onClick = {
                            overflow = false; messages.clear(); convId = null; onConvChanged(null)
                        })
                        DropdownMenuItem(text = { Text("Samtaler") }, onClick = { overflow = false; onOpenConversations() })
                        DropdownMenuItem(text = { Text("Modeller") }, onClick = { overflow = false; onOpenModels() })
                        DropdownMenuItem(text = { Text("Viden") }, onClick = { overflow = false; onOpenKnowledge() })
                        DropdownMenuItem(text = { Text("Indstillinger") }, onClick = { overflow = false; onOpenSettings() })
                        HorizontalDivider(color = KalivTheme.colors.hairline)
                        // Light / dark. A manual choice (TokenStore.darkMode), so it
                        // stays put when Android auto-switches at sunset. Lives in the
                        // overflow menu next to Settings -- reachable in every mode,
                        // unlike the model-picker dropdown it was wrongly placed in.
                        DropdownMenuItem(
                            text = {
                                Text(if (darkMode) "☀  Lyst tema" else "☾  Mørkt tema")
                            },
                            onClick = { overflow = false; onToggleDark(!darkMode) },
                        )
                    }
                }
            }
            // Persistent routing strip: always shows, at a glance, WHICH model
            // answers text and WHICH answers voice (and whether voice uses cloud).
            // Before this, the voice-cloud state was buried in the model menu and
            // only visible after a reply via the chip -- not transparent.
            Row(
                Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 2.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                val textLabel = when (mode) {
                    "cloud" -> "☁ tekst: $cloudModel"
                    else -> "◈ tekst: $currentModel"
                }
                Text(textLabel, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                Spacer(Modifier.width(10.dp))
                // Voice routing: cloud only when the toggle is on AND a key exists.
                val voiceCloud = voiceUsesCloud && store.cloudKey != null
                val voiceLabel = if (voiceCloud) "☁ tale: ${store.voiceCloudModel}" else "🎙 tale: $currentModel"
                Text(
                    voiceLabel,
                    color = if (voiceCloud) KalivTheme.colors.amber else KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
            }
            if (ingesting || ingestStatus != null || ingestError != null) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp)) {
                    when {
                        ingesting -> Text("Ingesterer…", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                        ingestError != null -> Text("Fejl: ${friendlyError(ingestError!!)}", color = KalivTheme.colors.danger, fontSize = 11.sp)
                        ingestStatus != null -> Text(ingestStatus!!, color = KalivTheme.colors.signal, fontSize = 11.sp)
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
                // The empty state is the welcome screen: the mark, the wordmark,
                // then the mode. The ankh is the launcher foreground -- one
                // asset, one identity, no second copy to drift out of sync.
                Image(
                    painter = painterResource(R.drawable.ic_launcher_foreground),
                    contentDescription = null,
                    modifier = Modifier.size(140.dp),
                )
                Text(
                    "KALIV",
                    fontFamily = androidx.compose.ui.text.font.FontFamily.Serif,
                    fontSize = 30.sp, fontWeight = FontWeight.Bold,
                    color = KalivTheme.colors.textHigh, letterSpacing = 8.sp,
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    "Lokal intelligens. Privat.",
                    color = KalivTheme.colors.textMuted, fontSize = 13.sp, letterSpacing = 1.sp,
                )
                Spacer(Modifier.height(28.dp))
                // KalivTheme.colors.hairline divider: the branded-seal feel is quiet structure,
                // not more colour.
                androidx.compose.foundation.layout.Box(
                    Modifier.width(48.dp).height(1.dp)
                        .background(KalivTheme.colors.hairline),
                )
                Spacer(Modifier.height(20.dp))
                Text(
                    when { mode == "cloud" -> "Cloud-tilstand"; ragMode -> "RAG-tilstand"; else -> "Rig-tilstand" },
                    color = if (mode == "cloud") KalivTheme.colors.amber else KalivTheme.colors.signal,
                    fontSize = 14.sp, fontWeight = FontWeight.Medium, letterSpacing = 1.sp,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    if (ragMode) "Spørg om dine ingesterede dokumenter" else "Skriv en besked for at starte",
                    color = KalivTheme.colors.textMuted, fontSize = 13.sp,
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
        Surface(color = KalivTheme.colors.surface, tonalElevation = 3.dp) {
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
                        Text("🖼 Billede vedhæftet", color = KalivTheme.colors.signal, fontSize = 12.sp)
                        Spacer(Modifier.weight(1f))
                        // Save the photo into the RAG index instead of (or as well
                        // as) sending it to chat: a vision model on the rig reads
                        // it and it becomes searchable knowledge. Needs a paired
                        // backend + KALIV_VISION_MODEL -- the worker says so with a
                        // clear 501 if it's off, surfaced here.
                        TextButton(
                            enabled = imageIngestStatus != "gemmer" && store.token != null,
                            onClick = {
                                val b64 = pendingImageB64 ?: return@TextButton
                                imageIngestStatus = "gemmer"
                                scope.launch {
                                    val res = withContext(Dispatchers.IO) {
                                        runCatching {
                                            val bytes = android.util.Base64.decode(b64, android.util.Base64.NO_WRAP)
                                            ModelRigClient(store.baseUrl ?: "", store.token)
                                                .ingestImage("foto ${java.text.SimpleDateFormat("dd-MM HH:mm", java.util.Locale("da")).format(java.util.Date())}", bytes)
                                        }
                                    }
                                    res.onSuccess {
                                        imageIngestStatus = "✓ gemt i Viden (${it.chunksAdded} chunks)"
                                        pendingImageB64 = null
                                    }.onFailure {
                                        imageIngestStatus = friendlyError(it)
                                    }
                                }
                            },
                        ) {
                            Text("＋ Gem i Viden", color = KalivTheme.colors.signal, fontSize = 12.sp)
                        }
                        TextButton(onClick = { pendingImageB64 = null; imageIngestStatus = null }) {
                            Text("✕ Fjern", color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                        }
                    }
                }
                imageIngestStatus?.let {
                    Text(it,
                        color = if (it.startsWith("✓")) KalivTheme.colors.success
                                else if (it == "gemmer") KalivTheme.colors.textMuted
                                else KalivTheme.colors.danger,
                        fontSize = 11.sp, modifier = Modifier.padding(bottom = 4.dp))
                }
                pendingImageError?.let {
                    Text("Billedfejl: $it", color = KalivTheme.colors.danger, fontSize = 11.sp, modifier = Modifier.padding(bottom = 4.dp))
                }
                // Kaliv Tools: the confirmation card. Nothing has executed while
                // this is on screen. Deny is exactly as easy to hit as approve --
                // a big green yes next to a grey line is a dark pattern, and it is
                // how people approve things they did not read.
                if (showToolCtl) {
                    AlertDialog(
                        onDismissRequest = { showToolCtl = false },
                        confirmButton = {
                            TextButton(onClick = { showToolCtl = false }) { Text("Luk", color = KalivTheme.colors.signal) }
                        },
                        title = {
                            Text("Tool-styring", color = KalivTheme.colors.textHigh,
                                fontFamily = androidx.compose.ui.text.font.FontFamily.Serif)
                        },
                        text = {
                            Column(Modifier.heightIn(max = 440.dp).verticalScroll(rememberScrollState())) {
                                registryError?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp) }
                                val reg = registry
                                if (reg == null && registryError == null) {
                                    Text("Henter…", color = KalivTheme.colors.textMuted, fontSize = 13.sp)
                                }
                                reg?.let { r ->
                                    // The kill switch. Turning tools OFF is never
                                    // confirmed and never delayed: an emergency
                                    // brake that asks "are you sure" is not a brake.
                                    Row(verticalAlignment = Alignment.CenterVertically) {
                                        Column(Modifier.weight(1f)) {
                                            Text("Tool-laget på riggen", color = KalivTheme.colors.textHigh, fontSize = 14.sp)
                                            Text(
                                                if (r.enabled) "Aktivt" else "Slået fra — intet tool kan køre",
                                                color = if (r.enabled) KalivTheme.colors.success else KalivTheme.colors.textMuted, fontSize = 11.sp,
                                            )
                                        }
                                        Switch(
                                            checked = r.enabled,
                                            enabled = !registryBusy,
                                            onCheckedChange = { toggleTool(it, null) },
                                        )
                                    }
                                    r.toolsDir?.let {
                                        Text("Skrivninger lander i: $it", color = KalivTheme.colors.textMuted,
                                            fontSize = 11.sp, lineHeight = 15.sp)
                                    }
                                    Spacer(Modifier.height(8.dp))
                                    HorizontalDivider(color = KalivTheme.colors.hairline)
                                    Spacer(Modifier.height(8.dp))
                                    r.tools.forEach { tool ->
                                        Row(
                                            Modifier.fillMaxWidth().padding(vertical = 4.dp),
                                            verticalAlignment = Alignment.CenterVertically,
                                        ) {
                                            Column(Modifier.weight(1f)) {
                                                Row(verticalAlignment = Alignment.CenterVertically) {
                                                    Text(tool.name, color = KalivTheme.colors.textHigh, fontSize = 13.sp)
                                                    Spacer(Modifier.width(6.dp))
                                                    // Writes are the ones that need a card.
                                                    // Say so before anything is enabled.
                                                    Text(
                                                        if (tool.risk == "write") "SKRIVER" else "læser",
                                                        color = if (tool.risk == "write") KalivTheme.colors.amber else KalivTheme.colors.textMuted,
                                                        fontSize = 10.sp, fontWeight = FontWeight.Bold,
                                                    )
                                                }
                                                Text(tool.description, color = KalivTheme.colors.textMuted,
                                                    fontSize = 11.sp, lineHeight = 15.sp)
                                            }
                                            Switch(
                                                checked = tool.enabled,
                                                enabled = !registryBusy && r.enabled,
                                                onCheckedChange = { toggleTool(it, tool.name) },
                                            )
                                        }
                                    }
                                }
                            }
                        },
                        containerColor = KalivTheme.colors.surfaceHigh,
                    )
                }

                if (showAudit) {
                    AlertDialog(
                        onDismissRequest = { showAudit = false },
                        confirmButton = {
                            TextButton(onClick = { showAudit = false }) {
                                Text("Luk", color = KalivTheme.colors.signal)
                            }
                        },
                        title = { Text("Handlingslog", color = KalivTheme.colors.textHigh, fontFamily = androidx.compose.ui.text.font.FontFamily.Serif) },
                        text = {
                            Column(Modifier.heightIn(max = 420.dp).verticalScroll(rememberScrollState())) {
                                auditError?.let {
                                    Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp)
                                }
                                if (auditError == null && auditRows.isEmpty()) {
                                    Text("Ingen handlinger registreret endnu.", color = KalivTheme.colors.textMuted, fontSize = 13.sp)
                                }
                                auditRows.forEach { e ->
                                    // Colour by outcome: a refusal or a failure should
                                    // catch the eye, an ordinary success should not.
                                    val c = when (e.outcome) {
                                        "executed" -> KalivTheme.colors.success
                                        "denied", "expired", "blocked" -> KalivTheme.colors.amber
                                        "error" -> KalivTheme.colors.danger
                                        else -> KalivTheme.colors.textMuted
                                    }
                                    Column(Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
                                        Row {
                                            Text(e.outcome.uppercase(), color = c, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                            Spacer(Modifier.width(6.dp))
                                            Text(e.tool, color = KalivTheme.colors.textHigh, fontSize = 12.sp)
                                            if (e.origin == "cloud") {
                                                Spacer(Modifier.width(6.dp))
                                                Text("☁", fontSize = 12.sp)
                                            }
                                        }
                                        Text(
                                            "${e.ts} · ${e.risk}" + if (e.summary.isNotBlank()) " · ${e.summary.take(80)}" else "",
                                            color = KalivTheme.colors.textMuted, fontSize = 11.sp, lineHeight = 15.sp,
                                        )
                                    }
                                    HorizontalDivider(color = KalivTheme.colors.hairline)
                                }
                            }
                        },
                        containerColor = KalivTheme.colors.surfaceHigh,
                    )
                }

                pendingTool?.let { prop ->
                    Surface(
                        color = KalivTheme.colors.surfaceHigh,
                        shape = RoundedCornerShape(14.dp),
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp),
                    ) {
                        Column(Modifier.padding(14.dp)) {
                            Text(
                                "⚠ Kaliv vil udføre en handling",
                                color = KalivTheme.colors.signal, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                            )
                            Spacer(Modifier.height(6.dp))
                            Text(prop.summary.orEmpty(), color = KalivTheme.colors.textHigh, fontSize = 14.sp, lineHeight = 20.sp)
                            // The clock is visible because a timeout is a DENIAL,
                            // not an acceptance. Nothing happens if you walk away;
                            // the card should say so rather than let you assume.
                            var remaining by remember(prop.confirmationId) {
                                mutableStateOf(prop.expiresInSeconds)
                            }
                            LaunchedEffect(prop.confirmationId) {
                                while (remaining > 0) { delay(1000); remaining -= 1 }
                                // Client-side only. The worker enforces the real
                                // expiry; this just stops offering a dead button.
                                if (pendingTool?.confirmationId == prop.confirmationId) {
                                    pendingTool = null
                                    messages.add(Msg("assistant",
                                        "Bekræftelsen udløb. Handlingen blev ikke udført."))
                                }
                            }
                            if (remaining > 0) {
                                Spacer(Modifier.height(6.dp))
                                Text(
                                    "Udløber om $remaining s — sker der intet, bliver handlingen afvist.",
                                    color = KalivTheme.colors.textMuted, fontSize = 12.sp,
                                )
                            }
                            Spacer(Modifier.height(12.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                                val cid = prop.confirmationId
                                val decide: (Boolean) -> Unit = { approve ->
                                    toolBusy = true
                                    scope.launch {
                                        val r = withContext(Dispatchers.IO) {
                                            runCatching {
                                                ModelRigClient(store.baseUrl ?: "", store.token)
                                                    .toolsConfirm(cid!!, approve)
                                            }
                                        }
                                        toolBusy = false
                                        val next = r.getOrNull()
                                        if (next?.status == "confirmation_required") {
                                            // Agent v2: an approved write may continue the
                                            // chain, and the NEXT write comes back as its own
                                            // confirmation card. Show it instead of ending the
                                            // turn -- one approval never authorises the next write.
                                            pendingTool = next
                                        } else {
                                            pendingTool = null
                                            val text = next?.answer
                                                // 410 means the confirmation expired. A timeout is a
                                                // denial, never an acceptance -- say so plainly.
                                                ?: r.exceptionOrNull()?.let { e ->
                                                    if (e.message?.contains("410") == true)
                                                        "Bekræftelsen udløb. Handlingen blev ikke udført."
                                                    else friendlyError(e)
                                                } ?: ""
                                            if (text.isNotBlank()) {
                                                messages.add(Msg("assistant", text))
                                                // Persist it. What you approved, and what
                                                // Kaliv did about it, belongs in the
                                                // conversation -- not only in RAM until the
                                                // next app restart.
                                                convId?.let { id ->
                                                    withContext(Dispatchers.IO) {
                                                        db.addMessage(id, "assistant", text)
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                // Symmetric on purpose. Same size, same weight, same
                                // affordance -- the ONLY difference is the word and
                                // the hue. v1.21.0 shipped Godkend in bronze
                                // SemiBold next to a plain grey Afvis, which is the
                                // exact dark pattern KRAVSPEC_V5_TOOLS.md section 8
                                // forbids: nudging toward yes on the actions that
                                // change something. A comment claiming symmetry is
                                // not symmetry.
                                TextButton(
                                    onClick = { decide(false) },
                                    enabled = !toolBusy && cid != null,
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("Afvis", color = KalivTheme.colors.textHigh, fontSize = 14.sp,
                                         fontWeight = FontWeight.SemiBold)
                                }
                                TextButton(
                                    onClick = { decide(true) },
                                    enabled = !toolBusy && cid != null,
                                    modifier = Modifier.weight(1f),
                                ) {
                                    Text("Godkend", color = KalivTheme.colors.signal, fontSize = 14.sp,
                                         fontWeight = FontWeight.SemiBold)
                                }
                            }
                        }
                    }
                }

                // Kaliv Voice status as a distinct card (design guide: "Voice-
                // status skal kunne vises som separat card/state"), not a bare
                // line of text. The card colour signals the state: an error is
                // danger-tinted, an active turn is bronze.
                if (recording || voiceBusy || voiceError != null) {
                    val isError = voiceError != null && !recording && !voiceBusy
                    val vt = when {
                        recording -> "🎙  Optager… tryk igen for at sende"
                        speaking && bargeInEnabled && hasMicPermission ->
                            "🔊  Kaliv taler… ⏹ afbryder · mik %.0f (top %.0f, grænse %d)"
                                .format(liveRms, peakRms, bargeInThreshold)
                        speaking -> "🔊  Kaliv taler… tryk ⏹ for at afbryde"
                        voiceBusy -> "🔊  Kaliv lytter og svarer… tryk ⏹ for at afbryde"
                        else -> "Stemme-fejl: ${voiceError.orEmpty()}"
                    }
                    val accent = if (isError) KalivTheme.colors.danger else KalivTheme.colors.signal
                    Surface(
                        color = KalivTheme.colors.surfaceHigh,
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp)
                            .padding(bottom = 8.dp),
                    ) {
                        Row(
                            Modifier.padding(horizontal = 14.dp, vertical = 12.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            // a small state dot in the accent colour
                            Box(
                                Modifier.size(8.dp)
                                    .background(accent, RoundedCornerShape(4.dp)),
                            )
                            Spacer(Modifier.width(10.dp))
                            Text(vt, color = accent, fontSize = 16.sp, lineHeight = 22.sp)
                        }
                    }
                }
                modelError?.let {
                    Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp, modifier = Modifier.padding(bottom = 6.dp))
                }
                if (wasInterrupted && !voiceBusy && !recording) {
                    Text(
                        "✋ Du afbrød Kaliv — tryk 🎙 for at sige noget",
                        color = KalivTheme.colors.textMuted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 6.dp),
                    )
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    // Vision is chat-only (cloud/rig), not RAG. Requires a
                    // vision-capable model; the button just attaches — the
                    // model choice is the user's.
                    if (mode != "rig" || !ragMode) {
                        Box(
                            Modifier.size(48.dp).clickable(enabled = !busy, onClick = {
                                pendingImageError = null
                                pickImage.launch(arrayOf("image/*"))
                            }),
                            contentAlignment = Alignment.Center,
                        ) { Text("📎", fontSize = 20.sp) }
                        Spacer(Modifier.width(2.dp))
                    }
                    // Kaliv Voice mic button: rig mode only (voice runs on the
                    // rig). Tap to start recording, tap again to send. Disabled
                    // while a voice turn is in flight.
                    if (mode == "rig") {
                        // One button, three jobs. While a turn is in flight it
                        // becomes ⏹: the mic is busy anyway, so a separate stop
                        // button would just be another thing to aim at.
                        Box(
                            Modifier.size(48.dp).clickable(enabled = !busy || voiceBusy, onClick = {
                                voiceError = null
                                if (voiceBusy) {
                                    stopVoiceTurn()
                                } else if (!hasMicPermission) {
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
                        ) {
                            Text(
                                when {
                                    voiceBusy -> "⏹"
                                    recording -> "⏺"
                                    else -> "🎙"
                                },
                                fontSize = 20.sp,
                            )
                        }
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
                            Modifier.size(48.dp).clickable(onClick = { activeCall?.cancel() }),
                            contentAlignment = Alignment.Center,
                        ) { StopGlyph(color = KalivTheme.colors.danger, modifier = Modifier.size(20.dp)) }
                    } else {
                        // Can send with text OR just an image (vision prompts
                        // are often "what's in this?" with an image and no text).
                        val canSend = input.isNotBlank() || pendingImageB64 != null
                        Box(
                            Modifier.size(48.dp).clickable(enabled = canSend, onClick = onSend),
                            contentAlignment = Alignment.Center,
                        ) { SendGlyph(color = if (canSend) KalivTheme.colors.signal else KalivTheme.colors.textMuted, modifier = Modifier.size(26.dp)) }
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
    activeConvId: Long?,
    onOpen: (Long) -> Unit,
    onNew: () -> Unit,
    onActiveDeleted: () -> Unit,
    onBack: () -> Unit,
) {
    val context = LocalContext.current
    val ioScope = rememberCoroutineScope()
    var convos by remember { mutableStateOf(db.listConversations()) }
    var ioStatus by remember { mutableStateOf<String?>(null) }
    var query by remember { mutableStateOf("") }

    // Full backup of all conversations as JSON via SAF -- the user picks where
    // (Downloads, Drive, ...). This is what makes a future keystore rotation or
    // a lost phone cost nothing: conversations otherwise live ONLY in this
    // app's private SQLite. Import restores them, with a cheap exact-duplicate
    // check so re-importing the same file doesn't double everything.
    val exportLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.CreateDocument("application/json"),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        ioStatus = "eksporterer…"
        ioScope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching {
                    val root = org.json.JSONObject()
                        .put("format", "kaliv-conversations")
                        .put("version", 1)
                        .put("exported_at", System.currentTimeMillis())
                    val arr = org.json.JSONArray()
                    db.listConversations().forEach { meta ->
                        val convObj = org.json.JSONObject()
                            .put("title", meta.title)
                            .put("source", meta.source)
                            .put("model", meta.model)
                            .put("updated_at", meta.updatedAt)
                        val msgs = org.json.JSONArray()
                        db.loadMessages(meta.id).forEach { (role, content) ->
                            msgs.put(org.json.JSONObject().put("role", role).put("content", content))
                        }
                        convObj.put("messages", msgs)
                        arr.put(convObj)
                    }
                    root.put("conversations", arr)
                    context.contentResolver.openOutputStream(uri)?.use { out ->
                        out.write(root.toString(2).toByteArray())
                    } ?: throw RuntimeException("kunne ikke åbne filen til skrivning")
                    arr.length()
                }
            }
            ioStatus = res.fold({ "✓ $it samtaler eksporteret" }, { "eksport fejlede: ${it.message}" })
        }
    }
    val importLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.OpenDocument(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        ioStatus = "importerer…"
        ioScope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching {
                    val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().decodeToString() }
                        ?: throw RuntimeException("kunne ikke læse filen")
                    val root = org.json.JSONObject(text)
                    if (root.optString("format") != "kaliv-conversations") {
                        throw RuntimeException("ikke en Kaliv-samtale-eksport")
                    }
                    val arr = root.getJSONArray("conversations")
                    var imported = 0; var skipped = 0
                    // Snapshot existing convs once for the duplicate check.
                    val existing = db.listConversations()
                    for (i in 0 until arr.length()) {
                        val c = arr.getJSONObject(i)
                        val title = c.optString("title")
                        val source = c.optString("source").ifBlank { "rig" }
                        val model = c.optString("model")
                        val msgsArr = c.optJSONArray("messages") ?: org.json.JSONArray()
                        val msgs = (0 until msgsArr.length()).map {
                            val m = msgsArr.getJSONObject(it)
                            m.optString("role") to m.optString("content")
                        }
                        // Exact-duplicate check: same title+source AND identical
                        // (role, content) sequence -> skip. Cheap at personal scale.
                        val dup = existing.filter { it.title == title && it.source == source }
                            .any { db.loadMessages(it.id) == msgs }
                        if (dup) { skipped++; continue }
                        val cid = db.newConversation(source, model, title)
                        msgs.forEach { (role, content) -> db.addMessage(cid, role, content) }
                        imported++
                    }
                    imported to skipped
                }
            }
            res.onSuccess { (imp, skip) ->
                convos = db.listConversations()
                ioStatus = "✓ $imp importeret" + (if (skip > 0) " · $skip dubletter sprunget over" else "")
            }.onFailure { ioStatus = "import fejlede: ${it.message}" }
        }
    }

    var renamingId by remember { mutableStateOf<Long?>(null) }
    var renameText by remember { mutableStateOf("") }
    val fmt = remember { SimpleDateFormat("d/M HH:mm", Locale.getDefault()) }
    val visible = remember(convos, query) {
        if (query.isBlank()) convos else convos.filter { it.title.contains(query, ignoreCase = true) }
    }

    Column(Modifier.fillMaxSize()) {
        Surface(color = KalivTheme.colors.surface, tonalElevation = 2.dp) {
            Column(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onBack) { Text("←", color = KalivTheme.colors.textHigh, fontSize = 18.sp) }
                    Text("Samtaler", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = onNew) { Text("+ Ny", color = KalivTheme.colors.signal) }
                }
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = {
                        val d = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(java.util.Date())
                        exportLauncher.launch("kaliv-samtaler-$d.json")
                    }) { Text("⬇ Eksportér alt", color = KalivTheme.colors.signal, fontSize = 12.sp) }
                    TextButton(onClick = { importLauncher.launch(arrayOf("application/json")) }) {
                        Text("⬆ Importér", color = KalivTheme.colors.signal, fontSize = 12.sp)
                    }
                    ioStatus?.let {
                        Spacer(Modifier.width(6.dp))
                        Text(it,
                            color = if (it.startsWith("✓")) KalivTheme.colors.success
                                    else if (it.endsWith("…")) KalivTheme.colors.textMuted
                                    else KalivTheme.colors.danger,
                            fontSize = 11.sp)
                    }
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
                    color = KalivTheme.colors.textMuted, fontSize = 14.sp,
                )
            }
        } else {
            LazyColumn(
                Modifier.weight(1f).fillMaxWidth(),
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 8.dp),
            ) {
                items(visible, key = { it.id }) { c ->
                    Surface(
                        color = KalivTheme.colors.surface,
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
                                    ) { Text("Gem", color = if (renameText.isNotBlank()) KalivTheme.colors.signal else KalivTheme.colors.textMuted) }
                                    TextButton(onClick = { renamingId = null }) { Text("✕", color = KalivTheme.colors.textMuted) }
                                }
                            } else {
                                Row(
                                    Modifier.fillMaxWidth().clickable { onOpen(c.id) },
                                    verticalAlignment = Alignment.CenterVertically,
                                ) {
                                    Column(Modifier.weight(1f)) {
                                        Text(
                                            c.title.ifBlank { "(uden titel)" },
                                            color = KalivTheme.colors.textHigh, fontSize = 14.sp,
                                            maxLines = 1,
                                        )
                                        Spacer(Modifier.height(2.dp))
                                        Row(verticalAlignment = Alignment.CenterVertically) {
                                            SourceBadge(c.source)
                                            Spacer(Modifier.width(8.dp))
                                            Text(fmt.format(Date(c.updatedAt)), color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                                        }
                                    }
                                }
                                Row {
                                    TextButton(onClick = {
                                        renamingId = c.id
                                        renameText = c.title
                                    }) { Text("✎", color = KalivTheme.colors.textMuted, fontSize = 13.sp) }
                                    TextButton(onClick = {
                                        val md = buildString {
                                            appendLine("# ${c.title.ifBlank { "Kaliv-samtale" }}")
                                            appendLine()
                                            db.loadMessages(c.id).forEach { (role, content) ->
                                                appendLine(if (role == "user") "**Du:**" else "**Assistent:**")
                                                appendLine(content)
                                                appendLine()
                                            }
                                        }
                                        val intent = Intent(Intent.ACTION_SEND).apply {
                                            type = "text/plain"
                                            putExtra(Intent.EXTRA_SUBJECT, c.title.ifBlank { "Kaliv-samtale" })
                                            putExtra(Intent.EXTRA_TEXT, md)
                                        }
                                        context.startActivity(Intent.createChooser(intent, "Del samtale"))
                                    }) { Text("Del", color = KalivTheme.colors.signal, fontSize = 12.sp) }
                                    TextButton(onClick = {
                                        db.deleteConversation(c.id)
                                        // Deleting the conversation we're in would
                                        // leave the active convId dangling, so the
                                        // next send / streaming finalize writes to a
                                        // gone conversation -> FOREIGN KEY crash
                                        // (seen on desktop 12/7; same bug here).
                                        if (activeConvId == c.id) onActiveDeleted()
                                        convos = db.listConversations()
                                    }) { Text("Slet", color = KalivTheme.colors.danger, fontSize = 12.sp) }
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
private fun SplashScreen(onDone: () -> Unit) {
    // The textured launch screen. The design guide calls for texture in the
    // splash; the OS SplashScreen API only permits a flat colour plus a centred
    // icon, so the texture is drawn here, in Compose, over the brand ground the
    // OS splash already faded in. Shown briefly, then hands off to the app.
    val dark = KalivTheme.colors.isDark
    LaunchedEffect(Unit) {
        delay(900)
        onDone()
    }
    Box(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        // full-bleed brand texture, dimmed so the mark stays legible
        Image(
            painter = painterResource(
                if (dark) R.drawable.kaliv_splash_texture_dark
                else R.drawable.kaliv_splash_texture_light,
            ),
            contentDescription = null,
            contentScale = ContentScale.Crop,
            alpha = if (dark) 0.55f else 0.40f,
            modifier = Modifier.fillMaxSize(),
        )
        Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Image(
                painter = painterResource(R.drawable.ic_launcher_foreground),
                contentDescription = null,
                modifier = Modifier.size(160.dp),
            )
            Text(
                "KALIV",
                fontFamily = androidx.compose.ui.text.font.FontFamily.Serif,
                fontSize = 34.sp, fontWeight = FontWeight.Bold,
                color = KalivTheme.colors.textHigh, letterSpacing = 10.sp,
            )
            Spacer(Modifier.height(6.dp))
            Text(
                "Lokal intelligens. Privat.",
                color = KalivTheme.colors.textMuted, fontSize = 16.sp, letterSpacing = 1.sp,
            )
        }
    }
}

@Composable
private fun KnowledgeScreen(store: TokenStore, onBack: () -> Unit) {
    // "Knowledge" as its own section (design guide navigation list). Shows the
    // rig's RAG sources -- the documents Kaliv can draw on -- and adds to them
    // with the same ingest contract the chat composer uses.
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var sources by remember { mutableStateOf<List<String>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    fun refresh() {
        loading = true
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
            }
            loading = false
            sources = r.getOrDefault(emptyList())
            error = r.exceptionOrNull()?.let { friendlyError(it) }
        }
    }
    LaunchedEffect(Unit) { refresh() }

    val pick = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        status = "Læser fil…"; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching {
                    val resolver = context.contentResolver
                    var name = uri.lastPathSegment ?: "dokument"
                    resolver.query(uri, null, null, null, null)?.use { c ->
                        val idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        if (idx >= 0 && c.moveToFirst()) name = c.getString(idx)
                    }
                    val mime = resolver.getType(uri) ?: ""
                    val lower = name.lowercase()
                    val bytes = resolver.openInputStream(uri)?.use { it.readBytes() }
                        ?: throw RuntimeException("kunne ikke læse filen")
                    if (bytes.isEmpty()) throw RuntimeException("filen er tom")
                    val client = ModelRigClient(store.baseUrl ?: "", store.token)
                    when {
                        mime == "application/pdf" || lower.endsWith(".pdf") -> name to client.ingestPdf(name, bytes)
                        lower.endsWith(".docx") -> name to client.ingestDocx(name, bytes)
                        lower.endsWith(".pptx") -> name to client.ingestPptx(name, bytes)
                        lower.endsWith(".html") || lower.endsWith(".htm") -> name to client.ingestHtml(name, bytes)
                        else -> name to client.ingestText(name, bytes.toString(Charsets.UTF_8))
                    }
                }
            }
            r.onSuccess { (name, res) -> status = "Ingesteret: $name (${res.chunksAdded} chunks)"; refresh() }
            r.onFailure { status = null; error = friendlyError(it) }
        }
    }

    Column(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        Surface(color = KalivTheme.colors.surface, tonalElevation = 2.dp) {
            Row(
                Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                // 48dp touch target (design guide minimum)
                TextButton(onClick = onBack, modifier = Modifier.heightIn(min = 48.dp)) {
                    Text("‹ Tilbage", color = KalivTheme.colors.signal, fontSize = 16.sp)
                }
                Spacer(Modifier.weight(1f))
                Text("Viden", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                Spacer(Modifier.weight(1f))
                TextButton(
                    onClick = { pick.launch(arrayOf("*/*")) },
                    modifier = Modifier.heightIn(min = 48.dp),
                ) { Text("+ Tilføj", color = KalivTheme.colors.signal, fontSize = 16.sp) }
            }
        }
        status?.let {
            Text(it, color = KalivTheme.colors.signal, fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
        error?.let {
            Text(it, color = KalivTheme.colors.danger, fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp))
        }
        when {
            loading -> Text("Henter…", color = KalivTheme.colors.textMuted, fontSize = 16.sp,
                modifier = Modifier.padding(16.dp))
            sources.isEmpty() -> Column(Modifier.fillMaxWidth().padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Ingen dokumenter endnu.", color = KalivTheme.colors.textHigh, fontSize = 16.sp)
                Spacer(Modifier.height(6.dp))
                Text("Tilføj PDF, DOCX, PPTX, HTML eller tekst, så kan Kaliv trække på dem.",
                    color = KalivTheme.colors.textMuted, fontSize = 16.sp,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
            else -> androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize()) {
                items(sources.size) { i ->
                    Row(
                        Modifier.fillMaxWidth().heightIn(min = 48.dp)
                            .padding(horizontal = 16.dp, vertical = 10.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("📄", fontSize = 18.sp)
                        Spacer(Modifier.width(12.dp))
                        Text(sources[i], color = KalivTheme.colors.textHigh, fontSize = 16.sp)
                    }
                    HorizontalDivider(color = KalivTheme.colors.hairline)
                }
            }
        }
    }
}

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
        Surface(color = KalivTheme.colors.surface, tonalElevation = 2.dp) {
            Row(
                Modifier.fillMaxWidth()
                    .windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                TextButton(onClick = onBack) { Text("←", color = KalivTheme.colors.textHigh, fontSize = 18.sp) }
                Text("Modeller", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                Spacer(Modifier.weight(1f))
                TextButton(onClick = { refresh() }) { Text(if (loading) "…" else "Genindlæs", color = KalivTheme.colors.signal) }
            }
        }

        if (!store.hasRig) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Kræver rig-forbindelse", color = KalivTheme.colors.textMuted, fontSize = 14.sp)
            }
            return@Column
        }

        Column(Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(16.dp)) {
            // ---- pull new model ----
            Text("Hent ny model", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
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
            pullStatus?.let { Spacer(Modifier.height(6.dp)); Text(it, color = KalivTheme.colors.signal, fontSize = 12.sp) }
            pullError?.let { Spacer(Modifier.height(6.dp)); Text("Fejl: ${friendlyError(it)}", color = KalivTheme.colors.danger, fontSize = 12.sp) }

            Spacer(Modifier.height(20.dp))

            // ---- running now ----
            Text("Kører nu", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(8.dp))
            if (running.isEmpty()) {
                Text("Ingen modeller indlæst i hukommelsen lige nu", color = KalivTheme.colors.textMuted, fontSize = 13.sp)
            } else {
                running.forEach { m ->
                    Surface(
                        color = KalivTheme.colors.surface, shape = RoundedCornerShape(10.dp),
                        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                    ) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(m.name, color = KalivTheme.colors.textHigh, fontSize = 13.sp)
                                Text(
                                    "${m.sizeVramBytes / 1_000_000_000.0} GB VRAM",
                                    color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                                )
                            }
                        }
                    }
                }
            }

            Spacer(Modifier.height(20.dp))

            // ---- installed ----
            Text("Installeret", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold, fontSize = 15.sp)
            Spacer(Modifier.height(8.dp))
            loadError?.let { Text("Fejl: ${friendlyError(it)}", color = KalivTheme.colors.danger, fontSize = 12.sp); Spacer(Modifier.height(6.dp)) }
            installed.forEach { m ->
                Surface(
                    color = KalivTheme.colors.surface, shape = RoundedCornerShape(10.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp),
                ) {
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(m.name, color = KalivTheme.colors.textHigh, fontSize = 13.sp)
                            Text("${m.sizeBytes / 1_000_000_000.0} GB", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                        }
                        TextButton(onClick = { confirmDelete = m.name }) { Text("Slet", color = KalivTheme.colors.danger, fontSize = 12.sp) }
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
                }) { Text("Slet", color = KalivTheme.colors.danger) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Annullér", color = KalivTheme.colors.textMuted) } },
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
private fun CloudModelPickerScreen(store: TokenStore, forVoice: Boolean = false, onPicked: () -> Unit, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var models by remember { mutableStateOf(listOf<String>()) }
    var query by remember { mutableStateOf("") }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val selected = if (forVoice) store.voiceCloudModel else store.cloudModel

    fun reload() {
        val key = store.cloudKey
        if (key == null) {
            error = "Ingen API-nøgle sat. Gem en nøgle i ☁-menuen (ollama.com/settings/keys) først."
            return
        }
        loading = true; error = null
        scope.launch {
            val res = withContext(Dispatchers.IO) { runCatching { CloudClient(key).listModels() } }
            res.onSuccess {
                models = it.sorted(); loading = false
                if (it.isEmpty()) error = "Nøglen virker, men kontoen viser ingen cloud-modeller. Skriv modelnavnet manuelt (fx gpt-oss:120b) i ☁-menuen."
            }.onFailure { error = friendlyError(it); loading = false }
        }
    }
    LaunchedEffect(Unit) { if (models.isEmpty()) reload() }

    val shown = remember(models, query) {
        val others = models.filter { it != selected }
        (if (query.isBlank()) others else others.filter { it.contains(query, ignoreCase = true) })
    }

    Column(Modifier.fillMaxSize()) {
        Surface(color = KalivTheme.colors.surface, tonalElevation = 2.dp) {
            Column(
                Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars)
                    .padding(horizontal = 8.dp, vertical = 8.dp),
            ) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    TextButton(onClick = onBack) { Text("←", color = KalivTheme.colors.textHigh, fontSize = 18.sp) }
                    Text(if (forVoice) "Cloud-model til tale" else "Vælg cloud-model", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Spacer(Modifier.weight(1f))
                    TextButton(onClick = { reload() }) { Text("↻", color = KalivTheme.colors.signal, fontSize = 16.sp) }
                }
                OutlinedTextField(
                    value = query, onValueChange = { query = it },
                    placeholder = { Text("Søg i modeller…", fontSize = 13.sp) },
                    singleLine = true, modifier = Modifier.fillMaxWidth().padding(top = 4.dp),
                )
            }
        }
        error?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp, modifier = Modifier.padding(12.dp)) }
        if (loading && models.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Henter modeller…", color = KalivTheme.colors.textMuted, fontSize = 14.sp)
            }
        } else {
            LazyColumn(Modifier.weight(1f).fillMaxWidth(), contentPadding = PaddingValues(vertical = 8.dp)) {
                // pinned selected/default
                item {
                    Text("Nuværende standard", color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    Row(
                        Modifier.fillMaxWidth().clickable { onBack() }
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("✓", color = KalivTheme.colors.signal, fontSize = 15.sp, modifier = Modifier.width(24.dp))
                        Text(selected, color = KalivTheme.colors.signal, fontWeight = FontWeight.Bold, fontSize = 15.sp)
                    }
                    if (shown.isNotEmpty()) {
                        HorizontalDivider()
                        Text("Alle modeller", color = KalivTheme.colors.textMuted, fontSize = 11.sp,
                            modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp))
                    }
                }
                items(shown, key = { it }) { m ->
                    Row(
                        Modifier.fillMaxWidth()
                            .clickable { if (forVoice) store.voiceCloudModel = m else store.cloudModel = m; onPicked() }
                            .padding(horizontal = 16.dp, vertical = 12.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Spacer(Modifier.width(24.dp))
                        Text(m, color = KalivTheme.colors.textHigh, fontSize = 15.sp)
                    }
                }
                if (shown.isEmpty() && query.isNotBlank()) {
                    item {
                        Text("Ingen match på \"$query\"", color = KalivTheme.colors.textMuted, fontSize = 14.sp,
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
        color = KalivTheme.colors.surfaceHigh,
        // 48dp touch target (design guide). heightIn on the Surface gives the
        // height; the inner Box centres the label WITHOUT fillMaxHeight -- that
        // was filling the parent Row's unbounded height and stretching the whole
        // header down the screen (v1.34.0 regression).
        modifier = Modifier.heightIn(min = 48.dp).clickable(onClick = onClick),
    ) {
        Box(contentAlignment = Alignment.Center) {
            Text(label, color = KalivTheme.colors.textHigh, fontSize = 15.sp,
                maxLines = 1,
                modifier = Modifier.padding(horizontal = 14.dp, vertical = 6.dp))
        }
    }
}

@Composable
private fun SourceBadge(mode: String) {
    val (label, color, onColor) = when (mode) {
        "cloud" -> Triple("☁ Cloud", KalivTheme.colors.amber, KalivTheme.colors.onSignal)
        "rag" -> Triple("⌕ RAG", KalivTheme.colors.signal, KalivTheme.colors.onSignal)
        else -> Triple("◈ Rig", KalivTheme.colors.signal, KalivTheme.colors.onSignal)
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

// The Kaliv "thinking" animation -- shown in the assistant bubble while the
// reply is still empty (the moment before the first streamed token), the same
// place Claude shows its thinking indicator. The asset is an animated WebP;
// Compose's painterResource would only draw the first (static) frame, so we
// play it via AnimatedImageDrawable in a tiny ImageView. That API is 28+, so on
// API 26-27 we fall back to the plain ellipsis rather than crash.
@Composable
private fun ThinkingIndicator() {
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        AndroidView(
            modifier = Modifier.size(52.dp),
            factory = { ctx ->
                ImageView(ctx).apply {
                    val src = ImageDecoder.createSource(ctx.resources, R.drawable.kaliv_thinking)
                    val d = ImageDecoder.decodeDrawable(src)
                    setImageDrawable(d)
                    if (d is AnimatedImageDrawable) {
                        d.repeatCount = AnimatedImageDrawable.REPEAT_INFINITE
                        d.start()
                    }
                }
            },
        )
    } else {
        Text("…", color = KalivTheme.colors.textMuted, fontSize = 15.sp, lineHeight = 21.sp)
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
            color = if (isUser) KalivTheme.colors.signal else KalivTheme.colors.surfaceHigh,
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
                            Surface(shape = RoundedCornerShape(999.dp), color = KalivTheme.colors.surfaceHigh) {
                                Text(
                                    (if (m.voiceViaCloud) "☁ " else "◈ ") + "🎙 ${m.voiceModel}",
                                    fontSize = 10.sp,
                                    color = if (m.voiceViaCloud) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                )
                            }
                        }
                    }
                    if (!isUser && m.fellBackToCloud) {
                        Row(Modifier.padding(bottom = 6.dp)) {
                            Surface(
                                shape = RoundedCornerShape(999.dp),
                                color = KalivTheme.colors.surfaceHigh,
                            ) {
                                Text(
                                    "☁ via cloud (rig utilgængelig)",
                                    fontSize = 10.sp, color = KalivTheme.colors.textMuted,
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
                                    color = KalivTheme.colors.surfaceHigh,
                                    modifier = Modifier.padding(end = 4.dp),
                                ) {
                                    Text(
                                        s, fontSize = 10.sp, color = KalivTheme.colors.textMuted,
                                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                                    )
                                }
                            }
                        }
                    }
                    when {
                        isUser -> Text(m.text, color = KalivTheme.colors.onSignal, fontSize = 15.sp, lineHeight = 21.sp)
                        m.error -> Text(m.text, color = KalivTheme.colors.danger, fontSize = 14.sp, lineHeight = 20.sp)
                        m.streaming && m.text.isEmpty() -> ThinkingIndicator()
                        m.streaming -> Text(m.text + "▍", color = KalivTheme.colors.textHigh, fontSize = 15.sp, lineHeight = 21.sp)
                        else -> MarkdownText(m.text, color = KalivTheme.colors.textHigh)
                    }
                    if (m.error && onRetry != null) {
                        Spacer(Modifier.height(6.dp))
                        TextButton(onClick = onRetry, contentPadding = PaddingValues(0.dp)) {
                            Text("↻ Prøv igen", color = KalivTheme.colors.signal, fontSize = 12.sp)
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

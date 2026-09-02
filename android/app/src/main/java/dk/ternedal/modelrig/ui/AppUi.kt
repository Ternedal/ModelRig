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
import androidx.compose.ui.semantics.Role
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
import dk.ternedal.modelrig.logic.TurnInput
import dk.ternedal.modelrig.logic.TurnRouter
import dk.ternedal.modelrig.logic.TurnStatus
import dk.ternedal.modelrig.net.VoiceCapability
import dk.ternedal.modelrig.net.WorkerCapabilities
import dk.ternedal.modelrig.net.IngestCapability
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.TextStyle
import dk.ternedal.modelrig.ui.chat.ChatComposer
import dk.ternedal.modelrig.ui.chat.ChatContextChip
import dk.ternedal.modelrig.ui.chat.ChatEmptyState
import dk.ternedal.modelrig.ui.chat.ChatTopBar
import dk.ternedal.modelrig.ui.components.ChipRow
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.chat.AssistantMessage
import dk.ternedal.modelrig.ui.chat.ChatConversationTopBar
import dk.ternedal.modelrig.ui.chat.ChatMessageUi
import dk.ternedal.modelrig.ui.chat.UserMessage
import dk.ternedal.modelrig.ui.chat.SourceModelSheet
import dk.ternedal.modelrig.ui.chat.ModelRowUi
import dk.ternedal.modelrig.ui.chat.paramsLabelFor
import dk.ternedal.modelrig.ui.chat.CapabilitiesSheet
import androidx.compose.foundation.border
import androidx.compose.ui.graphics.graphicsLayer
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

private enum class Screen { Splash, Setup, Chat, Convos, Models, Knowledge, Schedules, Audit, ControlCenter, CloudPicker, VoiceCloudPicker, RigStatus, Devices, QrScan, Onboarding }

@Composable
fun AppUi(
    pairingLink: dk.ternedal.modelrig.net.PairingLink? = null,
    shared: dk.ternedal.modelrig.net.SharedPayload? = null,
    sharedTruncated: Boolean = false,
) {
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
        // Et scannet link lever her, så det overlever navigationen tilbage
        // fra skanneren til parringskortet.
        var scannedLink by remember { mutableStateOf<dk.ternedal.modelrig.net.PairingLink?>(null) }
        // bumped when the cloud model is changed elsewhere (picker), so
        // ChatScreen re-reads store.cloudModel when it comes back into view.
        var cloudModelTick by remember { mutableStateOf(0) }

        Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
            when (screen) {
                Screen.Splash -> SplashScreen(onDone = {
                    // Velkomsten vises KUN første gang og kun når der hverken
                    // er rig eller cloud. Har man allerede en kilde, er den
                    // en forhindring frem for en introduktion.
                    screen = when {
                        store.hasRig || store.hasCloud -> Screen.Chat
                        !store.onboardingSeen -> Screen.Onboarding
                        else -> Screen.Setup
                    }
                })
                Screen.Onboarding -> Column(
                    Modifier
                        .fillMaxSize()
                        .background(KalivTheme.colors.background)
                        .kalivScreenInsets()
                        .padding(horizontal = 24.dp, vertical = 32.dp),
                ) {
                    dk.ternedal.modelrig.ui.chat.OnboardingCard(
                        onScanQr = { store.onboardingSeen = true; screen = Screen.QrScan },
                        onEnterCode = { store.onboardingSeen = true; screen = Screen.Setup },
                        onSkip = { store.onboardingSeen = true; screen = Screen.Setup },
                    )
                }
                Screen.QrScan -> QrScanScreen(
                    onBack = { screen = Screen.Setup },
                    onLink = { link -> scannedLink = link; screen = Screen.Setup },
                )
                Screen.Setup -> SetupScreen(
                    store,
                    db,
                    pairingLink = scannedLink ?: pairingLink,
                    onScanQr = { screen = Screen.QrScan },
                    onDone = { screen = Screen.Chat },
                    onOpenControlCenter = { screen = Screen.ControlCenter },
                )
                Screen.Chat -> ChatScreen(
                    store, db, openConvId,
                    shared = shared,
                    sharedTruncated = sharedTruncated,
                    cloudModelTick = cloudModelTick,
                    darkMode = darkMode,
                    onToggleDark = { store.darkMode = it; darkMode = it },
                    onOpenSettings = { screen = Screen.Setup },
                    onOpenConversations = { screen = Screen.Convos },
                    onOpenModels = { screen = Screen.Models },
                    onOpenRigStatus = { screen = Screen.RigStatus },
                    onOpenDevices = { screen = Screen.Devices },
                    onOpenKnowledge = { screen = Screen.Knowledge },
                    onOpenAudit = { screen = Screen.Audit },
                    onOpenSchedules = { screen = Screen.Schedules },
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
                Screen.RigStatus -> RigStatusScreen(store, onBack = { screen = Screen.Chat })
                Screen.Devices -> DevicesScreen(
                    store,
                    onBack = { screen = Screen.Chat },
                    onSelfRevoked = {
                        // Denne telefons adgang er væk — tilbage til parring.
                        store.clearRig()
                        store.deviceId = null
                        screen = Screen.Setup
                    },
                )
                Screen.Knowledge -> KnowledgeScreen(store, onBack = { screen = Screen.Chat })
                Screen.Audit -> AuditScreen(store, onBack = { screen = Screen.Chat })
                Screen.Schedules -> ScheduleScreen(store = store, onClose = { screen = Screen.Chat })
                Screen.ControlCenter -> ControlCenterScreen(
                    store = store,
                    onClose = { screen = Screen.Setup },
                )
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
private fun SetupScreen(
    store: TokenStore,
    db: ChatDb,
    onDone: () -> Unit,
    onOpenControlCenter: () -> Unit,
    pairingLink: dk.ternedal.modelrig.net.PairingLink? = null,
    onScanQr: (() -> Unit)? = null,
) {
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
            dk.ternedal.modelrig.ui.chat.PairingHeader(
                subtitle = "Vælg mindst én kilde for at starte",
                modifier = Modifier.weight(1f),
            )
            if (canChat) TextButton(onClick = onDone) { Text("Til chat →", color = KalivTheme.colors.signal) }
        }
        Spacer(Modifier.height(22.dp))
        RigCard(store, db, onConnected = { refresh++; onDone() }, pairingLink = pairingLink, onScanQr = onScanQr)
        Spacer(Modifier.height(13.dp))
        CloudCard(store, db) { refresh++; onDone() }
        if (store.hasRig) {
            Spacer(Modifier.height(13.dp))
            dk.ternedal.modelrig.ui.chat.KalivOutlineActionCard("Åbn Control Center", onOpenControlCenter)
            Text(
                "Read-only drift, routing og freshness fra riggen.",
                color = KalivTheme.colors.textMuted,
                fontSize = 12.sp,
                modifier = Modifier.padding(top = 6.dp, start = 4.dp),
            )
        }
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

    var expanded by remember { mutableStateOf(false) }
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(17.dp),
        border = androidx.compose.foundation.BorderStroke(KalivTokens.Layout.hairline, KalivTheme.colors.hairline),
    ) {
        Column(Modifier.fillMaxWidth().padding(18.dp)) {
            // Kollapset som mockuppen: hoved m. status-sub; indholdet foldes ud.
            Box(Modifier.clickable(onClickLabel = if (expanded) "Fold sammen" else "Fold ud") { expanded = !expanded }) {
                dk.ternedal.modelrig.ui.chat.PairingCardHeader(
                    icon = R.drawable.ic_kaliv_cloud,
                    iconTint = KalivTheme.colors.textMuted,
                    title = "Ollama Cloud",
                    subtitle = if (configured) "${store.cloudModel} · ingen rig påkrævet"
                               else "Chat uden rig · kræver API-nøgle",
                    trailing = {
                        Icon(
                            painterResource(if (expanded) R.drawable.ic_kaliv_chevron_down else R.drawable.ic_kaliv_chevron_right),
                            contentDescription = null,
                            tint = KalivTheme.colors.faint,
                            modifier = Modifier.size(18.dp),
                        )
                    },
                )
            }
            if (expanded) {
            Spacer(Modifier.height(12.dp))
            if (configured) { Text("✓ konfigureret", color = KalivTheme.colors.signal, fontSize = 13.sp); Spacer(Modifier.height(4.dp)) }
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
                        val saved = store.saveCloudConfiguration(
                            key = key.trim().takeIf { it.isNotBlank() },
                            model = model,
                        )
                        if (saved) {
                            key = ""
                            configured = true
                            msg = null
                            onSaved()
                        } else {
                            msg = "Kunne ikke gemme cloud-adgangen sikkert. Prøv igen."
                        }
                    },
                ) { Text("Gem & brug cloud") }
                if (configured) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(
                        onClick = {
                            if (store.clearCloud()) {
                                configured = false
                                key = ""
                                msg = null
                            } else {
                                msg = "Cloud-adgangen kunne ikke ryddes sikkert."
                            }
                        },
                    ) { Text("Ryd", color = KalivTheme.colors.danger) }
                }
            }
            msg?.let { Spacer(Modifier.height(6.dp)); Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp) }
            }
        }
    }
}

@Composable
private fun RigCard(
    store: TokenStore,
    db: ChatDb,
    onConnected: () -> Unit,
    pairingLink: dk.ternedal.modelrig.net.PairingLink? = null,
    onScanQr: (() -> Unit)? = null,
) {
    // Et parringslink UDFYLDER felterne — det parrer ikke. Kortet nedenfor
    // viser værten, og først et tryk bruger koden.
    var baseUrl by remember { mutableStateOf(pairingLink?.baseUrl ?: store.baseUrl ?: "http://192.168.1.10:8080") }
    var code by remember { mutableStateOf(pairingLink?.code ?: "") }
    var linkNotice by remember { mutableStateOf(pairingLink) }
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

    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(17.dp),
        border = androidx.compose.foundation.BorderStroke(2.dp, KalivTheme.colors.hairline),
    ) {
        Column(Modifier.fillMaxWidth().padding(18.dp)) {
            dk.ternedal.modelrig.ui.chat.PairingCardHeader(
                icon = R.drawable.ic_kaliv_rig,
                iconTint = KalivTheme.colors.accent,
                title = "Din rig",
                subtitle = "Lokale modeller + Viden (RAG)",
                modifier = Modifier.padding(bottom = 14.dp),
            )
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
                    if (store.saveRigConnection(profile.serverUrl, profile.deviceToken)) {
                        baseUrl = profile.serverUrl
                        connected = true
                        msg = null
                        onConnected()
                    } else {
                        msg = "Kunne ikke gemme den valgte rig sikkert."
                    }
                },
            )
            Spacer(Modifier.height(8.dp))
            linkNotice?.let { link ->
                dk.ternedal.modelrig.ui.chat.PairingLinkNotice(
                    host = link.host,
                    onDismiss = { linkNotice = null; code = "" },
                    modifier = Modifier.padding(bottom = 9.dp),
                )
            }
            dk.ternedal.modelrig.ui.chat.PairingField("Server-URL", baseUrl, { baseUrl = it })
            dk.ternedal.modelrig.ui.chat.PairingField(
                "Parringskode", code, { code = it },
                letterSpacingEm = 0.16f, placeholder = "XXXX-XXXX",
            )
            dk.ternedal.modelrig.ui.chat.PairingField("Enhedsnavn", deviceName, { deviceName = it })
            onScanQr?.let { scan ->
                Spacer(Modifier.height(9.dp))
                dk.ternedal.modelrig.ui.chat.KalivOutlineActionCard("Skan QR fra riggen", scan)
            }
            dk.ternedal.modelrig.ui.chat.PairingBindNote()
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
                dk.ternedal.modelrig.ui.components.KalivPrimaryButton(
                    text = if (busy) "Forbinder\u2026" else "Forbind",
                    modifier = Modifier.fillMaxWidth(),
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
                                    val saved = store.saveRigConnection(url)
                                    if (saved) {
                                        connected = true; reachable = true; onConnected()
                                    } else {
                                        reachable = true
                                        msg = "Rig'en svarer, men den nye adresse kunne ikke gemmes sikkert."
                                    }
                                } else {
                                    reachable = false
                                    msg = "Rig'en svarer ikke på $url. Tjek IP'en og at serveren kører."
                                }
                            } else {
                                val res = withContext(Dispatchers.IO) { runCatching { ModelRigClient(url).claimPairing(n, c) } }
                                res.onSuccess { pairing ->
                                    val claimedToken = pairing.token
                                    // Enhedens id gemmes, så enhedslisten kan markere DENNE enhed.
                                    store.deviceId = pairing.deviceId
                                    val saved = store.saveRigConnection(url, claimedToken)
                                    busy = false
                                    if (saved) {
                                        connected = true; reachable = true; onConnected()
                                    } else {
                                        reachable = true
                                        msg = "Parringen lykkedes, men credential kunne ikke gemmes sikkert. Par igen."
                                    }
                                }.onFailure { msg = it.message ?: "Kunne ikke forbinde"; busy = false }
                            }
                        }
                    },
                )
                if (connected) {
                    Spacer(Modifier.width(8.dp))
                    TextButton(
                        onClick = {
                            if (store.clearRig()) {
                                connected = false
                                reachable = null
                                msg = null
                            } else {
                                msg = "Rig-adgangen kunne ikke ryddes sikkert."
                            }
                        },
                    ) { Text("Afbryd", color = KalivTheme.colors.danger) }
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
    // Designguiden afsnit 08: "Loading: Kaliv thinking-animation + kort status."
    // Stemplet naar pladsholderen oprettes, hvor turens plan er kendt.
    val status: String = TurnStatus.THINKING,
    val error: Boolean = false, // shown in UI, but never persisted or sent as history
    val sources: List<String> = emptyList(), // RAG source names, if this reply used RAG
    // De udsnit riggen FAKTISK hentede til svaret. Tom på ældre rigge —
    // så viser fladen kun kildechips, som hidtil.
    val context: List<dk.ternedal.modelrig.net.UsedChunk> = emptyList(),
    val fellBackToCloud: Boolean = false, // rig was unreachable -> answered via cloud
    // For a spoken turn: which model answered, and whether it was a cloud model.
    // Deliberately separate from fellBackToCloud -- using cloud for voice is a
    // deliberate choice, not a fallback, and conflating them would mislead.
    val voiceModel: String? = null,
    val voiceViaCloud: Boolean = false,
    // Epoch-ms for turens oprettelse (capslinjens klokkeslaet). null for
    // indlaest historik, hvor DB'en ikke gemmer tid pr. besked.
    val at: Long? = System.currentTimeMillis(),
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
            "Tidsudløb — der kom intet svar (prøvet to gange på frisk forbindelse). Ustabilt mobilnet eller en model i kø. Prøv igen, skift til WiFi, eller vælg en anden model (fx gpt-oss:120b)."
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
    shared: dk.ternedal.modelrig.net.SharedPayload? = null,
    sharedTruncated: Boolean = false,
    cloudModelTick: Int,
    darkMode: Boolean,
    onToggleDark: (Boolean) -> Unit,
    onOpenSettings: () -> Unit,
    onOpenConversations: () -> Unit,
    onOpenModels: () -> Unit,
    onOpenRigStatus: () -> Unit,
    onOpenDevices: () -> Unit,
    onOpenKnowledge: () -> Unit,
    onOpenAudit: () -> Unit,
    onOpenSchedules: () -> Unit,
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
    var showSourceSheet by remember { mutableStateOf(false) }
    var showCapSheet by remember { mutableStateOf(false) }
    var runningModels by remember { mutableStateOf(setOf<String>()) }
    var cloudModel by remember { mutableStateOf(store.cloudModel) }
    var ragMode by remember { mutableStateOf(false) }
    // D4 consent, persisted (2a trin 1): may RAG document content be sent to
    // a CLOUD model? Off -> the rig keeps document content local. Backed by
    // TokenStore so the choice survives restarts; toggled in the ⋮-menu.
    var allowRagCloud by remember { mutableStateOf(store.allowRagCloud) }
    var autoFallback by remember { mutableStateOf(store.autoCloudFallback) }
    var ragSources by remember { mutableStateOf(listOf<String>()) }
    var ragSourceFilter by remember { mutableStateOf<String?>(null) }
    var ragSourceMenu by remember { mutableStateOf(false) }
    var overflow by remember { mutableStateOf(false) }
    // Beskeden der er valgt til en agent-plan (null = ingen). Saettes KUN af
    // et tryk i Kapaciteter; intet i send-stien roerer den.
    var agentPlanFor by remember { mutableStateOf<String?>(null) }
    // Del til Kaliv: hvad en anden app sendte. Kortet nedenfor er det ENESTE
    // sted der handler på det — intet indekseres eller sendes af sig selv.
    var sharePayload by remember { mutableStateOf(shared) }
    var shareBusy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val listState = rememberLazyListState()
    val context = LocalContext.current
    // Offline-kø: beskeder skrevet mens riggen var væk. Telefonens eget
    // regnskab — riggen kender den ikke, og INTET herfra sendes af sig selv.
    val queueStore = remember {
        dk.ternedal.modelrig.data.OfflineQueue(
            context.getSharedPreferences("kaliv_queue", android.content.Context.MODE_PRIVATE),
        )
    }
    var queued by remember { mutableStateOf(queueStore.all()) }
    // Én vej til godkendelsesfladen, saa baade panelet og plan-kortet lander
    // samme sted (ADR-A3-001 D4: godkendelser bor paa agent-skaermen).
    val openAgentCheckpoint = {
        val i = Intent(context, dk.ternedal.modelrig.MainActivity::class.java)
        i.putExtra(dk.ternedal.modelrig.MainActivity.EXTRA_AGENT3_REVIEW, true)
        context.startActivity(i)
    }

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

    // Rigens EGNE evner (GET /capabilities), hentet en gang pr. forbindelse.
    // Skal ligge i tilstand frem for at blive hentet paa stedet: onOpenVoice
    // koerer paa main-traaden, og et netvaerkskald derfra ville kaste.
    // UNKNOWN indtil svaret er inde -- og UNKNOWN betyder ALT TILLADT, saa
    // ingen funktion er blokeret imens.
    var workerCaps by remember { mutableStateOf(WorkerCapabilities.UNKNOWN) }

    /**
     * ENESTE indgang til mikrofonen.
     *
     * Optagelsen blev tidligere startet fire uafhaengige steder — composerens
     * mic-tap, overlayets knap, Kapaciteter-arket og permission-fortsaettelsen.
     * En gate der kun daekkede det ene lod de tre andre staa aabne, og det var
     * netop det den strukturelle gate fangede. Derfor er der nu eet sted, og
     * gaten kraever at `voiceCapture.start()` KUN staar her.
     *
     * Returnerer true hvis optagelsen faktisk koerer.
     */
    fun startVoiceCaptureGuarded(): Boolean {
        val verdict = VoiceCapability.check(workerCaps)
        if (verdict is VoiceCapability.Verdict.Blocked) {
            voiceError = verdict.reason
            return false
        }
        return try {
            voiceCapture.start()
            recording = true
            true
        } catch (e: Exception) {
            voiceError = "Optagelse fejlede: ${e.message}"
            false
        }
    }
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
    var showVoice by remember { mutableStateOf(false) }
    // Skaerm 13: rig-liveness. null = ukendt endnu; loekken auto-retry'er
    // (hurtigere naar offline) og driver banner, sheet-prik og composer.
    var rigOnline by remember { mutableStateOf<Boolean?>(null) }
    var lastOnlineAt by remember { mutableStateOf<Long?>(null) }
    var pingBusy by remember { mutableStateOf(false) }
    // Cloud-tilbuddet stilles én gang pr. session. Riggen kan være nede i
    // lang tid, og banneret dukkede op igen hver gang man skiftede tilbage
    // til rig-mode -- altså samme spørgsmål igen og igen efter man havde
    // svaret. Selve offline-beskeden bliver (den er sand og styrer køen),
    // men knappen forsvinder: valget er truffet og kendt.
    var cloudOfferTaken by remember { mutableStateOf(false) }
    var availableUpdate by remember { mutableStateOf<String?>(null) }
    var updDownloading by remember { mutableStateOf(false) }
    var updProgress by remember { mutableStateOf(0) }
    var voiceTranscript by remember { mutableStateOf("") }
    LaunchedEffect(mode, store.hasRig) {
        while (true) {
            if (mode == "rig" && store.hasRig) {
                val ok = withContext(Dispatchers.IO) {
                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).ping() }.getOrDefault(false)
                }
                rigOnline = ok
                if (ok) lastOnlineAt = System.currentTimeMillis()
                kotlinx.coroutines.delay(if (ok) 30_000 else 12_000)
            } else {
                rigOnline = null
                kotlinx.coroutines.delay(30_000)
            }
        }
    }
    fun checkForUpdate(manual: Boolean) {
        scope.launch {
            val latest = withContext(Dispatchers.IO) { dk.ternedal.modelrig.net.UpdateChecker.latestVersion() }
            val cur = dk.ternedal.modelrig.BuildConfig.VERSION_NAME
            when {
                latest == null -> if (manual) {
                    android.widget.Toast.makeText(context, "Kunne ikke tjekke for opdatering", android.widget.Toast.LENGTH_SHORT).show()
                }
                dk.ternedal.modelrig.net.UpdateChecker.isNewer(cur, latest) -> {
                    if (manual || latest != store.dismissedUpdateVersion) {
                        if (manual) store.dismissedUpdateVersion = null
                        availableUpdate = latest
                    }
                }
                else -> if (manual) {
                    android.widget.Toast.makeText(context, "Du k\u00f8rer nyeste ($cur)", android.widget.Toast.LENGTH_SHORT).show()
                }
            }
        }
    }
    fun startUpdateDownload() {
        updDownloading = true; updProgress = 0
        val dm = context.getSystemService(android.content.Context.DOWNLOAD_SERVICE) as android.app.DownloadManager
        val dest = java.io.File(context.getExternalFilesDir(null), "kaliv-latest.apk")
        if (dest.exists()) dest.delete()
        val req = android.app.DownloadManager.Request(android.net.Uri.parse(dk.ternedal.modelrig.net.UpdateChecker.APK_URL))
            .setTitle("Kaliv-opdatering")
            .setDestinationInExternalFilesDir(context, null, "kaliv-latest.apk")
            .setNotificationVisibility(android.app.DownloadManager.Request.VISIBILITY_VISIBLE)
        val id = dm.enqueue(req)
        scope.launch {
            var running = true
            while (running) {
                kotlinx.coroutines.delay(500)
                val cur = dm.query(android.app.DownloadManager.Query().setFilterById(id))
                if (cur == null || !cur.moveToFirst()) { running = false; updDownloading = false; cur?.close(); break }
                val status = cur.getInt(cur.getColumnIndexOrThrow(android.app.DownloadManager.COLUMN_STATUS))
                val done = cur.getLong(cur.getColumnIndexOrThrow(android.app.DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR))
                val total = cur.getLong(cur.getColumnIndexOrThrow(android.app.DownloadManager.COLUMN_TOTAL_SIZE_BYTES))
                cur.close()
                if (total > 0) updProgress = ((done * 100) / total).toInt()
                when (status) {
                    android.app.DownloadManager.STATUS_SUCCESSFUL -> {
                        running = false
                        updDownloading = false
                        val uri = androidx.core.content.FileProvider.getUriForFile(
                            context, context.packageName + ".fileprovider", dest,
                        )
                        val i = Intent(Intent.ACTION_VIEW)
                            .setDataAndType(uri, "application/vnd.android.package-archive")
                            .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
                        runCatching { context.startActivity(i) }
                            .onFailure {
                                android.widget.Toast.makeText(context, "Kunne ikke starte installationen", android.widget.Toast.LENGTH_SHORT).show()
                            }
                    }
                    android.app.DownloadManager.STATUS_FAILED -> {
                        running = false
                        updDownloading = false
                        android.widget.Toast.makeText(context, "Hentning fejlede \u2014 pr\u00f8v igen", android.widget.Toast.LENGTH_SHORT).show()
                    }
                }
            }
        }
    }
    LaunchedEffect(Unit) {
        val now = System.currentTimeMillis()
        if (now - store.lastUpdateCheckAt > 12 * 3_600_000L) {
            store.lastUpdateCheckAt = now
            checkForUpdate(manual = false)
        }
    }
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
    ) { granted ->
        hasMicPermission = granted
        if (!granted) {
            voiceError = "Mikrofon-adgang nægtet"
        } else if (showVoice && !recording && !voiceBusy) {
            // Fortsaettelse: overlayet blev aabnet uden permission — start nu.
            startVoiceCaptureGuarded()
        }
    }

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
                                voiceTranscript = tt
                                // messages is a SnapshotStateList -- safe to mutate
                                // from this IO thread; the recomposer picks it up.
                                // Set replyIdx synchronously (the callbacks run in
                                // order on the reader thread) so the first chunk
                                // can reference it.
                                messages.add(Msg("user", tt))
                                replyIdx = messages.size
                                // Stemme-turen har ingen turnPlan i scope; defaulten er den rigtige.
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

                    // Spoerg riggen FOER filen sendes. Den udgivne core-worker
                    // sendes uden PyMuPDF/python-docx/python-pptx, og uden det
                    // her bruger brugeren et filvalg, en upload og en ventetid
                    // paa at faa rigens raa fejl. Blokerer kun paa et
                    // UDTRYKKELIGT nej -- aeldre rig eller mislykket probe
                    // sender som hidtil.
                    val format = when {
                        isPdf -> IngestCapability.Format.PDF
                        isDocx -> IngestCapability.Format.DOCX
                        isPptx -> IngestCapability.Format.PPTX
                        isHtml -> IngestCapability.Format.HTML
                        else -> IngestCapability.Format.TEXT
                    }
                    val verdict = IngestCapability.check(format, client.workerCapabilities())
                    if (verdict is IngestCapability.Verdict.Blocked) {
                        throw RuntimeException(verdict.reason)
                    }

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
    // Hent rigens evner naar forbindelsen skifter. Fejler den, forbliver
    // workerCaps UNKNOWN og alt er tilladt -- et mislykket probe maa ikke
    // amputere en app der virker.
    LaunchedEffect(store.baseUrl, store.token) {
        val b = store.baseUrl
        workerCaps = if (b.isNullOrBlank()) WorkerCapabilities.UNKNOWN
        else withContext(Dispatchers.IO) {
            ModelRigClient(b, store.token).workerCapabilities()
        }
    }

    LaunchedEffect(cloudModelTick) { cloudModel = store.cloudModel }

    LaunchedEffect(openConvId) {
        // The send path creates the conversation lazily and reports its id
        // through onConvChanged -- which lands right here, while the first
        // reply is still streaming. Clearing and reloading on THAT change
        // replaced the list under the stream's feet: the first delta then
        // indexed past the reloaded [user] and killed the app (#789: crash on
        // the first send after a fresh pairing, never after a restart, where
        // convId already exists). Only a switch to a DIFFERENT conversation
        // reloads; the id this screen just minted is already on screen.
        if (openConvId != null && openConvId == convId) return@LaunchedEffect
        messages.clear()
        // A pending confirmation belongs to the conversation that proposed it.
        // Leaving it on screen across a switch means approving an action in the
        // wrong context -- the confirmation_id still points at the old thread.
        // The rig would happily execute it: it parked the arguments, not the UI.
        pendingTool = null
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
                messages.add(Msg(role, if (role == "assistant") stripEmojis(content) else content, at = null))
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
        // Route decision comes from the ONE table-tested router (see
        // TurnRouter) -- the retry path derives its flags from the same place,
        // so send and retry cannot diverge again.
        val turnPlan = TurnRouter.plan(TurnInput(mode, toolsMode, ragMode, store.cloudKey != null, allowRagCloud))
        val useCloud = turnPlan.useCloud
        val useRag = turnPlan.useRag
        val sys = (if (useCloud) store.cloudSystem else store.rigSystem).trim()
        val convo = messages.filter { !it.error }.map { it.role to it.text }
        val history = trimHistory(sys, convo)
        val idx = messages.size
        messages.add(Msg("assistant", "", streaming = true, status = TurnStatus.forPlan(turnPlan)))
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
                    // Nested launch: an exception here is NOT caught by the
                    // runCatching around the stream -- it is an app crash. Guard
                    // the index; a replaced list means the user moved on.
                    val cur = messages.getOrNull(idx) ?: return@launch
                    messages[idx] = cur.copy(text = cur.text + delta)
                }
            }
            val onContext: (List<dk.ternedal.modelrig.net.UsedChunk>) -> Unit = { cs ->
                scope.launch {
                    val i = messages.lastIndex
                    if (i >= 0) messages[i] = messages[i].copy(context = cs)
                }
            }
            val onSources: (List<String>) -> Unit = { srcs ->
                scope.launch {
                    val cur = messages.getOrNull(idx) ?: return@launch
                    messages[idx] = cur.copy(sources = srcs)
                }
            }
            // Riggens egen fase erstatter startgaettet fra TurnStatus.forPlan.
            // Ukendt fase -> null -> statussen staar; en nyere worker maa ikke
            // kunne blanke indikatoren.
            val onPhase: (String) -> Unit = { name ->
                TurnStatus.forPhase(name)?.let { label ->
                    scope.launch {
                        val cur = messages.getOrNull(idx) ?: return@launch
                        if (cur.streaming) messages[idx] = cur.copy(status = label)
                    }
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
            val useTools = turnPlan.useTools
            // RAG and Tools compose: documents ground the answer, and the model
            // may still propose an action about them. Retrieval runs against the
            // rig's index; sending those chunks to a CLOUD model is gated behind
            // the D4 consent toggle (allowRagCloud), off by default.
            val toolsWithRag = turnPlan.toolsWithRag
            var proposal: dk.ternedal.modelrig.net.ToolTurn? = null
            val err = withContext(Dispatchers.IO) {
                runCatching {
                    when {
                        // Tools: not a stream. One turn in, either an answer or a
                        // proposal that has executed nothing. Checked before RAG and
                        // cloud because it is the most restrictive mode.
                        useTools -> {
                            val viaCloud = mode == "cloud"
                            // Tools live behind the rig's gate, so cloud+tools
                            // routes THROUGH the rig -- a tailnet address the
                            // phone can't reach with Tailscale off (on-device
                            // 14/7: first send hung/errored, while retry --
                            // whose path has no tools branch -- answered
                            // instantly via CloudClient). Probe the rig fast;
                            // if it is unreachable in cloud mode, degrade to
                            // plain cloud chat WITHOUT tools and say so,
                            // instead of hanging on a route that cannot work.
                            // No implicit downgrade (audit P1-2): "slet model X"
                            // silently answered WITHOUT tools changes what the
                            // turn means. Fail fast with the choice spelled out
                            // -- retry (needs the rig) or turn Tools off for
                            // plain cloud chat. Also fixes P2-1: no synthetic
                            // note in the bubble, so a later error shows as the
                            // real error, not "[afbrudt]".
                            if (viaCloud && !ModelRigClient(store.baseUrl ?: "", store.token).quickHealth()) {
                                throw dk.ternedal.modelrig.net.ModelRigException("Riggen kan ikke nås, og Tools er slået til — tool-kørsel går gennem riggens sikkerhedsgate. Prøv igen når riggen kan nås (Tailscale/hjemmenetværk), eller slå Tools fra for at chatte direkte med cloud uden tools.")
                            }
                            // history minus the just-added user turn (the rig
                            // appends that itself; sending it twice makes the
                            // model answer its own echo) and minus the system
                            // prompt, which now travels in its own field.
                            val prior = history.dropLast(1).filter { it.first != "system" }
                            val turn = ModelRigClient(store.baseUrl ?: "", store.token)
                                .toolsChatStream(
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
                                    registerCall = hook,
                                    onPhase = onPhase,
                                )
                            if (turn.sources.isNotEmpty()) onSources(turn.sources)
                            if (turn.context.isNotEmpty()) onContext(turn.context)
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
                            .ragChatStream(t, rigModel, srcFilter, registerCall = hook, onSources = onSources,
                                onDelta = onDelta, onPhase = onPhase)
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
            // The list can have been replaced mid-stream (a real conversation
            // switch). Then there is nothing on screen to finish; bail rather
            // than index past the end. The reply is not persisted in that
            // case -- a loss, but a bounded one, where before it was a crash.
            val cur = messages.getOrNull(idx) ?: run { busy = false; return@launch }
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
        // ONE router for send + retry (audit P1-1 -> 1.58.38): the retry can
        // no longer diverge from the original turn's route -- the decision
        // lives in TurnRouter and is table-tested on the JVM. Only the image
        // is gone (consumed by the original turn).
        val turnPlan = TurnRouter.plan(TurnInput(mode, toolsMode, ragMode, store.cloudKey != null, allowRagCloud))
        val useCloud = turnPlan.useCloud
        val useRag = turnPlan.useRag
        val useTools = turnPlan.useTools
        val toolsWithRag = turnPlan.toolsWithRag
        val sys = (if (useCloud) store.cloudSystem else store.rigSystem).trim()
        val convo = messages.filterIndexed { idx2, mm -> idx2 != i && !mm.error }.map { it.role to it.text }
        val history = trimHistory(sys, convo)
        val rigModel = currentModel
        val cModel = cloudModel
        val srcFilter = ragSourceFilter
        val cidNow = convId
        messages[i] = Msg("assistant", "", streaming = true, status = TurnStatus.forPlan(turnPlan))
        busy = true
        var proposal: dk.ternedal.modelrig.net.ToolTurn? = null
        scope.launch {
            val onDelta: (String) -> Unit = { delta ->
                scope.launch { val cur = messages.getOrNull(i) ?: return@launch; messages[i] = cur.copy(text = cur.text + delta) }
            }
            val onContext: (List<dk.ternedal.modelrig.net.UsedChunk>) -> Unit = { cs ->
                scope.launch {
                    val i = messages.lastIndex
                    if (i >= 0) messages[i] = messages[i].copy(context = cs)
                }
            }
            val onSources: (List<String>) -> Unit = { srcs ->
                scope.launch { val cur = messages[i]; messages[i] = cur.copy(sources = srcs) }
            }
            val onPhase: (String) -> Unit = { name ->
                TurnStatus.forPhase(name)?.let { label ->
                    scope.launch {
                        val cur = messages[i]
                        if (cur.streaming) messages[i] = cur.copy(status = label)
                    }
                }
            }
            val hook: (okhttp3.Call) -> Unit = { activeCall = it }
            val err = withContext(Dispatchers.IO) {
                runCatching {
                    when {
                        useTools -> {
                            val viaCloud = mode == "cloud"
                            if (viaCloud && !ModelRigClient(store.baseUrl ?: "", store.token).quickHealth()) {
                                throw dk.ternedal.modelrig.net.ModelRigException("Riggen kan ikke nås, og Tools er slået til — tool-kørsel går gennem riggens sikkerhedsgate. Prøv igen når riggen kan nås (Tailscale/hjemmenetværk), eller slå Tools fra for at chatte direkte med cloud uden tools.")
                            }
                            val prior = history.dropLast(1).filter { it.first != "system" }
                            val turn = ModelRigClient(store.baseUrl ?: "", store.token)
                                .toolsChatStream(
                                    t,
                                    model = if (viaCloud) cModel else rigModel,
                                    cloudBaseUrl = if (viaCloud) "https://ollama.com" else null,
                                    cloudKey = if (viaCloud) store.cloudKey else null,
                                    history = prior,
                                    rag = toolsWithRag,
                                    ragSource = if (toolsWithRag) srcFilter else null,
                                    allowRagCloud = allowRagCloud,
                                    imageB64 = null,
                                    system = sys,
                                    registerCall = hook,
                                    onPhase = onPhase,
                                )
                            if (turn.sources.isNotEmpty()) onSources(turn.sources)
                            if (turn.context.isNotEmpty()) onContext(turn.context)
                            if (turn.status == "confirmation_required") {
                                proposal = turn
                            } else {
                                onDelta(turn.answer)
                            }
                        }
                        useRag -> ModelRigClient(store.baseUrl ?: "", store.token)
                            .ragChatStream(t, rigModel, srcFilter, registerCall = hook, onSources = onSources,
                                onDelta = onDelta, onPhase = onPhase)
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
            // Same as the main path: a parked write proposal surfaces the card.
            proposal?.let { pendingTool = it }
            val cur = messages.getOrNull(i) ?: run { busy = false; return@launch }
            val cancelled = err != null && cur.text.isNotEmpty()
            messages[i] = when {
                err == null -> cur.copy(streaming = false, text = stripEmojis(cur.text))
                cur.text.isEmpty() -> cur.copy(streaming = false, error = true, text = friendlyError(err!!))
                else -> cur.copy(streaming = false, text = stripEmojis(cur.text) + "\n\n_[afbrudt]_")
            }
            val finalText = messages[i].text
            // Mirror the main path: a parked proposal has no answer yet --
            // never persist a blank assistant turn.
            if (cidNow != null && (err == null || cancelled) && finalText.isNotBlank()) {
                withContext(Dispatchers.IO) { db.addMessage(cidNow, "assistant", finalText) }
            }
            busy = false
        }
    }

    Column(Modifier.fillMaxSize()) {
        // top bar
        Surface(color = KalivTheme.colors.background) {
            Column {
            // Redesignets topbar (DDR-001 fase 2). Tom samtale = brand-baren;
            // aaben samtale = titel-baren m. tilbage-pil (skaerm 2). Overflow-
            // menuen deles og ankres ved prik-knappen i begge varianter.
            val chatOverflowMenu: @Composable () -> Unit = {
                DropdownMenu(expanded = overflow, onDismissRequest = { overflow = false }) {
                        DropdownMenuItem(text = { Text("Ny samtale") }, onClick = {
                            overflow = false; messages.clear(); convId = null; onConvChanged(null)
                        })
                        DropdownMenuItem(text = { Text("Samtaler") }, onClick = { overflow = false; onOpenConversations() })
                        DropdownMenuItem(text = { Text("Modeller") }, onClick = { overflow = false; onOpenModels() })
                        DropdownMenuItem(text = { Text("Rig-status") }, onClick = { overflow = false; onOpenRigStatus() })
                        DropdownMenuItem(text = { Text("Enheder") }, onClick = { overflow = false; onOpenDevices() })
                        DropdownMenuItem(text = { Text("Viden") }, onClick = { overflow = false; onOpenKnowledge() })
                        DropdownMenuItem(text = { Text("Planer") }, onClick = { overflow = false; onOpenSchedules() })
                        if (mode == "rig" && store.hasRig) {
                            // Operatør-skærmen for Agent 3-opgaver fandtes kun bag
                            // kaliv://tasks -- ingen vej ind fra UI'et. Den er
                            // read-only og serverstyret, så et menupunkt er
                            // ufarligt; ligesom Planer giver den kun mening med
                            // en parret rig.
                            DropdownMenuItem(text = { Text("Opgaver") }, onClick = {
                                overflow = false
                                val i = Intent(context, dk.ternedal.modelrig.MainActivity::class.java)
                                i.putExtra(dk.ternedal.modelrig.MainActivity.EXTRA_AGENT3_TASK, true)
                                context.startActivity(i)
                            })
                            // Hvem Kaliv er (#752): vælg person; aktivering af
                            // revisioner er en operatørhandling på riggen.
                            DropdownMenuItem(text = { Text("Personer") }, onClick = {
                                overflow = false
                                val i = Intent(context, dk.ternedal.modelrig.MainActivity::class.java)
                                i.putExtra(dk.ternedal.modelrig.MainActivity.EXTRA_PERSONS, true)
                                context.startActivity(i)
                            })
                        }
                        if (mode == "rig" && store.cloudKey != null) {
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        (if (voiceUsesCloud) "\u2601 " else "\u25c7 ") + "Stemme svarer via cloud",
                                        color = if (voiceUsesCloud) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                                        fontSize = 13.sp,
                                    )
                                },
                                onClick = {
                                    voiceUsesCloud = !voiceUsesCloud
                                    store.voiceUsesCloud = voiceUsesCloud
                                },
                            )
                        }
                        if (ragMode) {
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        ragSourceFilter?.let { "\u2315 Kilde: $it" } ?: "\u2315 Kilder: alle",
                                        color = KalivTheme.colors.textMuted, fontSize = 13.sp,
                                    )
                                },
                                onClick = { overflow = false; ragSourceMenu = true },
                            )
                        }
                        DropdownMenuItem(
                            text = { Text("\u2699 Tool-styring", color = KalivTheme.colors.textMuted, fontSize = 13.sp) },
                            onClick = {
                                overflow = false
                                registryError = null
                                showToolCtl = true
                                loadRegistry()
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("\ud83d\udcdc Handlingslog", color = KalivTheme.colors.textMuted, fontSize = 13.sp) },
                            onClick = { overflow = false; onOpenAudit() },
                        )
                        if (bargeInEnabled) {
                            DropdownMenuItem(
                                text = {
                                    Text(
                                        "Barge-in f\u00f8lsomhed: $bargeInThreshold" +
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
                        DropdownMenuItem(text = { Text("S\u00f8g efter opdatering") }, onClick = { overflow = false; checkForUpdate(manual = true) })
                        DropdownMenuItem(text = { Text("Kapaciteter") }, onClick = { overflow = false; showCapSheet = true })
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
                        // 2a trin 1: the consents become REAL -- persisted in
                        // TokenStore, toggleable here next to the theme toggle
                        // (the app's only other toggle). Before this,
                        // allowRagCloud was a dead remember{false}: the D4
                        // consent literally could not be given by a user.
                        DropdownMenuItem(
                            text = {
                                Text(if (allowRagCloud) "✓  Dokumentviden → cloud: TIL" else "Dokumentviden → cloud: FRA")
                            },
                            onClick = {
                                overflow = false
                                allowRagCloud = !allowRagCloud
                                store.allowRagCloud = allowRagCloud
                            },
                        )
                        DropdownMenuItem(
                            text = {
                                Text(if (autoFallback) "✓  Auto cloud-fallback: TIL" else "Auto cloud-fallback: FRA")
                            },
                            onClick = {
                                overflow = false
                                autoFallback = !autoFallback
                                store.autoCloudFallback = autoFallback
                            },
                        )
                    }
            }
            if (messages.isEmpty()) {
                ChatTopBar(
                    dark = darkMode,
                    onToggleDark = { onToggleDark(!darkMode) },
                    onOverflow = { overflow = true },
                    modifier = Modifier.windowInsetsPadding(WindowInsets.statusBars),
                    overflowContent = chatOverflowMenu,
                )
            } else {
                val convTitle = remember(convId, messages.size) {
                    convId?.let { id -> db.listConversations().firstOrNull { it.id == id }?.title }
                        ?: messages.firstOrNull { it.role == "user" }?.text?.take(28)
                        ?: "Samtale"
                }
                ChatConversationTopBar(
                    title = convTitle,
                    onBack = { onOpenConversations() },
                    onOverflow = { overflow = true },
                    modifier = Modifier.windowInsetsPadding(WindowInsets.statusBars),
                    overflowContent = chatOverflowMenu,
                )
            }
            // Kontekst-chips: model (+menuen som er appens capability-hub),
            // RAG- og Tools-tilstand. Kilde-badge/Skift-knappen er afloest af
            // routing-strippen nedenfor + Skift-punktet i overflow-menuen.
            ChipRow(
                background = KalivTheme.colors.background,
                modifier = Modifier.fillMaxWidth().padding(start = 20.dp, bottom = 10.dp),
            ) {
                if (mode == "cloud") {
                    ChatContextChip(
                        text = cloudModel,
                        emphasized = true,
                        leadingIcon = painterResource(R.drawable.ic_kaliv_model),
                        leadingTint = KalivTheme.colors.accent,
                        trailingIcon = painterResource(R.drawable.ic_kaliv_chevron_down),
                        onClick = { showSourceSheet = true },
                    )
                } else {
                    Box {
                        ChatContextChip(
                            text = currentModel,
                            emphasized = true,
                            leadingIcon = painterResource(R.drawable.ic_kaliv_model),
                            leadingTint = KalivTheme.colors.accent,
                            trailingIcon = painterResource(R.drawable.ic_kaliv_chevron_down),
                            onClick = { showSourceSheet = true },
                        )
                        // Auto-load the installed rig models the first time the menu
                        // opens (and whenever it reopens empty), so there's an actual
                        // list to pick from -- previously the list only appeared after
                        // tapping "Genindlæs modeller", so rig mode looked like it had
                        // no model switcher at all.
                        LaunchedEffect(showSourceSheet) {
                            if (showSourceSheet && store.baseUrl != null) {
                                val res = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listModels() }
                                }
                                if (models.isEmpty()) {
                                    res.onSuccess { models = it }
                                        .onFailure { modelError = "Kan ikke hente modeller: rig'en svarer ikke" }
                                }
                                val run = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRunningModels() }
                                }
                                run.onSuccess { rm -> runningModels = rm.map { it.name }.toSet() }
                            }
                        }
                        // Model-/kildevalg bor nu i Kilde & model-sheetet (skaerm 3);
                        // resten af den gamle menu er flyttet til \u22ee-menuen.
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
                if (mode == "rig") {
                    ChatContextChip(
                        text = if (ragMode) "RAG \u00b7 Til" else "RAG",
                        active = ragMode,
                        leadingIcon = painterResource(R.drawable.ic_kaliv_search),
                        onClick = {
                            val on = !ragMode
                            ragMode = on
                            if (on) scope.launch {
                                val res = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
                                }
                                res.onSuccess { ragSources = it }
                            }
                        },
                    )
                }
                ChatContextChip(
                    text = "Tools",
                    active = toolsMode,
                    leadingIcon = painterResource(R.drawable.ic_kaliv_tools),
                    onClick = {
                        toolsMode = !toolsMode
                        store.toolsMode = toolsMode
                        if (!toolsMode) pendingTool = null
                    },
                )
            }
            if (showSourceSheet) {
                val host = store.baseUrl?.removePrefix("https://")?.removePrefix("http://")?.trimEnd('/')
                SourceModelSheet(
                    rigSelected = mode == "rig",
                    rigStatus = when {
                        host == null -> "Ikke parret"
                        rigOnline == true -> "Forbundet \u00b7 $host"
                        rigOnline == false -> "Svarer ikke \u00b7 $host"
                        else -> "Parret \u00b7 $host"
                    },
                    rigConnected = rigOnline ?: store.hasRig,
                    cloudAvailable = hasCloud,
                    cloudStatus = if (hasCloud) "$cloudModel \u00b7 forlader enheden" else "Ingen n\u00f8gle",
                    models = models.map {
                        ModelRowUi(
                            name = it,
                            selected = it == currentModel,
                            loaded = it in runningModels,
                            paramsLabel = paramsLabelFor(it),
                        )
                    },
                    onSelectRig = { mode = "rig"; store.chatMode = "rig" },
                    onSelectCloud = {
                        if (mode == "cloud") {
                            showSourceSheet = false
                            onOpenCloudPicker()
                        } else {
                            mode = "cloud"; store.chatMode = "cloud"; ragMode = false
                        }
                    },
                    onSelectModel = { currentModel = it; store.model = it },
                    onReload = {
                        scope.launch {
                            modelError = null
                            val res = withContext(Dispatchers.IO) {
                                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listModels() }
                            }
                            res.onSuccess {
                                models = it
                                if (it.isEmpty()) modelError = "Rig'en svarede, men har ingen modeller"
                            }.onFailure { modelError = "Kan ikke hente modeller: rig'en svarer ikke" }
                            val run = withContext(Dispatchers.IO) {
                                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRunningModels() }
                            }
                            run.onSuccess { rm -> runningModels = rm.map { it.name }.toSet() }
                        }
                    },
                    onDismiss = { showSourceSheet = false },
                )
            }
            if (showCapSheet) {
                CapabilitiesSheet(
                    onRunAsAgent = if (mode == "rig" && store.hasRig && input.isNotBlank()) ({
                        agentPlanFor = input
                        showCapSheet = false
                    }) else null,
                    ragOn = ragMode,
                    ragSubtitle = if (ragMode && ragSources.isNotEmpty())
                        "${ragSources.size} dokument" + (if (ragSources.size == 1) "" else "er") + " \u00b7 svarer med kilder"
                    else "Svarer med kilder fra dine dokumenter",
                    ragSourceLabel = ragSourceFilter?.let { "Kilder: $it" } ?: "Kilder: Alle",
                    onToggleRag = { on ->
                        if (mode == "rig") {
                            ragMode = on
                            if (on) scope.launch {
                                val res = withContext(Dispatchers.IO) {
                                    runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSources() }
                                }
                                res.onSuccess { ragSources = it }
                            }
                        }
                    },
                    onSources = { showCapSheet = false; ragSourceMenu = true },
                    toolsOn = toolsMode,
                    onToggleTools = { on ->
                        toolsMode = on
                        store.toolsMode = on
                        if (!on) pendingTool = null
                    },
                    voiceCloudAvailable = mode == "rig" && store.cloudKey != null,
                    voiceViaCloud = voiceUsesCloud,
                    onToggleVoiceCloud = { on ->
                        voiceUsesCloud = on
                        store.voiceUsesCloud = on
                    },
                    onOpenVoice = {
                        showCapSheet = false
                        showVoice = true
                        voiceError = null
                        // Spoerg FOER mikrofonen aabnes. Uden det taler
                        // brugeren faerdig, uploader, og faar saa rigens 501.
                        if (!recording && !voiceBusy) {
                            if (hasMicPermission) {
                                startVoiceCaptureGuarded()
                            } else {
                                micPermLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
                            }
                        }
                    },
                    onDismiss = { showCapSheet = false },
                )
            }
            if (showVoice) {
                androidx.compose.ui.window.Dialog(
                    onDismissRequest = {
                        if (recording) { runCatching { voiceCapture.stopToWav() } }
                        recording = false
                        stopVoiceTurn()
                        showVoice = false
                    },
                    properties = androidx.compose.ui.window.DialogProperties(usePlatformDefaultWidth = false, decorFitsSystemWindows = false),
                ) {
                    // Pixel-feedback 14/08: Dialog-vinduet skal SELV fylde skaermen —
                    // ellers staar overlayet som en svaevende boks med dim omkring
                    // (indholdets fillMaxSize kan ikke straekke vinduet).
                    val dialogWindow = (androidx.compose.ui.platform.LocalView.current.parent
                        as? androidx.compose.ui.window.DialogWindowProvider)?.window
                    androidx.compose.runtime.SideEffect {
                        dialogWindow?.setLayout(
                            android.view.WindowManager.LayoutParams.MATCH_PARENT,
                            android.view.WindowManager.LayoutParams.MATCH_PARENT,
                        )
                        dialogWindow?.setBackgroundDrawable(
                            android.graphics.drawable.ColorDrawable(android.graphics.Color.TRANSPARENT),
                        )
                        dialogWindow?.setDimAmount(0f)
                    }
                    dk.ternedal.modelrig.ui.chat.VoiceOverlayContent(
                        modifier = Modifier.windowInsetsPadding(WindowInsets.statusBars),
                        pillText = if (voiceUsesCloud && store.cloudKey != null) "Via cloud" else "Lokalt",
                        pillDot = if (voiceUsesCloud && store.cloudKey != null) KalivTheme.colors.signal else KalivTheme.colors.success,
                        stateText = when {
                            recording -> "Lytter \u2026"
                            voiceBusy && !speaking -> "T\u00e6nker \u2026"
                            speaking -> "Taler \u2026"
                            else -> "Klar"
                        },
                        transcript = voiceTranscript,
                        buttonLabel = when {
                            recording -> "Tryk for at sende"
                            voiceBusy || speaking -> "Tryk for at afbryde"
                            else -> "Tryk for at tale"
                        },
                        onMainTap = {
                            when {
                                recording -> {
                                    recording = false
                                    val wav = voiceCapture.stopToWav()
                                    if (wav != null) runVoiceTurn(wav) else voiceError = "ingen lyd optaget"
                                }
                                voiceBusy || speaking -> stopVoiceTurn()
                                else -> {
                                    voiceTranscript = ""
                                    if (hasMicPermission) {
                                        startVoiceCaptureGuarded()
                                    } else {
                                        micPermLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
                                    }
                                }
                            }
                        },
                        onClose = {
                            if (recording) { runCatching { voiceCapture.stopToWav() }; recording = false }
                            stopVoiceTurn()
                            showVoice = false
                        },
                    )
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
                // Tale-etiketten følger mikrofonen: den vises kun i rig-mode,
                // hvor mic-knappen findes. I cloud-mode er knappen væk (ASR
                // kører rig-side), så en "🎙 tale: …"-linje dér lovede en
                // kapabilitet man ikke kunne starte -- samme slags falske
                // signal som en Stop-knap uden handle bag.
                if (mode == "rig") {
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

        val rigOffline = mode == "rig" && store.hasRig && rigOnline == false
        if (rigOffline) {
            dk.ternedal.modelrig.ui.chat.RigOfflineBanner(
                lastSeenLabel = lastOnlineAt?.let {
                    SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(it))
                },
                showCloudSwitch = hasCloud && !cloudOfferTaken,
                retryBusy = pingBusy,
                onRetry = {
                    pingBusy = true
                    scope.launch {
                        val ok = withContext(Dispatchers.IO) {
                            runCatching { ModelRigClient(store.baseUrl ?: "", store.token).ping() }.getOrDefault(false)
                        }
                        rigOnline = ok
                        if (ok) lastOnlineAt = System.currentTimeMillis()
                        pingBusy = false
                    }
                },
                onSwitchCloud = {
                    cloudOfferTaken = true
                    mode = "cloud"; store.chatMode = "cloud"; ragMode = false
                },
                modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
            )
        }
        availableUpdate?.let { v ->
            dk.ternedal.modelrig.ui.chat.UpdateCard(
                newVersion = v,
                currentVersion = dk.ternedal.modelrig.BuildConfig.VERSION_NAME,
                downloading = updDownloading,
                progressPct = updProgress,
                onInstall = { startUpdateDownload() },
                onLater = {
                    store.dismissedUpdateVersion = v
                    availableUpdate = null
                },
                modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
            )
        }
        if (queued.isNotEmpty()) {
            dk.ternedal.modelrig.ui.chat.OfflineQueueCard(
                items = queued,
                nowMillis = System.currentTimeMillis(),
                rigBack = !rigOffline,
                onSend = { item ->
                    // Ét tryk = én besked. Vi tømmer ALDRIG køen i ét hug,
                    // og vi sender kun den du valgte.
                    queued = queueStore.remove(item)
                    input = item.text
                    onSend()
                },
                onEdit = { item ->
                    queued = queueStore.remove(item)
                    input = if (input.isBlank()) item.text else input + "\n" + item.text
                },
                onDiscard = { item -> queued = queueStore.remove(item) },
                modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
            )
        }
        sharePayload?.let { payload ->
            val isDoc = payload is dk.ternedal.modelrig.net.SharedPayload.Document
            val title = when (payload) {
                is dk.ternedal.modelrig.net.SharedPayload.Text -> payload.suggestedName
                is dk.ternedal.modelrig.net.SharedPayload.Document -> payload.suggestedName
            }
            val preview = when (payload) {
                is dk.ternedal.modelrig.net.SharedPayload.Text -> payload.text.take(300)
                is dk.ternedal.modelrig.net.SharedPayload.Document ->
                    payload.mimeType ?: "Filen læses først når du vælger noget"
            }
            dk.ternedal.modelrig.ui.chat.ShareLandingCard(
                title = title,
                preview = preview,
                isDocument = isDoc,
                truncated = sharedTruncated,
                rigAvailable = store.hasRig,
                busy = shareBusy,
                onDismiss = { sharePayload = null },
                onAsk = {
                    when (payload) {
                        is dk.ternedal.modelrig.net.SharedPayload.Text -> {
                            // Teksten lander i composeren — den sendes IKKE
                            // automatisk. Du skriver selv hvad du vil vide.
                            input = if (input.isBlank()) payload.text else input + "\n\n" + payload.text
                            sharePayload = null
                        }
                        is dk.ternedal.modelrig.net.SharedPayload.Document -> {
                            input = if (input.isBlank()) {
                                "Om dokumentet \u201c${payload.suggestedName}\u201d: "
                            } else {
                                input
                            }
                            sharePayload = null
                        }
                    }
                },
                onSaveToKnowledge = {
                    val base = store.baseUrl
                    val tok = store.token
                    if (base != null && tok != null) {
                        shareBusy = true
                        scope.launch {
                            val res = withContext(Dispatchers.IO) {
                                runCatching {
                                    val c = ModelRigClient(base, tok)
                                    when (payload) {
                                        is dk.ternedal.modelrig.net.SharedPayload.Text ->
                                            c.ingestText(payload.suggestedName, payload.text)
                                        is dk.ternedal.modelrig.net.SharedPayload.Document -> {
                                            // Samme veje som filvælgeren bruger — delt fil og
                                            // valgt fil skal indekseres ens, ellers får man to
                                            // forskellige korpusser af samme dokument.
                                            val u = android.net.Uri.parse(payload.uri)
                                            val bytes = context.contentResolver.openInputStream(u)?.use { it.readBytes() }
                                                ?: throw IllegalStateException("kunne ikke laese filen")
                                            val n = payload.suggestedName
                                            val mime = payload.mimeType.orEmpty().lowercase()
                                            when {
                                                mime.contains("pdf") -> c.ingestPdf(n, bytes)
                                                mime.contains("wordprocessingml") -> c.ingestDocx(n, bytes)
                                                mime.contains("presentationml") -> c.ingestPptx(n, bytes)
                                                mime.contains("html") -> c.ingestHtml(n, bytes)
                                                else -> c.ingestText(n, String(bytes, Charsets.UTF_8))
                                            }
                                        }
                                    }
                                }
                            }
                            shareBusy = false
                            res.onSuccess { r ->
                                sharePayload = null
                                // Rigens EGET tal, ikke vores forventning.
                                ingestStatus = "Gemt i Viden \u00b7 ${r.chunksAdded} udsnit"
                            }.onFailure {
                                ingestError = "Kunne ikke gemme i Viden."
                            }
                        }
                    }
                },
                modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
            )
        }
        agentPlanFor?.let { msg ->
            dk.ternedal.modelrig.ui.agent.AgentStartHost(
                baseUrl = store.baseUrl,
                token = store.token,
                conversationId = openConvId?.toString(),
                message = msg,
                // KILDEN er hele pointen: kun en eksplicit handling kommer hertil.
                source = dk.ternedal.modelrig.ui.agent.AgentStartPolicy.Source.ExplicitUserAction,
                onOpenApproval = { openAgentCheckpoint() },
                onDismiss = { agentPlanFor = null },
                modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
            )
        }
        // Agent-panelet (ADR-A3-001). Chatten kender ÉN neutral indgang og
        // ved ellers intet om agenten; alt hvad der taler med riggen bor i
        // ui/agent-pakken, og dvale-gaten haandhaever den arbejdsdeling.
        dk.ternedal.modelrig.ui.agent.AgentRunPanelHost(
            baseUrl = store.baseUrl,
            token = store.token,
            conversationId = openConvId?.toString(),
            onOpenCheckpoint = { openAgentCheckpoint() },
            modifier = Modifier.padding(horizontal = 15.dp, vertical = 6.dp),
        )
        // messages
        if (messages.isEmpty()) {
            Column(
                Modifier.weight(1f).fillMaxWidth(),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                // Tom-tilstanden 1:1 (skaerm 1). Tilstandsteksterne fra den gamle
                // velkomst baeres nu af routing-strippen + RAG-/Tools-chipsene.
                ChatEmptyState(
                    suggestions = listOf(
                        "Opsummér et dokument",
                        "Forklar en fejl i min kode",
                        "Udkast til en e-mail",
                    ),
                    onSuggestion = { input = it },
                )
            }
        } else {
            LazyColumn(
                state = listState,
                modifier = Modifier.weight(1f).fillMaxWidth()
                    .graphicsLayer { alpha = if (rigOffline) 0.45f else 1f },
                contentPadding = PaddingValues(horizontal = 12.dp, vertical = 10.dp),
            ) {
                itemsIndexed(messages) { i, m ->
                    if (m.role == "user") {
                        UserMessage(m.text)
                    } else {
                        val pills = buildList {
                            if (m.voiceModel != null) {
                                add((if (m.voiceViaCloud) "\u2601 " else "\u25c8 ") + "\ud83c\udf99 ${m.voiceModel}")
                            }
                            if (m.fellBackToCloud) add("\u2601 via cloud (rig utilg\u00e6ngelig)")
                        }
                        AssistantMessage(
                            m = ChatMessageUi(
                                isUser = false,
                                text = m.text,
                                streaming = m.streaming,
                                atMillis = m.at,
                                sources = m.sources,
                                error = m.error,
                                pills = pills,
                            ),
                            thinking = { ThinkingIndicator(m.status) },
                            body = { MarkdownText(m.text, color = KalivTheme.colors.textBody) },
                            onRetry = if (m.error) ({ retry(i) }) else null,
                        )
                        if (m.context.isNotEmpty() && !m.streaming) {
                            var showCitations by remember(m.at) { mutableStateOf(false) }
                            Text(
                                if (showCitations) "Skjul hvad der blev l\u00e6st"
                                else "Vis hvad der blev l\u00e6st (${m.context.size})",
                                color = KalivTheme.colors.textMuted,
                                fontSize = 13.sp,
                                modifier = Modifier
                                    .padding(start = 15.dp, top = 4.dp, bottom = 4.dp)
                                    .clickable { showCitations = !showCitations },
                            )
                            if (showCitations) {
                                dk.ternedal.modelrig.ui.chat.CitationsList(
                                    chunks = m.context,
                                    modifier = Modifier.padding(horizontal = 15.dp, vertical = 4.dp),
                                )
                            }
                        }
                    }
                }
            }
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
                voiceError?.takeIf { !recording && !voiceBusy }?.let { err ->
                    Text(
                        "Stemme-fejl: $err",
                        color = KalivTheme.colors.danger,
                        fontSize = 13.sp,
                        modifier = Modifier.padding(horizontal = 14.dp).padding(bottom = 6.dp),
                    )
                }
                modelError?.let {
                    Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp, modifier = Modifier.padding(bottom = 6.dp))
                }
                if (wasInterrupted && !voiceBusy && !recording) {
                    Text(
                        "Du afbrød Kaliv — tryk på mikrofonen for at sige noget",
                        color = KalivTheme.colors.textMuted, fontSize = 12.sp,
                        modifier = Modifier.padding(bottom = 6.dp),
                    )
                }
                val canSendNow = input.isNotBlank() || pendingImageB64 != null
                ChatComposer(
                    text = input,
                    placeholder = if (rigOffline) "Skriv — den lægges i kø" else "Skriv til Kaliv …",
                    onAttach = if (mode != "rig" || !ragMode) ({
                        if (!busy) {
                            pendingImageError = null
                            pickImage.launch(arrayOf("image/*"))
                        }
                    }) else null,
                    onMic = null,
                    micSlot = if (mode == "rig") ({
                        Box(
                            Modifier.size(37.dp).clickable(
                                // Stemme kraever riggen: ASR koerer rig-side, ogsaa
                                // naar svaret gaar via cloud (voiceConverseStream
                                // rammer altid store.baseUrl).
                                enabled = (!busy || voiceBusy) && !rigOffline,
                                onClickLabel = if (recording) "Stop optagelse" else "Optag tale",
                                role = Role.Button,
                                onClick = {
                                    // Al stemmeinteraktion bor i skaerm 6-overlayet;
                                    // mic-tap aabner det (og starter optagelsen naar
                                    // mikrofonen er givet). Under en igangvaerende
                                    // tur aabnes overlayet i Taenker/Taler-tilstand.
                                    voiceError = null
                                    showVoice = true
                                    if (!voiceBusy && !recording) {
                                        if (hasMicPermission) {
                                            wasInterrupted = false
                                            startVoiceCaptureGuarded()
                                        } else {
                                            micPermLauncher.launch(android.Manifest.permission.RECORD_AUDIO)
                                        }
                                    }
                                },
                            ),
                            contentAlignment = Alignment.Center,
                        ) {
                            if (voiceBusy) {
                                Box(
                                    Modifier.size(14.dp)
                                        .background(KalivTheme.colors.danger, RoundedCornerShape(3.dp)),
                                )
                            } else {
                                Icon(
                                    painterResource(R.drawable.ic_kaliv_mic),
                                    contentDescription = null,
                                    tint = if (recording) KalivTheme.colors.accent else KalivTheme.colors.textMuted,
                                    modifier = Modifier.size(22.dp),
                                )
                            }
                        }
                    }) else null,
                    onSend = {
                        if (rigOffline) {
                            // Riggen er væk: beskeden LÆGGES i kø. Den sendes
                            // først når du selv trykker Send nu bagefter —
                            // se OfflineQueueCard for hvorfor.
                            queued = queueStore.add(input, System.currentTimeMillis())
                            input = ""
                        } else {
                            onSend()
                        }
                    },
                    sendEnabled = canSendNow && !busy,
                    busy = busy,
                    onStop = { activeCall?.cancel() },
                    inputField = {
                        BasicTextField(
                            value = input,
                            onValueChange = { input = it },
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !busy,
                            maxLines = 5,
                            textStyle = TextStyle(
                                fontFamily = KalivType.Inter,
                                fontSize = 17.sp,
                                color = KalivTheme.colors.textHigh,
                            ),
                            cursorBrush = SolidColor(KalivTheme.colors.accent),
                            decorationBox = { inner ->
                                if (input.isEmpty()) {
                                    Text(
                                        // Skal spejle placeholder-param'en — den custom
                                        // inputField forbigaar ChatComposers default
                                        // (fund B fra Anders' screenshot 14/08).
                                        if (rigOffline) "Skriv — den lægges i kø" else "Skriv til Kaliv …",
                                        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 17.sp),
                                        color = KalivTheme.colors.faint,
                                    )
                                }
                                inner()
                            },
                        )
                    },
                )
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

    // -- Skaerm 7-hjaelpere: preview pr. samtale + tidsmaerker + grupper -----
    var previews by remember { mutableStateOf(mapOf<Long, String>()) }
    LaunchedEffect(convos) {
        val snap = convos
        val loaded = withContext(Dispatchers.IO) {
            snap.associate { meta ->
                val last = runCatching { db.loadMessages(meta.id).lastOrNull()?.second }.getOrNull()
                meta.id to (last?.let { dk.ternedal.modelrig.ui.chat.previewFromMarkdown(it).take(90) } ?: "")
            }
        }
        previews = loaded
    }
    fun timeLabel(ts: Long): String {
        val cal = java.util.Calendar.getInstance()
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0); cal.set(java.util.Calendar.MINUTE, 0)
        cal.set(java.util.Calendar.SECOND, 0); cal.set(java.util.Calendar.MILLISECOND, 0)
        val startOfToday = cal.timeInMillis
        return when {
            ts >= startOfToday -> SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(ts))
            ts >= startOfToday - 86_400_000L -> "i g\u00e5r"
            ts >= startOfToday - 6 * 86_400_000L ->
                SimpleDateFormat("EEE", Locale.getDefault()).format(Date(ts)).trimEnd('.')
            else -> fmt.format(Date(ts)).substringBefore(' ')
        }
    }
    fun rowOf(c: ChatDb.ConvMeta): dk.ternedal.modelrig.ui.chat.ConvRowUi =
        dk.ternedal.modelrig.ui.chat.ConvRowUi(
            id = c.id,
            title = c.title,
            preview = previews[c.id] ?: "",
            timeLabel = timeLabel(c.updatedAt),
            cloud = c.source == "cloud",
            active = c.id == activeConvId,
        )
    val startOfTodayMs = remember(convos) {
        val cal = java.util.Calendar.getInstance()
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0); cal.set(java.util.Calendar.MINUTE, 0)
        cal.set(java.util.Calendar.SECOND, 0); cal.set(java.util.Calendar.MILLISECOND, 0)
        cal.timeInMillis
    }
    var topMenu by remember { mutableStateOf(false) }
    var rowMenuFor by remember { mutableStateOf<Long?>(null) }

    Column(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        Column(
            Modifier.fillMaxWidth()
                .windowInsetsPadding(WindowInsets.statusBars)
                .padding(horizontal = 8.dp),
        ) {
            dk.ternedal.modelrig.ui.chat.ConversationsTopBar(
                onBack = onBack,
                onNew = onNew,
                onMenu = { topMenu = true },
                menuContent = {
                    DropdownMenu(expanded = topMenu, onDismissRequest = { topMenu = false }) {
                        DropdownMenuItem(
                            text = { Text("\u2b07 Eksport\u00e9r alt", fontSize = 13.sp) },
                            onClick = {
                                topMenu = false
                                val d = SimpleDateFormat("yyyy-MM-dd", Locale.getDefault()).format(java.util.Date())
                                exportLauncher.launch("kaliv-samtaler-$d.json")
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("\u2b06 Import\u00e9r", fontSize = 13.sp) },
                            onClick = { topMenu = false; importLauncher.launch(arrayOf("application/json")) },
                        )
                    }
                },
            )
            dk.ternedal.modelrig.ui.chat.ConversationsSearchField(
                query = query,
                onQuery = { query = it },
                modifier = Modifier.padding(horizontal = 7.dp),
            )
            ioStatus?.let {
                Text(
                    it,
                    color = if (it.startsWith("\u2713")) KalivTheme.colors.success
                    else if (it.endsWith("\u2026")) KalivTheme.colors.textMuted
                    else KalivTheme.colors.danger,
                    fontSize = 12.sp,
                    modifier = Modifier.padding(start = 9.dp, top = 6.dp),
                )
            }
            // Inline-omdoebning (aabnes fra raekkens langtryks-menu)
            renamingId?.let { rid ->
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 7.dp, vertical = 8.dp)
                        .background(KalivTheme.colors.surface, RoundedCornerShape(KalivTokens.Radius.card))
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.card))
                        .padding(horizontal = 12.dp, vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    androidx.compose.foundation.text.BasicTextField(
                        value = renameText, onValueChange = { renameText = it },
                        singleLine = true, modifier = Modifier.weight(1f),
                        textStyle = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, color = KalivTheme.colors.textHigh),
                        cursorBrush = SolidColor(KalivTheme.colors.accent),
                    )
                    TextButton(
                        enabled = renameText.isNotBlank(),
                        onClick = {
                            db.renameConversation(rid, renameText.trim())
                            convos = db.listConversations()
                            renamingId = null
                        },
                    ) { Text("Gem", color = if (renameText.isNotBlank()) KalivTheme.colors.signal else KalivTheme.colors.textMuted) }
                    TextButton(onClick = { renamingId = null }) { Text("\u2715", color = KalivTheme.colors.textMuted) }
                }
            }
        }
        if (visible.isEmpty()) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    if (convos.isEmpty()) "Ingen samtaler endnu" else "Ingen match p\u00e5 \"$query\"",
                    color = KalivTheme.colors.textMuted, fontSize = 14.sp,
                )
            }
        } else {
            dk.ternedal.modelrig.ui.chat.ConversationsList(
                today = visible.filter { it.updatedAt >= startOfTodayMs }.map { rowOf(it) },
                earlier = visible.filter { it.updatedAt < startOfTodayMs }.map { rowOf(it) },
                onOpen = { onOpen(it) },
                onLongPress = { rowMenuFor = it },
                modifier = Modifier.weight(1f).padding(horizontal = 15.dp),
                rowMenu = { id ->
                    DropdownMenu(expanded = rowMenuFor == id, onDismissRequest = { rowMenuFor = null }) {
                        DropdownMenuItem(
                            text = { Text("\u270e Omd\u00f8b", fontSize = 13.sp) },
                            onClick = {
                                rowMenuFor = null
                                val c = convos.firstOrNull { it.id == id } ?: return@DropdownMenuItem
                                renamingId = id; renameText = c.title
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Del", fontSize = 13.sp) },
                            onClick = {
                                rowMenuFor = null
                                val c = convos.firstOrNull { it.id == id } ?: return@DropdownMenuItem
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
                            },
                        )
                        DropdownMenuItem(
                            text = { Text("Slet", color = KalivTheme.colors.danger, fontSize = 13.sp) },
                            onClick = {
                                rowMenuFor = null
                                db.deleteConversation(id)
                                if (id == activeConvId) onActiveDeleted()
                                convos = db.listConversations()
                            },
                        )
                    }
                },
            )
        }
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
    var details by remember { mutableStateOf<List<ModelRigClient.RagSource>>(emptyList()) }
    val sources = details.map { it.name }
    var loading by remember { mutableStateOf(true) }
    var status by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var deleting by remember { mutableStateOf<ModelRigClient.RagSource?>(null) }

    fun refresh() {
        loading = true
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).listRagSourceDetails() }
            }
            loading = false
            details = r.getOrDefault(emptyList())
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
        Column(Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars).padding(horizontal = 8.dp)) {
            dk.ternedal.modelrig.ui.chat.ConversationsTopBar(
                title = "Viden",
                onBack = onBack,
                onNew = { pick.launch(arrayOf("*/*")) },
            )
            dk.ternedal.modelrig.ui.chat.KnowledgeIntroNote(Modifier.padding(bottom = 15.dp))
        }
        status?.let {
            Text(it, color = KalivTheme.colors.signal, fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        }
        error?.let {
            Text(it, color = KalivTheme.colors.danger, fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        }
        when {
            loading -> Text("Henter\u2026", color = KalivTheme.colors.textMuted, fontSize = 16.sp,
                modifier = Modifier.padding(20.dp))
            sources.isEmpty() -> Column(Modifier.weight(1f).fillMaxWidth().padding(32.dp),
                horizontalAlignment = Alignment.CenterHorizontally) {
                Text("Ingen dokumenter endnu.", color = KalivTheme.colors.textHigh, fontSize = 16.sp)
                Spacer(Modifier.height(6.dp))
                Text("Tilf\u00f8j PDF, DOCX, PPTX, HTML eller tekst, s\u00e5 kan Kaliv tr\u00e6kke p\u00e5 dem.",
                    color = KalivTheme.colors.textMuted, fontSize = 16.sp,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center)
                Spacer(Modifier.height(20.dp))
                dk.ternedal.modelrig.ui.chat.KnowledgeList(
                    docs = emptyList(),
                    onAdd = { pick.launch(arrayOf("*/*")) },
                )
            }
            else -> dk.ternedal.modelrig.ui.chat.KnowledgeList(
                docs = details.map {
                    dk.ternedal.modelrig.ui.chat.KnowledgeDocUi(
                        name = it.name,
                        badge = dk.ternedal.modelrig.ui.chat.knowledgeBadgeFor(it.name),
                        statsLine = dk.ternedal.modelrig.ui.chat.knowledgeStatsLine(it.chunks, it.lastIngestedAt),
                        enabled = it.enabled,
                    )
                },
                onAdd = { pick.launch(arrayOf("*/*")) },
                onDelete = { doc -> deleting = details.firstOrNull { it.name == doc.name } },
                onToggle = { doc, want ->
                    val base = store.baseUrl
                    val tok = store.token
                    if (base != null && tok != null) {
                        scope.launch {
                            val res = withContext(Dispatchers.IO) {
                                runCatching { ModelRigClient(base, tok).setRagSourceEnabled(doc.name, want) }
                            }
                            res.onSuccess { actual ->
                                // RIGGENS svar vinder — ikke det vi håbede på.
                                details = details.map { d ->
                                    if (d.name == doc.name) d.copy(enabled = actual) else d
                                }
                                status = if (actual) "\u201c${doc.name}\u201d bruges igen"
                                         else "\u201c${doc.name}\u201d bruges ikke l\u00e6ngere \u2014 teksten er der stadig"
                            }.onFailure { error = "Kunne ikke \u00e6ndre kilden." }
                        }
                    }
                },
                modifier = Modifier.weight(1f).padding(horizontal = 17.dp),
            )
        }
        deleting?.let { target ->
            dk.ternedal.modelrig.ui.chat.KnowledgeDeleteConfirm(
                name = target.name,
                chunks = target.chunks,
                busy = loading,
                onConfirm = {
                    scope.launch {
                        val r = withContext(Dispatchers.IO) {
                            runCatching {
                                ModelRigClient(store.baseUrl ?: "", store.token).deleteRagSource(target.name)
                            }
                        }
                        deleting = null
                        r.onSuccess { removed ->
                            status = "Fjernet \u00b7 $removed udsnit slettet"
                            error = null
                            refresh()
                        }.onFailure { error = friendlyError(it) }
                    }
                },
                onCancel = { deleting = null },
                modifier = Modifier.padding(horizontal = 17.dp, vertical = 8.dp),
            )
        }
        if (details.isNotEmpty()) {
            dk.ternedal.modelrig.ui.chat.KnowledgeCorpusFooter(
                sourceCount = details.size,
                chunkCount = details.sumOf { it.chunks },
                modifier = Modifier.padding(horizontal = 17.dp, vertical = 6.dp),
            )
        }
        dk.ternedal.modelrig.ui.chat.KnowledgeFooterNote(
            Modifier.padding(horizontal = 17.dp, vertical = 10.dp),
        )
    }
}


@Composable
private fun AuditScreen(store: TokenStore, onBack: () -> Unit) {
    val scope = rememberCoroutineScope()
    var rows by remember { mutableStateOf<List<dk.ternedal.modelrig.net.AuditEntry>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var filter by remember { mutableStateOf<String?>(null) }  // null = alle
    var filterMenu by remember { mutableStateOf(false) }

    fun refresh() {
        loading = true; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { ModelRigClient(store.baseUrl ?: "", store.token).toolsAudit(100) }
            }
            rows = r.getOrDefault(emptyList())
            error = r.exceptionOrNull()?.let { friendlyError(it) }
            loading = false
        }
    }
    LaunchedEffect(Unit) { refresh() }

    fun parseTs(ts: String): Long =
        runCatching { java.time.OffsetDateTime.parse(ts).toInstant().toEpochMilli() }
            .getOrElse {
                runCatching {
                    java.time.LocalDateTime.parse(ts.replace(" ", "T"))
                        .atZone(java.time.ZoneId.systemDefault()).toInstant().toEpochMilli()
                }.getOrElse { 0L }
            }
    fun badgeFor(outcome: String): Pair<String, dk.ternedal.modelrig.ui.chat.AuditBadgeKind> = when (outcome) {
        "executed" -> "Udf\u00f8rt" to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Ok
        "denied" -> "Afvist" to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Warn
        "blocked" -> "Blokeret" to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Warn
        "expired" -> "Udl\u00f8bet" to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Warn
        "error" -> "Fejl" to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Error
        else -> outcome to dk.ternedal.modelrig.ui.chat.AuditBadgeKind.Neutral
    }
    fun rowOf(e: dk.ternedal.modelrig.net.AuditEntry): dk.ternedal.modelrig.ui.chat.AuditRowUi {
        val ms = parseTs(e.ts)
        val time = if (ms > 0L) SimpleDateFormat("HH:mm", Locale.getDefault()).format(Date(ms)) else e.ts
        val (b, k) = badgeFor(e.outcome)
        return dk.ternedal.modelrig.ui.chat.AuditRowUi(
            title = e.summary.ifBlank { e.tool },
            sub = buildString {
                append("V\u00e6rkt\u00f8j: ${e.tool} \u00b7 $time")
                if (e.risk.isNotBlank()) append(" \u00b7 ${e.risk}")
            },
            badge = b,
            kind = k,
            cloud = e.origin == "cloud",
            tool = e.tool,
        )
    }

    val startOfToday = remember {
        val cal = java.util.Calendar.getInstance()
        cal.set(java.util.Calendar.HOUR_OF_DAY, 0); cal.set(java.util.Calendar.MINUTE, 0)
        cal.set(java.util.Calendar.SECOND, 0); cal.set(java.util.Calendar.MILLISECOND, 0)
        cal.timeInMillis
    }
    val visible = rows.filter { e ->
        when (filter) {
            "ok" -> e.outcome == "executed"
            "warn" -> e.outcome in setOf("denied", "blocked", "expired")
            "error" -> e.outcome == "error"
            else -> true
        }
    }

    Column(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        Column(Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars).padding(horizontal = 8.dp)) {
            dk.ternedal.modelrig.ui.chat.ConversationsTopBar(
                title = "Handlingslog",
                onBack = onBack,
                onMenu = { filterMenu = true },
                menuIcon = R.drawable.ic_kaliv_filter,
                menuContent = {
                    DropdownMenu(expanded = filterMenu, onDismissRequest = { filterMenu = false }) {
                        listOf(
                            null to "Alle",
                            "ok" to "Udf\u00f8rt",
                            "warn" to "Afvist / blokeret / udl\u00f8bet",
                            "error" to "Fejl",
                        ).forEach { (key, label) ->
                            DropdownMenuItem(
                                text = { Text(if (filter == key) "\u2713 $label" else label, fontSize = 13.sp) },
                                onClick = { filter = key; filterMenu = false },
                            )
                        }
                    }
                },
            )
            dk.ternedal.modelrig.ui.chat.KnowledgeIntroNote(
                Modifier.padding(bottom = 13.dp),
                text = "Alt hvad v\u00e6rkt\u00f8jer og agent udf\u00f8rer, logges her. Kun p\u00e5 din rig.",
            )
        }
        error?.let {
            Text(it, color = KalivTheme.colors.danger, fontSize = 14.sp,
                modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        }
        when {
            loading -> Text("Henter\u2026", color = KalivTheme.colors.textMuted, fontSize = 16.sp,
                modifier = Modifier.padding(20.dp))
            visible.isEmpty() -> Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text(
                    if (rows.isEmpty()) "Ingen handlinger registreret endnu"
                    else "Ingen handlinger matcher filtret",
                    color = KalivTheme.colors.textMuted, fontSize = 14.sp,
                )
            }
            else -> dk.ternedal.modelrig.ui.chat.AuditGroupedList(
                today = visible.filter { parseTs(it.ts) >= startOfToday }.map { rowOf(it) },
                earlier = visible.filter { parseTs(it.ts) < startOfToday }.map { rowOf(it) },
                modifier = Modifier.weight(1f).padding(horizontal = 20.dp),
            )
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
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

    var pullDone by remember { mutableStateOf(0L) }
    var pullTotal by remember { mutableStateOf(0L) }
    var showPull by remember { mutableStateOf(false) }
    var rowMenuFor by remember { mutableStateOf<String?>(null) }

    Column(Modifier.fillMaxSize().background(KalivTheme.colors.background)) {
        Column(Modifier.fillMaxWidth().windowInsetsPadding(WindowInsets.statusBars).padding(horizontal = 8.dp)) {
            dk.ternedal.modelrig.ui.chat.ConversationsTopBar(
                title = "Modeller",
                onBack = onBack,
                onNew = { showPull = true },
            )
            val vramInUse = running.sumOf { it.sizeVramBytes }
            dk.ternedal.modelrig.ui.chat.ModelsVramLine(
                text = if (vramInUse > 0)
                    "Din rig \u00b7 %.1f GB VRAM i brug".format(vramInUse / 1_000_000_000.0)
                else "Din rig \u00b7 ingen modeller i hukommelsen",
                onReload = { refresh() },
                modifier = Modifier.padding(bottom = 13.dp),
            )
        }

        if (!store.hasRig) {
            Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                Text("Kr\u00e6ver rig-forbindelse", color = KalivTheme.colors.textMuted, fontSize = 14.sp)
            }
        } else {
            loadError?.let {
                Text("Fejl: ${friendlyError(it)}", color = KalivTheme.colors.danger, fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
            }
            pullError?.let {
                Text("Fejl: ${friendlyError(it)}", color = KalivTheme.colors.danger, fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
            }
            pullStatus?.let {
                if (!pulling) Text(it, color = KalivTheme.colors.signal, fontSize = 13.sp,
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
            }
            if (showPull && !pulling) {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 17.dp, vertical = 6.dp)
                        .background(KalivTheme.colors.surface, RoundedCornerShape(KalivTokens.Radius.card))
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.card))
                        .padding(horizontal = 15.dp, vertical = 8.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    BasicTextField(
                        value = pullName, onValueChange = { pullName = it },
                        singleLine = true, modifier = Modifier.weight(1f),
                        textStyle = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, color = KalivTheme.colors.textHigh),
                        cursorBrush = SolidColor(KalivTheme.colors.accent),
                        decorationBox = { inner ->
                            if (pullName.isEmpty()) Text("fx llama3.2:3b",
                                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp),
                                color = KalivTheme.colors.faint)
                            inner()
                        },
                    )
                    TextButton(
                        enabled = pullName.isNotBlank(),
                        onClick = {
                            val name = pullName.trim()
                            pulling = true; pullError = null; pullStatus = null
                            pullDone = 0L; pullTotal = 0L
                            scope.launch {
                                val err = withContext(Dispatchers.IO) {
                                    runCatching {
                                        client.pullModel(name) { _, completed, total ->
                                            scope.launch { pullDone = completed; pullTotal = total }
                                        }
                                    }.exceptionOrNull()
                                }
                                pulling = false
                                if (err != null) { pullError = err.message }
                                else {
                                    pullStatus = "F\u00e6rdig og verificeret: $name"
                                    pullName = ""; showPull = false
                                    refresh()
                                }
                            }
                        },
                    ) { Text("Hent", color = if (pullName.isNotBlank()) KalivTheme.colors.signal else KalivTheme.colors.textMuted) }
                }
            }
            androidx.compose.foundation.lazy.LazyColumn(
                Modifier.weight(1f).padding(horizontal = 17.dp),
                verticalArrangement = Arrangement.spacedBy(11.dp),
            ) {
                if (pulling) {
                    item {
                        dk.ternedal.modelrig.ui.chat.PullProgressCard(
                            name = pullName.trim().ifEmpty { "model" },
                            progressText = if (pullTotal > 0)
                                "Henter \u00b7 %.1f af %.1f GB".format(pullDone / 1e9, pullTotal / 1e9)
                            else "Henter \u2026",
                            fraction = if (pullTotal > 0) pullDone.toFloat() / pullTotal else 0f,
                        )
                    }
                }
                items(installed.size, key = { installed[it].name }) { i ->
                    val m = installed[i]
                    val loadedVram = running.firstOrNull { it.name == m.name }?.sizeVramBytes
                    androidx.compose.foundation.layout.Box {
                        dk.ternedal.modelrig.ui.chat.InstalledModelCard(
                            m = dk.ternedal.modelrig.ui.chat.InstalledModelUi(
                                name = m.name,
                                standard = m.name == store.model,
                                loaded = loadedVram != null,
                                metaLabel = buildString {
                                    append("%.1f GB".format(m.sizeBytes / 1e9))
                                    val p = dk.ternedal.modelrig.ui.chat.paramsLabelFor(m.name)
                                    if (p.isNotEmpty()) append(" \u00b7 $p")
                                    if (loadedVram != null) append(" \u00b7 %.1f GB VRAM".format(loadedVram / 1e9))
                                },
                            ),
                            onLongPress = { rowMenuFor = m.name },
                        )
                        DropdownMenu(expanded = rowMenuFor == m.name, onDismissRequest = { rowMenuFor = null }) {
                            if (m.name != store.model) {
                                DropdownMenuItem(
                                    text = { Text("S\u00e6t som standard", fontSize = 13.sp) },
                                    onClick = { rowMenuFor = null; store.model = m.name },
                                )
                            }
                            DropdownMenuItem(
                                text = { Text("Slet", color = KalivTheme.colors.danger, fontSize = 13.sp) },
                                onClick = { rowMenuFor = null; confirmDelete = m.name },
                            )
                        }
                    }
                }
                item {
                    dk.ternedal.modelrig.ui.chat.KalivOutlineActionCard("Hent ny model", { showPull = true })
                }
            }
        }
        Spacer(Modifier.windowInsetsPadding(WindowInsets.navigationBars))
    }

    confirmDelete?.let { name ->
        AlertDialog(
            onDismissRequest = { confirmDelete = null },
            title = { Text("Slet $name?") },
            text = { Text("Dette kan ikke fortrydes \u2014 modellen skal hentes igen for at bruges.", fontSize = 13.sp) },
            confirmButton = {
                TextButton(onClick = {
                    confirmDelete = null
                    scope.launch {
                        val err = withContext(Dispatchers.IO) { runCatching { client.deleteModel(name) }.exceptionOrNull() }
                        if (err == null) refresh() else loadError = err.message
                    }
                }) { Text("Slet", color = KalivTheme.colors.danger) }
            },
            dismissButton = { TextButton(onClick = { confirmDelete = null }) { Text("Annull\u00e9r", color = KalivTheme.colors.textMuted) } },
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

// The Kaliv "thinking" animation -- shown in the assistant bubble while the
// reply is still empty (the moment before the first streamed token), the same
// place Claude shows its thinking indicator. The asset is an animated WebP;
// Compose's painterResource would only draw the first (static) frame, so we
// play it via AnimatedImageDrawable in a tiny ImageView. That API is 28+, so on
// API 26-27 we fall back to the plain ellipsis rather than crash.
@Composable
private fun ThinkingIndicator(status: String = TurnStatus.THINKING) {
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
        Text(status, color = KalivTheme.colors.textMuted, fontSize = 15.sp, lineHeight = 21.sp)
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

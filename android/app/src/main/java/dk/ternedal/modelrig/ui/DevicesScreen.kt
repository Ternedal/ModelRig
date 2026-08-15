package dk.ternedal.modelrig.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.ui.chat.ConversationsTopBar
import dk.ternedal.modelrig.ui.chat.DeviceRevokeConfirm
import dk.ternedal.modelrig.ui.chat.DeviceRow
import dk.ternedal.modelrig.ui.chat.DeviceRowUi
import dk.ternedal.modelrig.ui.chat.DevicesUnknownSelfNote
import dk.ternedal.modelrig.ui.chat.KnowledgeIntroNote
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

/**
 * Enheder — hvem har adgang til riggen, og fjernelse af adgang.
 * Ingen mockup findes; skærmen er tegnet i systemets eget sprog.
 *
 * Fjernelse er ægte og øjeblikkelig: riggen slår enheden op i sit
 * live-lager ved hvert kald. Derfor er hver fjernelse bag et
 * bekræftelseskort, og fjerner man DENNE telefon, siger kortet det rent ud.
 */
@Composable
fun DevicesScreen(store: TokenStore, onBack: () -> Unit, onSelfRevoked: () -> Unit) {
    val scope = rememberCoroutineScope()
    var devices by remember { mutableStateOf<List<ModelRigClient.PairedDevice>>(emptyList()) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirming by remember { mutableStateOf<ModelRigClient.PairedDevice?>(null) }
    var busy by remember { mutableStateOf(false) }

    fun client(): ModelRigClient? {
        val base = store.baseUrl
        return if (base.isNullOrEmpty()) null else ModelRigClient(base, store.token)
    }

    fun load() {
        val c = client() ?: run { error = "Ingen rig parret."; return }
        loading = true
        scope.launch {
            val res = withContext(Dispatchers.IO) { runCatching { c.listDevices() } }
            res.onSuccess { devices = it; error = null }
                .onFailure { error = it.message ?: "Kunne ikke hente enheder" }
            loading = false
        }
    }

    LaunchedEffect(Unit) { load() }

    Column(
        Modifier
            .fillMaxSize()
            .background(KalivTheme.colors.background)
            .kalivScreenInsets()
            .verticalScroll(rememberScrollState()),
    ) {
        ConversationsTopBar(
            title = "Enheder",
            onBack = onBack,
            onMenu = { load() },
            menuIcon = R.drawable.ic_kaliv_retry,
        )
        KnowledgeIntroNote(
            Modifier.padding(bottom = 13.dp),
            text = "Enheder der er parret med din rig. Fjernes en enhed, holder dens adgang op med at virke med det samme.",
        )
        Column(Modifier.padding(horizontal = 15.dp)) {
            val myId = store.deviceId
            if (devices.isNotEmpty() && myId == null) {
                DevicesUnknownSelfNote()
                Spacer(Modifier.height(11.dp))
            }
            confirming?.let { target ->
                DeviceRevokeConfirm(
                    deviceName = target.name,
                    isThisDevice = myId != null && target.id == myId,
                    busy = busy,
                    onConfirm = {
                        val c = client() ?: return@DeviceRevokeConfirm
                        busy = true
                        scope.launch {
                            val res = withContext(Dispatchers.IO) { runCatching { c.revokeDevice(target.id) } }
                            busy = false
                            res.onSuccess {
                                confirming = null
                                if (myId != null && target.id == myId) {
                                    onSelfRevoked()
                                } else {
                                    load()
                                }
                            }.onFailure { error = it.message ?: "Fjernelsen fejlede" }
                        }
                    },
                    onCancel = { confirming = null },
                )
                Spacer(Modifier.height(11.dp))
            }
            error?.let {
                Text(
                    it,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.danger,
                    modifier = Modifier.padding(bottom = 11.dp),
                )
            }
            if (devices.isEmpty() && !loading && error == null) {
                Text(
                    "Ingen parrede enheder.",
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
            devices.forEach { d ->
                DeviceRow(
                    ui = DeviceRowUi(
                        id = d.id,
                        name = d.name,
                        pairedLabel = "Parret " + formatStamp(d.createdAt),
                        lastSeenLabel = "Sidst set " + formatStamp(d.lastSeen),
                        isThisDevice = myId != null && d.id == myId,
                    ),
                    busy = busy,
                    onRevoke = { confirming = d },
                )
                Spacer(Modifier.height(11.dp))
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

/** ISO-8601 fra riggen → dansk dato/tid; ukendt format vises ikke som pynt. */
internal fun formatStamp(raw: String?): String {
    if (raw.isNullOrBlank()) return "ukendt"
    val cleaned = raw.substringBefore('.').removeSuffix("Z")
    val parser = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss", Locale.US)
    parser.timeZone = TimeZone.getTimeZone("UTC")
    val parsed = runCatching { parser.parse(cleaned) }.getOrNull() ?: return "ukendt"
    return SimpleDateFormat("d/M yyyy HH:mm", Locale("da", "DK")).format(parsed)
}

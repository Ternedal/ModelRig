package dk.ternedal.modelrig.ui

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.ModelRigClient
import dk.ternedal.modelrig.net.ScheduleClient
import dk.ternedal.modelrig.net.ScheduleItem
import dk.ternedal.modelrig.net.SchedulePreview
import dk.ternedal.modelrig.net.ScheduleRuntimeStatus
import dk.ternedal.modelrig.net.ToolInfo
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Human-only schedule administration.
 *
 * The screen never asks a model to create a plan. Every create and renewal is
 * previewed first, and changing any term clears the preview token. There is no
 * delete action: pause is reversible, deletion is deliberately absent from the
 * worker API, and the client does not invent one.
 */
@Composable
fun ScheduleScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var runtime by remember { mutableStateOf<ScheduleRuntimeStatus?>(null) }
    var schedules by remember { mutableStateOf<List<ScheduleItem>>(emptyList()) }
    var tools by remember { mutableStateOf<List<ToolInfo>>(emptyList()) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var notice by remember { mutableStateOf<String?>(null) }

    var tool by remember { mutableStateOf("current_datetime") }
    var argsJson by remember { mutableStateOf("{}") }
    var cadence by remember { mutableStateOf("daily:08:00") }
    var timezone by remember { mutableStateOf(ScheduleClient.DEFAULT_TIMEZONE) }
    var ttlDays by remember { mutableStateOf("90") }
    var maxRuns by remember { mutableStateOf("0") }
    var preview by remember { mutableStateOf<SchedulePreview?>(null) }

    var renewalTarget by remember { mutableStateOf<ScheduleItem?>(null) }
    var renewalTtl by remember { mutableStateOf("90") }
    var renewalMaxRuns by remember { mutableStateOf("0") }
    var renewalMode by remember { mutableStateOf("preserve") }
    var renewalPreview by remember { mutableStateOf<SchedulePreview?>(null) }

    fun client(): ScheduleClient {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return ScheduleClient(base, token)
    }

    fun <T> execute(action: () -> T, success: (T) -> Unit, fallback: String) {
        if (busy) return
        busy = true
        error = null
        notice = null
        scope.launch {
            val result = withContext(Dispatchers.IO) { runCatching(action) }
            busy = false
            result.onSuccess(success).onFailure { error = friendlyScheduleError(it.message ?: fallback) }
        }
    }

    fun load() {
        execute(
            action = {
                val api = client()
                Triple(
                    api.status(),
                    api.list(),
                    ModelRigClient(store.baseUrl ?: "", store.token).toolsList().tools,
                )
            },
            success = {
                runtime = it.first
                schedules = it.second
                tools = it.third.filter { info -> info.risk == "read" || info.risk == "write" }
                if (tools.none { info -> info.name == tool }) {
                    tool = tools.firstOrNull()?.name ?: tool
                }
                notice = "${schedules.size} planer hentet. Ingen handling er kørt."
            },
            fallback = "Planer kunne ikke hentes",
        )
    }

    fun clearCreatePreview() {
        preview = null
        notice = null
    }

    fun previewCreate() {
        val ttl = ttlDays.toIntOrNull()
        val runs = maxRuns.toIntOrNull()
        if (ttl == null || runs == null) {
            error = "TTL og kørselsbudget skal være hele tal."
            return
        }
        val args = runCatching { JSONObject(argsJson) }.getOrElse {
            error = "Argumenter skal være ét gyldigt JSON-objekt, fx {\"text\":\"Husk brygdag\"}."
            return
        }
        execute(
            action = {
                client().preview(
                    tool = tool.trim(),
                    args = args,
                    cadence = cadence.trim(),
                    ttlDays = ttl,
                    maxRuns = runs,
                    timezone = timezone.trim(),
                    misfirePolicy = ScheduleClient.RUN_ONCE_MISFIRE_POLICY,
                )
            },
            success = {
                preview = it
                notice = "Preview klar. Læs hele stående tilladelse før du opretter."
            },
            fallback = "Preview kunne ikke oprettes",
        )
    }

    fun createFromPreview() {
        val approved = preview ?: return
        execute(
            action = { client().create(approved) },
            success = {
                schedules = listOf(it) + schedules.filterNot { row -> row.id == it.id }
                preview = null
                notice = "Planen er gemt. Der er ikke kørt noget nu."
            },
            fallback = "Planen kunne ikke oprettes",
        )
    }

    fun toggle(schedule: ScheduleItem) {
        execute(
            action = { client().setEnabled(schedule.id, !schedule.enabled) },
            success = {
                schedules = schedules.map { row -> if (row.id == it.id) it else row }
                notice = if (it.enabled) "Planen er genoptaget fra næste fremtidige tidspunkt." else "Planen er sat på pause."
            },
            fallback = "Planens tilstand kunne ikke ændres",
        )
    }

    fun beginRenewal(schedule: ScheduleItem) {
        renewalTarget = schedule
        renewalTtl = "90"
        renewalMaxRuns = schedule.maxRuns.toString()
        renewalMode = if (schedule.enabled) "preserve" else "pause"
        renewalPreview = null
        error = null
        notice = "Fornyelse kræver et nyt preview — den gamle godkendelse genbruges ikke."
    }

    fun clearRenewalPreview() {
        renewalPreview = null
        notice = null
    }

    fun previewRenewal() {
        val target = renewalTarget ?: return
        val ttl = renewalTtl.toIntOrNull()
        val runs = renewalMaxRuns.toIntOrNull()
        if (ttl == null || runs == null) {
            error = "TTL og kørselsbudget skal være hele tal."
            return
        }
        val enable = when (renewalMode) {
            "enable" -> true
            "pause" -> false
            else -> null
        }
        execute(
            action = { client().previewRenewal(target.id, ttl, runs, enable) },
            success = {
                renewalPreview = it
                notice = "Nyt renewal-preview klar. Kontrollér vilkårene før godkendelse."
            },
            fallback = "Fornyelsen kunne ikke previewes",
        )
    }

    fun renewFromPreview() {
        val approved = renewalPreview ?: return
        execute(
            action = { client().renew(approved) },
            success = {
                schedules = schedules.map { row -> if (row.id == it.id) it else row }
                renewalTarget = null
                renewalPreview = null
                notice = "Planens udløb og budget er fornyet."
            },
            fallback = "Planen kunne ikke fornyes",
        )
    }

    LaunchedEffect(Unit) { load() }

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 18.dp, vertical = 14.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Planer", fontSize = 28.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Text(
                        "Menneskestyret scheduler · intet modelværktøj",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(12.dp))
            ScheduleCard {
                Text("Scheduler-status", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                val state = runtime
                when {
                    state == null -> Text("Henter status…", color = KalivTheme.colors.textMuted)
                    state.running -> Text("Kører", color = KalivTheme.colors.signal, fontWeight = FontWeight.Bold)
                    state.configured -> Text("Konfigureret, men ikke startet", color = KalivTheme.colors.danger)
                    else -> Text("Slået fra på riggen", color = KalivTheme.colors.textMuted)
                }
                Text(
                    if (state?.running == true) "Nye planer kan blive kørt ved næste forfald."
                    else "Planer kan gemmes, men kører ikke før KALIV_SCHEDULER=1 og workeren er genstartet.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                state?.lastError?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 11.sp) }
                Spacer(Modifier.height(6.dp))
                OutlinedButton(enabled = !busy, onClick = ::load) { Text("Genindlæs") }
            }

            Spacer(Modifier.height(12.dp))
            ScheduleCard {
                Text("Opret plan", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Text(
                    "Du skal først previewe handling, kadence, timezone, udløb og budget.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(8.dp))
                if (tools.isNotEmpty()) {
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                        tools.forEach { info ->
                            FilterChip(
                                selected = tool == info.name,
                                onClick = { tool = info.name; clearCreatePreview() },
                                label = { Text(info.name, fontSize = 11.sp) },
                                modifier = Modifier.padding(end = 6.dp),
                            )
                        }
                    }
                }
                OutlinedTextField(
                    value = tool,
                    onValueChange = { tool = it; clearCreatePreview() },
                    label = { Text("Tool") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = argsJson,
                    onValueChange = { argsJson = it; clearCreatePreview() },
                    label = { Text("Argumenter som JSON") },
                    supportingText = { Text("Eksempel: {\"text\":\"Husk brygdag\"}") },
                    minLines = 2,
                    maxLines = 6,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = cadence,
                    onValueChange = { cadence = it; clearCreatePreview() },
                    label = { Text("Kadence") },
                    supportingText = { Text("every:3600 eller daily:08:00") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                OutlinedTextField(
                    value = timezone,
                    onValueChange = { timezone = it; clearCreatePreview() },
                    label = { Text("Timezone") },
                    supportingText = {
                        Text("IANA-zone, fx Europe/Copenhagen. Misfire: kør én gang; ældre forfald registreres som missed.")
                    },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(7.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    OutlinedTextField(
                        value = ttlDays,
                        onValueChange = { ttlDays = it.filter(Char::isDigit); clearCreatePreview() },
                        label = { Text("TTL, dage") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                    OutlinedTextField(
                        value = maxRuns,
                        onValueChange = { maxRuns = it.filter(Char::isDigit); clearCreatePreview() },
                        label = { Text("Max kørsler") },
                        supportingText = { Text("0 = kun TTL") },
                        singleLine = true,
                        modifier = Modifier.weight(1f),
                    )
                }
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && tool.isNotBlank() && cadence.isNotBlank() && timezone.isNotBlank() && ttlDays.isNotBlank() && maxRuns.isNotBlank(),
                    onClick = ::previewCreate,
                ) { Text(if (busy) "Arbejder…" else "Forhåndsvis") }
            }

            preview?.let { approved ->
                Spacer(Modifier.height(12.dp))
                ApprovalCard(
                    title = "Godkend ny stående tilladelse",
                    preview = approved,
                    confirmLabel = if (approved.requiresApproval) "Godkend og opret" else "Opret plan",
                    busy = busy,
                    onCancel = { preview = null },
                    onConfirm = ::createFromPreview,
                )
            }

            renewalTarget?.let { target ->
                Spacer(Modifier.height(12.dp))
                ScheduleCard {
                    Text("Forny ${target.tool}", fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                    Text("Plan ${target.id} · argumenterne kan ikke ændres ved renewal.", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    Spacer(Modifier.height(7.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        OutlinedTextField(
                            value = renewalTtl,
                            onValueChange = { renewalTtl = it.filter(Char::isDigit); clearRenewalPreview() },
                            label = { Text("Ny TTL") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                        OutlinedTextField(
                            value = renewalMaxRuns,
                            onValueChange = { renewalMaxRuns = it.filter(Char::isDigit); clearRenewalPreview() },
                            label = { Text("Nyt budget") },
                            singleLine = true,
                            modifier = Modifier.weight(1f),
                        )
                    }
                    Spacer(Modifier.height(7.dp))
                    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState())) {
                        listOf(
                            "preserve" to "Bevar tilstand",
                            "enable" to "Forny og aktivér",
                            "pause" to "Forny på pause",
                        ).forEach { (value, label) ->
                            FilterChip(
                                selected = renewalMode == value,
                                onClick = { renewalMode = value; clearRenewalPreview() },
                                label = { Text(label, fontSize = 11.sp) },
                                modifier = Modifier.padding(end = 6.dp),
                            )
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(enabled = !busy, onClick = ::previewRenewal) { Text("Preview renewal") }
                        TextButton(onClick = { renewalTarget = null; renewalPreview = null }) { Text("Annullér") }
                    }
                }
            }

            renewalPreview?.let { approved ->
                Spacer(Modifier.height(12.dp))
                ApprovalCard(
                    title = "Godkend fornyet stående tilladelse",
                    preview = approved,
                    confirmLabel = "Godkend renewal",
                    busy = busy,
                    onCancel = { renewalPreview = null },
                    onConfirm = ::renewFromPreview,
                )
            }

            error?.let {
                Spacer(Modifier.height(10.dp))
                Text(it, color = KalivTheme.colors.danger, fontSize = 12.sp)
            }
            notice?.let {
                Spacer(Modifier.height(10.dp))
                Text(it, color = KalivTheme.colors.signal, fontSize = 12.sp)
            }

            Spacer(Modifier.height(18.dp))
            Text("Gemte planer", fontSize = 20.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
            Text("Der findes bevidst ingen slet-knap. Pause stopper fremtidige claims.", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
            Spacer(Modifier.height(8.dp))
            if (schedules.isEmpty()) {
                Text("Ingen planer endnu.", color = KalivTheme.colors.textMuted)
            }
            schedules.forEach { schedule ->
                ScheduleRow(
                    schedule = schedule,
                    busy = busy,
                    onToggle = { toggle(schedule) },
                    onRenew = { beginRenewal(schedule) },
                )
                Spacer(Modifier.height(9.dp))
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ScheduleRow(
    schedule: ScheduleItem,
    busy: Boolean,
    onToggle: () -> Unit,
    onRenew: () -> Unit,
) {
    ScheduleCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(schedule.tool, fontWeight = FontWeight.SemiBold, color = KalivTheme.colors.textHigh)
                Text(schedule.id, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            val label = when {
                schedule.eligible -> "klar"
                schedule.enabled -> "blokeret"
                else -> "pause"
            }
            Text(
                label,
                color = if (schedule.eligible) KalivTheme.colors.signal else if (schedule.enabled) KalivTheme.colors.danger else KalivTheme.colors.textMuted,
                fontSize = 12.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Spacer(Modifier.height(6.dp))
        Text(schedule.argsJson, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text("Kadence: ${schedule.cadence}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text("Timezone: ${schedule.timezone}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text("Misfire: ${scheduleMisfireLabel(schedule.misfirePolicy)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text("Næste: ${authoritativeScheduleTime(schedule.dueAtLocal, schedule.timezone)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text("Udløb: ${formatEpoch(schedule.expiresAt)}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(
            "Kørsler: ${schedule.runsUsed}/${if (schedule.maxRuns == 0) "∞ (TTL)" else schedule.maxRuns}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        schedule.blockedReason?.let { Text(it, color = KalivTheme.colors.danger, fontSize = 11.sp) }
        Spacer(Modifier.height(8.dp))
        HorizontalDivider(color = KalivTheme.colors.hairline)
        Spacer(Modifier.height(7.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(enabled = !busy, onClick = onToggle) {
                Text(if (schedule.enabled) "Sæt på pause" else "Genoptag")
            }
            OutlinedButton(enabled = !busy, onClick = onRenew) { Text("Forny") }
        }
    }
}

@Composable
private fun ApprovalCard(
    title: String,
    preview: SchedulePreview,
    confirmLabel: String,
    busy: Boolean,
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
) {
    ScheduleCard {
        Text(title, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
        Text(
            if (preview.requiresApproval) "Dette er en stående skrivegodkendelse." else "Dette er en planlagt læsehandling.",
            color = if (preview.requiresApproval) KalivTheme.colors.danger else KalivTheme.colors.textMuted,
            fontSize = 12.sp,
        )
        Spacer(Modifier.height(8.dp))
        Text(preview.humanSummary, color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(5.dp))
        ApprovalLine("Operation", preview.operation)
        preview.scheduleId?.let { ApprovalLine("Plan", it) }
        ApprovalLine("Tool", preview.tool)
        ApprovalLine("Argumenter", preview.argsJson)
        ApprovalLine("Kadence", preview.cadence)
        ApprovalLine("Timezone", preview.timezone)
        ApprovalLine("Misfire", scheduleMisfireLabel(preview.misfirePolicy))
        ApprovalLine("Risiko", preview.risk)
        ApprovalLine("Følsomhed", preview.sensitivity)
        ApprovalLine("Første/næste kørsel", authoritativeScheduleTime(preview.dueAtLocal, preview.timezone))
        ApprovalLine("Udløb", formatEpoch(preview.expiresAt))
        ApprovalLine("Budget", if (preview.maxRuns == 0) "Ingen antalgrænse; TTL gælder" else "${preview.maxRuns} kørsler")
        preview.enable?.let { ApprovalLine("Tilstand efter renewal", if (it) "aktiv" else "pause") }
        Spacer(Modifier.height(9.dp))
        Text(
            "Ændrer du et felt, forsvinder dette preview og skal laves igen.",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Spacer(Modifier.height(9.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(enabled = !busy, onClick = onConfirm) { Text(confirmLabel) }
            TextButton(onClick = onCancel) { Text("Annullér") }
        }
    }
}

@Composable
private fun ApprovalLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text("$label:", color = KalivTheme.colors.textMuted, fontSize = 11.sp, modifier = Modifier.weight(0.38f))
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp, modifier = Modifier.weight(0.62f))
    }
}

@Composable
private fun ScheduleCard(content: @Composable ColumnScope.() -> Unit) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp), content = content)
    }
}

internal fun authoritativeScheduleTime(dueAtLocal: String, timezone: String): String {
    val local = dueAtLocal.trim()
    val zone = timezone.trim()
    return when {
        local.isNotEmpty() && zone.isNotEmpty() -> "$local · $zone"
        local.isNotEmpty() -> local
        zone.isNotEmpty() -> "ukendt · $zone"
        else -> "ukendt"
    }
}

internal fun scheduleMisfireLabel(policy: String): String = when (policy) {
    ScheduleClient.RUN_ONCE_MISFIRE_POLICY -> "Kør én gang; ældre forfald registreres som missed"
    else -> policy.ifBlank { "ukendt" }
}

private fun formatEpoch(seconds: Double): String {
    if (!seconds.isFinite() || seconds <= 0.0) return "ukendt"
    val fmt = SimpleDateFormat("d. MMM yyyy HH:mm", Locale("da", "DK"))
    return fmt.format(Date((seconds * 1000.0).toLong()))
}

private fun friendlyScheduleError(message: String): String = when {
    message.contains("(401)") -> "Ikke godkendt. Genpar telefonen under Indstillinger."
    message.contains("(403)") -> "Scheduler-administration blev afvist af sikkerhedsgaten."
    message.contains("(409)") -> "Planens godkendelse eller vilkår er ændret. Lav et nyt preview."
    message.contains("(422)") -> "Planen er ugyldig: ${message.substringAfter(":", message)}"
    message.contains("(502)") || message.contains("(503)") -> "Riggen eller scheduler-workeren svarer ikke."
    else -> message
}

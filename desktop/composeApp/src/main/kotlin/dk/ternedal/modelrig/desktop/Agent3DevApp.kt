package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
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
import dk.ternedal.modelrig.desktop.net.Agent3Client
import dk.ternedal.modelrig.desktop.net.Agent3PlanPreview
import dk.ternedal.modelrig.desktop.net.Agent3Run
import dk.ternedal.modelrig.desktop.net.Agent3Step
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Developer-only Agent 3.0 UI. MainKt renders this only with `--agent3`.
 * The ordinary desktop App() and its routing are not touched.
 */
@Composable
fun Agent3DevApp() {
    val db = remember { DesktopChatDb() }
    fun setting(key: String, env: String?, default: String): String =
        System.getenv(env ?: "")?.takeIf { it.isNotBlank() }
            ?: db.getSetting(key) ?: default

    var darkMode by remember { mutableStateOf(db.getSetting("darkMode") != "false") }
    KalivTheme(dark = darkMode) {
        val scope = rememberCoroutineScope()
        var baseUrl by remember {
            mutableStateOf(
                System.getenv("MODELRIG_AGENT3_URL")?.takeIf { it.isNotBlank() }
                    ?: setting("localUrl", "MODELRIG_LOCAL_URL", "http://127.0.0.1:8080")
            )
        }
        var token by remember { mutableStateOf(setting("deviceToken", "MODELRIG_TOKEN", "")) }
        var message by remember { mutableStateOf("") }
        var useMemory by remember { mutableStateOf(false) }
        var memorySubjects by remember { mutableStateOf("") }
        var preview by remember { mutableStateOf<Agent3PlanPreview?>(null) }
        var run by remember { mutableStateOf<Agent3Run?>(null) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun client(): Agent3Client {
            require(baseUrl.isNotBlank()) { "Base-URL mangler" }
            require(token.isNotBlank()) { "Device-token mangler" }
            return Agent3Client(baseUrl.trim(), token.trim())
        }

        fun selectedSubjects(): List<String> = memorySubjects
            .split(',')
            .map { it.trim() }
            .filter { it.isNotEmpty() }
            .distinct()
            .take(20)

        fun previewPlan() {
            val text = message.trim()
            if (text.isEmpty() || busy) return
            busy = true
            error = null
            run = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        client().previewPlan(
                            message = text,
                            mode = "rig",
                            useMemory = useMemory,
                            memorySubjects = if (useMemory) selectedSubjects() else emptyList(),
                        )
                    }
                }
                busy = false
                result.onSuccess { preview = it }
                    .onFailure { error = it.message ?: "Planlægning fejlede" }
            }
        }

        fun startPlan() {
            val id = preview?.planId ?: return
            if (busy) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { client().startPlan(id) } }
                busy = false
                result.onSuccess { run = it }
                    .onFailure { error = it.message ?: "Planen kunne ikke startes" }
            }
        }

        fun refreshRun() {
            val id = run?.id ?: return
            if (busy) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { client().getRun(id) } }
                busy = false
                result.onSuccess { run = it }
                    .onFailure { error = it.message ?: "Run-status kunne ikke hentes" }
            }
        }

        fun decide(approve: Boolean) {
            val current = run ?: return
            val step = current.steps.getOrNull(current.currentStep) ?: return
            val stepId = step.id ?: return
            val digest = step.confirmationDigest ?: return
            if (busy) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching { client().confirm(current.id, stepId, digest, approve) }
                }
                busy = false
                result.onSuccess { run = it }
                    .onFailure { error = it.message ?: "Godkendelsen fejlede" }
            }
        }

        fun cancelRun() {
            val id = run?.id ?: return
            if (busy) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) { runCatching { client().cancel(id) } }
                busy = false
                result.onSuccess { run = it }
                    .onFailure { error = it.message ?: "Run kunne ikke annulleres" }
            }
        }

        Column(
            Modifier
                .fillMaxSize()
                .background(KalivTheme.colors.Graphite)
                .padding(20.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Agent 3.0",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Eksperimentel desktop-plan og run-visning · --agent3",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                OutlinedButton(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            DevCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it },
                    label = { Text("Device-token") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    "Felterne er midlertidige på denne skærm. Standarderne læses fra desktop-indstillinger/env.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
            }

            Spacer(Modifier.height(12.dp))
            DevCard {
                Text("Forespørgsel", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = message,
                    onValueChange = { message = it },
                    label = { Text("Hvad skal agenten planlægge?") },
                    minLines = 3,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(10.dp))
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (useMemory) {
                        Button(onClick = { useMemory = false; memorySubjects = ""; preview = null }) {
                            Text("Memory: til")
                        }
                    } else {
                        OutlinedButton(onClick = { useMemory = true; preview = null }) {
                            Text("Memory: fra")
                        }
                    }
                    Text(
                        if (useMemory) "Kun bekræftede records sendes til den lokale planner."
                        else "Planner-memory er opt-in og slukket.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
                if (useMemory) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = memorySubjects,
                        onValueChange = { memorySubjects = it; preview = null },
                        label = { Text("Valgfrit subject-filter, kommasepareret") },
                        supportingText = { Text("Tomt felt bruger alle eligible memories inden for serverens budget.") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                    )
                }
                Spacer(Modifier.height(10.dp))
                Button(enabled = !busy && message.isNotBlank(), onClick = ::previewPlan) {
                    Text(if (busy) "Arbejder…" else "Lav plan-preview")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                DevCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }

            preview?.let {
                Spacer(Modifier.height(12.dp))
                PlanCard(it, busy, ::startPlan)
            }

            run?.let {
                Spacer(Modifier.height(12.dp))
                RunCard(it, busy, ::refreshRun, { decide(true) }, { decide(false) }, ::cancelRun)
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun DevCard(content: @Composable ColumnScope.() -> Unit) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(KalivTheme.colors.Surface)
            .padding(14.dp),
        content = content,
    )
}

@Composable
private fun PlanCard(preview: Agent3PlanPreview, busy: Boolean, onStart: () -> Unit) {
    DevCard {
        Text("Plan-preview", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        Text(
            "Route: ${preview.route.kind.ifBlank { "ukendt" }}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 12.sp,
        )
        if (preview.rationale.isNotBlank()) {
            Spacer(Modifier.height(6.dp))
            Text(preview.rationale, color = KalivTheme.colors.TextHigh, fontSize = 13.sp)
        }
        if (preview.memoryContext.requested) {
            Spacer(Modifier.height(10.dp))
            Column(
                Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(9.dp))
                    .background(KalivTheme.colors.SurfaceHigh)
                    .padding(10.dp),
            ) {
                Text("Memory receipt", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(
                    if (preview.memoryContext.sentToModel) "Sendt til planner · ${preview.memoryContext.target}"
                    else "Anmodet, men ingen eligible memory blev sendt",
                    color = if (preview.memoryContext.sentToModel) KalivTheme.colors.Signal else KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
                Text(
                    "inkluderet=${preview.memoryContext.includedIds.size} · udelukket=${preview.memoryContext.excludedIds.size} · tegn=${preview.memoryContext.characterCount}",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
                if (preview.memoryContext.includedIds.isNotEmpty()) {
                    Text(
                        "ids: ${preview.memoryContext.includedIds.joinToString(", ")}",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 9.sp,
                    )
                }
                preview.memoryContext.sha256?.let {
                    Text("sha256: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
                }
            }
        }
        Spacer(Modifier.height(10.dp))
        if (preview.plan.isEmpty()) {
            Text("Ingen tool-steps.", color = KalivTheme.colors.TextMuted)
        } else {
            preview.plan.forEachIndexed { index, step ->
                StepCard(index + 1, step)
                if (index != preview.plan.lastIndex) Spacer(Modifier.height(7.dp))
            }
        }
        Spacer(Modifier.height(12.dp))
        Button(
            enabled = !busy && preview.planId != null && preview.plan.isNotEmpty(),
            onClick = onStart,
        ) { Text("Start den viste plan") }
        preview.expiresInSeconds?.let {
            Text("Plan-id udløber om ca. $it sek.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        }
    }
}

@Composable
private fun RunCard(
    run: Agent3Run,
    busy: Boolean,
    onRefresh: () -> Unit,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    onCancel: () -> Unit,
) {
    val current = run.steps.getOrNull(run.currentStep)
    val waiting = run.state == "waiting_confirmation" && current?.id != null && current.confirmationDigest != null
    DevCard {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Run", color = KalivTheme.colors.TextHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
                Text(run.id, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
            }
            Text(run.state, color = KalivTheme.colors.Signal, fontSize = 12.sp)
        }
        Spacer(Modifier.height(8.dp))
        run.steps.forEachIndexed { index, step ->
            StepCard(index + 1, step, active = index == run.currentStep)
            if (index != run.steps.lastIndex) Spacer(Modifier.height(7.dp))
        }
        run.answer?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(10.dp)); HorizontalDivider(); Spacer(Modifier.height(8.dp))
            Text(it, color = KalivTheme.colors.TextHigh)
        }
        run.error?.takeIf { it.isNotBlank() }?.let {
            Spacer(Modifier.height(8.dp)); Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp)
        }
        if (waiting) {
            Spacer(Modifier.height(12.dp))
            Text(current?.summary.orEmpty(), color = KalivTheme.colors.Amber, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(enabled = !busy, onClick = onApprove) { Text("Godkend") }
                OutlinedButton(enabled = !busy, onClick = onDeny) { Text("Afvis") }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(enabled = !busy, onClick = onRefresh) { Text("Opdatér") }
            if (run.state !in setOf("completed", "failed", "cancelled")) {
                OutlinedButton(enabled = !busy, onClick = onCancel) { Text("Annullér") }
            }
        }
    }
}

@Composable
private fun StepCard(number: Int, step: Agent3Step, active: Boolean = false) {
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(9.dp))
            .background(if (active) KalivTheme.colors.SurfaceHigh else KalivTheme.colors.Graphite)
            .padding(10.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                "$number. ${step.tool}",
                color = KalivTheme.colors.TextHigh,
                fontWeight = FontWeight.SemiBold,
                modifier = Modifier.weight(1f),
            )
            Text(step.state ?: step.risk, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        }
        if (step.summary.isNotBlank()) {
            Spacer(Modifier.height(3.dp)); Text(step.summary, color = KalivTheme.colors.TextHigh, fontSize = 12.sp)
        }
        Spacer(Modifier.height(3.dp))
        Text(
            "risiko=${step.risk} · følsomhed=${step.sensitivity} · egress=${step.egress}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        if (step.args.isNotEmpty()) {
            Text(step.args.toString(), color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        step.error?.takeIf { it.isNotBlank() }?.let {
            Text(it, color = KalivTheme.colors.Danger, fontSize = 11.sp)
        }
    }
}

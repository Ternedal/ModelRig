package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
fun Agent3Screen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var message by remember { mutableStateOf("") }
    var useMemory by remember { mutableStateOf(false) }
    var memorySubjects by remember { mutableStateOf("") }
    var preview by remember { mutableStateOf<Agent3Client.PlanPreview?>(null) }
    var run by remember { mutableStateOf<Agent3Client.Run?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun client(): Agent3Client {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return Agent3Client(base, token)
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
        val current = preview ?: return
        val id = current.planId ?: return
        if (current.capabilityReceipt?.allowed == false || busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client().startPlan(id) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure { error = it.message ?: "Kunne ikke starte planen" }
        }
    }

    fun refreshRun() {
        val id = run?.id ?: return
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching { client().getRun(id) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure { error = it.message ?: "Kunne ikke hente run-status" }
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
            val result = withContext(Dispatchers.IO) {
                runCatching { client().cancel(id) }
            }
            busy = false
            result.onSuccess { run = it }
                .onFailure { error = it.message ?: "Kunne ikke annullere run" }
        }
    }

    Surface(color = KalivTheme.colors.background, modifier = Modifier.fillMaxSize()) {
        Column(
            Modifier
                .fillMaxSize()
                .padding(horizontal = 18.dp, vertical = 14.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(
                        "Agent 3.0",
                        fontSize = 26.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Eksperimentel plan- og run-visning",
                        fontSize = 12.sp,
                        color = KalivTheme.colors.textMuted,
                    )
                }
                TextButton(onClick = onClose) { Text("Luk", color = KalivTheme.colors.signal) }
            }

            Spacer(Modifier.height(14.dp))
            Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
                Column(Modifier.fillMaxWidth().padding(14.dp)) {
                    Text(
                        "Forespørgsel",
                        fontWeight = FontWeight.SemiBold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(
                        value = message,
                        onValueChange = { message = it },
                        modifier = Modifier.fillMaxWidth(),
                        minLines = 3,
                        maxLines = 8,
                        label = { Text("Hvad skal agenten planlægge?") },
                    )
                    Spacer(Modifier.height(10.dp))
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        if (useMemory) {
                            Button(onClick = { useMemory = false; memorySubjects = ""; preview = null }) {
                                Text("Memory: til")
                            }
                        } else {
                            OutlinedButton(onClick = { useMemory = true; preview = null }) {
                                Text("Memory: fra")
                            }
                        }
                    }
                    Text(
                        if (useMemory) "Kun bekræftede records sendes til den lokale planner."
                        else "Planner-memory er opt-in og slukket.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 11.sp,
                    )
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
                    Button(
                        enabled = !busy && message.isNotBlank(),
                        onClick = { previewPlan() },
                    ) {
                        Text(if (busy) "Arbejder…" else "Lav plan-preview")
                    }
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(12.dp)) {
                    Text(
                        it,
                        color = KalivTheme.colors.danger,
                        modifier = Modifier.fillMaxWidth().padding(12.dp),
                        fontSize = 13.sp,
                    )
                }
            }

            preview?.let { p ->
                Spacer(Modifier.height(14.dp))
                Agent3PlanCard(p, busy = busy, onStart = { startPlan() })
            }

            run?.let { r ->
                Spacer(Modifier.height(14.dp))
                Agent3RunCard(
                    run = r,
                    busy = busy,
                    onRefresh = { refreshRun() },
                    onApprove = { decide(true) },
                    onDeny = { decide(false) },
                    onCancel = { cancelRun() },
                )
            }

            Spacer(Modifier.height(30.dp))
        }
    }
}

@Composable
private fun Agent3PlanCard(
    preview: Agent3Client.PlanPreview,
    busy: Boolean,
    onStart: () -> Unit,
) {
    val capabilityAllowed = preview.capabilityReceipt?.allowed != false
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text("Plan-preview", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
            Text(
                "Route: ${preview.routeKind.ifBlank { "ukendt" }}",
                fontSize = 12.sp,
                color = KalivTheme.colors.textMuted,
            )
            if (preview.rationale.isNotBlank()) {
                Spacer(Modifier.height(6.dp))
                Text(preview.rationale, fontSize = 13.sp, color = KalivTheme.colors.textHigh)
            }
            if (preview.memoryContext.requested) {
                Spacer(Modifier.height(10.dp))
                Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
                    Column(Modifier.fillMaxWidth().padding(10.dp)) {
                        Text("Memory receipt", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
                        Text(
                            if (preview.memoryContext.sentToModel) {
                                "Sendt til planner · ${preview.memoryContext.target}"
                            } else {
                                "Anmodet, men ingen eligible memory blev sendt"
                            },
                            color = if (preview.memoryContext.sentToModel) KalivTheme.colors.success else KalivTheme.colors.textMuted,
                            fontSize = 11.sp,
                        )
                        Text(
                            "inkluderet=${preview.memoryContext.includedIds.size} · udelukket=${preview.memoryContext.excludedIds.size} · tegn=${preview.memoryContext.characterCount}",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 10.sp,
                        )
                        if (preview.memoryContext.includedIds.isNotEmpty()) {
                            Text(
                                "ids: ${preview.memoryContext.includedIds.joinToString(", ")}",
                                color = KalivTheme.colors.textMuted,
                                fontSize = 9.sp,
                            )
                        }
                        preview.memoryContext.sha256?.let {
                            Text("sha256: $it", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
                        }
                    }
                }
            }
            preview.capabilityReceipt?.let {
                Spacer(Modifier.height(10.dp))
                Agent3CapabilityReceiptCard(it)
            }
            Spacer(Modifier.height(10.dp))
            if (preview.steps.isEmpty()) {
                Text("Planen indeholder ingen tool-steps.", color = KalivTheme.colors.textMuted)
            } else {
                preview.steps.forEachIndexed { index, step ->
                    Agent3StepCard(index + 1, step)
                    if (index != preview.steps.lastIndex) Spacer(Modifier.height(8.dp))
                }
            }
            Spacer(Modifier.height(12.dp))
            Button(
                enabled = !busy && capabilityAllowed && preview.planId != null && preview.steps.isNotEmpty(),
                onClick = onStart,
            ) {
                Text("Start den viste plan")
            }
            preview.expiresInSeconds?.let {
                Spacer(Modifier.height(4.dp))
                Text("Plan-id udløber om ca. $it sek.", fontSize = 11.sp, color = KalivTheme.colors.textMuted)
            }
        }
    }
}

@Composable
private fun Agent3RunCard(
    run: Agent3Client.Run,
    busy: Boolean,
    onRefresh: () -> Unit,
    onApprove: () -> Unit,
    onDeny: () -> Unit,
    onCancel: () -> Unit,
) {
    val current = run.steps.getOrNull(run.currentStep)
    val waiting = run.state == "waiting_confirmation" && current?.confirmationDigest != null && current.id != null

    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Run", fontSize = 18.sp, fontWeight = FontWeight.Bold, color = KalivTheme.colors.textHigh)
                    Text(run.id, fontSize = 10.sp, color = KalivTheme.colors.textMuted)
                }
                Text(run.state, fontSize = 12.sp, color = KalivTheme.colors.signal)
            }
            Spacer(Modifier.height(8.dp))
            run.steps.forEachIndexed { index, step ->
                Agent3StepCard(index + 1, step, active = index == run.currentStep)
                if (index != run.steps.lastIndex) Spacer(Modifier.height(8.dp))
            }

            run.answer?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(10.dp))
                HorizontalDivider()
                Spacer(Modifier.height(8.dp))
                Text(it, color = KalivTheme.colors.textHigh)
            }
            run.error?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(8.dp))
                Text(it, color = KalivTheme.colors.danger, fontSize = 13.sp)
            }

            if (waiting) {
                Spacer(Modifier.height(12.dp))
                Text(
                    current?.summary ?: "Dette step kræver godkendelse.",
                    color = KalivTheme.colors.amber,
                    fontWeight = FontWeight.SemiBold,
                )
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
                    Button(
                        enabled = !busy,
                        onClick = onCancel,
                        colors = ButtonDefaults.buttonColors(containerColor = KalivTheme.colors.danger),
                    ) {
                        Text("Annullér")
                    }
                }
            }
        }
    }
}

@Composable
private fun Agent3StepCard(
    number: Int,
    step: Agent3Client.Step,
    active: Boolean = false,
) {
    Surface(
        color = if (active) KalivTheme.colors.background else KalivTheme.colors.surface,
        shape = RoundedCornerShape(10.dp),
        tonalElevation = if (active) 2.dp else 0.dp,
    ) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "$number. ${step.tool}",
                    fontWeight = FontWeight.SemiBold,
                    color = KalivTheme.colors.textHigh,
                    modifier = Modifier.weight(1f),
                )
                Text(step.state ?: step.risk, fontSize = 11.sp, color = KalivTheme.colors.textMuted)
            }
            if (step.summary.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(step.summary, fontSize = 12.sp, color = KalivTheme.colors.textHigh)
            }
            Spacer(Modifier.height(4.dp))
            Text(
                "risiko=${step.risk} · følsomhed=${step.sensitivity} · egress=${step.egress}",
                fontSize = 10.sp,
                color = KalivTheme.colors.textMuted,
            )
            if (step.args != "{}") {
                Spacer(Modifier.height(3.dp))
                Text(step.args, fontSize = 10.sp, color = KalivTheme.colors.textMuted)
            }
            step.error?.takeIf { it.isNotBlank() }?.let {
                Spacer(Modifier.height(4.dp))
                Text(it, fontSize = 11.sp, color = KalivTheme.colors.danger)
            }
        }
    }
}

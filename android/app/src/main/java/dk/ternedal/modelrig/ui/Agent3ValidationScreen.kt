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
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent3TaskReadinessClient
import dk.ternedal.modelrig.net.Agent3ValidationClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/** Developer-only, read-only promotion evidence view. */
@Composable
fun Agent3ValidationScreen(store: TokenStore, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    var status by remember { mutableStateOf<Agent3ValidationClient.Status?>(null) }
    var readiness by remember { mutableStateOf<Agent3TaskReadinessClient.Readiness?>(null) }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }

    fun connection(): Pair<String, String> {
        val base = store.baseUrl?.takeIf { it.isNotBlank() }
            ?: error("Ingen rig-URL er gemt")
        val token = store.token?.takeIf { it.isNotBlank() }
            ?: error("Ingen device-token er gemt")
        return base to token
    }

    fun refresh() {
        if (busy) return
        busy = true
        error = null
        scope.launch {
            val result = withContext(Dispatchers.IO) {
                runCatching {
                    val (base, token) = connection()
                    Agent3ValidationClient(base, token).status() to
                        Agent3TaskReadinessClient(base, token).readiness()
                }
            }
            busy = false
            result.onSuccess {
                status = it.first
                readiness = it.second
            }.onFailure { error = it.message ?: "Valideringsstatus kunne ikke hentes" }
        }
    }

    LaunchedEffect(Unit) { refresh() }

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
                        "Agent 3.0 Validation Center",
                        fontSize = 24.sp,
                        fontWeight = FontWeight.Bold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Text(
                        "Read-only promotionsstatus · ingen aktivering",
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
                        "Sikkerhedslås",
                        fontWeight = FontWeight.SemiBold,
                        color = KalivTheme.colors.textHigh,
                    )
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "Denne skærm kan kun læse validation og task-readiness. " +
                            "Den kan ikke vælge en rapport, godkende tools eller åbne normal chat-routing.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(enabled = !busy, onClick = { refresh() }) {
                        Text(if (busy) "Henter…" else "Opdatér status")
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

            readiness?.let {
                Spacer(Modifier.height(12.dp))
                TaskReadinessCard(it)
            }

            status?.let {
                Spacer(Modifier.height(12.dp))
                ValidationSummaryCard(it)
                Spacer(Modifier.height(12.dp))
                ValidationProofCard(it.assessment)
                if (it.assessment.reasons.isNotEmpty() ||
                    it.assessment.writePilotReasons.isNotEmpty() ||
                    it.assessment.warnings.isNotEmpty()
                ) {
                    Spacer(Modifier.height(12.dp))
                    ValidationReasonsCard(it.assessment)
                }
            }

            Spacer(Modifier.height(28.dp))
        }
    }
}

@Composable
private fun TaskReadinessCard(readiness: Agent3TaskReadinessClient.Readiness) {
    val headline = if (readiness.eligibleForTaskUi) {
        "Task-UI-evidens er klar"
    } else {
        "Task-UI-evidens er blokeret"
    }
    val headlineColor = if (readiness.eligibleForTaskUi) {
        KalivTheme.colors.signal
    } else {
        KalivTheme.colors.amber
    }
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text(headline, color = headlineColor, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            StatusRow("Aktiv surface", readiness.selectedSurface)
            StatusRow("Kandidat", readiness.candidateSurface)
            StatusRow("Fallback", readiness.fallbackSurface)
            StatusRow("Serverårsag", readiness.reason)
            StatusRow("Pilot-tasks", readiness.pilot.successes?.let { "$it/${readiness.pilot.tasks}" } ?: "ukendt")
            StatusRow("Replans", readiness.pilot.replans?.toString() ?: "ukendt")
            StatusRow("Retry-events", readiness.pilot.retryEvents?.toString() ?: "ukendt")
            Spacer(Modifier.height(8.dp))
            GateRow("Operatørkontakt slået til", readiness.operatorEnabled)
            GateRow("Pilot frisk", readiness.pilot.fresh)
            GateRow("Version matcher", readiness.pilot.versionMatch)
            GateRow("Kode matcher", readiness.pilot.codeMatch)
            GateRow("Stop + fallback bevist", readiness.pilot.stopFallbackProven)
            GateRow("Normal chat urørt", readiness.normalChatRouteUnchanged)
            GateRow("Produktion stadig låst", !readiness.productionActivation)
            if (readiness.reasons.isNotEmpty()) {
                Spacer(Modifier.height(8.dp))
                readiness.reasons.distinct().forEach {
                    Text("• $it", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                }
            }
        }
    }
}

@Composable
private fun ValidationSummaryCard(status: Agent3ValidationClient.Status) {
    val assessment = status.assessment
    val headline = when {
        assessment.eligibleForWritePilot -> "Write-pilot dokumenteret"
        assessment.eligibleForDeveloperPreview -> "Developer-preview dokumenteret"
        else -> "Promotion blokeret"
    }
    val headlineColor = when {
        assessment.eligibleForWritePilot -> KalivTheme.colors.success
        assessment.eligibleForDeveloperPreview -> KalivTheme.colors.signal
        else -> KalivTheme.colors.amber
    }

    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text(headline, color = headlineColor, fontSize = 18.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(8.dp))
            StatusRow("Worker-version", status.workerVersion ?: "ukendt")
            StatusRow("Valideret version", assessment.validatedVersion ?: "ingen")
            StatusRow("Planner-model", assessment.plannerModel ?: "ingen")
            StatusRow("Write-bevis", assessment.writeDecision ?: "ingen")
            StatusRow("Rapportalder", assessment.ageSeconds.formatAge())
            StatusRow("Maksimal alder", "${assessment.maxAgeHours.roundToInt()} timer")
            Spacer(Modifier.height(8.dp))
            GateRow("Rapport konfigureret", assessment.configured)
            GateRow("Rapport fundet", assessment.present)
            GateRow("Struktur gyldig", assessment.structurallyValid)
            GateRow("Rapport frisk", assessment.fresh)
            GateRow("Version matcher", assessment.versionMatch)
            GateRow("Produktion stadig låst", !status.productionActivation)
            if (!status.productionToolsPathUntouched) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "ADVARSEL: status bekræfter ikke, at production tools-stien er urørt.",
                    color = KalivTheme.colors.danger,
                    fontSize = 12.sp,
                )
            }
            assessment.finishedAt?.let {
                Spacer(Modifier.height(6.dp))
                Text("Færdig: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
            assessment.reportSha256?.let {
                Text("rapport-sha256: $it", color = KalivTheme.colors.textMuted, fontSize = 9.sp)
            }
        }
    }
}

@Composable
private fun ValidationProofCard(assessment: Agent3ValidationClient.Assessment) {
    val p = assessment.proofs
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text("Maskinelle beviser", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            GateRow("Eksperimentel status", p.status)
            GateRow("Memory receipt-binding", p.memoryBinding)
            GateRow("Read-eventkæde", p.readPath)
            GateRow("Confirmation før write", p.confirmationPath)
            GateRow("Single-use plan", p.singleUse)
            GateRow("Content-free cleanup", p.cleanup)
            GateRow("Write faktisk udført", p.writeExecution)
            Spacer(Modifier.height(8.dp))
            Text(
                "Write-bevis må gerne være falsk i en sikker standard-deny rapport.",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
private fun ValidationReasonsCard(assessment: Agent3ValidationClient.Assessment) {
    Surface(color = KalivTheme.colors.surface, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.fillMaxWidth().padding(14.dp)) {
            Text("Blockers og advarsler", color = KalivTheme.colors.textHigh, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(8.dp))
            ReasonGroup("Developer-preview", assessment.reasons, KalivTheme.colors.danger)
            ReasonGroup("Write-pilot", assessment.writePilotReasons, KalivTheme.colors.amber)
            ReasonGroup("Advarsler", assessment.warnings, KalivTheme.colors.textMuted)
        }
    }
}

@Composable
private fun ReasonGroup(title: String, values: List<String>, color: Color) {
    if (values.isEmpty()) return
    Text(title, color = KalivTheme.colors.textHigh, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    values.distinct().forEach { Text("• $it", color = color, fontSize = 11.sp) }
    Spacer(Modifier.height(7.dp))
}

@Composable
private fun StatusRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.textHigh, fontSize = 11.sp)
    }
}

@Composable
private fun GateRow(label: String, passed: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        Text(
            if (passed) "OK" else "NEJ",
            color = if (passed) KalivTheme.colors.success else KalivTheme.colors.danger,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
    }
}

private fun Double?.formatAge(): String {
    val seconds = this ?: return "ukendt"
    return when {
        seconds < 60 -> "${seconds.roundToInt()} sek."
        seconds < 3_600 -> "${(seconds / 60).roundToInt()} min."
        else -> "${(seconds / 3_600).roundToInt()} timer"
    }
}

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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.data.DesktopChatDb
import dk.ternedal.modelrig.desktop.net.Agent3TaskReadiness
import dk.ternedal.modelrig.desktop.net.Agent3TaskReadinessClient
import dk.ternedal.modelrig.desktop.net.Agent3ValidationAssessment
import dk.ternedal.modelrig.desktop.net.Agent3ValidationClient
import dk.ternedal.modelrig.desktop.net.Agent3ValidationStatus
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/** Developer-only, read-only Agent 3.0 promotion evidence view. */
@Composable
fun Agent3ValidationDevApp() {
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
        var status by remember { mutableStateOf<Agent3ValidationStatus?>(null) }
        var readiness by remember { mutableStateOf<Agent3TaskReadiness?>(null) }
        var busy by remember { mutableStateOf(false) }
        var error by remember { mutableStateOf<String?>(null) }

        fun refresh() {
            if (busy || baseUrl.isBlank() || token.isBlank()) return
            busy = true
            error = null
            scope.launch {
                val result = withContext(Dispatchers.IO) {
                    runCatching {
                        val base = baseUrl.trim()
                        val bearer = token.trim()
                        Agent3ValidationClient(base, bearer).status() to
                            Agent3TaskReadinessClient(base, bearer).readiness()
                    }
                }
                busy = false
                result.onSuccess {
                    status = it.first
                    readiness = it.second
                }.onFailure { error = it.message ?: "Validation status could not be loaded" }
            }
        }

        LaunchedEffect(Unit) {
            if (baseUrl.isNotBlank() && token.isNotBlank()) refresh()
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
                        "Agent 3.0 Validation Center",
                        color = KalivTheme.colors.TextHigh,
                        fontSize = 28.sp,
                        fontWeight = FontWeight.Bold,
                    )
                    Text(
                        "Read-only promotionsstatus · --agent3-validation",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 12.sp,
                    )
                }
                Button(onClick = { darkMode = !darkMode }) {
                    Text(if (darkMode) "Lys" else "Mørk")
                }
            }

            Spacer(Modifier.height(14.dp))
            ValidationCard {
                Text("Forbindelse", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = baseUrl,
                    onValueChange = { baseUrl = it; status = null; readiness = null },
                    label = { Text("ModelRig backend-URL") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                OutlinedTextField(
                    value = token,
                    onValueChange = { token = it; status = null; readiness = null },
                    label = { Text("Device-token") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(8.dp))
                Text(
                    "Skærmen udfører kun GET status og task-readiness. " +
                        "Den kan ikke vælge rapport, godkende tools eller aktivere routing.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 11.sp,
                )
                Spacer(Modifier.height(10.dp))
                Button(
                    enabled = !busy && baseUrl.isNotBlank() && token.isNotBlank(),
                    onClick = ::refresh,
                ) {
                    Text(if (busy) "Henter…" else "Opdatér status")
                }
            }

            error?.let {
                Spacer(Modifier.height(12.dp))
                ValidationCard { Text(it, color = KalivTheme.colors.Danger, fontSize = 13.sp) }
            }

            readiness?.let {
                Spacer(Modifier.height(12.dp))
                TaskReadinessSummary(it)
            }

            status?.let {
                Spacer(Modifier.height(12.dp))
                ValidationSummary(it)
                Spacer(Modifier.height(12.dp))
                ValidationProofs(it.assessment)
                if (it.assessment.reasons.isNotEmpty() ||
                    it.assessment.writePilotReasons.isNotEmpty() ||
                    it.assessment.warnings.isNotEmpty()
                ) {
                    Spacer(Modifier.height(12.dp))
                    ValidationReasons(it.assessment)
                }
            }
            Spacer(Modifier.height(24.dp))
        }
    }
}

@Composable
private fun ValidationCard(content: @Composable ColumnScope.() -> Unit) {
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
private fun TaskReadinessSummary(value: Agent3TaskReadiness) {
    val headline = if (value.eligibleForTaskUi) {
        "Task-UI evidence ready"
    } else {
        "Task-UI evidence blocked"
    }
    ValidationCard {
        Text(
            headline,
            color = if (value.eligibleForTaskUi) KalivTheme.colors.Signal else KalivTheme.colors.Amber,
            fontSize = 19.sp,
            fontWeight = FontWeight.Bold,
        )
        Spacer(Modifier.height(8.dp))
        ValueRow("Active surface", value.selectedSurface)
        ValueRow("Candidate", value.candidateSurface)
        ValueRow("Fallback", value.fallbackSurface)
        ValueRow("Server reason", value.reason)
        ValueRow("Pilot tasks", value.pilot.successes?.let { "$it/${value.pilot.tasks}" } ?: "unknown")
        ValueRow("Replans", value.pilot.replans?.toString() ?: "unknown")
        ValueRow("Retry events", value.pilot.retryEvents?.toString() ?: "unknown")
        Spacer(Modifier.height(8.dp))
        GateRow("Operator switch enabled", value.operatorEnabled)
        GateRow("Pilot fresh", value.pilot.fresh)
        GateRow("Version matches", value.pilot.versionMatch)
        GateRow("Code matches", value.pilot.codeMatch)
        GateRow("Stop + fallback proven", value.pilot.stopFallbackProven)
        GateRow("Normal chat unchanged", value.normalChatRouteUnchanged)
        GateRow("Production remains locked", !value.productionActivation)
        if (value.reasons.isNotEmpty()) {
            Spacer(Modifier.height(8.dp))
            value.reasons.distinct().forEach {
                Text("• $it", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
            }
        }
    }
}

@Composable
private fun ValidationSummary(status: Agent3ValidationStatus) {
    val a = status.assessment
    val headline = when {
        a.eligibleForWritePilot -> "Write-pilot dokumenteret"
        a.eligibleForDeveloperPreview -> "Developer-preview dokumenteret"
        else -> "Promotion blokeret"
    }
    val headlineColor = when {
        a.eligibleForWritePilot -> KalivTheme.colors.Signal
        a.eligibleForDeveloperPreview -> KalivTheme.colors.Signal
        else -> KalivTheme.colors.Amber
    }
    ValidationCard {
        Text(headline, color = headlineColor, fontSize = 19.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        ValueRow("Worker-version", status.workerVersion ?: "ukendt")
        ValueRow("Valideret version", a.validatedVersion ?: "ingen")
        ValueRow("Planner-model", a.plannerModel ?: "ingen")
        ValueRow("Write-bevis", a.writeDecision ?: "ingen")
        ValueRow("Rapportalder", a.ageSeconds.formatAge())
        ValueRow("Maksimal alder", "${a.maxAgeHours.roundToInt()} timer")
        Spacer(Modifier.height(8.dp))
        GateRow("Rapport konfigureret", a.configured)
        GateRow("Rapport fundet", a.present)
        GateRow("Struktur gyldig", a.structurallyValid)
        GateRow("Rapport frisk", a.fresh)
        GateRow("Version matcher", a.versionMatch)
        GateRow("Produktion stadig låst", !status.productionActivation)
        if (!status.productionToolsPathUntouched) {
            Spacer(Modifier.height(6.dp))
            Text(
                "ADVARSEL: production tools-stien er ikke bekræftet urørt.",
                color = KalivTheme.colors.Danger,
                fontSize = 12.sp,
            )
        }
        a.finishedAt?.let {
            Spacer(Modifier.height(6.dp))
            Text("Færdig: $it", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        }
        a.reportSha256?.let {
            Text("rapport-sha256: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        }
    }
}

@Composable
private fun ValidationProofs(a: Agent3ValidationAssessment) {
    val p = a.proofs
    ValidationCard {
        Text("Maskinelle beviser", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
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
            "Write-bevis må være falsk i den sikre standard-deny rapport.",
            color = KalivTheme.colors.TextMuted,
            fontSize = 11.sp,
        )
    }
}

@Composable
private fun ValidationReasons(a: Agent3ValidationAssessment) {
    ValidationCard {
        Text("Blockers og advarsler", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        ReasonGroup("Developer-preview", a.reasons, KalivTheme.colors.Danger)
        ReasonGroup("Write-pilot", a.writePilotReasons, KalivTheme.colors.Amber)
        ReasonGroup("Advarsler", a.warnings, KalivTheme.colors.TextMuted)
    }
}

@Composable
private fun ReasonGroup(title: String, values: List<String>, color: Color) {
    if (values.isEmpty()) return
    Text(title, color = KalivTheme.colors.TextHigh, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    values.distinct().forEach { Text("• $it", color = color, fontSize = 11.sp) }
    Spacer(Modifier.height(7.dp))
}

@Composable
private fun ValueRow(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(value, color = KalivTheme.colors.TextHigh, fontSize = 11.sp)
    }
}

@Composable
private fun GateRow(label: String, passed: Boolean) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(label, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
        Text(
            if (passed) "OK" else "NEJ",
            color = if (passed) KalivTheme.colors.Signal else KalivTheme.colors.Danger,
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

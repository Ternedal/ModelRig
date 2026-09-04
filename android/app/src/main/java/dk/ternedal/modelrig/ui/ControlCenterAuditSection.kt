package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.ControlCenterAuditClient
import dk.ternedal.modelrig.net.ControlCenterAuditEntry
import dk.ternedal.modelrig.net.ControlCenterAuditFilter
import dk.ternedal.modelrig.net.ControlCenterAuditSnapshot
import dk.ternedal.modelrig.net.ControlCenterClient
import dk.ternedal.modelrig.net.ControlCenterPrivacy
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

internal fun controlCenterAuditOutcomeLabel(outcome: String): String = when (outcome) {
    "executed" -> "Udført"
    "denied" -> "Afvist"
    "blocked" -> "Blokeret"
    "failed" -> "Fejlet"
    "attempt" -> "Forsøg registreret"
    else -> "Ukendt udfald · $outcome"
}

internal fun controlCenterAuditOriginLabel(origin: String): String = when (origin) {
    "local" -> "Lokal"
    "cloud" -> "Cloud"
    "schedule" -> "Planlagt"
    else -> origin
}

internal fun controlCenterAuditConnectorEvidenceLabel(state: String, reason: String?): String = when (state) {
    "unavailable" -> when (reason) {
        "tool_audit_does_not_record_connector_id" ->
            "Connector-filter er utilgængeligt: ToolGate-audit registrerer ikke connector-id endnu."
        else -> "Connector-evidens er utilgængelig."
    }
    "ready" -> "Connector-evidens er tilgængelig."
    else -> "Connector-evidens har ukendt status."
}

internal fun controlCenterAuditError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") ->
            "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(404)") ->
            "Audit-loggen er ikke eksponeret på denne rig."
        message.contains("(502)") || message.contains("(503)") ->
            "Audit-loggen er midlertidigt utilgængelig fra riggen."
        message.contains("timed out", ignoreCase = true) ->
            "Audit-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") ->
            "Kan ikke nå riggen for audit."
        message.isBlank() -> "Audit kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun ControlCenterAuditLoader(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<ControlCenterAuditSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var privacy by remember { mutableStateOf(ControlCenterPrivacy.unreported()) }

    LaunchedEffect(baseUrl, token, refreshGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            loading = false
            snapshot = null
            error = null
            privacy = ControlCenterPrivacy.unreported()
            return@LaunchedEffect
        }
        loading = true
        error = null
        privacy = ControlCenterPrivacy.unreported().copy(reason = "privacy_refresh_in_progress")
        val results = withContext(Dispatchers.IO) {
            Pair(
                runCatching { ControlCenterAuditClient(baseUrl, token).snapshot() },
                runCatching { ControlCenterClient(baseUrl, token).status().privacy },
            )
        }
        results.first.onSuccess {
            snapshot = it
            error = null
        }.onFailure {
            snapshot = null
            error = controlCenterAuditError(it.message)
        }
        results.second.onSuccess {
            privacy = it
        }.onFailure {
            privacy = ControlCenterPrivacy.unreported().copy(reason = "privacy_status_unavailable")
        }
        loading = false
    }

    ControlCenterPrivacySection(privacy)
    ControlCenterGitHubConnectorLoader(
        baseUrl = baseUrl,
        token = token,
        refreshGeneration = refreshGeneration,
    )
    ControlCenterAuditSection(
        snapshot = snapshot,
        error = error,
        loading = loading,
    )
}

@Composable
internal fun ControlCenterAuditSection(
    snapshot: ControlCenterAuditSnapshot?,
    error: String?,
    loading: Boolean,
) {
    var taskFilter by remember { mutableStateOf("") }
    var capabilityFilter by remember { mutableStateOf("") }
    var approvalFilter by remember { mutableStateOf("") }

    Column(
        modifier = Modifier.padding(top = 10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                "Audit",
                color = KalivTheme.colors.textHigh,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "ToolGate-evidens · indholdsfri Control Center-projektion · kun læsning",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier
                        .padding(top = 6.dp)
                        .height(20.dp),
                    strokeWidth = 2.dp,
                    color = KalivTheme.colors.signal,
                )
            }
        }

        error?.let {
            AuditNeutralCard {
                Text(
                    "Audit ikke tilgængelig",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text(
                    "Manglende audit-evidens bliver ikke fortolket som en tom eller fejlfri log.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }
        }

        snapshot?.let { current ->
            AuditNeutralCard {
                Text(
                    "Filtre",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                OutlinedTextField(
                    value = taskFilter,
                    onValueChange = { taskFilter = it },
                    label = { Text("Task / conversation-ref") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = capabilityFilter,
                    onValueChange = { capabilityFilter = it },
                    label = { Text("Capability") },
                    placeholder = { Text("fx tool:note_append") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = approvalFilter,
                    onValueChange = { approvalFilter = it },
                    label = { Text("Approval") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    controlCenterAuditConnectorEvidenceLabel(
                        current.connectorEvidence.state,
                        current.connectorEvidence.reason,
                    ),
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
                Text(
                    "Origin (local/cloud/schedule) bliver ikke brugt som erstatning for connector-id.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }

            val filtered = current.filtered(
                ControlCenterAuditFilter(
                    task = taskFilter,
                    capability = capabilityFilter,
                    approval = approvalFilter,
                ),
            )
            Text(
                "Viser ${filtered.size} af ${current.entries.size} auditposter",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )

            if (filtered.isEmpty()) {
                AuditNeutralCard {
                    Text(
                        if (current.entries.isEmpty()) {
                            "Ingen ToolGate-auditposter er registreret i den hentede projektion."
                        } else {
                            "Ingen auditposter matcher de aktive filtre."
                        },
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                filtered.forEach { entry -> AuditEntryCard(entry) }
            }
        }
    }
}

@Composable
private fun AuditEntryCard(entry: ControlCenterAuditEntry) {
    AuditNeutralCard {
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                entry.tool,
                color = KalivTheme.colors.textHigh,
                fontSize = 15.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(entry.capabilityId, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            Text(
                controlCenterAuditOutcomeLabel(entry.outcome),
                modifier = Modifier.padding(top = 4.dp),
                color = KalivTheme.colors.textHigh,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
        }
        Spacer(Modifier.height(4.dp))
        Text("Tid: ${entry.timestamp}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        Text(
            "Task/ref: ${entry.taskRef ?: "ikke registreret"}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        entry.approvalId?.let {
            Text("Approval: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }
        Text(
            "Origin: ${controlCenterAuditOriginLabel(entry.origin)}" +
                (entry.risk?.let { " · risk: $it" } ?: ""),
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        entry.durationMs?.let {
            Text("Varighed: $it ms", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }
        Text(
            "Tool-argumenter og resultatsammendrag kopieres ikke ind i Control Center.",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun AuditNeutralCard(content: @Composable () -> Unit) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            content()
        }
    }
}

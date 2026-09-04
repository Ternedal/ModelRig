package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterGitHubConnectorClient
import dk.ternedal.modelrig.desktop.net.DesktopGitHubAuditEntry
import dk.ternedal.modelrig.desktop.net.DesktopGitHubConnectorSnapshot
import dk.ternedal.modelrig.desktop.net.DesktopGitHubGrant
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal fun desktopGitHubOperationLabel(operation: String): String = when (operation) {
    "repository" -> "Repository"
    "issue" -> "Issue"
    "pull_request" -> "Pull request"
    "workflow_run" -> "CI / workflow-run"
    else -> operation
}

internal fun desktopGitHubOutcomeLabel(outcome: String): String = when (outcome) {
    "executed" -> "Udført"
    "blocked" -> "Blokeret"
    "error" -> "Fejl"
    else -> "Ukendt · $outcome"
}

internal fun desktopGitHubConnectorMatchesFilter(filter: String): Boolean {
    val needle = filter.trim()
    return needle.isEmpty() || needle.equals("github", ignoreCase = true)
}

internal fun desktopGitHubExternalAccountLabel(account: String): String =
    "Ekstern konto: GitHub · $account"

internal fun desktopGitHubOutboundDataLabel(): String =
    "Data der sendes til GitHub ved læsning: repository, valgt read-operation og evt. objekt-id. Credentialen tilføjes kun i worker-transporten og vises aldrig i Control Center."

internal fun desktopGitHubConnectorError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") -> "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(404)") && message.contains("GitHub connector POST") ->
            "GitHub-tilladelsen findes ikke længere eller er allerede tilbagekaldt. Opdatér status før et nyt forsøg."
        message.contains("(404)") -> "GitHub connector-piloten er slået fra eller ikke landet på denne rig."
        message.contains("(502)") || message.contains("(503)") ->
            "GitHub connector-authority kan ikke nå den lokale worker lige nu."
        message.contains("timed out", ignoreCase = true) ||
            message.contains("HttpTimeout", ignoreCase = true) ->
            "GitHub connector-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") -> "Kan ikke nå riggen for GitHub connector-status."
        message.isBlank() -> "GitHub connector-status kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun DesktopControlCenterGitHubConnectorSection(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var localGeneration by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<DesktopGitHubConnectorSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var mutationError by remember { mutableStateOf<String?>(null) }
    var revokingId by remember { mutableStateOf<String?>(null) }
    var pendingRevokeId by remember { mutableStateOf<String?>(null) }
    var connectorFilter by remember { mutableStateOf("") }
    var repositoryFilter by remember { mutableStateOf("") }
    var operationFilter by remember { mutableStateOf("") }
    var outcomeFilter by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()

    LaunchedEffect(baseUrl, token, refreshGeneration, localGeneration) {
        if (baseUrl.isBlank() || token.isBlank()) {
            loading = false
            snapshot = null
            error = null
            mutationError = null
            return@LaunchedEffect
        }
        loading = true
        error = null
        val result = withContext(Dispatchers.IO) {
            runCatching { ControlCenterGitHubConnectorClient(baseUrl, token).snapshot() }
        }
        result.onSuccess {
            snapshot = it
            error = null
        }.onFailure {
            snapshot = null
            error = desktopGitHubConnectorError(it.message)
        }
        loading = false
    }

    val mutationBusy = revokingId != null

    Column(
        modifier = Modifier.padding(top = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "GitHub connector",
            color = KalivTheme.colors.TextHigh,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Repository-scope · connector-audit · tilbagekaldelig authority",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        if (loading) {
            CircularProgressIndicator(strokeWidth = 2.dp, color = KalivTheme.colors.Signal)
        }

        error?.let {
            DesktopGitHubCard {
                Text("GitHub connector ikke tilgængelig", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Text(
                    "Manglende connector-evidens bliver ikke fortolket som tomt scope eller fejlfri drift.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }
        }

        mutationError?.let {
            DesktopGitHubCard {
                Text("Tilbagekaldelse blev ikke gennemført", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                Text(
                    "Visningen ændres først efter serverbekræftet revoke og efterfølgende refresh.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }
        }

        snapshot?.let { current ->
            DesktopGitHubCard {
                Text("Tilladelser", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(
                    "${current.activeGrants.size} aktive · ${current.grants.size - current.activeGrants.size} tilbagekaldte",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
                Text(
                    "Desktop Control Center kan kun tilbagekalde eksisterende GitHub-scope; nye grants oprettes ikke her.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }

            if (current.grants.isEmpty()) {
                DesktopGitHubCard {
                    Text("Ingen GitHub-tilladelser er registreret.", color = KalivTheme.colors.TextMuted, fontSize = 11.sp)
                }
            } else {
                current.grants.forEach { grant ->
                    DesktopGitHubGrantCard(
                        grant = grant,
                        pending = pendingRevokeId == grant.grantId,
                        revoking = revokingId == grant.grantId,
                        mutationBusy = mutationBusy,
                        onRequest = { if (!mutationBusy) pendingRevokeId = grant.grantId },
                        onCancel = { pendingRevokeId = null },
                        onConfirm = {
                            if (!mutationBusy) {
                                pendingRevokeId = null
                                revokingId = grant.grantId
                                mutationError = null
                                scope.launch {
                                    val result = withContext(Dispatchers.IO) {
                                        runCatching {
                                            ControlCenterGitHubConnectorClient(baseUrl, token).revoke(grant)
                                        }
                                    }
                                    result.onSuccess {
                                        mutationError = null
                                        localGeneration += 1
                                    }.onFailure {
                                        mutationError = desktopGitHubConnectorError(it.message)
                                    }
                                    revokingId = null
                                }
                            }
                        },
                    )
                }
            }

            DesktopGitHubCard {
                Text("Connector-audit", color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(
                    "Connector-identitet kommer fra registreret connector=github-evidens og udledes aldrig af ToolGate-origin.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
                OutlinedTextField(
                    value = connectorFilter,
                    onValueChange = { connectorFilter = it.trim() },
                    label = { Text("Connector") },
                    placeholder = { Text("github") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = repositoryFilter,
                    onValueChange = { repositoryFilter = it },
                    label = { Text("Repository") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = operationFilter,
                    onValueChange = { operationFilter = it.trim() },
                    label = { Text("Operation") },
                    placeholder = { Text("issue / pull_request / workflow_run") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = outcomeFilter,
                    onValueChange = { outcomeFilter = it.trim() },
                    label = { Text("Udfald") },
                    placeholder = { Text("executed / blocked / error") },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }

            val connectorMatches = desktopGitHubConnectorMatchesFilter(connectorFilter)
            val filtered = if (connectorMatches) {
                current.filteredAudit(repositoryFilter, operationFilter, outcomeFilter)
            } else {
                emptyList()
            }
            Text(
                "Viser ${filtered.size} af ${current.audit.size} GitHub-auditposter",
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
            if (filtered.isEmpty()) {
                DesktopGitHubCard {
                    Text(
                        if (current.audit.isEmpty()) "Ingen connector-reads er registreret i den hentede GitHub-audit."
                        else "Ingen GitHub-auditposter matcher de aktive filtre.",
                        color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp,
                    )
                }
            } else {
                filtered.forEach { DesktopGitHubAuditCard(it) }
            }
        }
    }
}

@Composable
private fun DesktopGitHubGrantCard(
    grant: DesktopGitHubGrant,
    pending: Boolean,
    revoking: Boolean,
    mutationBusy: Boolean,
    onRequest: () -> Unit,
    onCancel: () -> Unit,
    onConfirm: () -> Unit,
) {
    DesktopGitHubCard {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(grant.account, color = KalivTheme.colors.TextHigh, fontWeight = FontWeight.SemiBold)
                Text(
                    if (grant.active) "Aktiv GitHub-tilladelse" else "Tilbagekaldt GitHub-tilladelse",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
            }
            Text(
                if (grant.active) "AKTIV" else "REVOKED",
                color = if (grant.active) KalivTheme.colors.Signal else KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Text(
            desktopGitHubExternalAccountLabel(grant.account),
            color = KalivTheme.colors.TextHigh,
            fontSize = 10.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            desktopGitHubOutboundDataLabel(),
            color = KalivTheme.colors.TextMuted,
            fontSize = 9.sp,
        )
        Text("Repositories: ${grant.repositories.joinToString()}", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        Text(
            "Reads: ${grant.operations.joinToString { desktopGitHubOperationLabel(it) }}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )
        Text(
            "Scope: ${grant.scopeSha256.take(16)}… · oprettet ${grant.createdAt}",
            color = KalivTheme.colors.TextMuted,
            fontSize = 9.sp,
        )
        grant.revokedAt?.let { Text("Tilbagekaldt: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp) }

        if (grant.active && !pending) {
            OutlinedButton(onClick = onRequest, enabled = !mutationBusy) {
                Text(
                    when {
                        revoking -> "Tilbagekalder…"
                        mutationBusy -> "En anden tilbagekaldelse kører…"
                        else -> "Tilbagekald tilladelse"
                    },
                )
            }
        }
        if (grant.active && pending) {
            Text(
                "Bekræft: dette stopper nye GitHub-kald for præcis dette scope. Serveren genvaliderer scope-digest før ændringen.",
                color = KalivTheme.colors.TextHigh,
                fontSize = 10.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onConfirm, enabled = !mutationBusy) { Text("Bekræft tilbagekaldelse") }
                OutlinedButton(onClick = onCancel, enabled = !mutationBusy) { Text("Annullér") }
            }
        }
    }
}

@Composable
private fun DesktopGitHubAuditCard(entry: DesktopGitHubAuditEntry) {
    DesktopGitHubCard {
        Text(
            "${desktopGitHubOperationLabel(entry.operation)} · ${desktopGitHubOutcomeLabel(entry.outcome)}",
            color = KalivTheme.colors.TextHigh,
            fontWeight = FontWeight.SemiBold,
        )
        Text(entry.repository, color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
        entry.objectId?.let { Text("Objekt: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp) }
        Text("Tid: ${entry.timestamp} · ${entry.durationMs} ms", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        entry.revision?.let { Text("Revision: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp) }
        entry.grantId?.let { Text("Grant: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp) }
        Text("Detail: ${entry.detail}", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
        Text(
            "Issue/PR-body, diff, logtekst og credentials indgår ikke i connector-auditprojektionen.",
            color = KalivTheme.colors.TextMuted,
            fontSize = 9.sp,
        )
    }
}

@Composable
private fun DesktopGitHubCard(content: @Composable () -> Unit) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.Surface, RoundedCornerShape(12.dp))
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        content()
    }
}

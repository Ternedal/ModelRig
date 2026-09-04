package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
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
import dk.ternedal.modelrig.net.ControlCenterGitHubAuditEntry
import dk.ternedal.modelrig.net.ControlCenterGitHubConnectorClient
import dk.ternedal.modelrig.net.ControlCenterGitHubConnectorSnapshot
import dk.ternedal.modelrig.net.ControlCenterGitHubGrant
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

internal fun controlCenterGitHubOperationLabel(operation: String): String = when (operation) {
    "repository" -> "Repository"
    "issue" -> "Issue"
    "pull_request" -> "Pull request"
    "workflow_run" -> "CI / workflow-run"
    else -> operation
}

internal fun controlCenterGitHubOutcomeLabel(outcome: String): String = when (outcome) {
    "executed" -> "Udført"
    "blocked" -> "Blokeret"
    "error" -> "Fejl"
    else -> "Ukendt · $outcome"
}

internal fun controlCenterGitHubConnectorMatchesFilter(filter: String): Boolean {
    val needle = filter.trim()
    return needle.isEmpty() || needle.equals("github", ignoreCase = true)
}

internal fun controlCenterGitHubExternalAccountLabel(account: String): String =
    "Ekstern konto: GitHub · $account"

internal fun controlCenterGitHubOutboundDataLabel(): String =
    "Data der sendes til GitHub ved læsning: repository, valgt read-operation og evt. objekt-id. Credentialen tilføjes kun i worker-transporten og vises aldrig i Control Center."

internal fun controlCenterGitHubError(raw: String?): String {
    val message = raw.orEmpty()
    return when {
        message.contains("(401)") -> "Ikke godkendt. Parringen mangler eller er udløbet."
        message.contains("(404)") && message.contains("GitHub connector POST") ->
            "GitHub-tilladelsen findes ikke længere eller er allerede tilbagekaldt. Opdatér status før et nyt forsøg."
        message.contains("(404)") -> "GitHub connector-piloten er slået fra eller ikke landet på denne rig."
        message.contains("(502)") || message.contains("(503)") ->
            "GitHub connector-authority kan ikke nå den lokale worker lige nu."
        message.contains("timed out", ignoreCase = true) -> "GitHub connector-kaldet fik tidsudløb. Prøv igen."
        message.contains("Connection refused", ignoreCase = true) ||
            message.contains("ConnectException") -> "Kan ikke nå riggen for GitHub connector-status."
        message.isBlank() -> "GitHub connector-status kunne ikke hentes."
        else -> message.take(300)
    }
}

@Composable
internal fun ControlCenterGitHubConnectorLoader(
    baseUrl: String,
    token: String,
    refreshGeneration: Int,
) {
    var localGeneration by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var snapshot by remember { mutableStateOf<ControlCenterGitHubConnectorSnapshot?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var mutationError by remember { mutableStateOf<String?>(null) }
    var revokingId by remember { mutableStateOf<String?>(null) }
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
            error = controlCenterGitHubError(it.message)
        }
        loading = false
    }

    ControlCenterGitHubConnectorSection(
        snapshot = snapshot,
        loading = loading,
        error = error,
        mutationError = mutationError,
        revokingId = revokingId,
        onRevoke = { grant ->
            if (revokingId == null) {
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
                        mutationError = controlCenterGitHubError(it.message)
                    }
                    revokingId = null
                }
            }
        },
    )
}

@Composable
internal fun ControlCenterGitHubConnectorSection(
    snapshot: ControlCenterGitHubConnectorSnapshot?,
    loading: Boolean,
    error: String?,
    mutationError: String?,
    revokingId: String?,
    onRevoke: (ControlCenterGitHubGrant) -> Unit,
) {
    var pendingRevokeId by remember { mutableStateOf<String?>(null) }
    var connectorFilter by remember { mutableStateOf("") }
    var repositoryFilter by remember { mutableStateOf("") }
    var operationFilter by remember { mutableStateOf("") }
    var outcomeFilter by remember { mutableStateOf("") }
    val mutationBusy = revokingId != null

    Column(
        modifier = Modifier.padding(top = 10.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Column(modifier = Modifier.fillMaxWidth()) {
            Text(
                "GitHub connector",
                color = KalivTheme.colors.textHigh,
                fontSize = 20.sp,
                fontWeight = FontWeight.Bold,
            )
            Text(
                "Repository-scope · connector-audit · tilbagekaldelig authority",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            if (loading) {
                CircularProgressIndicator(
                    modifier = Modifier.padding(top = 6.dp).height(20.dp),
                    strokeWidth = 2.dp,
                    color = KalivTheme.colors.signal,
                )
            }
        }

        error?.let {
            GitHubNeutralCard {
                Text(
                    "GitHub connector ikke tilgængelig",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(it, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text(
                    "Manglende connector-evidens bliver ikke fortolket som tomt scope eller fejlfri drift.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }
        }

        mutationError?.let {
            GitHubNeutralCard {
                Text(
                    "Tilbagekaldelse blev ikke gennemført",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 14.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(it, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                Text(
                    "Den lokale visning ændres først efter serverbekræftet revoke og efterfølgende refresh.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }
        }

        snapshot?.let { current ->
            GitHubNeutralCard {
                Text(
                    "Tilladelser",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "${current.activeGrants.size} aktive · ${current.grants.size - current.activeGrants.size} tilbagekaldte",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Text(
                    "Control Center kan kun tilbagekalde eksisterende GitHub-scope. Nye grants oprettes ikke fra denne visning.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
            }

            if (current.grants.isEmpty()) {
                GitHubNeutralCard {
                    Text(
                        "Ingen GitHub-tilladelser er registreret.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                current.grants.forEach { grant ->
                    GitHubGrantCard(
                        grant = grant,
                        pending = pendingRevokeId == grant.grantId,
                        revoking = revokingId == grant.grantId,
                        mutationBusy = mutationBusy,
                        onRequestRevoke = {
                            if (!mutationBusy) pendingRevokeId = grant.grantId
                        },
                        onCancelRevoke = { pendingRevokeId = null },
                        onConfirmRevoke = {
                            if (!mutationBusy) {
                                pendingRevokeId = null
                                onRevoke(grant)
                            }
                        },
                    )
                }
            }

            GitHubNeutralCard {
                Text(
                    "Connector-audit",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    "Connector-identitet kommer fra registreret connector=github-evidens og udledes aldrig af origin.",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
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
                    placeholder = { Text("fx ternedal/modelrig") },
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

            val connectorMatches = controlCenterGitHubConnectorMatchesFilter(connectorFilter)
            val filtered = if (connectorMatches) {
                current.filteredAudit(
                    repository = repositoryFilter,
                    operation = operationFilter,
                    outcome = outcomeFilter,
                )
            } else {
                emptyList()
            }
            Text(
                "Viser ${filtered.size} af ${current.audit.size} GitHub-auditposter",
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
            if (filtered.isEmpty()) {
                GitHubNeutralCard {
                    Text(
                        if (current.audit.isEmpty()) {
                            "Ingen connector-reads er registreret i den hentede GitHub-audit."
                        } else {
                            "Ingen GitHub-auditposter matcher de aktive filtre."
                        },
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                }
            } else {
                filtered.forEach { GitHubAuditCard(it) }
            }
        }
    }
}

@Composable
private fun GitHubGrantCard(
    grant: ControlCenterGitHubGrant,
    pending: Boolean,
    revoking: Boolean,
    mutationBusy: Boolean,
    onRequestRevoke: () -> Unit,
    onCancelRevoke: () -> Unit,
    onConfirmRevoke: () -> Unit,
) {
    GitHubNeutralCard {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    grant.account,
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    if (grant.active) "Aktiv GitHub-tilladelse" else "Tilbagekaldt GitHub-tilladelse",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
            }
            Text(
                if (grant.active) "AKTIV" else "REVOKED",
                color = if (grant.active) KalivTheme.colors.signal else KalivTheme.colors.textMuted,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
            )
        }
        Text(
            controlCenterGitHubExternalAccountLabel(grant.account),
            color = KalivTheme.colors.textHigh,
            fontSize = 11.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            controlCenterGitHubOutboundDataLabel(),
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        Text(
            "Repositories: ${grant.repositories.joinToString()}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Reads: ${grant.operations.joinToString { controlCenterGitHubOperationLabel(it) }}",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        Text(
            "Scope: ${grant.scopeSha256.take(16)}… · oprettet ${grant.createdAt}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        grant.revokedAt?.let {
            Text("Tilbagekaldt: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }

        if (grant.active && !pending) {
            OutlinedButton(onClick = onRequestRevoke, enabled = !mutationBusy) {
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
                "Bekræft: dette stopper nye GitHub-kald for præcis dette scope. Scope-digest genvalideres af serveren før ændringen.",
                color = KalivTheme.colors.textHigh,
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = onConfirmRevoke, enabled = !mutationBusy) {
                    Text("Bekræft tilbagekaldelse")
                }
                OutlinedButton(onClick = onCancelRevoke, enabled = !mutationBusy) {
                    Text("Annullér")
                }
            }
        }
    }
}

@Composable
private fun GitHubAuditCard(entry: ControlCenterGitHubAuditEntry) {
    GitHubNeutralCard {
        Text(
            "${controlCenterGitHubOperationLabel(entry.operation)} · ${controlCenterGitHubOutcomeLabel(entry.outcome)}",
            color = KalivTheme.colors.textHigh,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(entry.repository, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
        entry.objectId?.let {
            Text("Objekt: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }
        Text("Tid: ${entry.timestamp} · ${entry.durationMs} ms", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        entry.revision?.let {
            Text("Revision: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }
        entry.grantId?.let {
            Text("Grant: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
        }
        Text(
            "Detail: ${entry.detail}",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
        Text(
            "Issue/PR-body, diff, logtekst og credentials indgår ikke i connector-auditprojektionen.",
            color = KalivTheme.colors.textMuted,
            fontSize = 10.sp,
        )
    }
}

@Composable
private fun GitHubNeutralCard(content: @Composable () -> Unit) {
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

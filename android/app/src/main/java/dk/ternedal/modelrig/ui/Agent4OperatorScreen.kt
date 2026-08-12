package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
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
import dk.ternedal.modelrig.data.TokenStore
import dk.ternedal.modelrig.net.Agent4OperatorClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

private const val AGENT4_CAMPAIGN_PAGE_SIZE = 25

private sealed interface Agent4ScreenState {
    data object Loading : Agent4ScreenState
    data object PairingRequired : Agent4ScreenState
    data object GrantRequired : Agent4ScreenState
    data object FeatureDisabled : Agent4ScreenState
    data class Unavailable(val message: String) : Agent4ScreenState
    data class ProtocolFailure(val message: String) : Agent4ScreenState
    data class Ready(val page: Agent4OperatorClient.CampaignList) : Agent4ScreenState
}

/**
 * Read-only Agent 4 operator surface. It deliberately owns no lifecycle action,
 * grant administration or cached privileged data.
 */
@Composable
fun Agent4OperatorScreen(
    store: TokenStore,
    onClose: () -> Unit,
) {
    var selectedCampaignId by remember { mutableStateOf<String?>(null) }
    selectedCampaignId?.let { campaignId ->
        Agent4CampaignDetailScreen(
            store = store,
            campaignId = campaignId,
            onBack = { selectedCampaignId = null },
        )
        return
    }

    var refresh by remember { mutableIntStateOf(0) }
    var paging by remember { mutableStateOf(false) }
    var state: Agent4ScreenState by remember { mutableStateOf(Agent4ScreenState.Loading) }
    val scope = rememberCoroutineScope()
    val responseEpoch = remember { Agent4ResponseEpoch() }

    fun connection(): Agent4ConnectionIdentity? {
        val baseUrl = store.baseUrl?.trim().orEmpty()
        val token = store.token?.trim().orEmpty()
        return if (baseUrl.isBlank() || token.isBlank()) {
            null
        } else {
            Agent4ConnectionIdentity(baseUrl, token)
        }
    }

    fun failureState(failure: Throwable): Agent4ScreenState = when (failure) {
        is Agent4OperatorClient.OperatorException -> when (failure.kind) {
            Agent4OperatorClient.ErrorKind.AUTH_REQUIRED -> Agent4ScreenState.PairingRequired
            Agent4OperatorClient.ErrorKind.GRANT_REQUIRED -> Agent4ScreenState.GrantRequired
            Agent4OperatorClient.ErrorKind.FEATURE_DISABLED -> Agent4ScreenState.FeatureDisabled
            Agent4OperatorClient.ErrorKind.UNAVAILABLE ->
                Agent4ScreenState.Unavailable(failure.message.orEmpty())
            Agent4OperatorClient.ErrorKind.NOT_FOUND,
            Agent4OperatorClient.ErrorKind.REQUEST_REJECTED,
            Agent4OperatorClient.ErrorKind.PROTOCOL ->
                Agent4ScreenState.ProtocolFailure(failure.message.orEmpty())
        }
        is IllegalArgumentException ->
            Agent4ScreenState.ProtocolFailure(failure.message ?: "Campaign paging blev afvist")
        else -> Agent4ScreenState.Unavailable("Agent 4 kunne ikke indlæses")
    }

    LaunchedEffect(refresh, store.baseUrl, store.rigCredentialStatus) {
        state = Agent4ScreenState.Loading
        paging = false
        val currentConnection = connection()
        if (currentConnection == null) {
            responseEpoch.invalidate()
            state = Agent4ScreenState.PairingRequired
            return@LaunchedEffect
        }
        val ticket = responseEpoch.begin(currentConnection)
        try {
            val page = withContext(Dispatchers.IO) {
                Agent4OperatorClient(currentConnection.baseUrl, currentConnection.token)
                    .listCampaigns(limit = AGENT4_CAMPAIGN_PAGE_SIZE)
            }
            if (responseEpoch.accepts(ticket, connection())) {
                val campaigns = Agent4PagingPolicy.appendCampaigns(emptyList(), page.campaigns)
                state = Agent4ScreenState.Ready(page.copy(campaigns = campaigns))
            }
        } catch (failure: Throwable) {
            if (responseEpoch.accepts(ticket, connection())) {
                state = failureState(failure)
            }
        }
    }

    fun loadMore(current: Agent4OperatorClient.CampaignList) {
        val currentConnection = connection() ?: run {
            responseEpoch.invalidate()
            state = Agent4ScreenState.PairingRequired
            return
        }
        val ticket = responseEpoch.capture(currentConnection)
        paging = true
        scope.launch {
            try {
                val next = withContext(Dispatchers.IO) {
                    Agent4OperatorClient(currentConnection.baseUrl, currentConnection.token)
                        .listCampaigns(
                            after = current.nextCursor,
                            snapshotHead = current.headCursor,
                            limit = AGENT4_CAMPAIGN_PAGE_SIZE,
                        )
                }
                if (!responseEpoch.accepts(ticket, connection())) return@launch
                require(next.startCursor == current.nextCursor) {
                    "Agent 4 campaign-side starter ved en anden cursor end requestet"
                }
                require(next.headCursor == current.headCursor) {
                    "Agent 4 campaign-snapshot ændrede head under paging"
                }
                state = Agent4ScreenState.Ready(
                    current.copy(
                        campaigns = Agent4PagingPolicy.appendCampaigns(
                            current.campaigns,
                            next.campaigns,
                        ),
                        nextCursor = next.nextCursor,
                        hasMore = next.hasMore,
                    ),
                )
            } catch (failure: Throwable) {
                if (responseEpoch.accepts(ticket, connection())) {
                    state = failureState(failure)
                }
            } finally {
                if (responseEpoch.accepts(ticket, connection())) {
                    paging = false
                }
            }
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(20.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "Agent 4",
                    color = KalivTheme.colors.textHigh,
                    fontSize = 24.sp,
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    text = "Read-only kampagner, tidslinje og evidens",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 12.sp,
                )
            }
            OutlinedButton(onClick = onClose) { Text("Luk") }
        }

        Spacer(Modifier.height(12.dp))
        Surface(
            color = KalivTheme.colors.surface,
            shape = RoundedCornerShape(12.dp),
        ) {
            Text(
                text = "Kun læseadgang · ingen start, pause, annullering eller retry",
                modifier = Modifier.padding(12.dp),
                color = KalivTheme.colors.textMuted,
                fontSize = 12.sp,
            )
        }
        Spacer(Modifier.height(16.dp))

        when (val current = state) {
            Agent4ScreenState.Loading -> LoadingState()
            Agent4ScreenState.PairingRequired -> MessageState(
                title = "Rig-adgangen skal fornyes",
                message = "Par enheden igen i Kaliv-indstillingerne.",
                retry = { refresh++ },
            )
            Agent4ScreenState.GrantRequired -> MessageState(
                title = "Agent 4 er låst",
                message = "Denne enhed mangler den særskilte agent4:read-tilladelse. Tilladelsen kan kun gives lokalt på riggen.",
                retry = { refresh++ },
            )
            Agent4ScreenState.FeatureDisabled -> MessageState(
                title = "Agent 4 er ikke slået til",
                message = "Read-fladen er ikke aktiveret på riggen. Appen åbner ingen fallback eller direkte worker-forbindelse.",
                retry = { refresh++ },
            )
            is Agent4ScreenState.Unavailable -> MessageState(
                title = "Agent 4 er ikke tilgængelig",
                message = current.message,
                retry = { refresh++ },
            )
            is Agent4ScreenState.ProtocolFailure -> MessageState(
                title = "Agent 4-svaret blev afvist",
                message = current.message,
                retry = { refresh++ },
            )
            is Agent4ScreenState.Ready -> CampaignListState(
                page = current.page,
                paging = paging,
                refresh = { refresh++ },
                loadMore = { loadMore(current.page) },
                openCampaign = { selectedCampaignId = it },
            )
        }
    }
}

@Composable
private fun LoadingState() {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        CircularProgressIndicator()
        Spacer(Modifier.height(12.dp))
        Text("Indlæser read-only Agent 4-data…", color = KalivTheme.colors.textMuted)
    }
}

@Composable
private fun MessageState(
    title: String,
    message: String,
    retry: () -> Unit,
) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(title, color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            Text(message, color = KalivTheme.colors.textMuted, fontSize = 13.sp)
            Spacer(Modifier.height(12.dp))
            Button(onClick = retry) { Text("Prøv igen") }
        }
    }
}

@Composable
private fun CampaignListState(
    page: Agent4OperatorClient.CampaignList,
    paging: Boolean,
    refresh: () -> Unit,
    loadMore: () -> Unit,
    openCampaign: (String) -> Unit,
) {
    if (page.campaigns.isEmpty()) {
        MessageState(
            title = "Ingen kampagner",
            message = "Agent 4-readfladen er tilgængelig, men datarooten indeholder ingen kampagner.",
            retry = refresh,
        )
        return
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = "${page.campaigns.size} kampagner indlæst",
            color = KalivTheme.colors.textHigh,
            fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(1f),
        )
        OutlinedButton(onClick = refresh, enabled = !paging) { Text("Opdatér") }
    }
    Spacer(Modifier.height(8.dp))
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        items(page.campaigns, key = { it.campaignId }) { campaign ->
            Surface(
                color = KalivTheme.colors.surface,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = campaign.name,
                            color = KalivTheme.colors.textHigh,
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.weight(1f),
                        )
                        Text(
                            text = campaign.status.wireValue,
                            color = KalivTheme.colors.signal,
                            fontSize = 12.sp,
                        )
                    }
                    Text(
                        text = campaign.campaignId,
                        color = KalivTheme.colors.textMuted,
                        fontSize = 11.sp,
                    )
                    Spacer(Modifier.height(8.dp))
                    HorizontalDivider()
                    Spacer(Modifier.height(8.dp))
                    Text(
                        text = "Tidslinje ${campaign.timelineEntries} · events ${campaign.eventEntries} · evidens ${campaign.evidenceEntries}",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 12.sp,
                    )
                    campaign.latestTimelineHash?.let {
                        Text(
                            text = it,
                            color = KalivTheme.colors.textMuted,
                            fontSize = 10.sp,
                            maxLines = 1,
                        )
                    }
                    Spacer(Modifier.height(10.dp))
                    OutlinedButton(onClick = { openCampaign(campaign.campaignId) }) {
                        Text("Se detail, tidslinje og evidens")
                    }
                }
            }
        }
        if (page.hasMore) {
            item {
                OutlinedButton(onClick = loadMore, enabled = !paging) {
                    Text(if (paging) "Henter…" else "Hent næste kampagneside")
                }
            }
        }
        item { Spacer(Modifier.height(18.dp)) }
    }
}

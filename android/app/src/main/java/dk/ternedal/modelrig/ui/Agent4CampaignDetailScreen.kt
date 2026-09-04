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
import dk.ternedal.modelrig.ui.components.kalivScreenInsets

private const val AGENT4_PAGE_SIZE = 25

private data class Agent4DetailData(
    val campaign: Agent4OperatorClient.CampaignOverview,
    val detail: Agent4CampaignDetail,
    val verification: Agent4OperatorClient.EvidenceVerification,
    val timeline: List<Agent4TimelineRow>,
    val timelineNext: Agent4OperatorClient.Cursor,
    val timelineHead: Agent4OperatorClient.Cursor,
    val timelineHasMore: Boolean,
    val evidence: List<Agent4EvidenceRow>,
    val evidenceNext: Agent4OperatorClient.Cursor,
    val evidenceHead: Agent4OperatorClient.Cursor,
    val evidenceHasMore: Boolean,
)

private sealed interface Agent4DetailLoadState {
    data object Loading : Agent4DetailLoadState
    data class Failed(val title: String, val message: String) : Agent4DetailLoadState
    data class Ready(val value: Agent4DetailData) : Agent4DetailLoadState
}

@Composable
internal fun Agent4CampaignDetailScreen(
    store: TokenStore,
    campaignId: String,
    onBack: () -> Unit,
) {
    var generation by remember { mutableIntStateOf(0) }
    var state: Agent4DetailLoadState by remember { mutableStateOf(Agent4DetailLoadState.Loading) }
    var pagingTimeline by remember { mutableStateOf(false) }
    var pagingEvidence by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val responseEpoch = remember { Agent4ResponseEpoch() }

    fun credentials(): Agent4ConnectionIdentity? {
        val base = store.baseUrl?.trim().orEmpty()
        val token = store.token?.trim().orEmpty()
        return if (base.isBlank() || token.isBlank()) null else Agent4ConnectionIdentity(base, token)
    }

    fun fail(failure: Throwable): Agent4DetailLoadState.Failed = when (failure) {
        is Agent4OperatorClient.OperatorException -> when (failure.kind) {
            Agent4OperatorClient.ErrorKind.AUTH_REQUIRED ->
                Agent4DetailLoadState.Failed("Rig-adgangen skal fornyes", "Par enheden igen i Kaliv-indstillingerne.")
            Agent4OperatorClient.ErrorKind.GRANT_REQUIRED ->
                Agent4DetailLoadState.Failed("Agent 4 er låst", "Denne enhed mangler agent4:read. Tidligere viste data er ryddet.")
            Agent4OperatorClient.ErrorKind.FEATURE_DISABLED ->
                Agent4DetailLoadState.Failed("Agent 4 er ikke slået til", "Read-fladen er deaktiveret på riggen. Tidligere viste data er ryddet.")
            Agent4OperatorClient.ErrorKind.NOT_FOUND ->
                Agent4DetailLoadState.Failed("Kampagnen findes ikke", failure.message.orEmpty())
            Agent4OperatorClient.ErrorKind.REQUEST_REJECTED,
            Agent4OperatorClient.ErrorKind.PROTOCOL ->
                Agent4DetailLoadState.Failed("Agent 4-svaret blev afvist", failure.message.orEmpty())
            Agent4OperatorClient.ErrorKind.UNAVAILABLE ->
                Agent4DetailLoadState.Failed("Agent 4 er ikke tilgængelig", failure.message.orEmpty())
        }
        is IllegalArgumentException -> Agent4DetailLoadState.Failed(
            "Agent 4-svaret blev afvist",
            failure.message ?: "Paging-kontrakten blev brudt",
        )
        else -> Agent4DetailLoadState.Failed("Agent 4 kunne ikke indlæses", failure.message.orEmpty())
    }

    LaunchedEffect(campaignId, generation, store.baseUrl, store.rigCredentialStatus) {
        state = Agent4DetailLoadState.Loading
        pagingTimeline = false
        pagingEvidence = false
        val connection = credentials()
        if (connection == null) {
            responseEpoch.invalidate()
            state = Agent4DetailLoadState.Failed(
                "Rig-adgangen mangler",
                "Par enheden med ModelRig i indstillingerne.",
            )
            return@LaunchedEffect
        }
        val ticket = responseEpoch.begin(connection)
        try {
            val loaded = withContext(Dispatchers.IO) {
                val client = Agent4OperatorClient(connection.baseUrl, connection.token)
                val campaign = client.campaign(campaignId)
                val timelinePage = client.timeline(campaignId, limit = AGENT4_PAGE_SIZE)
                val evidencePage = client.evidencePage(campaignId, limit = AGENT4_PAGE_SIZE)
                val verification = client.evidenceVerification(campaignId)
                Agent4DetailSnapshotPolicy.requireConsistent(
                    campaign = campaign,
                    timelineHead = timelinePage.headCursor,
                    evidenceHead = evidencePage.headCursor,
                    verification = verification,
                )
                val timelineRows = timelinePage.entries.map(Agent4OperatorPresentation::timelineRow)
                val evidenceRows = evidencePage.records.map(Agent4OperatorPresentation::evidenceRow)
                Agent4DetailData(
                    campaign = campaign,
                    detail = Agent4OperatorPresentation.campaignDetail(campaign.record),
                    verification = verification,
                    timeline = Agent4PagingPolicy.appendTimeline(emptyList(), timelineRows),
                    timelineNext = timelinePage.nextCursor,
                    timelineHead = timelinePage.headCursor,
                    timelineHasMore = timelinePage.hasMore,
                    evidence = Agent4PagingPolicy.appendEvidence(emptyList(), evidenceRows),
                    evidenceNext = evidencePage.nextCursor,
                    evidenceHead = evidencePage.headCursor,
                    evidenceHasMore = evidencePage.hasMore,
                )
            }
            if (responseEpoch.accepts(ticket, credentials())) state = Agent4DetailLoadState.Ready(loaded)
        } catch (failure: Throwable) {
            if (responseEpoch.accepts(ticket, credentials())) state = fail(failure)
        }
    }

    fun loadMoreTimeline(current: Agent4DetailData) {
        val connection = credentials() ?: run {
            responseEpoch.invalidate()
            state = Agent4DetailLoadState.Failed("Rig-adgangen mangler", "Tidligere viste data er ryddet.")
            return
        }
        val ticket = responseEpoch.capture(connection)
        pagingTimeline = true
        scope.launch {
            try {
                val page = withContext(Dispatchers.IO) {
                    Agent4OperatorClient(connection.baseUrl, connection.token).timeline(
                        campaignId = campaignId,
                        after = current.timelineNext,
                        snapshotHead = current.timelineHead,
                        limit = AGENT4_PAGE_SIZE,
                    )
                }
                if (!responseEpoch.accepts(ticket, credentials())) return@launch
                val rows = page.entries.map(Agent4OperatorPresentation::timelineRow)
                val active = (state as? Agent4DetailLoadState.Ready)?.value
                if (active != null) {
                    require(page.startCursor == active.timelineNext) {
                        "Agent 4 timeline-side starter ved en anden cursor end requestet"
                    }
                    require(page.headCursor == active.timelineHead) {
                        "Agent 4 timeline-snapshot ændrede head under paging"
                    }
                    state = Agent4DetailLoadState.Ready(
                        active.copy(
                            timeline = Agent4PagingPolicy.appendTimeline(active.timeline, rows),
                            timelineNext = page.nextCursor,
                            timelineHasMore = page.hasMore,
                        ),
                    )
                }
            } catch (failure: Throwable) {
                if (responseEpoch.accepts(ticket, credentials())) state = fail(failure)
            } finally {
                if (responseEpoch.accepts(ticket, credentials())) pagingTimeline = false
            }
        }
    }

    fun loadMoreEvidence(current: Agent4DetailData) {
        val connection = credentials() ?: run {
            responseEpoch.invalidate()
            state = Agent4DetailLoadState.Failed("Rig-adgangen mangler", "Tidligere viste data er ryddet.")
            return
        }
        val ticket = responseEpoch.capture(connection)
        pagingEvidence = true
        scope.launch {
            try {
                val page = withContext(Dispatchers.IO) {
                    Agent4OperatorClient(connection.baseUrl, connection.token).evidencePage(
                        campaignId = campaignId,
                        after = current.evidenceNext,
                        snapshotHead = current.evidenceHead,
                        limit = AGENT4_PAGE_SIZE,
                    )
                }
                if (!responseEpoch.accepts(ticket, credentials())) return@launch
                val rows = page.records.map(Agent4OperatorPresentation::evidenceRow)
                val active = (state as? Agent4DetailLoadState.Ready)?.value
                if (active != null) {
                    require(page.startCursor == active.evidenceNext) {
                        "Agent 4 evidence-side starter ved en anden cursor end requestet"
                    }
                    require(page.headCursor == active.evidenceHead) {
                        "Agent 4 evidence-snapshot ændrede head under paging"
                    }
                    state = Agent4DetailLoadState.Ready(
                        active.copy(
                            evidence = Agent4PagingPolicy.appendEvidence(active.evidence, rows),
                            evidenceNext = page.nextCursor,
                            evidenceHasMore = page.hasMore,
                        ),
                    )
                }
            } catch (failure: Throwable) {
                if (responseEpoch.accepts(ticket, credentials())) state = fail(failure)
            } finally {
                if (responseEpoch.accepts(ticket, credentials())) pagingEvidence = false
            }
        }
    }

    val visibleCampaignId = (state as? Agent4DetailLoadState.Ready)?.value?.campaign?.campaignId

    Column(
        modifier = Modifier
            .fillMaxSize()
            .kalivScreenInsets()
            .padding(20.dp),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Text("Agent 4-kampagne", color = KalivTheme.colors.textHigh, fontSize = 23.sp, fontWeight = FontWeight.Bold)
                visibleCampaignId?.let {
                    Text(it, color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                }
            }
            OutlinedButton(onClick = onBack) { Text("Tilbage") }
        }
        Spacer(Modifier.height(14.dp))

        when (val current = state) {
            Agent4DetailLoadState.Loading -> Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                CircularProgressIndicator()
                Spacer(Modifier.height(10.dp))
                Text("Indlæser canonical detail, tidslinje og evidens…", color = KalivTheme.colors.textMuted)
            }
            is Agent4DetailLoadState.Failed -> Surface(
                color = KalivTheme.colors.surface,
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth(),
            ) {
                Column(Modifier.padding(16.dp)) {
                    Text(current.title, color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(6.dp))
                    Text(current.message, color = KalivTheme.colors.textMuted)
                    Spacer(Modifier.height(12.dp))
                    Button(onClick = { generation++ }) { Text("Prøv igen") }
                }
            }
            is Agent4DetailLoadState.Ready -> Agent4DetailContent(
                data = current.value,
                pagingTimeline = pagingTimeline,
                pagingEvidence = pagingEvidence,
                refresh = { generation++ },
                loadMoreTimeline = { loadMoreTimeline(current.value) },
                loadMoreEvidence = { loadMoreEvidence(current.value) },
            )
        }
    }
}

@Composable
private fun Agent4DetailContent(
    data: Agent4DetailData,
    pagingTimeline: Boolean,
    pagingEvidence: Boolean,
    refresh: () -> Unit,
    loadMoreTimeline: () -> Unit,
    loadMoreEvidence: () -> Unit,
) {
    LazyColumn(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        item {
            Agent4DetailCard("Kampagne") {
                Text(data.campaign.name, color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
                Text("Status: ${data.campaign.status.wireValue}", color = KalivTheme.colors.signal)
                Text("Workflow: ${data.detail.workflow}", color = KalivTheme.colors.textMuted)
                Text("Oprettet: ${data.detail.createdAt}", color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text("Forsøg ${data.detail.attempt}/${data.detail.maxAttempts} · revision ${data.detail.revision} · prioritet ${data.detail.priority}", color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                data.detail.lastError?.let { Text("Seneste fejl: $it", color = KalivTheme.colors.danger, fontSize = 12.sp) }
                Spacer(Modifier.height(8.dp))
                OutlinedButton(onClick = refresh) { Text("Opdatér alt") }
            }
        }
        item {
            Agent4DetailCard("Evidens-verifikation") {
                Text("Records: ${data.verification.recordCount}", color = KalivTheme.colors.textHigh)
                Text("Head: ${data.verification.headHash ?: "ingen"}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                Text("Timeline-head: ${data.verification.latestTimelineHeadHash ?: "ingen"}", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
            }
        }
        item { Text("Tidslinje", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold) }
        items(data.timeline, key = { "timeline-${it.sequence}-${it.eventId}" }) { row ->
            Agent4DetailCard("#${row.sequence} · ${row.kind}") {
                Text(row.occurredAt, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text(row.eventId, color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                Text("Evidensrefs: ${row.evidenceCount}", color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text(row.entryHash, color = KalivTheme.colors.textMuted, fontSize = 9.sp, maxLines = 1)
            }
        }
        if (data.timelineHasMore) {
            item {
                OutlinedButton(onClick = loadMoreTimeline, enabled = !pagingTimeline) {
                    Text(if (pagingTimeline) "Henter…" else "Hent næste tidslinjeside")
                }
            }
        }
        item {
            HorizontalDivider()
            Spacer(Modifier.height(6.dp))
            Text("Evidens", color = KalivTheme.colors.textHigh, fontSize = 18.sp, fontWeight = FontWeight.Bold)
        }
        items(data.evidence, key = { "evidence-${it.sequence}-${it.evidenceId}" }) { row ->
            Agent4DetailCard("#${row.sequence} · ${row.evidenceId}") {
                Text(row.mediaType, color = KalivTheme.colors.signal, fontSize = 12.sp)
                Text(row.location, color = KalivTheme.colors.textMuted, fontSize = 12.sp)
                Text("${row.sizeBytes} bytes · ${row.recordedAt}", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                Text(row.recordHash, color = KalivTheme.colors.textMuted, fontSize = 9.sp, maxLines = 1)
            }
        }
        if (data.evidenceHasMore) {
            item {
                OutlinedButton(onClick = loadMoreEvidence, enabled = !pagingEvidence) {
                    Text(if (pagingEvidence) "Henter…" else "Hent næste evidensside")
                }
            }
        }
        item { Spacer(Modifier.height(20.dp)) }
    }
}

@Composable
private fun Agent4DetailCard(
    title: String,
    content: @Composable () -> Unit,
) {
    Surface(
        color = KalivTheme.colors.surface,
        shape = RoundedCornerShape(14.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(title, color = KalivTheme.colors.textHigh, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(7.dp))
            content()
        }
    }
}

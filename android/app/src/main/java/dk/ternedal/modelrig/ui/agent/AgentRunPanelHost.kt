package dk.ternedal.modelrig.ui.agent

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.net.Agent3TaskReadinessClient
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Agent-panelet i chatten — ADR-A3-001 slice 2.
 *
 * Dette er den ENE indgang chatten har til Agent 3. Chatskærmen kalder den
 * med samtalens id og ved ellers intet om agenten: alt hvad der taler med
 * riggen, bor her i ui/agent-pakken, og dvale-gaten håndhæver netop den
 * arbejdsdeling.
 *
 * Tre egenskaber er værd at kende:
 *
 *  - VISER, STARTER IKKE. Panelet kan ikke sætte en kørsel i gang; det viser
 *    den kørsel der er BUNDET til denne samtale. Start kommer i slice 3, og
 *    kun fra en eksplicit handling.
 *  - FAIL-QUIET. Agent 3 er slukket på riggen som udgangspunkt. Svarer ruten
 *    ikke, holder vi op med at spørge i denne session — ingen banken på hvert
 *    femte sekund, ingen fejl i ansigtet på nogen der ikke bruger agenten.
 *  - ANTAGER ALDRIG STOP. Forsvinder svaret MENS en bundet kørsel er i gang,
 *    siger panelet at det ikke længere kan se kørslen. Det VED ikke om den er
 *    stoppet, og må derfor ikke påstå det.
 */
/**
 * Start af en kørsel fra chatten — ADR-A3-001 slice 3.
 *
 * Kaldes KUN fra en eksplicit menneskehandling; kilden bæres helt ind i
 * AgentStartPolicy, så reglen kan bevises frem for at loves. Rækkefølgen er
 * preview → politik → (måske) start: vi spørger altså riggen hvad planen
 * indeholder, FØR noget køres, og et skrivetrin stopper starten her.
 */
@Composable
fun AgentStartHost(
    baseUrl: String?,
    token: String?,
    conversationId: String?,
    message: String,
    source: AgentStartPolicy.Source,
    onOpenApproval: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val bindings = remember { AgentRunBinding(context) }
    val scope = rememberCoroutineScope()
    var preview by remember(message) { mutableStateOf<Agent3Client.PlanPreview?>(null) }
    var busy by remember(message) { mutableStateOf(false) }
    var error by remember(message) { mutableStateOf<String?>(null) }

    val gate = AgentStartPolicy.verdict(source, message)
    if (gate !is AgentStartPolicy.Verdict.Start || baseUrl.isNullOrBlank() || token.isNullOrBlank()) return

    LaunchedEffect(message, baseUrl, token) {
        val res = withContext(Dispatchers.IO) {
            runCatching { Agent3Client(baseUrl, token).previewPlan(message = gate.message, conversationId = conversationId) }
        }
        res.onSuccess { preview = it }.onFailure { error = "Riggen kunne ikke lægge en plan." }
    }

    val p = preview
    Column(modifier.fillMaxWidth()) {
        when {
            error != null -> AgentRunUnavailableNote()
            p == null -> Unit
            else -> {
                val writes = p.steps.count { AgentStartPolicy.isWriteStep(it) }
                AgentPlanPreviewCard(
                    title = AgentRunPresentation.titleOf(p.routeKind),
                    steps = AgentRunPresentation.previewSteps(p.steps),
                    writeSteps = writes,
                    busy = busy,
                    onDismiss = onDismiss,
                    onOpenApproval = onOpenApproval,
                    onStartReadOnly = {
                        // Starten går gennem vagten — den ER politikken, og den
                        // er det eneste sted i fladen der må kalde riggen om
                        // det. Afvises den, sker der ingenting her.
                        busy = true
                        scope.launch {
                            val res = withContext(Dispatchers.IO) {
                                runCatching {
                                    AgentStartGuard.start(
                                        client = Agent3Client(baseUrl, token),
                                        source = source,
                                        message = message,
                                        steps = p.steps,
                                        planId = p.planId,
                                    )
                                }
                            }
                            busy = false
                            res.onSuccess { run ->
                                if (run == null) {
                                    error = "Planen må ikke startes herfra."
                                } else {
                                    bindings.bind(conversationId, run.id)
                                    onDismiss()
                                }
                            }.onFailure { error = "Kørslen kunne ikke startes." }
                        }
                    },
                )
            }
        }
    }
}

@Composable
fun AgentRunPanelHost(
    baseUrl: String?,
    token: String?,
    conversationId: String?,
    onOpenCheckpoint: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val bindings = remember { AgentRunBinding(context) }
    val boundRunId = remember(conversationId) { bindings.runFor(conversationId) }
    if (boundRunId == null || baseUrl.isNullOrBlank() || token.isNullOrBlank()) return

    val scope = rememberCoroutineScope()
    var run by remember(boundRunId) { mutableStateOf<Agent3Client.Run?>(null) }
    var reachable by remember(boundRunId) { mutableStateOf(true) }
    var stopArmed by remember(boundRunId) { mutableStateOf(false) }
    var stopping by remember(boundRunId) { mutableStateOf(false) }
    // Fladen og begrundelsen kommer fra riggens egen readiness -- panelet
    // kendte kun planens rutenavn, så operatøren kunne ikke se hvilken flade
    // der kørte, hvorfor, eller at den var faldet tilbage til agent2.
    var surface by remember(boundRunId) {
        mutableStateOf<AgentRunPresentation.SurfaceUi?>(null)
    }
    // Omplanlægninger er en del af det operatøren skal kunne se
    // (replans_visible). Null betyder "riggen tæller dem ikke her", og så
    // vises linjen ikke -- ikke "0".
    var replans by remember(boundRunId) { mutableStateOf<Int?>(null) }

    LaunchedEffect(boundRunId, baseUrl, token) {
        // Readiness er billig og ændrer sig sjældent under en kørsel: hentes
        // én gang, og udebliver den, viser panelet bare ingen fladelinje
        // frem for at gætte på operatørens vegne.
        val ready = withContext(Dispatchers.IO) {
            runCatching { Agent3TaskReadinessClient(baseUrl, token).readiness() }
        }
        surface = ready.getOrNull()?.let { AgentRunPresentation.surfaceUi(it) }
    }

    LaunchedEffect(boundRunId, baseUrl, token) {
        var keepAsking = true
        while (keepAsking) {
            val res = withContext(Dispatchers.IO) {
                runCatching { Agent3Client(baseUrl, token).listRuns() }
            }
            res.onSuccess { runs ->
                reachable = true
                val visible = AgentRunPresentation.visibleRun(runs, boundRunId)
                run = visible
                if (visible != null) {
                    replans = withContext(Dispatchers.IO) {
                        Agent3Client(baseUrl, token).replanCount(visible.id)
                    }
                }
                if (visible == null) {
                    // Kørslen er slut (eller findes ikke mere): bindingen skal
                    // ikke overleve den, ellers spøger den i samtalen.
                    bindings.clear(conversationId)
                    keepAsking = false
                }
            }.onFailure {
                reachable = false
                keepAsking = false
            }
            if (keepAsking) delay(5_000)
        }
    }

    val current = run
    Column(modifier.fillMaxWidth()) {
        if (!reachable) {
            AgentRunUnavailableNote()
            return@Column
        }
        if (current == null) return@Column
        surface?.let { ui ->
            AgentSurfaceNote(
                line = AgentRunPresentation.surfaceLine(ui),
                fallback = AgentRunPresentation.fallbackLine(ui),
                replans = AgentRunPresentation.replanLine(replans),
            )
            Spacer(Modifier.height(6.dp))
        }
        AgentRunCard(
            steps = AgentRunPresentation.steps(current),
            title = AgentRunPresentation.title(current),
            onStop = { stopArmed = true },
            onOpen = onOpenCheckpoint,
        )
        if (stopArmed) {
            Spacer(Modifier.height(6.dp))
            AgentRunStopConfirm(
                busy = stopping,
                onCancel = { stopArmed = false },
                onConfirm = {
                    stopping = true
                    scope.launch {
                        val res = withContext(Dispatchers.IO) {
                            runCatching { Agent3Client(baseUrl, token).cancel(current.id) }
                        }
                        stopping = false
                        stopArmed = false
                        // RIGGENS svar bestemmer — ikke vores håb.
                        res.onSuccess { updated ->
                            if (AgentRunPresentation.isTerminal(updated)) {
                                bindings.clear(conversationId)
                                run = null
                            } else {
                                run = updated
                            }
                        }
                    }
                },
            )
        }
    }
}

/**
 * Når ruten ikke svarer, mens en bundet kørsel er i gang.
 *
 * Teksten siger præcis hvad vi ved — og hvad vi ikke ved. "Stoppet" ville
 * være et gæt, og et gæt om en kørsel der måske stadig arbejder på riggen er
 * den værste slags.
 */
@Composable
private fun AgentSurfaceNote(
    line: String,
    fallback: String?,
    replans: String?,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Text(
            line,
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )
        if (replans != null) {
            Text(
                replans,
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
            )
        }
        if (fallback != null) {
            Text(
                fallback,
                color = KalivTheme.colors.danger,
                fontSize = 11.sp,
            )
        }
    }
}

@Composable
fun AgentRunUnavailableNote(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 12.dp),
    ) {
        Text(
            "Kan ikke længere se kørslen",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(3.dp))
        Text(
            "Riggen svarer ikke på agent-kald lige nu. Om planen stadig kører, ved telefonen ikke.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

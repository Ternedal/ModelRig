package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.Agent3Client
import dk.ternedal.modelrig.desktop.net.Agent3Run
import dk.ternedal.modelrig.desktop.net.Agent3Step
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * The 1b agent cockpit, built on Agent 3 instead of the V2 tools loop.
 *
 * Why this exists next to KalivAgentCockpit rather than replacing it (Sol,
 * 25/07): "Byg 1b mod Agent 3 nu, men kun som developer/experimental cockpit;
 * flyt ikke normal chat fra V2, før den fysiske validering og Anders'
 * eksplicitte aktivering er bestået." Agent 3 is still served behind
 * KALIV_AGENT3_ENABLED and under /experimental/, and the readiness page refuses
 * activation without a physical report. So both surfaces exist, and the normal
 * chat path is untouched.
 *
 * The design handoff describes THIS model, not V2's. The mockup's
 * "Agent-plan · 2 af 4 trin" needs a known total, and only Agent 3 has one: the
 * planner returns the whole list (max 12 steps), it is stored server-side
 * behind a single-use plan_id, and start clones it into the run.
 *
 * Sol's invariant, which shapes every line below: **the client must not
 * reconstruct run, approval or replan semantics locally.** So this composable
 * holds no opinion about what a step means. It renders `run.steps` with each
 * step's own `state`, uses `run.currentStep` as the pointer, and approves with
 * the server's `confirmation_digest`. Where a state string is unknown to the
 * icon mapping, the raw string is still shown -- an unrecognised state must
 * look unrecognised, not quietly become "pending".
 */
@Composable
fun KalivAgentCockpitA3(
    baseUrl: String,
    bearer: String?,
    modifier: Modifier = Modifier,
) {
    val scope = rememberCoroutineScope()
    var input by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var unavailable by remember { mutableStateOf<String?>(null) }
    var error by remember { mutableStateOf<String?>(null) }

    // Server state, held as-is. Nothing here is derived.
    var planId by remember { mutableStateOf<String?>(null) }
    var previewSteps by remember { mutableStateOf<List<Agent3Step>>(emptyList()) }
    var rationale by remember { mutableStateOf("") }
    var run by remember { mutableStateOf<Agent3Run?>(null) }
    // A replan may replace the remaining pending read-suffix, so the total is
    // not eternal. The mockup's "2 af 4" becomes "Plan 2 · 2 af 5" when that
    // happens -- pretending the first total still holds would be a lie.
    var revision by remember { mutableStateOf(1) }
    var lastTotal by remember { mutableStateOf(0) }
    val log = remember { mutableStateListOf<String>() }

    fun client() = Agent3Client(baseUrl, bearer.orEmpty())

    // Availability is discovered, not assumed: Agent 3 is dormant unless the
    // rig opted in, and a cockpit that pretends otherwise would fail at the
    // first click with a confusing error.
    LaunchedEffect(baseUrl, bearer) {
        val r = withContext(Dispatchers.IO) { runCatching { client().listRuns() } }
        unavailable = if (r.isSuccess) null else
            "Agent 3 svarer ikke på denne rig. Den serveres kun med " +
                "KALIV_AGENT3_ENABLED=1 og ligger under /experimental/."
    }

    fun refresh(runId: String) {
        scope.launch {
            val r = withContext(Dispatchers.IO) { runCatching { client().getRun(runId) } }
            r.onSuccess { fresh ->
                val total = fresh.steps.size
                if (lastTotal != 0 && total != lastTotal) revision += 1
                lastTotal = total
                run = fresh
            }.onFailure { error = it.message }
            val ev = withContext(Dispatchers.IO) { runCatching { client().events(runId) } }
            ev.onSuccess { list ->
                log.clear()
                list.takeLast(40).forEach { log.add(it.kind) }
            }
        }
    }

    fun preview() {
        val text = input.trim()
        if (text.isEmpty() || busy) return
        busy = true; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) {
                runCatching { client().previewPlan(message = text) }
            }
            r.onSuccess { p ->
                planId = p.planId
                previewSteps = p.plan
                rationale = p.rationale
                lastTotal = p.plan.size
                revision = 1
                run = null
            }.onFailure { error = it.message }
            busy = false
        }
    }

    fun start() {
        val id = planId ?: return
        busy = true; error = null
        scope.launch {
            val r = withContext(Dispatchers.IO) { runCatching { client().startPlan(id) } }
            r.onSuccess {
                run = it
                lastTotal = it.steps.size
                planId = null // single-use: the id cannot be started twice
                refresh(it.id)
            }.onFailure { error = it.message }
            busy = false
        }
    }

    fun decide(step: Agent3Step, approve: Boolean) {
        val r = run ?: return
        val sid = step.id ?: return
        val digest = step.confirmationDigest ?: return
        busy = true
        scope.launch {
            val res = withContext(Dispatchers.IO) {
                runCatching { client().confirm(r.id, sid, digest, approve) }
            }
            res.onSuccess { run = it; refresh(it.id) }.onFailure { error = it.message }
            busy = false
        }
    }

    fun cancel() {
        val r = run ?: return
        scope.launch {
            withContext(Dispatchers.IO) { runCatching { client().cancel(r.id) } }
                .onSuccess { run = it; refresh(it.id) }
        }
    }

    val steps = run?.steps ?: previewSteps
    val doneCount = steps.count { isTerminal(it.state) }

    Row(modifier.fillMaxSize()) {
        // ---------------------------------------------------------- task
        Column(
            Modifier.width(360.dp).fillMaxHeight()
                .border(1.dp, Color(0x33785A37))
                .padding(24.dp),
        ) {
            Text("Opgave", color = KalivTheme.colors.TextHigh, fontSize = 17.sp,
                fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(6.dp))
            Text(
                "Agent 3 lægger en fuld plan først. Du ser den før noget kører.",
                color = KalivTheme.colors.TextMuted, fontSize = 12.5.sp,
            )
            Spacer(Modifier.height(16.dp))

            if (unavailable != null) {
                KalivCard {
                    Text(unavailable!!, color = KalivTheme.colors.Warning, fontSize = 12.5.sp)
                }
            } else {
                AgentComposer(
                    value = input, onValue = { input = it },
                    enabled = !busy, placeholder = "Ny opgave \u2026",
                    onSend = { preview() },
                )
                if (rationale.isNotBlank()) {
                    Spacer(Modifier.height(14.dp))
                    SectionLabel("PLANNERENS BEGRUNDELSE")
                    Spacer(Modifier.height(6.dp))
                    Text(rationale, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                }
                if (planId != null) {
                    Spacer(Modifier.height(16.dp))
                    Row {
                        PrimaryButton("Start planen", enabled = !busy) { start() }
                        Spacer(Modifier.width(8.dp))
                        OutlineButton("Kassér") { planId = null; previewSteps = emptyList() }
                    }
                }
                if (run != null && !isTerminal(run!!.state)) {
                    Spacer(Modifier.height(16.dp))
                    OutlineButton("\u25A0  Stop") { cancel() }
                }
            }
            error?.let {
                Spacer(Modifier.height(14.dp))
                Text(it, color = KalivTheme.colors.Danger, fontSize = 12.sp)
            }
        }

        // ---------------------------------------------------------- plan
        Column(
            Modifier.weight(1f).fillMaxHeight().padding(24.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Agent-plan", color = KalivTheme.colors.TextHigh, fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold, softWrap = false, maxLines = 1)
                if (steps.isNotEmpty()) {
                    Spacer(Modifier.width(10.dp))
                    // Revision is shown as soon as one exists: a replan changes
                    // the total, and the header must not keep claiming the
                    // original plan is still what will happen.
                    val prefix = if (revision > 1) "Plan $revision \u00b7 " else ""
                    Text("$prefix$doneCount af ${steps.size} trin",
                        color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
                }
                Spacer(Modifier.weight(1f))
                run?.let {
                    Text("run: ${it.state}", color = KalivTheme.colors.TextMuted,
                        fontSize = 11.sp, fontFamily = FontFamily.Monospace,
                        softWrap = false, maxLines = 1)
                }
            }
            Spacer(Modifier.height(18.dp))

            if (steps.isEmpty()) {
                Text(
                    if (unavailable != null) "\u2014" else
                        "Skriv en opgave til venstre.\nAgent 3 planlægger hele forløbet, " +
                            "og du godkender hver skrivning.",
                    color = KalivTheme.colors.TextMuted, fontSize = 13.sp,
                )
            } else {
                steps.forEachIndexed { i, s ->
                    A3StepRow(
                        index = i + 1,
                        step = s,
                        isCurrent = run?.currentStep == i,
                        onApprove = { decide(s, true) },
                        onReject = { decide(s, false) },
                        busy = busy,
                    )
                }
                run?.answer?.takeIf { it.isNotBlank() }?.let {
                    Spacer(Modifier.height(16.dp))
                    KalivCard { Text(it, color = KalivTheme.colors.TextHigh, fontSize = 13.5.sp) }
                }
            }
        }

        // ----------------------------------------------------------- log
        Column(
            Modifier.width(264.dp).fillMaxHeight()
                .background(Color(0x8014110E)).padding(20.dp)
                .verticalScroll(rememberScrollState()),
        ) {
            SectionLabel("HÆNDELSER")
            Spacer(Modifier.height(12.dp))
            if (log.isEmpty()) {
                Text("(ingen endnu)", color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
            } else {
                log.forEach {
                    Text(it, color = KalivTheme.colors.TextMuted, fontSize = 11.5.sp,
                        fontFamily = FontFamily.Monospace)
                    Spacer(Modifier.height(6.dp))
                }
            }
        }
    }
}

/**
 * Terminal states, kept in ONE place and deliberately conservative: anything
 * not recognised is treated as still in flight, never as finished. Guessing in
 * the other direction would let the UI claim work completed that did not.
 */
internal fun isTerminal(state: String?): Boolean = when (state?.lowercase()) {
    "done", "completed", "succeeded", "success",
    "denied", "cancelled", "canceled", "failed", "error",
    "completed_after_cancel",
    -> true
    else -> false
}

internal fun statusOf(step: Agent3Step, isCurrent: Boolean): StepStatus =
    when (step.state?.lowercase()) {
        "done", "completed", "succeeded", "success" -> StepStatus.DONE
        "denied", "cancelled", "canceled", "failed", "error" -> StepStatus.CANCELLED
        "running", "executing", "active", "awaiting_confirmation" -> StepStatus.ACTIVE
        else -> if (isCurrent) StepStatus.ACTIVE else StepStatus.PENDING
    }

@Composable
private fun A3StepRow(
    index: Int,
    step: Agent3Step,
    isCurrent: Boolean,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    busy: Boolean,
) {
    Row(Modifier.fillMaxWidth()) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.width(44.dp)) {
            StatusCircle(index, statusOf(step, isCurrent))
        }
        Column(Modifier.weight(1f).padding(bottom = 14.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    step.tool,
                    color = if (statusOf(step, isCurrent) == StepStatus.PENDING)
                        KalivTheme.colors.TextMuted else KalivTheme.colors.TextHigh,
                    fontSize = 13.5.sp, fontFamily = FontFamily.Monospace,
                    fontWeight = FontWeight.Medium,
                )
                Spacer(Modifier.width(8.dp))
                // Agent 3 owns the FINE vocabulary (destructive/admin), so its
                // risk string is passed through as impact -- no name table.
                RiskBadge(riskOf(step.risk, step.tool, step.risk))
                step.state?.let {
                    Spacer(Modifier.width(8.dp))
                    // The server's own word, verbatim. If the icon mapping does
                    // not recognise a state, this is what tells the truth.
                    Text(it, color = KalivTheme.colors.TextMuted, fontSize = 10.5.sp,
                        fontFamily = FontFamily.Monospace)
                }
            }
            if (step.summary.isNotBlank()) {
                Spacer(Modifier.height(4.dp))
                Text(step.summary, color = KalivTheme.colors.TextMuted, fontSize = 12.sp)
            }
            step.error?.let {
                Spacer(Modifier.height(4.dp))
                Text(it, color = KalivTheme.colors.Danger, fontSize = 12.sp)
            }
            // A card exists only when the server issued a digest for this step.
            // The client never decides that a confirmation is needed.
            if (step.confirmationDigest != null && !isTerminal(step.state)) {
                Spacer(Modifier.height(10.dp))
                A3ApprovalCard(
                    tool = step.tool,
                    argsPreview = step.args.toString(),
                    onApprove = onApprove,
                    onReject = onReject,
                    enabled = !busy,
                )
            }
        }
    }
}

@Composable
private fun PrimaryButton(label: String, enabled: Boolean, onClick: () -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier.clip(shape).background(kalivPrimaryGradient)
            .clickable(enabled = enabled) { onClick() }
            .padding(horizontal = 18.dp, vertical = 11.dp),
    ) { Text(label, color = kalivPrimaryInk, fontSize = 13.sp, fontWeight = FontWeight.Medium) }
}

@Composable
private fun OutlineButton(label: String, onClick: () -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    Box(
        contentAlignment = Alignment.Center,
        modifier = Modifier.clip(shape).border(1.dp, Color(0x4D785A37), shape)
            .clickable { onClick() }.padding(horizontal = 18.dp, vertical = 11.dp),
    ) { Text(label, color = KalivTheme.colors.TextHigh, fontSize = 13.sp) }
}

/**
 * Approval card for an Agent 3 step.
 *
 * Deliberately NOT the one in KalivScreens.kt: that one takes a V2 `ToolTurn`,
 * and binding the Agent 3 surface to V2's data class would be exactly the
 * host/client mismatch this whole file exists to undo.
 */
@Composable
private fun A3ApprovalCard(
    tool: String,
    argsPreview: String,
    onApprove: () -> Unit,
    onReject: () -> Unit,
    enabled: Boolean,
) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        Modifier.fillMaxWidth().clip(shape)
            .background(
                androidx.compose.ui.graphics.Brush.verticalGradient(
                    listOf(Color(0xFF241A10), Color(0xFF1B140D)),
                ),
            )
            .border(1.dp, Color(0x73C69A4B), shape)
            .padding(14.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            KalivAnkh(16)
            Spacer(Modifier.width(8.dp))
            Text("Kaliv vil bruge et v\u00e6rkt\u00f8j", color = KalivTheme.colors.TextHigh,
                fontSize = 13.5.sp, fontWeight = FontWeight.Medium)
        }
        Spacer(Modifier.height(10.dp))
        Box(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                .background(Color(0xFF100C09)).padding(10.dp),
        ) {
            Text(argsPreview, color = KalivTheme.colors.TextMuted, fontSize = 11.sp,
                fontFamily = FontFamily.Monospace)
        }
        Spacer(Modifier.height(12.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                    .background(kalivPrimaryGradient)
                    .clickable(enabled = enabled) { onApprove() }
                    .padding(vertical = 11.dp),
            ) { Text("Godkend", color = kalivPrimaryInk, fontSize = 13.sp,
                fontWeight = FontWeight.Medium) }
            Box(
                contentAlignment = Alignment.Center,
                modifier = Modifier.weight(1f).clip(RoundedCornerShape(10.dp))
                    .border(1.dp, Color(0x4D785A37), RoundedCornerShape(10.dp))
                    .clickable(enabled = enabled) { onReject() }
                    .padding(vertical = 11.dp),
            ) { Text("Afvis", color = KalivTheme.colors.TextHigh, fontSize = 13.sp) }
        }
    }
}

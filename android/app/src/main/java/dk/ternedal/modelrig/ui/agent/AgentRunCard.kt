package dk.ternedal.modelrig.ui.agent

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import androidx.compose.foundation.layout.height

/**
 * Skaerm 12 (Agent-koersel) — plan-/trinkortet, 1:1 mod HTML-referencen
 * x393/322 jf. DDR-001/B2. STATSLOEST OG ENDNU IKKE WIRET: klienten har
 * ingen agent-API (ingen plan/run/status-endpoints), saa kortet renderes
 * ikke live nogen steder — det er certificeret og klar, og wiring foelger
 * naar agent-tilstanden findes (kravspec-/fase 4-arbejde sammen med
 * Agent 3-checkpoint-skaermen (25)). Agent-kontakten i Kapaciteter forbliver
 * info uden kontakt (doede-kontakter-princippet, jf. #535). Capslinjens
 * "agent · trin X af Y"-suffix leveres af den fremtidige wiring via
 * ChatMessageUi naar kortet faar liv.
 */
enum class AgentStepState { Done, Active, Pending }

data class AgentStepUi(val text: String, val state: AgentStepState)

@Composable
fun AgentRunCard(
    steps: List<AgentStepUi>,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
    title: String = "Plan",
    onOpen: (() -> Unit)? = null,
    // Serveren afgør om planen overhovedet kan afbrydes. Kortet viste Stop
    // ubetinget, altså også for et trin runtime ikke har et handle til --
    // præcis den falske kontrol T-023 forbyder. Default true, så
    // eksisterende kaldesteder og screenshots er uændrede; panelet sender
    // den ægte værdi fra run.termination.plan.
    canStop: Boolean = true,
    stopBlockedReason: String? = null,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        // Tap paa kortet aabner checkpoint-skaermen. Selve godkendelserne
        // bor DER, ikke her (ADR-A3-001 D4) — kortet er en indgang, ikke en
        // genvej udenom.
        (if (onOpen != null) modifier.clickable(onClickLabel = "Aabn plan") { onOpen() } else modifier)
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(16.dp),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(bottom = 13.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                color = KalivTheme.colors.textSoft,
            )
            Spacer(Modifier.weight(1f))
            if (canStop) {
                Box(
                    Modifier
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.round))
                        .clickable(onClickLabel = "Stop plan") { onStop() }
                        .padding(horizontal = 13.dp, vertical = 5.dp),
                ) {
                    Text(
                        "Stop",
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.sp),
                        color = KalivTheme.colors.danger,
                    )
                }
            } else if (!stopBlockedReason.isNullOrBlank()) {
                // Ingen knap, men heller ingen tavshed: serverens egen
                // begrundelse for at planen ikke kan afbrydes lige nu.
                Text(
                    stopBlockedReason,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(11.dp)) {
            steps.forEach { s -> AgentStepRow(s) }
        }
    }
}

@Composable
private fun AgentStepRow(s: AgentStepUi) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.width(18.dp), contentAlignment = Alignment.Center) {
            when (s.state) {
                AgentStepState.Done -> Icon(
                    painterResource(R.drawable.ic_kaliv_check),
                    contentDescription = "Udf\u00f8rt",
                    tint = KalivTheme.colors.success,
                    modifier = Modifier.size(18.dp),
                )
                AgentStepState.Active -> Box(
                    Modifier.size(11.dp).background(KalivTokens.Gold.fill, CircleShape),
                )
                AgentStepState.Pending -> Box(
                    Modifier.size(11.dp).border(2.dp, KalivTheme.colors.hairline, CircleShape),
                )
            }
        }
        Spacer(Modifier.width(11.dp))
        Text(
            s.text,
            style = TextStyle(
                fontFamily = KalivType.Inter,
                fontWeight = if (s.state == AgentStepState.Active) FontWeight.SemiBold else FontWeight.Normal,
                fontSize = 15.sp,
            ),
            color = when (s.state) {
                AgentStepState.Done -> KalivTheme.colors.textMuted
                AgentStepState.Active -> KalivTheme.colors.textHigh
                AgentStepState.Pending -> KalivTheme.colors.faint
            },
        )
    }
}

/**
 * Bekræftelsen før en kørsel stoppes.
 *
 * At stoppe er en rigtig handling mod riggen, ikke en visning — og et
 * fejltryk i en chat er let. Derfor to skridt, og teksten siger hvad der
 * FAKTISK sker: allerede udførte trin ruller ikke tilbage. Alt andet ville
 * være et løfte Agent 3 ikke kan holde.
 */
@Composable
fun AgentRunStopConfirm(
    busy: Boolean,
    onConfirm: () -> Unit,
    onCancel: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.danger, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Text(
            "Stop planen?",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(3.dp))
        Text(
            "Resten af trinnene køres ikke. Det der allerede er udført, rulles ikke tilbage.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
            color = KalivTheme.colors.textMuted,
        )
        Spacer(Modifier.height(11.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(11.dp))
                    .clickable(enabled = !busy, onClickLabel = "Lad den køre") { onCancel() }
                    .padding(vertical = 10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Lad den køre",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
                    color = KalivTheme.colors.textSoft,
                )
            }
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.danger, RoundedCornerShape(11.dp))
                    .clickable(enabled = !busy, onClickLabel = "Stop") { onConfirm() }
                    .padding(vertical = 10.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (busy) "Stopper …" else "Stop planen",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
                    color = KalivTheme.colors.danger,
                )
            }
        }
    }
}

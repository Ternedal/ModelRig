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
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
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

/**
 * Planen, FØR den kører — ADR-A3-001 slice 3.
 *
 * Statsløst indhold: hvad riggen har planlagt, og hvad chatten må gøre ved
 * det. Kortet træffer ingen beslutning selv; verdict kommer fra
 * AgentStartPolicy, som er testet uden rig.
 *
 * To udfald, og de ser FORSKELLIGE ud med vilje:
 *  - Ren læseplan: guld startknap.
 *  - Ét skrivetrin: ingen startknap i chatten. I stedet en vej videre til
 *    agent-skærmen, hvor godkendelsen hører hjemme. Vi gør det ikke let at
 *    overse hvilken slags plan man står med.
 */
@Composable
fun AgentPlanPreviewCard(
    title: String,
    steps: List<AgentStepUi>,
    writeSteps: Int,
    busy: Boolean,
    onStartReadOnly: () -> Unit,
    onOpenApproval: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    val readOnly = writeSteps == 0 && steps.isNotEmpty()
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                painterResource(R.drawable.ic_kaliv_agent),
                contentDescription = null,
                tint = KalivTheme.colors.accent,
                modifier = Modifier.size(15.dp),
            )
            Spacer(Modifier.width(9.dp))
            Text(
                title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 15.sp),
                color = KalivTheme.colors.textHigh,
                modifier = Modifier.weight(1f),
            )
            Text(
                "Luk",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.sp),
                color = KalivTheme.colors.textMuted,
                modifier = Modifier.clickable(onClickLabel = "Luk") { onDismiss() },
            )
        }
        Spacer(Modifier.height(9.dp))
        steps.forEach { s ->
            Row(Modifier.padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier
                        .size(5.dp)
                        .background(KalivTheme.colors.textMuted, RoundedCornerShape(3.dp)),
                )
                Spacer(Modifier.width(9.dp))
                Text(
                    s.text,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textSoft,
                )
            }
        }
        Spacer(Modifier.height(11.dp))
        if (readOnly) {
            Text(
                "Planen læser kun. Den kan startes herfra.",
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
                color = KalivTheme.colors.textMuted,
            )
            Spacer(Modifier.height(9.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .background(KalivTheme.colors.signal, RoundedCornerShape(11.dp))
                    .clickable(enabled = !busy, onClickLabel = "Start planen") { onStartReadOnly() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (busy) "Starter …" else "Start planen",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.onSignal,
                )
            }
        } else {
            Text(
                if (steps.isEmpty()) {
                    "Riggen lagde ingen plan for den besked. Prøv agent-skærmen, hvis du vil grave i det."
                } else {
                    "Planen skriver noget ($writeSteps ${if (writeSteps == 1) "trin" else "trin"}). " +
                        "Den slags godkendes ikke i en chat — det sker på agent-skærmen."
                },
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
                color = KalivTheme.colors.textMuted,
            )
            Spacer(Modifier.height(9.dp))
            Box(
                Modifier
                    .fillMaxWidth()
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(11.dp))
                    .clickable(onClickLabel = "Åbn agent-skærmen") { onOpenApproval() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Åbn agent-skærmen",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textHigh,
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "Kaliv starter aldrig en plan af sig selv — kun når du trykker.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}


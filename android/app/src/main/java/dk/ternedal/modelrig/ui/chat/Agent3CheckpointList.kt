package dk.ternedal.modelrig.ui.chat

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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Agent 3 · read-checkpoint (skærm 25) — 1:1 mod referencen, ×1,2205.
 * Statsløst; Agent3ReviewScreen ejer kald og tilstand.
 *
 * Alt her er båret af RunEnvelope.readReview: vinduet (windowStart/End),
 * ventetilstanden, det færdige trin og removableStepIds. "KAN FJERNES"
 * er derfor en SANDFÆRDIG ETIKET fra riggen — ikke en knap: fjernelse
 * sker gennem replan-previewet, som er den eneste vej riggen tilbyder.
 */

/** Trinnets visuelle tilstand — afledt af Run.steps + readReview. */
enum class Agent3StepKind { Done, Active, Pending, WriteLocked }

@Composable
fun Agent3RunHeader(
    task: String,
    waitingLine: String,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth().padding(horizontal = 16.dp)) {
        Text(
            task,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(3.dp))
        Text(
            waitingLine,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

/** REVIEW-pillen i topbaren: accent på tint-flade. */
@Composable
fun Agent3ReviewBadge(modifier: Modifier = Modifier) {
    Text(
        "REVIEW",
        style = TextStyle(
            fontFamily = KalivType.Inter,
            fontWeight = FontWeight.SemiBold,
            fontSize = 11.5.sp,
            letterSpacing = 0.06.em,
        ),
        color = KalivTheme.colors.accent,
        modifier = modifier
            .background(KalivTokens.Gold.tint, RoundedCornerShape(KalivTokens.Radius.round))
            .padding(horizontal = 11.dp, vertical = 4.dp),
    )
}

@Composable
fun Agent3StepRow(
    kind: Agent3StepKind,
    title: String,
    sub: String,
    removable: Boolean,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.size(17.dp), contentAlignment = Alignment.Center) {
                when (kind) {
                    Agent3StepKind.Done -> Icon(
                        painterResource(R.drawable.ic_kaliv_check),
                        contentDescription = null,
                        tint = KalivTheme.colors.success,
                        modifier = Modifier.size(16.dp),
                    )
                    Agent3StepKind.Active -> Box(
                        Modifier.size(10.dp).background(KalivTokens.Gold.fill, RoundedCornerShape(KalivTokens.Radius.round)),
                    )
                    Agent3StepKind.Pending -> Box(
                        Modifier
                            .size(10.dp)
                            .border(2.dp, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.round)),
                    )
                    Agent3StepKind.WriteLocked -> Icon(
                        painterResource(R.drawable.ic_kaliv_lock),
                        contentDescription = null,
                        tint = KalivTheme.colors.faint,
                        modifier = Modifier.size(16.dp),
                    )
                }
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    title,
                    style = TextStyle(
                        fontFamily = KalivType.Inter,
                        fontWeight = if (kind == Agent3StepKind.Active) FontWeight.SemiBold else FontWeight.Medium,
                        fontSize = 14.5.sp,
                    ),
                    color = when (kind) {
                        Agent3StepKind.Pending, Agent3StepKind.WriteLocked -> KalivTheme.colors.faint
                        else -> KalivTheme.colors.textSoft
                    },
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(1.dp))
                Text(
                    sub,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
                    color = KalivTheme.colors.caps,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
            if (removable) {
                Spacer(Modifier.width(10.dp))
                Text(
                    "KAN FJERNES",
                    style = TextStyle(
                        fontFamily = KalivType.Inter,
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 11.sp,
                        letterSpacing = 0.06.em,
                    ),
                    color = KalivTheme.colors.textMuted,
                    modifier = Modifier
                        .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.round))
                        .padding(horizontal = 10.dp, vertical = 4.dp),
                )
            }
        }
        HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
    }
}

/** Resultatkortet for det netop afsluttede read. */
@Composable
fun Agent3ResultCard(
    toolCaps: String,
    body: String,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 13.dp),
    ) {
        Text(
            "RESULTAT · $toolCaps",
            style = TextStyle(
                fontFamily = KalivType.Inter,
                fontWeight = FontWeight.Bold,
                fontSize = 11.sp,
                letterSpacing = 0.18.em,
            ),
            color = KalivTheme.colors.caps,
        )
        Spacer(Modifier.height(7.dp))
        Text(
            body,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 21.sp),
            color = KalivTheme.colors.textSoft,
        )
    }
}

/**
 * Handlingerne: Fortsæt (ét read) = resume, Replan-preview = replan-fladen,
 * Stop plan = cancel. Noten "Fortsætter aldrig automatisk" er sand — runnet
 * pauser efter hvert read, og intet her starter af sig selv.
 */
@Composable
fun Agent3CheckpointActions(
    busy: Boolean,
    onContinue: () -> Unit,
    onReplan: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                Modifier
                    .weight(1f)
                    .background(KalivTokens.Gold.fill, RoundedCornerShape(12.dp))
                    .clickable(enabled = !busy, onClickLabel = "Fortsæt (ét read)") { onContinue() }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Fortsæt (ét read)",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTokens.Gold.on,
                )
            }
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                    .clickable(enabled = !busy, onClickLabel = "Replan-preview") { onReplan() }
                    .padding(vertical = 12.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Replan-preview",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textSoft,
                )
            }
        }
        Spacer(Modifier.height(9.dp))
        Text(
            "Fortsætter aldrig automatisk",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
            color = KalivTheme.colors.caps,
            modifier = Modifier.fillMaxWidth().padding(bottom = 9.dp),
        )
        Box(
            Modifier
                .fillMaxWidth()
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.danger, RoundedCornerShape(12.dp))
                .clickable(enabled = !busy, onClickLabel = "Stop plan") { onStop() }
                .padding(vertical = 12.dp),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                "Stop plan",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                color = KalivTheme.colors.danger,
            )
        }
    }
}

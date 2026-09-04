package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.UsedChunk
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import dk.ternedal.modelrig.ui.components.CapsLabel

/**
 * Hvad der blev læst — "Svar-citater", i den udgave riggen kan holde.
 *
 * DET VIGTIGSTE VED DENNE FLADE ER HVAD DEN IKKE PÅSTÅR. Kaliv ved præcis
 * hvilke udsnit der lå i konteksten, hvor godt de matchede spørgsmålet, og
 * hvad der stod i dem. Kaliv ved IKKE hvilken sætning i svaret der brugte
 * hvilket udsnit — den kobling findes ikke i modellen. Citater pr. sætning
 * ville se ud som et bevis og være et gæt, så fladen viser udsnittene som
 * det de er: det materiale svaret blev skrevet ovenpå.
 */
@Composable
fun CitationsList(
    chunks: List<UsedChunk>,
    modifier: Modifier = Modifier,
) {
    Column(modifier.fillMaxWidth()) {
        CapsLabel("Hvad der blev læst")
        Spacer(Modifier.height(9.dp))
        if (chunks.isEmpty()) {
            Text(
                "Ingen dokumenter blev hentet til dette svar.",
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                color = KalivTheme.colors.textMuted,
            )
            return@Column
        }
        chunks.forEach { c ->
            CitationRow(c)
            Spacer(Modifier.height(9.dp))
        }
        Text(
            "Udsnittene lå i konteksten, da svaret blev skrevet. Kaliv kan ikke " +
                "vise hvilken sætning der brugte hvilket udsnit.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp, lineHeight = 18.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

@Composable
private fun CitationRow(c: UsedChunk) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 13.dp, vertical = 11.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                c.source,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            Spacer(Modifier.width(9.dp))
            Text(
                citationMeta(c),
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 12.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
        if (c.excerpt.isNotBlank()) {
            Spacer(Modifier.height(5.dp))
            Text(
                c.excerpt.trim(),
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp, lineHeight = 19.sp),
                color = KalivTheme.colors.textSoft,
                maxLines = 4,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

/**
 * "Udsnit 3 · 71 % match" — begge dele er rigens egne tal.
 *
 * Mangler udsnitsnummeret (ældre indekser), står der kun matchet; vi
 * nummererer ikke selv, for så ville tallet pege på noget andet end riggens.
 */
fun citationMeta(c: UsedChunk): String {
    val pct = (c.score.coerceIn(0.0, 1.0) * 100).toInt()
    val idx = c.chunkIndex?.let { "Udsnit ${it + 1}" }
    return listOfNotNull(idx, "$pct % match").joinToString(" · ")
}

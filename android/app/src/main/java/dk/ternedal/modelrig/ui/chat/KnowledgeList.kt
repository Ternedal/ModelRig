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
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
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
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.height
import androidx.compose.ui.unit.em
import dk.ternedal.modelrig.ui.components.KalivSwitch

/**
 * Skaerm 8 (Viden/RAG) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Statsloest og screenshot-testbart; KnowledgeScreen ejer tilstand og
 * ingest-launcheren. Dokumenterede afvigelser fra mockuppen: (1) per-dokument-
 * kontakter og "slaaet fra" er UDELADT — der findes ingen disable-/slette-API
 * for RAG-kilder (kendt hul, doede-kontakter-princippet fra #533/#535);
 * (2) stoerrelse/udsnit-metadata pr. kilde er UDELADT — /rag/sources leverer
 * kun navne (kravspec-punkt sammen med sletning); (3) fodnoten siger "op til
 * 4 udsnit", ikke mockuppens "top 5" — worker'ens top_k er 4 (rag.py), og
 * sandheden vinder over mockup-teksten; chevron'en er droppet (ingen
 * destination = doed affordance).
 */
data class KnowledgeDocUi(
    val name: String,
    val badge: String,
    /** Rigens egne tal: "12 udsnit · 8/7 2026" — tom når de ikke findes. */
    val statsLine: String = "",
    /** Om kilden må hentes fra. Slukket = teksten bliver, men bruges ikke. */
    val enabled: Boolean = true,
)

/**
 * Kildens tal-linje. Antal udsnit kommer fra riggen; datoen udelades hvis
 * tidsstemplet mangler, i stedet for at fylde med noget opdigtet.
 */
fun knowledgeStatsLine(chunks: Int, lastIngestedAt: Double?): String {
    val chunkPart = if (chunks == 1) "1 udsnit" else "$chunks udsnit"
    val stamp = formatIngestDate(lastIngestedAt) ?: return chunkPart
    return "$chunkPart \u00b7 $stamp"
}

/** Unix-sekunder -> "8/7 2026"; null/ugyldigt -> null (ingen dato vises). */
fun formatIngestDate(epochSeconds: Double?): String? {
    if (epochSeconds == null || !epochSeconds.isFinite() || epochSeconds <= 0.0) return null
    return java.text.SimpleDateFormat("d/M yyyy", java.util.Locale("da", "DK"))
        .format(java.util.Date((epochSeconds * 1000.0).toLong()))
}

/** Filendelse -> caps-badge ("PDF", "MD", ...); ukendt -> "DOK". */
fun knowledgeBadgeFor(name: String): String {
    val ext = name.substringAfterLast('.', "").lowercase()
    return when (ext) {
        "pdf" -> "PDF"; "md" -> "MD"; "txt" -> "TXT"
        "docx" -> "DOCX"; "pptx" -> "PPTX"
        "html", "htm" -> "HTML"
        "png", "jpg", "jpeg", "webp" -> "IMG"
        else -> if (ext.length in 2..4) ext.uppercase() else "DOK"
    }
}

@Composable
fun KnowledgeIntroNote(
    modifier: Modifier = Modifier,
    text: String = "Dokumenter Kaliv kan sl\u00e5 op i. Alt indekseres og bliver p\u00e5 din rig.",
) {
    Row(modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.Top) {
        Icon(
            painterResource(R.drawable.ic_kaliv_shield),
            contentDescription = null,
            tint = KalivTokens.Gold.fill,
            modifier = Modifier.size(17.dp).padding(top = 1.dp),
        )
        Spacer(Modifier.width(9.dp))
        Text(
            text,
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp, lineHeight = 20.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

@Composable
fun KnowledgeList(
    docs: List<KnowledgeDocUi>,
    onAdd: () -> Unit,
    modifier: Modifier = Modifier,
    onDelete: ((KnowledgeDocUi) -> Unit)? = null,
    onToggle: ((KnowledgeDocUi, Boolean) -> Unit)? = null,
) {
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(11.dp)) {
        items(docs, key = { it.name }) { d -> KnowledgeDocCard(d, onDelete, onToggle) }
        item { KalivOutlineActionCard("Tilf\u00f8j dokument", onAdd) }
    }
}

@OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class)
@Composable
private fun KnowledgeDocCard(
    d: KnowledgeDocUi,
    onDelete: ((KnowledgeDocUi) -> Unit)? = null,
    onToggle: ((KnowledgeDocUi, Boolean) -> Unit)? = null,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .then(
                if (onDelete == null) {
                    Modifier
                } else {
                    // Langtryk = fjern kilden, samme mønster som Samtaler.
                    Modifier.combinedClickable(onClick = {}, onLongClick = { onDelete(d) })
                },
            )
            .padding(15.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            Modifier.size(49.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(12.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                d.badge,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Bold, fontSize = 11.5.sp),
                color = KalivTheme.colors.textMuted,
            )
        }
        Spacer(Modifier.width(15.dp))
        Column(Modifier.weight(1f)) {
            Text(
                d.name,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                color = if (d.enabled) KalivTheme.colors.textHigh else KalivTheme.colors.textMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            val stats = if (d.enabled) d.statsLine else {
                // Slukket kilde: sig hvad der FAKTISK gælder — teksten er der
                // stadig, den bliver bare ikke hentet.
                listOf(d.statsLine, "bruges ikke").filter { it.isNotEmpty() }.joinToString(" · ")
            }
            if (stats.isNotEmpty()) {
                Spacer(Modifier.height(2.dp))
                Text(
                    stats,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
            }
        }
        onToggle?.let { toggle ->
            Spacer(Modifier.width(11.dp))
            KalivSwitch(checked = d.enabled, onCheckedChange = { toggle(d, it) })
        }
    }
}

@Composable
fun KalivOutlineActionCard(text: String, onClick: () -> Unit, modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        modifier
            .fillMaxWidth()
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .clickable(onClickLabel = text) { onClick() }
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.Center,
    ) {
        Icon(
            painterResource(R.drawable.ic_kaliv_plus),
            contentDescription = null,
            tint = KalivTheme.colors.accent,
            modifier = Modifier.size(21.dp),
        )
        Spacer(Modifier.width(10.dp))
        Text(
            text,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.accent,
        )
    }
}

@Composable
fun KnowledgeFooterNote(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 16.dp, vertical = 12.dp),
    ) {
        Text(
            "Henter op til 4 udsnit \u00b7 kun lokalt",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 14.sp),
            color = KalivTheme.colors.textMuted,
        )
    }
}

/**
 * Korpus-foden: rigens totaler under listen. Tallene er summeret af
 * kildernes egne udsnitstal — ikke et separat estimat.
 */
@Composable
fun KnowledgeCorpusFooter(
    sourceCount: Int,
    chunkCount: Int,
    modifier: Modifier = Modifier,
) {
    Text(
        (if (sourceCount == 1) "1 kilde" else "$sourceCount kilder") + " \u00b7 " +
            (if (chunkCount == 1) "1 udsnit" else "$chunkCount udsnit") + " i indekset",
        style = TextStyle(
            fontFamily = KalivType.Inter,
            fontWeight = FontWeight.Bold,
            fontSize = 11.5.sp,
            letterSpacing = 0.18.em,
        ),
        color = KalivTheme.colors.caps,
        modifier = modifier.fillMaxWidth(),
    )
}

/**
 * Bekræftelse før en kilde fjernes. Sletningen er ægte og uigenkaldelig:
 * alle udsnit forsvinder fra indekset, og dokumentet skal indekseres forfra
 * for at komme igen. Derfor står tallet i teksten.
 */
@Composable
fun KnowledgeDeleteConfirm(
    name: String,
    chunks: Int,
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
            .padding(horizontal = 16.dp, vertical = 15.dp),
    ) {
        Text(
            "Fjern $name fra viden?",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.textHigh,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            (if (chunks == 1) "1 udsnit" else "$chunks udsnit") +
                " slettes fra indekset. Kaliv kan ikke trække på dokumentet igen, før det indekseres forfra.",
            style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
            color = KalivTheme.colors.textMuted,
        )
        Spacer(Modifier.height(13.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(12.dp))
                    .clickable(enabled = !busy, onClickLabel = "Behold") { onCancel() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Behold",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.textSoft,
                )
            }
            Box(
                Modifier
                    .weight(1f)
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.danger, RoundedCornerShape(12.dp))
                    .clickable(enabled = !busy, onClickLabel = "Fjern") { onConfirm() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    "Fjern",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.danger,
                )
            }
        }
    }
}

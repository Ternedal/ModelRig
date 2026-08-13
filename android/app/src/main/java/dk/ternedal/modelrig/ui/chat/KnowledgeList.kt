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
data class KnowledgeDocUi(val name: String, val badge: String)

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
fun KnowledgeIntroNote(modifier: Modifier = Modifier) {
    Row(modifier.padding(horizontal = 20.dp), verticalAlignment = Alignment.Top) {
        Icon(
            painterResource(R.drawable.ic_kaliv_shield),
            contentDescription = null,
            tint = KalivTokens.Gold.fill,
            modifier = Modifier.size(17.dp).padding(top = 1.dp),
        )
        Spacer(Modifier.width(9.dp))
        Text(
            "Dokumenter Kaliv kan sl\u00e5 op i. Alt indekseres og bliver p\u00e5 din rig.",
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
) {
    LazyColumn(modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(11.dp)) {
        items(docs, key = { it.name }) { d -> KnowledgeDocCard(d) }
        item { AddDocumentCard(onAdd) }
    }
}

@Composable
private fun KnowledgeDocCard(d: KnowledgeDocUi) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        Modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
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
        Text(
            d.name,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.textHigh,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun AddDocumentCard(onAdd: () -> Unit) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Row(
        Modifier
            .fillMaxWidth()
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .clickable(onClickLabel = "Tilf\u00f8j dokument") { onAdd() }
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
            "Tilf\u00f8j dokument",
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

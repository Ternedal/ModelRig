package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.CapsLabel
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 11 (Handlingslog) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Statsloest; AuditScreen ejer hentning og filter. Dokumenterede afvigelser:
 * mockuppens afventende-kort m. Godkend/Afvis er UDELADT — godkendelse sker
 * live i chattens tool-confirm-kort (audit-API'et har hverken pending-liste
 * eller approve-endpoint; doede knapper er vaerre end manglende). Badgen
 * siger "Udfoert" for outcome=executed — mockuppens "Godkendt" ville paastaa
 * mere end loggen ved. risk bevares i sub-linjen (paritet med den gamle
 * dialog — det er en audit, information vinder over pixels).
 */
enum class AuditBadgeKind { Ok, Warn, Error, Neutral }

data class AuditRowUi(
    val title: String,
    val sub: String,
    val badge: String,
    val kind: AuditBadgeKind,
    val cloud: Boolean,
    /** Værktøjets navn fra riggen; styrer ikon-brikken. */
    val tool: String = "",
)

@Composable
fun AuditGroupedList(
    today: List<AuditRowUi>,
    earlier: List<AuditRowUi>,
    modifier: Modifier = Modifier,
) {
    LazyColumn(modifier.fillMaxWidth()) {
        if (today.isNotEmpty()) {
            item { Box(Modifier.padding(start = 2.dp, top = 5.dp, bottom = 7.dp)) { CapsLabel("I DAG") } }
            items(today) { AuditRow(it); AuditDivider() }
        }
        if (earlier.isNotEmpty()) {
            item { Box(Modifier.padding(start = 2.dp, top = 12.dp, bottom = 7.dp)) { CapsLabel("TIDLIGERE") } }
            items(earlier) { AuditRow(it); AuditDivider() }
        }
    }
}

@Composable
private fun AuditDivider() {
    HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
}

@Composable
private fun AuditRow(r: AuditRowUi) {
    Row(
        Modifier.fillMaxWidth().padding(vertical = 13.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // Referencens brik: 32px flade, 9px radius, 15px glyf (×1,2205).
        Box(
            Modifier
                .size(39.dp)
                .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(11.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Icon(
                painterResource(auditToolIcon(r.tool)),
                contentDescription = null,
                tint = KalivTheme.colors.textMuted,
                modifier = Modifier.size(18.dp),
            )
        }
        Spacer(Modifier.width(13.dp))
        Column(Modifier.weight(1f)) {
            Text(
                r.title,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                color = KalivTheme.colors.textHigh,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(3.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    r.sub,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                    color = KalivTheme.colors.faint,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (r.cloud) {
                    Spacer(Modifier.width(6.dp))
                    Icon(
                        painterResource(R.drawable.ic_kaliv_cloud),
                        contentDescription = "Cloud",
                        tint = KalivTheme.colors.faint,
                        modifier = Modifier.size(14.dp),
                    )
                }
            }
        }
        Spacer(Modifier.width(13.dp))
        AuditBadge(r.badge, r.kind)
    }
}

@Composable
private fun AuditBadge(text: String, kind: AuditBadgeKind) {
    // Mockuppens form: glyf + farvet tekst, ingen pille.
    val color: Color = when (kind) {
        AuditBadgeKind.Ok -> KalivTheme.colors.success
        AuditBadgeKind.Warn -> KalivTheme.colors.warn
        AuditBadgeKind.Error -> KalivTheme.colors.danger
        AuditBadgeKind.Neutral -> KalivTheme.colors.textMuted
    }
    val glyph = when (kind) {
        AuditBadgeKind.Ok -> "\u2713 "
        AuditBadgeKind.Warn -> "\u2715 "
        AuditBadgeKind.Error -> "! "
        AuditBadgeKind.Neutral -> ""
    }
    Text(
        glyph + text,
        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.sp),
        color = color,
    )
}

/**
 * Værktøjs-ikonet i Handlingsloggen (referencens 32px-brik med 15px glyf).
 *
 * Da skærmen landede, udelod jeg brikken med begrundelsen "ukendt
 * navnerum". Den begrundelse holder ikke længere: riggens REGISTRY er
 * en kendt, lukket liste (ni faste værktøjer plus fire der registreres
 * dynamisk: desktop_screenshot, desktop_action_preview, github_read og
 * web_research). Hvert af dem får sit eget ikon.
 *
 * ALT ANDET får værktøjs-glyffen. Det er ikke et pænt fallback, det er
 * et ÆRLIGT et: et ukendt værktøjsnavn skal ligne "et værktøj jeg ikke
 * kender", ikke lade som om det er en fil eller en model.
 *
 * Mockuppens egne rækker viser "Filer" og "Terminal" — værktøjer der
 * ikke findes på riggen. Derfor er navnene IKKE oversat til pæne danske
 * etiketter her: under-linjen viser fortsat det rigtige værktøjsnavn.
 */
fun auditToolIcon(tool: String): Int = when (tool.trim().lowercase()) {
    "note_append" -> R.drawable.ic_kaliv_doc
    "list_documents" -> R.drawable.ic_kaliv_book
    "rig_status" -> R.drawable.ic_kaliv_rack
    "list_models" -> R.drawable.ic_kaliv_model
    "pull_model" -> R.drawable.ic_kaliv_download
    "delete_model" -> R.drawable.ic_kaliv_trash
    "current_datetime" -> R.drawable.ic_kaliv_clock
    "job_status" -> R.drawable.ic_kaliv_info
    "cancel_job" -> R.drawable.ic_kaliv_stop_circle
    "web_research" -> R.drawable.ic_kaliv_globe
    "github_read" -> R.drawable.ic_kaliv_branch
    "desktop_screenshot", "desktop_action_preview" -> R.drawable.ic_kaliv_screen
    else -> R.drawable.ic_kaliv_tools
}

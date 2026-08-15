package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
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
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.SolidColor
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
 * Skaerm 7 (Samtaler) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Statsloest og screenshot-testbart; ConversationsScreen ejer tilstand,
 * SAF-launchere og menuer. Kilde-ikonet er GULD paa den aktive raekke og
 * svagt ellers (referencens moenster); tider formateres af ejeren.
 */
data class ConvRowUi(
    val id: Long,
    val title: String,
    val preview: String,
    val timeLabel: String,
    val cloud: Boolean,
    val active: Boolean,
)

@Composable
fun ConversationsTopBar(
    onBack: () -> Unit,
    onNew: (() -> Unit)? = null,
    menuContent: (@Composable () -> Unit)? = null,
    onMenu: (() -> Unit)? = null,
    title: String = "Samtaler",
    menuIcon: Int = R.drawable.ic_kaliv_more_vert,
) {
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, top = 2.dp, bottom = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(
                painterResource(R.drawable.ic_kaliv_chevron_left),
                contentDescription = "Tilbage",
                tint = KalivTheme.colors.textMuted,
                modifier = Modifier.size(25.dp),
            )
        }
        Spacer(Modifier.weight(1f))
        Text(title, style = KalivType.Title, color = KalivTheme.colors.textHigh)
        Spacer(Modifier.weight(1f))
        if (onMenu != null) {
            Box {
                IconButton(onClick = onMenu) {
                    Icon(
                        painterResource(menuIcon),
                        contentDescription = "Mere",
                        tint = KalivTheme.colors.textMuted,
                        modifier = Modifier.size(22.dp),
                    )
                }
                menuContent?.invoke()
            }
        }
        if (onNew != null) {
            IconButton(onClick = onNew) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_plus),
                    contentDescription = "Ny samtale",
                    tint = KalivTheme.colors.accent,
                    modifier = Modifier.size(24.dp),
                )
            }
        }
    }
}

@Composable
fun ConversationsSearchField(query: String, onQuery: (String) -> Unit, modifier: Modifier = Modifier) {
    Row(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, RoundedCornerShape(KalivTokens.Radius.card))
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(KalivTokens.Radius.card))
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            painterResource(R.drawable.ic_kaliv_search),
            contentDescription = null,
            tint = KalivTheme.colors.faint,
            modifier = Modifier.size(20.dp),
        )
        Spacer(Modifier.width(11.dp))
        BasicTextField(
            value = query,
            onValueChange = onQuery,
            singleLine = true,
            modifier = Modifier.weight(1f),
            textStyle = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, color = KalivTheme.colors.textHigh),
            cursorBrush = SolidColor(KalivTheme.colors.accent),
            decorationBox = { inner ->
                if (query.isEmpty()) {
                    Text(
                        "S\u00f8g i samtaler",
                        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp),
                        color = KalivTheme.colors.faint,
                    )
                }
                inner()
            },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ConversationsList(
    today: List<ConvRowUi>,
    earlier: List<ConvRowUi>,
    onOpen: (Long) -> Unit,
    onLongPress: (Long) -> Unit,
    modifier: Modifier = Modifier,
    rowMenu: (@Composable (Long) -> Unit)? = null,
) {
    LazyColumn(modifier.fillMaxWidth()) {
        if (today.isNotEmpty()) {
            item { GroupLabel("I DAG") }
            items(today, key = { it.id }) { ConvRow(it, onOpen, onLongPress, rowMenu) }
        }
        if (earlier.isNotEmpty()) {
            item { GroupLabel("TIDLIGERE") }
            items(earlier, key = { it.id }) { ConvRow(it, onOpen, onLongPress, rowMenu) }
        }
    }
}

@Composable
private fun GroupLabel(text: String) {
    Box(Modifier.padding(start = 2.dp, top = 5.dp, bottom = 7.dp)) { CapsLabel(text) }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ConvRow(
    r: ConvRowUi,
    onOpen: (Long) -> Unit,
    onLongPress: (Long) -> Unit,
    rowMenu: (@Composable (Long) -> Unit)?,
) {
    Box {
        val shape = RoundedCornerShape(KalivTokens.Radius.card)
        val base = Modifier
            .fillMaxWidth()
            .padding(bottom = 9.dp)
        val styled = if (r.active) {
            base
                .background(KalivTheme.colors.surfaceDim, shape)
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
        } else base
        Row(
            styled
                .combinedClickable(onClick = { onOpen(r.id) }, onLongClick = { onLongPress(r.id) })
                .padding(horizontal = 15.dp, vertical = 13.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(
                    r.title.ifBlank { "(uden titel)" },
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.5.sp),
                    color = if (r.active) KalivTheme.colors.textHigh else KalivTheme.colors.textSoft,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                if (r.preview.isNotEmpty()) {
                    Spacer(Modifier.height(2.dp))
                    Text(
                        r.preview,
                        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 14.sp),
                        color = KalivTheme.colors.textMuted,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            Spacer(Modifier.width(13.dp))
            Column(horizontalAlignment = Alignment.End) {
                Icon(
                    painterResource(if (r.cloud) R.drawable.ic_kaliv_cloud else R.drawable.ic_kaliv_rig_simple),
                    contentDescription = if (r.cloud) "Cloud" else "Rig",
                    tint = if (r.active) KalivTokens.Gold.fill else KalivTheme.colors.faint,
                    modifier = Modifier.size(18.dp),
                )
                Spacer(Modifier.height(6.dp))
                Text(
                    r.timeLabel,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                    color = KalivTheme.colors.faint,
                )
            }
        }
        rowMenu?.invoke(r.id)
    }
}

/**
 * Rå markdown hører ikke hjemme i samtalelistens preview: referencen viser
 * ren prosa, men modellernes svar er fulde af **fed**, overskrifter og
 * kodehegn, som lækkede direkte ind i listen (Anders' Pixel, 15/08).
 *
 * Konservativ oversættelse — kun det der ellers står som støj:
 * kodehegn og backticks, fed/kursiv, overskrifter, citater, listetegn og
 * link-syntaks (teksten beholdes, URL'en droppes). Alt andet står urørt.
 */
fun previewFromMarkdown(raw: String): String {
    var s = raw
    s = s.replace(Regex("```[a-zA-Z0-9_+-]*"), " ")
    s = s.replace(Regex("!\\[([^\\]]*)\\]\\([^)]*\\)"), "$1")
    s = s.replace(Regex("\\[([^\\]]+)\\]\\([^)]*\\)"), "$1")
    s = s.replace(Regex("(?m)^\\s{0,3}#{1,6}\\s+"), "")
    s = s.replace(Regex("(?m)^\\s{0,3}>\\s?"), "")
    s = s.replace(Regex("(?m)^\\s{0,3}[-*+]\\s+"), "")
    s = s.replace(Regex("\\*\\*([^*]+)\\*\\*"), "$1")
    s = s.replace(Regex("__([^_]+)__"), "$1")
    s = s.replace(Regex("(?<![*\\w])\\*([^*\\n]+)\\*(?![*\\w])"), "$1")
    s = s.replace("`", "")
    return s.replace('\n', ' ').replace(Regex("\\s{2,}"), " ").trim()
}

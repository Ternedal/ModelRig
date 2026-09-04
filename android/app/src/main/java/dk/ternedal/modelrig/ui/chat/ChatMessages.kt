package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.res.painterResource
import androidx.compose.foundation.text.InlineTextContent
import androidx.compose.foundation.text.appendInlineContent
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.Placeholder
import androidx.compose.ui.text.PlaceholderVerticalAlign
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.StreamingCursor
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Skaerm 2 (Aktiv samtale) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Rendererne er statslose og tager [ChatMessageUi]; AppUi mapper sin private
 * Msg-model ind, saa skaermen kan screenshot-testes uden ViewModel/DB.
 */
data class ChatMessageUi(
    val isUser: Boolean,
    val text: String,
    val streaming: Boolean = false,
    /** Epoch-ms for turen; null for indlaest historik uden kendt tid. */
    val atMillis: Long? = null,
    val sources: List<String> = emptyList(),
    val error: Boolean = false,
    /** Smaa oplysningspiller over svaret (talemodel, cloud-fallback). */
    val pills: List<String> = emptyList(),
)

private val TimeFmt = SimpleDateFormat("HH:mm", Locale.getDefault())

/** Brugerboble: 78 % maxbredde, userBubble-flade m. kant, radius 17/17/6/17. */
@Composable
fun UserMessage(text: String, modifier: Modifier = Modifier) {
    Row(
        modifier = modifier.fillMaxWidth().padding(vertical = 10.dp),
        horizontalArrangement = Arrangement.End,
    ) {
        Surface(
            color = KalivTheme.colors.userBubble,
            border = androidx.compose.foundation.BorderStroke(
                KalivTokens.Layout.hairline,
                KalivTheme.colors.userBubbleBorder,
            ),
            shape = RoundedCornerShape(
                topStart = KalivTokens.Radius.bubbleUser,
                topEnd = KalivTokens.Radius.bubbleUser,
                bottomStart = KalivTokens.Radius.bubbleUser,
                bottomEnd = 6.dp,
            ),
            modifier = Modifier.widthIn(
                max = (LocalConfiguration.current.screenWidthDp * 0.78f).dp,
            ),
        ) {
            Text(
                text,
                color = KalivTheme.colors.userBubbleText,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.5.sp, lineHeight = 24.5.sp),
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 11.dp),
            )
        }
    }
}

/**
 * Assistentblok: KALIV-capslinje + tid/"skriver …", flad broedtekst,
 * kilde-chips og handlingsraekke (kopier). Ingen boble — teksten staar frit.
 */
@Composable
fun AssistantMessage(
    m: ChatMessageUi,
    modifier: Modifier = Modifier,
    thinking: (@Composable () -> Unit)? = null,
    body: (@Composable () -> Unit)? = null,
    onRetry: (() -> Unit)? = null,
) {
    val clipboard = LocalClipboardManager.current
    Column(
        modifier = modifier
            .widthIn(max = (LocalConfiguration.current.screenWidthDp * 0.93f).dp)
            .padding(vertical = 10.dp),
        horizontalAlignment = Alignment.Start,
    ) {
        Row(verticalAlignment = Alignment.Bottom) {
            Text(
                "KALIV",
                style = TextStyle(
                    fontFamily = KalivType.Inter,
                    fontWeight = FontWeight(KalivTokens.Typography.Brandline.weight),
                    fontSize = KalivTokens.Typography.Brandline.size,
                    letterSpacing = KalivTokens.Typography.Brandline.trackingEm.em,
                ),
                color = KalivTokens.Gold.fill,
            )
            Spacer(Modifier.width(10.dp))
            Text(
                when {
                    m.streaming -> "skriver \u2026"
                    m.atMillis != null -> TimeFmt.format(Date(m.atMillis))
                    else -> ""
                },
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                color = KalivTheme.colors.faint,
            )
        }
        Spacer(Modifier.height(7.dp))
        if (m.pills.isNotEmpty()) {
            Row(Modifier.padding(bottom = 7.dp)) {
                m.pills.forEach { p ->
                    Surface(
                        color = KalivTheme.colors.sheet,
                        border = androidx.compose.foundation.BorderStroke(
                            KalivTokens.Layout.hairline,
                            KalivTheme.colors.hairline,
                        ),
                        shape = RoundedCornerShape(11.dp),
                        modifier = Modifier.padding(end = 7.dp),
                    ) {
                        Text(
                            p, fontSize = 12.sp, color = KalivTheme.colors.textMuted,
                            fontFamily = KalivType.Inter,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        )
                    }
                }
            }
        }
        when {
            m.streaming && m.text.isEmpty() && thinking != null -> thinking()
            m.streaming -> Text(
                text = buildAnnotatedString {
                    append(m.text)
                    appendInlineContent("cursor", "\u258d")
                },
                inlineContent = mapOf(
                    "cursor" to InlineTextContent(
                        Placeholder(11.sp, 18.sp, PlaceholderVerticalAlign.TextBottom),
                    ) { StreamingCursor() },
                ),
                color = KalivTheme.colors.textBody,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.5.sp, lineHeight = 26.5.sp),
            )
            m.error -> Text(
                m.text, color = KalivTheme.colors.danger,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.sp, lineHeight = 24.sp),
            )
            body != null -> body()
            else -> Text(
                m.text,
                color = KalivTheme.colors.textBody,
                style = TextStyle(fontFamily = KalivType.Inter, fontSize = 16.5.sp, lineHeight = 26.5.sp),
            )
        }
        if (m.sources.isNotEmpty()) {
            Row(Modifier.padding(top = 11.dp)) {
                m.sources.distinct().take(4).forEach { s ->
                    Surface(
                        color = KalivTheme.colors.sheet,
                        border = androidx.compose.foundation.BorderStroke(
                            KalivTokens.Layout.hairline,
                            KalivTheme.colors.hairline,
                        ),
                        shape = RoundedCornerShape(11.dp),
                        modifier = Modifier.padding(end = 7.dp),
                    ) {
                        Row(
                            verticalAlignment = Alignment.CenterVertically,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        ) {
                            Box(
                                Modifier.size(7.dp)
                                    // Kildeprikken er #8A7A66 i referencen — bevidst
                                    // uden for tokensaettet (dekorativ, begge temaer).
                                    .background(Color(0xFF8A7A66), RoundedCornerShape(2.dp)),
                            )
                            Spacer(Modifier.width(6.dp))
                            Text(
                                s, fontSize = 12.sp, color = KalivTheme.colors.textMuted,
                                fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium,
                            )
                        }
                    }
                }
            }
        }
        if (!m.streaming && !m.error && m.text.isNotEmpty()) {
            Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                IconButton(
                    onClick = { clipboard.setText(AnnotatedString(m.text)) },
                    modifier = Modifier.size(24.dp),
                ) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_copy),
                        contentDescription = "Kopi\u00e9r svar",
                        tint = KalivTheme.colors.faint,
                        modifier = Modifier.size(18.dp),
                    )
                }
                if (onRetry != null) {
                    IconButton(onClick = onRetry, modifier = Modifier.size(24.dp)) {
                        Icon(
                            painterResource(R.drawable.ic_kaliv_retry),
                            contentDescription = "Genk\u00f8r",
                            tint = KalivTheme.colors.faint,
                            modifier = Modifier.size(18.dp),
                        )
                    }
                }
            }
        }
    }
}

/** Samtale-topbaren: tilbage-pil, mini-ankh-brik + titel (Inter 600), overflow. */
@Composable
fun ChatConversationTopBar(
    title: String,
    onBack: () -> Unit,
    onOverflow: () -> Unit,
    modifier: Modifier = Modifier,
    overflowContent: (@Composable () -> Unit)? = null,
) {
    Row(
        modifier = modifier.fillMaxWidth().padding(start = 8.dp, end = 8.dp, top = 2.dp, bottom = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        IconButton(onClick = onBack) {
            Icon(
                painterResource(R.drawable.ic_kaliv_chevron_left),
                contentDescription = "Tilbage",
                tint = KalivTheme.colors.textMuted,
                modifier = Modifier.size(26.dp),
            )
        }
        Spacer(Modifier.weight(1f))
        Box(
            modifier = Modifier
                .size(32.dp)
                .background(KalivTheme.colors.surface, RoundedCornerShape(10.dp))
                .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, RoundedCornerShape(10.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Image(
                painter = painterResource(R.drawable.kaliv_ankh_gold),
                contentDescription = null,
                modifier = Modifier.height(18.dp),
            )
        }
        Spacer(Modifier.width(10.dp))
        Text(
            title,
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 17.sp),
            color = KalivTheme.colors.textSoft,
            maxLines = 1,
        )
        Spacer(Modifier.weight(1f))
        Box {
            IconButton(onClick = onOverflow) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_more_vert),
                    contentDescription = "Mere",
                    tint = KalivTheme.colors.textMuted,
                    modifier = Modifier.size(24.dp),
                )
            }
            overflowContent?.invoke()
        }
    }
}

package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.ui.theme.KalivTheme

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/**
 * Minimal, dependency-free Markdown renderer for chat output.
 *
 * Covers: headings, bold/italic, inline code, fenced code blocks (with a copy
 * button), bullet/numbered lists, blockquotes, horizontal rules and links
 * (styled, not clickable). NOT covered: tables, deep list nesting, images.
 *
 * If you need full CommonMark, swap this one file for
 * `com.mikepenz:multiplatform-markdown-renderer-m3` — MarkdownText is the only
 * call site.
 */
@Composable
fun MarkdownText(
    markdown: String,
    modifier: Modifier = Modifier,
    color: Color = MaterialTheme.colorScheme.onSurface,
) {
    val blocks = remember(markdown) { parseBlocks(markdown) }
    // Resolved here, in composition, and passed into the (non-composable)
    // inline builder -- links are bronze in both palettes but read from the
    // active theme so a future palette change carries through.
    val linkColor = KalivTheme.colors.accent
    Column(modifier) {
        blocks.forEachIndexed { i, block ->
            if (i > 0) Spacer(Modifier.height(6.dp))
            when (block) {
                is Paragraph -> Text(inline(block.text, linkColor), color = color, fontSize = 16.sp, lineHeight = 24.sp)
                is Heading -> Text(
                    inline(block.text, linkColor),
                    color = color,
                    fontWeight = FontWeight.Bold,
                    lineHeight = 26.sp,
                    fontSize = when (block.level) {
                        1 -> 22.sp
                        2 -> 19.sp
                        3 -> 17.sp
                        else -> 15.sp
                    },
                )
                is Bullet -> Row {
                    Text("•  ", color = color, fontSize = 16.sp, lineHeight = 24.sp)
                    Text(inline(block.text, linkColor), color = color, fontSize = 16.sp, lineHeight = 24.sp)
                }
                is Numbered -> Row {
                    Text("${block.number}. ", color = color, fontSize = 16.sp, lineHeight = 24.sp)
                    Text(inline(block.text, linkColor), color = color, fontSize = 16.sp, lineHeight = 24.sp)
                }
                is Quote -> Row(Modifier.height(IntrinsicSize.Min)) {
                    Box(Modifier.width(3.dp).fillMaxHeight().background(KalivTheme.colors.signal))
                    Spacer(Modifier.width(8.dp))
                    Text(inline(block.text, linkColor), color = KalivTheme.colors.textMuted, fontSize = 16.sp, lineHeight = 24.sp)
                }
                is Code -> CodeBlock(block.language, block.code)
                Rule -> HorizontalDivider(color = MaterialTheme.colorScheme.outline)
            }
        }
    }
}

@Composable
private fun CodeBlock(language: String, code: String) {
    val clipboard = LocalClipboardManager.current
    Column(
        Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(8.dp))
            .background(KalivTheme.colors.codeSurface),
    ) {
        Row(
            Modifier.fillMaxWidth().padding(start = 12.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                language.ifBlank { "code" },
                color = KalivTheme.colors.textMuted,
                fontSize = 11.sp,
                fontFamily = FontFamily.Monospace,
            )
            Spacer(Modifier.weight(1f))
            TextButton(onClick = { clipboard.setText(AnnotatedString(code)) }) {
                Text("Kopiér", color = KalivTheme.colors.signal, fontSize = 12.sp)
            }
        }
        Text(
            code,
            modifier = Modifier
                .horizontalScroll(rememberScrollState())
                .padding(horizontal = 12.dp)
                .padding(bottom = 12.dp),
            color = MaterialTheme.colorScheme.onSurface,
            fontFamily = FontFamily.Monospace,
            fontSize = 13.sp,
            lineHeight = 19.sp,
        )
    }
}

// ---- block model ----
private sealed interface Block
private data class Paragraph(val text: String) : Block
private data class Heading(val level: Int, val text: String) : Block
private data class Bullet(val text: String) : Block
private data class Numbered(val number: String, val text: String) : Block
private data class Quote(val text: String) : Block
private data class Code(val language: String, val code: String) : Block
private data object Rule : Block

private val HEADING = Regex("^#{1,6}\\s+.*")
private val HR = Regex("^(-{3,}|\\*{3,}|_{3,})$")
private val BULLET = Regex("^[-*+]\\s+")
private val NUMBERED = Regex("^\\d+\\.\\s+")

private fun parseBlocks(md: String): List<Block> {
    val lines = md.replace("\r\n", "\n").split("\n")
    val blocks = mutableListOf<Block>()
    val para = StringBuilder()

    fun flushPara() {
        if (para.isNotBlank()) blocks.add(Paragraph(para.trim().toString()))
        para.setLength(0)
    }

    var i = 0
    while (i < lines.size) {
        val trimmed = lines[i].trim()
        when {
            trimmed.startsWith("```") -> {
                flushPara()
                val lang = trimmed.removePrefix("```").trim()
                val sb = StringBuilder()
                i++
                while (i < lines.size && !lines[i].trim().startsWith("```")) {
                    sb.append(lines[i]).append('\n')
                    i++
                }
                i++ // skip the closing fence
                blocks.add(Code(lang, sb.toString().trimEnd('\n')))
                continue
            }
            trimmed.isEmpty() -> flushPara()
            HEADING.matches(trimmed) -> {
                flushPara()
                val level = trimmed.takeWhile { it == '#' }.length
                blocks.add(Heading(level, trimmed.drop(level).trim()))
            }
            HR.matches(trimmed) -> {
                flushPara()
                blocks.add(Rule)
            }
            trimmed.startsWith("> ") -> {
                flushPara()
                blocks.add(Quote(trimmed.removePrefix("> ").trim()))
            }
            BULLET.containsMatchIn(trimmed) && BULLET.find(trimmed)?.range?.first == 0 -> {
                flushPara()
                blocks.add(Bullet(trimmed.replaceFirst(BULLET, "")))
            }
            NUMBERED.containsMatchIn(trimmed) && NUMBERED.find(trimmed)?.range?.first == 0 -> {
                flushPara()
                blocks.add(Numbered(trimmed.takeWhile { it.isDigit() }, trimmed.replaceFirst(NUMBERED, "")))
            }
            else -> {
                if (para.isNotEmpty()) para.append(' ')
                para.append(trimmed)
            }
        }
        i++
    }
    flushPara()
    return blocks
}

// ---- inline formatting ----
private val CODE_BG = Color(0x333A2A1F)  // smoke brown wash (was a cool grey tuned to sapphire)

private fun inline(text: String, linkColor: Color): AnnotatedString =
    buildAnnotatedString { appendInline(text, linkColor) }

private fun androidx.compose.ui.text.AnnotatedString.Builder.appendInline(
    text: String,
    linkColor: Color,
) {
    var i = 0
    val n = text.length
    while (i < n) {
        val c = text[i]
        when {
            c == '`' -> {
                val end = text.indexOf('`', i + 1)
                if (end == -1) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = CODE_BG)) {
                        append(text.substring(i + 1, end))
                    }
                    i = end + 1
                }
            }
            c == '*' && i + 1 < n && text[i + 1] == '*' -> {
                val end = text.indexOf("**", i + 2)
                if (end == -1) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { appendInline(text.substring(i + 2, end), linkColor) }
                    i = end + 2
                }
            }
            c == '_' && i + 1 < n && text[i + 1] == '_' -> {
                val end = text.indexOf("__", i + 2)
                if (end == -1) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { appendInline(text.substring(i + 2, end), linkColor) }
                    i = end + 2
                }
            }
            c == '*' -> {
                val end = text.indexOf('*', i + 1)
                if (end == -1) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { appendInline(text.substring(i + 1, end), linkColor) }
                    i = end + 1
                }
            }
            c == '_' -> {
                val end = text.indexOf('_', i + 1)
                if (end == -1) {
                    append(c); i++
                } else {
                    withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { appendInline(text.substring(i + 1, end), linkColor) }
                    i = end + 1
                }
            }
            c == '[' -> {
                val close = text.indexOf(']', i + 1)
                if (close != -1 && close + 1 < n && text[close + 1] == '(') {
                    val paren = text.indexOf(')', close + 2)
                    if (paren != -1) {
                        // Link text is styled (color + underline). Not clickable in v1;
                        // wrap with withLink(LinkAnnotation.Url(...)) on Compose 1.7+ to enable taps.
                        withStyle(SpanStyle(color = linkColor, textDecoration = TextDecoration.Underline)) {
                            appendInline(text.substring(i + 1, close), linkColor)
                        }
                        i = paren + 1
                    } else {
                        append(c); i++
                    }
                } else {
                    append(c); i++
                }
            }
            else -> {
                append(c); i++
            }
        }
    }
}

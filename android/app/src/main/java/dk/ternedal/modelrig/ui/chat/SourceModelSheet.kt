package dk.ternedal.modelrig.ui.chat

import androidx.compose.foundation.BorderStroke
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Icon
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.R
import dk.ternedal.modelrig.ui.components.CapsLabel
import dk.ternedal.modelrig.ui.components.KalivSheet
import dk.ternedal.modelrig.ui.theme.KalivTheme
import dk.ternedal.modelrig.ui.theme.KalivTokens
import dk.ternedal.modelrig.ui.theme.KalivType

/**
 * Skaerm 3 (Kilde & model) — 1:1 mod HTML-referencen, x393/322 jf. DDR-001/B2.
 * Indholdet er statsloest og screenshot-testbart; [SourceModelSheet] pakker det
 * i KalivSheet ved runtime. Live-status kommer fra /models + /models/running.
 */
data class ModelRowUi(
    val name: String,
    val selected: Boolean,
    val loaded: Boolean,
    /** "14B parametre" udledt af tagget; tom naar den ikke kan udledes. */
    val paramsLabel: String = "",
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SourceModelSheet(
    rigSelected: Boolean,
    rigStatus: String,
    rigConnected: Boolean,
    cloudAvailable: Boolean,
    cloudStatus: String,
    models: List<ModelRowUi>,
    onSelectRig: () -> Unit,
    onSelectCloud: () -> Unit,
    onSelectModel: (String) -> Unit,
    onReload: () -> Unit,
    onDismiss: () -> Unit,
) {
    KalivSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        SourceModelSheetContent(
            rigSelected, rigStatus, rigConnected, cloudAvailable, cloudStatus,
            models, onSelectRig, onSelectCloud, onSelectModel, onReload, onDismiss,
        )
    }
}

@Composable
fun SourceModelSheetContent(
    rigSelected: Boolean,
    rigStatus: String,
    rigConnected: Boolean,
    cloudAvailable: Boolean,
    cloudStatus: String,
    models: List<ModelRowUi>,
    onSelectRig: () -> Unit,
    onSelectCloud: () -> Unit,
    onSelectModel: (String) -> Unit,
    onReload: () -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(modifier.padding(start = 22.dp, end = 22.dp, bottom = 20.dp)) {
        Row(
            Modifier.fillMaxWidth().padding(bottom = 20.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                "Kilde & model",
                style = KalivType.Title,
                color = KalivTheme.colors.textHigh,
            )
            Spacer(Modifier.weight(1f))
            Box(
                Modifier
                    .size(34.dp)
                    .background(KalivTheme.colors.surfaceHigh, CircleShape)
                    .clickable(onClickLabel = "Luk") { onDismiss() },
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_close),
                    contentDescription = null,
                    tint = KalivTheme.colors.textMuted,
                    modifier = Modifier.size(18.dp),
                )
            }
        }

        CapsLabel("KILDE")
        Spacer(Modifier.height(11.dp))
        SourceCard(
            selected = rigSelected,
            icon = R.drawable.ic_kaliv_rig,
            iconTint = if (rigSelected) KalivTheme.colors.accent else KalivTheme.colors.textMuted,
            title = "Din rig",
            titleSuffix = " \u00b7 lokalt",
            statusDot = if (rigConnected) KalivTheme.colors.success else KalivTheme.colors.danger,
            statusText = rigStatus,
            statusColor = KalivTheme.colors.textMuted,
            onClick = onSelectRig,
        )
        Spacer(Modifier.height(11.dp))
        SourceCard(
            selected = !rigSelected && cloudAvailable,
            enabled = cloudAvailable,
            icon = R.drawable.ic_kaliv_cloud,
            iconTint = KalivTheme.colors.textMuted,
            title = "Ollama Cloud",
            titleSuffix = "",
            // Cloud-prikken er neutral graa i referencen (#5A5F60) — bevidst
            // uden for tokensaettet: hverken ok eller fejl, bare "derude".
            statusDot = Color(0xFF5A5F60),
            statusText = cloudStatus,
            statusColor = KalivTheme.colors.faint,
            onClick = onSelectCloud,
        )

        Spacer(Modifier.height(24.dp))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            CapsLabel("MODEL P\u00c5 DIN RIG")
            Spacer(Modifier.weight(1f))
            Row(
                Modifier.clickable(onClickLabel = "Genindl\u00e6s modeller") { onReload() },
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_retry),
                    contentDescription = null,
                    tint = KalivTheme.colors.accent,
                    modifier = Modifier.size(16.dp),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    "Genindl\u00e6s",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                    color = KalivTheme.colors.accent,
                )
            }
        }
        Spacer(Modifier.height(11.dp))
        models.forEachIndexed { i, m ->
            ModelRow(m, onClick = { onSelectModel(m.name) })
            if (i < models.lastIndex) HorizontalDivider(thickness = KalivTokens.Layout.hairline, color = KalivTheme.colors.divider)
        }
    }
}

@Composable
private fun SourceCard(
    selected: Boolean,
    icon: Int,
    iconTint: Color,
    title: String,
    titleSuffix: String,
    statusDot: Color,
    statusText: String,
    statusColor: Color,
    onClick: () -> Unit,
    enabled: Boolean = true,
) {
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(KalivTokens.Radius.card),
        color = if (selected) KalivTheme.colors.selectedTint else KalivTheme.colors.surface,
        border = BorderStroke(
            if (selected) 2.dp else KalivTokens.Layout.hairline,
            if (selected) KalivTokens.Gold.fill else KalivTheme.colors.hairline,
        ),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.padding(horizontal = 16.dp, vertical = 15.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(
                Modifier
                    .size(49.dp)
                    .background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(13.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(icon),
                    contentDescription = null,
                    tint = iconTint,
                    modifier = Modifier.size(25.dp),
                )
            }
            Spacer(Modifier.width(15.dp))
            Column(Modifier.weight(1f)) {
                Row {
                    Text(
                        title,
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 17.sp),
                        color = KalivTheme.colors.textHigh,
                    )
                    if (titleSuffix.isNotEmpty()) {
                        Text(
                            titleSuffix,
                            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 17.sp),
                            color = KalivTheme.colors.faint,
                        )
                    }
                }
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(9.dp).background(statusDot, CircleShape))
                    Spacer(Modifier.width(7.dp))
                    Text(
                        statusText,
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                        color = statusColor,
                        maxLines = 1,
                    )
                }
            }
            Spacer(Modifier.width(12.dp))
            if (selected) {
                Box(
                    Modifier.size(27.dp).background(KalivTokens.Gold.fill, CircleShape),
                    contentAlignment = Alignment.Center,
                ) {
                    Icon(
                        painterResource(R.drawable.ic_kaliv_check),
                        contentDescription = "Valgt",
                        tint = KalivTheme.colors.sheet,
                        modifier = Modifier.size(16.dp),
                    )
                }
            } else {
                Box(
                    Modifier
                        .size(27.dp)
                        .border(2.dp, KalivTheme.colors.hairline, CircleShape),
                )
            }
        }
    }
}

@Composable
private fun ModelRow(m: ModelRowUi, onClick: () -> Unit) {
    Row(
        Modifier
            .fillMaxWidth()
            .clickable(onClickLabel = "V\u00e6lg ${m.name}") { onClick() }
            .padding(vertical = 12.dp, horizontal = 2.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (m.selected) {
            Box(
                Modifier.size(23.dp).border(2.5.dp, KalivTokens.Gold.fill, CircleShape),
                contentAlignment = Alignment.Center,
            ) {
                Box(Modifier.size(11.dp).background(KalivTokens.Gold.fill, CircleShape))
            }
        } else {
            Box(Modifier.size(23.dp).border(2.5.dp, KalivTheme.colors.hairline, CircleShape))
        }
        Spacer(Modifier.width(13.dp))
        Column(Modifier.weight(1f)) {
            Text(
                m.name,
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.5.sp),
                color = if (m.selected) KalivTheme.colors.textHigh else KalivTheme.colors.textSoft,
            )
            if (m.paramsLabel.isNotEmpty()) {
                Text(
                    m.paramsLabel,
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.5.sp),
                    color = KalivTheme.colors.faint,
                )
            }
        }
        if (m.loaded) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.size(7.dp).background(KalivTheme.colors.success, CircleShape))
                Spacer(Modifier.width(6.dp))
                Text(
                    "Indl\u00e6st",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                    color = KalivTheme.colors.success,
                )
            }
        } else {
            Text(
                "Klar",
                style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.Medium, fontSize = 13.sp),
                color = KalivTheme.colors.faint,
            )
        }
    }
}

/** ":14b" -> "14B parametre"; tom naar tagget ikke baerer stoerrelsen. */
fun paramsLabelFor(name: String): String {
    val m = Regex("[:\\-](\\d+(?:\\.\\d+)?)b\\b", RegexOption.IGNORE_CASE).find(name)
    return m?.let { "${it.groupValues[1].uppercase()}B parametre" } ?: ""
}

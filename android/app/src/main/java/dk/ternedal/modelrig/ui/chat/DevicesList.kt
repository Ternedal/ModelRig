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
 * Enheder — parrede telefoner/klienter og tilbagekald af adgang.
 *
 * Der findes INGEN mockup for denne skærm; den er tegnet i systemets eget
 * sprog (samme form som Rig-status' kort). Alt vist kommer fra
 * GET /api/v1/devices, som bevidst ikke udleverer token-hashes.
 */
data class DeviceRowUi(
    val id: String,
    val name: String,
    val pairedLabel: String,
    val lastSeenLabel: String,
    val isThisDevice: Boolean,
)

@Composable
fun DeviceRow(
    ui: DeviceRowUi,
    busy: Boolean,
    onRevoke: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Column(
        modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surface, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 16.dp, vertical = 15.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Box(
                Modifier.size(41.dp).background(KalivTheme.colors.surfaceHigh, RoundedCornerShape(11.dp)),
                contentAlignment = Alignment.Center,
            ) {
                Icon(
                    painterResource(R.drawable.ic_kaliv_phone),
                    contentDescription = null,
                    tint = if (ui.isThisDevice) KalivTheme.colors.accent else KalivTheme.colors.textMuted,
                    modifier = Modifier.size(20.dp),
                )
            }
            Spacer(Modifier.width(13.dp))
            Column(Modifier.weight(1f)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        ui.name,
                        style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
                        color = KalivTheme.colors.textHigh,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (ui.isThisDevice) {
                        Spacer(Modifier.width(9.dp))
                        Text(
                            "DENNE ENHED",
                            style = TextStyle(
                                fontFamily = KalivType.Inter,
                                fontWeight = FontWeight.SemiBold,
                                fontSize = 11.sp,
                                letterSpacing = 0.08.em,
                            ),
                            color = KalivTheme.colors.accent,
                            modifier = Modifier
                                .background(KalivTokens.Gold.tint, RoundedCornerShape(KalivTokens.Radius.round))
                                .padding(horizontal = 9.dp, vertical = 3.dp),
                        )
                    }
                }
                Spacer(Modifier.height(3.dp))
                Text(
                    ui.pairedLabel,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
                    color = KalivTheme.colors.textMuted,
                )
                Text(
                    ui.lastSeenLabel,
                    style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.sp),
                    color = KalivTheme.colors.caps,
                )
            }
            Spacer(Modifier.width(10.dp))
            Box(
                Modifier
                    .border(KalivTokens.Layout.hairline, KalivTheme.colors.danger, RoundedCornerShape(11.dp))
                    .clickable(enabled = !busy, onClickLabel = "Fjern adgang") { onRevoke() }
                    .padding(horizontal = 13.dp, vertical = 8.dp),
            ) {
                Text(
                    "Fjern",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 13.5.sp),
                    color = KalivTheme.colors.danger,
                )
            }
        }
    }
}

/**
 * Noten når appen ikke ved hvilken række der er denne telefon: enheder
 * parret før 2.0.4 gemte ikke deres id. Så siger vi det, i stedet for at
 * gætte og risikere at man låser sig selv ude.
 */
@Composable
fun DevicesUnknownSelfNote(modifier: Modifier = Modifier) {
    val shape = RoundedCornerShape(KalivTokens.Radius.card)
    Text(
        "Appen kan ikke se hvilken række der er denne telefon — parringen skete før enheds-id blev gemt. Fjerner du den forkerte, mister du selv adgangen og skal parre igen.",
        style = TextStyle(fontFamily = KalivType.Inter, fontSize = 13.5.sp),
        color = KalivTheme.colors.textMuted,
        modifier = modifier
            .fillMaxWidth()
            .background(KalivTheme.colors.surfaceDim, shape)
            .border(KalivTokens.Layout.hairline, KalivTheme.colors.hairline, shape)
            .padding(horizontal = 15.dp, vertical = 12.dp),
    )
}

/** Bekræftelseskortet — vises i stedet for en systemdialog, i skærmens eget sprog. */
@Composable
fun DeviceRevokeConfirm(
    deviceName: String,
    isThisDevice: Boolean,
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
            if (isThisDevice) "Fjern DENNE telefons adgang?" else "Fjern adgang for $deviceName?",
            style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 16.sp),
            color = KalivTheme.colors.textHigh,
        )
        Spacer(Modifier.height(4.dp))
        Text(
            if (isThisDevice) {
                "Kaliv mister forbindelsen til riggen med det samme, og du skal parre igen med en ny kode fra riggen."
            } else {
                "Enhedens token holder op med at virke med det samme — også midt i en igangværende session."
            },
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
                    .clickable(enabled = !busy, onClickLabel = "Fjern adgang") { onConfirm() }
                    .padding(vertical = 11.dp),
                contentAlignment = Alignment.Center,
            ) {
                Text(
                    if (busy) "Fjerner …" else "Fjern adgang",
                    style = TextStyle(fontFamily = KalivType.Inter, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp),
                    color = KalivTheme.colors.danger,
                )
            }
        }
    }
}

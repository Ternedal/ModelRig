package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.net.Agent3Client
import dk.ternedal.modelrig.ui.theme.KalivTheme

/** Server-authoritative readiness receipt shown before a single-use plan may start. */
@Composable
fun Agent3CapabilityReceiptCard(receipt: Agent3Client.CapabilityReceipt) {
    Surface(color = KalivTheme.colors.surfaceHigh, shape = RoundedCornerShape(10.dp)) {
        Column(Modifier.fillMaxWidth().padding(10.dp)) {
            Row(Modifier.fillMaxWidth()) {
                Text(
                    "Capability receipt",
                    color = KalivTheme.colors.textHigh,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    if (receipt.allowed) "KLAR" else "BLOKERET",
                    color = if (receipt.allowed) KalivTheme.colors.success else KalivTheme.colors.danger,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.height(5.dp))
            Text(
                "route=${receipt.route} · krav=${receipt.requiredCapabilityIds.size} · blockers=${receipt.blockers.size}",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            if (receipt.requiredCapabilityIds.isNotEmpty()) {
                Text(
                    "kræver: ${receipt.requiredCapabilityIds.joinToString(", ")}",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                )
            }
            Text(
                "graph: ${receipt.graphSha256.take(16)}…",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
            )
            Text(
                "plan: ${receipt.planSha256.take(16)}…",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
            )
            receipt.blockers.forEach { blocker ->
                Spacer(Modifier.height(6.dp))
                Text(
                    "${blocker.capabilityId} · ${blocker.state}",
                    color = KalivTheme.colors.danger,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    blocker.reason,
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                )
            }
            if (!receipt.allowed) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Planen kan ikke startes. Lav et nyt preview efter capability-problemet er løst.",
                    color = KalivTheme.colors.danger,
                    fontSize = 10.sp,
                )
            }
        }
    }
}

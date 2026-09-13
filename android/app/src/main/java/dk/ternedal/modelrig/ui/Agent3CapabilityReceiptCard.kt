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
                    "Kapabilitetstjek",
                    color = KalivTheme.colors.textHigh,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.weight(1f),
                )
                Text(
                    presentAgent3CapabilityStatusLabel(receipt.allowed),
                    color = if (receipt.allowed) KalivTheme.colors.success else KalivTheme.colors.danger,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold,
                )
            }
            Spacer(Modifier.height(5.dp))
            Text(
                presentAgent3CapabilityStatusMessage(receipt.allowed),
                color = if (receipt.allowed) KalivTheme.colors.success else KalivTheme.colors.danger,
                fontSize = 10.sp,
            )
            Text(
                "Rute: ${presentAgent3CapabilityRoute(receipt.route)}",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            Text(
                "Krav: ${presentAgent3RequiredCapabilityCount(receipt.requiredCapabilityIds.size)} · " +
                    "Blokeringer: ${presentAgent3CapabilityBlockerCount(receipt.blockers.size)}",
                color = KalivTheme.colors.textMuted,
                fontSize = 10.sp,
            )
            Text(
                "Graf-hash: ${receipt.graphSha256.take(16)}…",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
            )
            Text(
                "Plan-hash: ${receipt.planSha256.take(16)}…",
                color = KalivTheme.colors.textMuted,
                fontSize = 9.sp,
            )
            if (receipt.requiredCapabilityIds.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Teknisk kvittering · krævede capabilities",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                receipt.requiredCapabilityIds.forEach { capabilityId ->
                    val field = agent3RequiredCapabilityEvidence(capabilityId)
                    Text(
                        "${field.label}: ${field.value}",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 9.sp,
                    )
                }
            }
            if (receipt.blockers.isNotEmpty()) {
                Spacer(Modifier.height(6.dp))
                Text(
                    "Teknisk kvittering · blokeringer",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                receipt.blockers.forEachIndexed { index, blocker ->
                    Text(
                        "Blokering ${index + 1}",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    agent3CapabilityBlockerEvidence(
                        blocker.capabilityId,
                        blocker.state,
                        blocker.reason,
                    ).forEach { field ->
                        Text(
                            "${field.label}: ${field.value}",
                            color = KalivTheme.colors.textMuted,
                            fontSize = 9.sp,
                        )
                    }
                }
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
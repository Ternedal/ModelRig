package dk.ternedal.modelrig.desktop

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import dk.ternedal.modelrig.desktop.net.ControlCenterPrivacy

internal fun desktopControlCenterPrivacyEvidenceLabel(state: String): String = when (state) {
    "ready" -> "Aktuel runtime-evidens"
    "unknown" -> "Privacy-status er ukendt"
    else -> "Ukendt privacy-status"
}

internal fun desktopControlCenterPrivateEgressLabel(privacy: ControlCenterPrivacy): String =
    when (privacy.toolResultEgress?.privateRule) {
        "blocked_requires_explicit_consent" ->
            "Privat cloud-data: blokeret · kræver eksplicit samtykke"
        "allowed_legacy_mode" ->
            "Privat cloud-data: tilladt i legacy-mode · egress-gaten er slået fra"
        else -> "Privat cloud-data: ukendt"
    }

internal fun desktopControlCenterCommonSharingLabel(privacy: ControlCenterPrivacy): String =
    when (privacy.commonDataSharing.state) {
        "dormant" -> "Fælles data-sharing: dormant · ikke runtime-integreret"
        else -> "Fælles data-sharing: ukendt"
    }

internal fun desktopControlCenterScopedPermissionsLabel(privacy: ControlCenterPrivacy): String =
    when {
        privacy.scopedPermissions.revocationSupported ->
            "Scoped tilladelser: tilbagekaldelse tilgængelig"
        privacy.scopedPermissions.state == "unavailable" ->
            "Scoped tilladelser: ingen aktiv authority · tilbagekaldelse utilgængelig"
        else -> "Scoped tilladelser: ukendt · tilbagekaldelse utilgængelig"
    }

@Composable
internal fun DesktopControlCenterPrivacySection(privacy: ControlCenterPrivacy) {
    Column(
        modifier = Modifier.padding(top = 8.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "Privacy & data-sharing",
            color = KalivTheme.colors.TextHigh,
            fontSize = 18.sp,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            "Aktiv ToolGate-policy · dormant permissions markeres som dormant",
            color = KalivTheme.colors.TextMuted,
            fontSize = 10.sp,
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .background(KalivTheme.colors.Surface, RoundedCornerShape(12.dp))
                .padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            Text(
                desktopControlCenterPrivacyEvidenceLabel(privacy.evidenceState),
                color = KalivTheme.colors.TextHigh,
                fontWeight = FontWeight.SemiBold,
            )
            if (privacy.evidenceState != "ready") {
                Text(
                    "Manglende privacy-evidens bliver ikke fortolket som en sikker standard.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 10.sp,
                )
                privacy.reason?.let {
                    Text("Årsag: $it", color = KalivTheme.colors.TextMuted, fontSize = 9.sp)
                }
            }

            privacy.toolResultEgress?.let { egress ->
                Text(
                    "Tool-resultater til cloud",
                    color = KalivTheme.colors.TextHigh,
                    fontSize = 12.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(top = 3.dp),
                )
                Text("Offentlig data: tilladt", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                Text("Driftsdata: tilladt", color = KalivTheme.colors.TextMuted, fontSize = 10.sp)
                Text(
                    desktopControlCenterPrivateEgressLabel(privacy),
                    color = if (egress.privateGateEnabled) {
                        KalivTheme.colors.TextHigh
                    } else {
                        KalivTheme.colors.TextMuted
                    },
                    fontSize = 10.sp,
                    fontWeight = if (egress.privateGateEnabled) FontWeight.SemiBold else FontWeight.Normal,
                )
                Text("Hemmelig data: altid forbudt", color = KalivTheme.colors.TextHigh, fontSize = 10.sp)
            }

            Text(
                desktopControlCenterCommonSharingLabel(privacy),
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
                modifier = Modifier.padding(top = 3.dp),
            )
            Text(
                desktopControlCenterScopedPermissionsLabel(privacy),
                color = KalivTheme.colors.TextMuted,
                fontSize = 10.sp,
            )
            Text(
                "Production activation: ${if (privacy.productionActivation) "JA" else "nej"}",
                color = KalivTheme.colors.TextMuted,
                fontSize = 9.sp,
            )
            if (!privacy.scopedPermissions.revocationSupported) {
                Text(
                    "Der vises ingen tilbagekald-knap, før en aktiv scoped permission-authority findes.",
                    color = KalivTheme.colors.TextMuted,
                    fontSize = 9.sp,
                )
            }
        }
    }
}

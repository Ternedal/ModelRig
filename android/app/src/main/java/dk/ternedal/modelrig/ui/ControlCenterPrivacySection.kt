package dk.ternedal.modelrig.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import dk.ternedal.modelrig.net.ControlCenterPrivacy
import dk.ternedal.modelrig.ui.theme.KalivTheme

internal fun controlCenterPrivacyEvidenceLabel(state: String): String = when (state) {
    "ready" -> "Aktuel runtime-evidens"
    "unknown" -> "Privacy-status er ukendt"
    else -> "Ukendt privacy-status"
}

internal fun controlCenterPrivateEgressLabel(privacy: ControlCenterPrivacy): String =
    when (privacy.toolResultEgress?.privateRule) {
        "blocked_requires_explicit_consent" ->
            "Privat cloud-data: blokeret · kræver eksplicit samtykke"
        "allowed_legacy_mode" ->
            "Privat cloud-data: tilladt i legacy-mode · egress-gaten er slået fra"
        else -> "Privat cloud-data: ukendt"
    }

internal fun controlCenterCommonSharingLabel(privacy: ControlCenterPrivacy): String =
    when (privacy.commonDataSharing.state) {
        "dormant" -> "Fælles data-sharing: dormant · ikke runtime-integreret"
        else -> "Fælles data-sharing: ukendt"
    }

internal fun controlCenterScopedPermissionsLabel(privacy: ControlCenterPrivacy): String =
    when {
        privacy.scopedPermissions.revocationSupported ->
            "Scoped tilladelser: tilbagekaldelse tilgængelig"
        privacy.scopedPermissions.state == "unavailable" ->
            "Scoped tilladelser: ingen aktiv authority · tilbagekaldelse utilgængelig"
        else -> "Scoped tilladelser: ukendt · tilbagekaldelse utilgængelig"
    }

@Composable
internal fun ControlCenterPrivacySection(privacy: ControlCenterPrivacy) {
    Column(
        modifier = Modifier.padding(top = 10.dp, bottom = 2.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            "Privacy & data-sharing",
            color = KalivTheme.colors.textHigh,
            fontSize = 20.sp,
            fontWeight = FontWeight.Bold,
        )
        Text(
            "Aktiv ToolGate-policy · dormant permissions markeres som dormant",
            color = KalivTheme.colors.textMuted,
            fontSize = 11.sp,
        )

        Surface(
            color = KalivTheme.colors.surface,
            shape = RoundedCornerShape(14.dp),
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(5.dp),
            ) {
                Text(
                    controlCenterPrivacyEvidenceLabel(privacy.evidenceState),
                    color = KalivTheme.colors.textHigh,
                    fontSize = 15.sp,
                    fontWeight = FontWeight.SemiBold,
                )
                if (privacy.evidenceState != "ready") {
                    Text(
                        "Manglende privacy-evidens bliver ikke fortolket som en sikker standard.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 11.sp,
                    )
                    privacy.reason?.let {
                        Text("Årsag: $it", color = KalivTheme.colors.textMuted, fontSize = 10.sp)
                    }
                }

                privacy.toolResultEgress?.let { egress ->
                    Spacer(Modifier.height(3.dp))
                    Text(
                        "Tool-resultater til cloud",
                        color = KalivTheme.colors.textHigh,
                        fontSize = 13.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text("Offentlig data: tilladt", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    Text("Driftsdata: tilladt", color = KalivTheme.colors.textMuted, fontSize = 11.sp)
                    Text(
                        controlCenterPrivateEgressLabel(privacy),
                        color = if (egress.privateGateEnabled) {
                            KalivTheme.colors.textHigh
                        } else {
                            KalivTheme.colors.textMuted
                        },
                        fontSize = 11.sp,
                        fontWeight = if (egress.privateGateEnabled) FontWeight.SemiBold else FontWeight.Normal,
                    )
                    Text("Hemmelig data: altid forbudt", color = KalivTheme.colors.textHigh, fontSize = 11.sp)
                }

                Spacer(Modifier.height(3.dp))
                Text(
                    controlCenterCommonSharingLabel(privacy),
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Text(
                    controlCenterScopedPermissionsLabel(privacy),
                    color = KalivTheme.colors.textMuted,
                    fontSize = 11.sp,
                )
                Text(
                    "Production activation: ${if (privacy.productionActivation) "JA" else "nej"}",
                    color = KalivTheme.colors.textMuted,
                    fontSize = 10.sp,
                )
                if (!privacy.scopedPermissions.revocationSupported) {
                    Text(
                        "Der vises ingen tilbagekald-knap, før en aktiv scoped permission-authority findes.",
                        color = KalivTheme.colors.textMuted,
                        fontSize = 10.sp,
                    )
                }
            }
        }
    }
}

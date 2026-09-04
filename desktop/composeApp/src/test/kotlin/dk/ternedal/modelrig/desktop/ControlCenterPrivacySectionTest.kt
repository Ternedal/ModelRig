package dk.ternedal.modelrig.desktop

import dk.ternedal.modelrig.desktop.net.ControlCenterCommonDataSharing
import dk.ternedal.modelrig.desktop.net.ControlCenterPrivacy
import dk.ternedal.modelrig.desktop.net.ControlCenterScopedPermissions
import dk.ternedal.modelrig.desktop.net.ControlCenterToolResultEgress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ControlCenterPrivacySectionTest {
    @Test
    fun gateOffIsExplicitLegacyWarningRatherThanProtectedState() {
        val privacy = privacy(privateGateEnabled = false)

        assertTrue(desktopControlCenterPrivateEgressLabel(privacy).contains("legacy-mode"))
        assertTrue(desktopControlCenterPrivateEgressLabel(privacy).contains("slået fra"))
        assertEquals("Aktuel runtime-evidens", desktopControlCenterPrivacyEvidenceLabel("ready"))
    }

    @Test
    fun gateOnNamesExplicitConsentRequirement() {
        val privacy = privacy(privateGateEnabled = true)

        assertTrue(desktopControlCenterPrivateEgressLabel(privacy).contains("blokeret"))
        assertTrue(desktopControlCenterPrivateEgressLabel(privacy).contains("eksplicit samtykke"))
    }

    @Test
    fun dormantDataSharingAndUnavailableRevocationStayVisible() {
        val privacy = privacy(privateGateEnabled = true)

        assertTrue(desktopControlCenterCommonSharingLabel(privacy).contains("dormant"))
        assertTrue(desktopControlCenterCommonSharingLabel(privacy).contains("ikke runtime-integreret"))
        assertTrue(desktopControlCenterScopedPermissionsLabel(privacy).contains("tilbagekaldelse utilgængelig"))
        assertFalse(privacy.scopedPermissions.revocationSupported)
    }

    @Test
    fun missingPrivacyIsUnknownNeverProtected() {
        val privacy = ControlCenterPrivacy.unreported()

        assertEquals("Privacy-status er ukendt", desktopControlCenterPrivacyEvidenceLabel(privacy.evidenceState))
        assertEquals("Privat cloud-data: ukendt", desktopControlCenterPrivateEgressLabel(privacy))
        assertTrue(desktopControlCenterScopedPermissionsLabel(privacy).contains("ukendt"))
    }

    private fun privacy(privateGateEnabled: Boolean) = ControlCenterPrivacy(
        schema = "kaliv-control-center-privacy/v1",
        evidenceState = "ready",
        reason = null,
        toolResultEgress = ControlCenterToolResultEgress(
            privateGateEnabled = privateGateEnabled,
            publicRule = "allowed",
            operationalRule = "allowed",
            privateRule = if (privateGateEnabled) {
                "blocked_requires_explicit_consent"
            } else {
                "allowed_legacy_mode"
            },
            secretRule = "forbidden",
        ),
        commonDataSharing = ControlCenterCommonDataSharing(
            state = "dormant",
            runtimeIntegrated = false,
            reason = "common_data_sharing_not_runtime_integrated",
        ),
        scopedPermissions = ControlCenterScopedPermissions(
            state = "unavailable",
            revocationSupported = false,
            reason = "no_active_scoped_permission_authority",
        ),
        productionActivation = false,
    )
}

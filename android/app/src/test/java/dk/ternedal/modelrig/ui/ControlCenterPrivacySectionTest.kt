package dk.ternedal.modelrig.ui

import dk.ternedal.modelrig.net.ControlCenterCommonDataSharing
import dk.ternedal.modelrig.net.ControlCenterPrivacy
import dk.ternedal.modelrig.net.ControlCenterScopedPermissions
import dk.ternedal.modelrig.net.ControlCenterToolResultEgress
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterPrivacySectionTest {
    @Test
    fun gateOffIsExplicitLegacyWarningRatherThanProtectedState() {
        val privacy = privacy(privateGateEnabled = false)

        assertTrue(controlCenterPrivateEgressLabel(privacy).contains("legacy-mode"))
        assertTrue(controlCenterPrivateEgressLabel(privacy).contains("slået fra"))
        assertEquals("Aktuel runtime-evidens", controlCenterPrivacyEvidenceLabel("ready"))
    }

    @Test
    fun gateOnNamesExplicitConsentRequirement() {
        val privacy = privacy(privateGateEnabled = true)

        assertTrue(controlCenterPrivateEgressLabel(privacy).contains("blokeret"))
        assertTrue(controlCenterPrivateEgressLabel(privacy).contains("eksplicit samtykke"))
    }

    @Test
    fun dormantDataSharingAndUnavailableRevocationStayVisible() {
        val privacy = privacy(privateGateEnabled = true)

        assertTrue(controlCenterCommonSharingLabel(privacy).contains("dormant"))
        assertTrue(controlCenterCommonSharingLabel(privacy).contains("ikke runtime-integreret"))
        assertTrue(controlCenterScopedPermissionsLabel(privacy).contains("tilbagekaldelse utilgængelig"))
        assertFalse(privacy.scopedPermissions.revocationSupported)
    }

    @Test
    fun missingPrivacyIsUnknownNeverProtected() {
        val privacy = ControlCenterPrivacy.unreported()

        assertEquals("Privacy-status er ukendt", controlCenterPrivacyEvidenceLabel(privacy.evidenceState))
        assertEquals("Privat cloud-data: ukendt", controlCenterPrivateEgressLabel(privacy))
        assertTrue(controlCenterScopedPermissionsLabel(privacy).contains("ukendt"))
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

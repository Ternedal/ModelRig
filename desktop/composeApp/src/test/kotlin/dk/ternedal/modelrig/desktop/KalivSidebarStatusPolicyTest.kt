package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivSidebarStatusPolicyTest {
    @Test
    fun localOnlyPolicyDoesNotClaimCloudCapability() {
        val status = presentSidebarStatus(
            preferLocal = true,
            autoCloudFallback = false,
            cloudConfigured = true,
            localModel = "local-model",
            cloudModel = "cloud-model",
        )

        assertEquals("local-model", status.modelName)
        assertEquals("Primær · lokal", status.modelAuthority)
        assertEquals("Chat: kun lokal", status.privacyTitle)
        assertEquals("Ingen automatisk cloud-fallback", status.privacyDetail)
        assertTrue(status.localOnly)
    }

    @Test
    fun localFirstWithConfiguredFallbackMakesCloudPossibilityExplicit() {
        val status = presentSidebarStatus(
            preferLocal = true,
            autoCloudFallback = true,
            cloudConfigured = true,
            localModel = "local-model",
            cloudModel = "cloud-model",
        )

        assertEquals("local-model", status.modelName)
        assertEquals("Lokal først · cloud muligt", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun cloudPreferredNamesCloudModelAndPolicy() {
        val status = presentSidebarStatus(
            preferLocal = false,
            autoCloudFallback = false,
            cloudConfigured = true,
            localModel = "local-model",
            cloudModel = "cloud-model",
        )

        assertEquals("cloud-model", status.modelName)
        assertEquals("Primær · cloud", status.modelAuthority)
        assertEquals("Cloud foretrukket", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun unavailablePreferredCloudFailsClosedInsteadOfClaimingLocalOnly() {
        val status = presentSidebarStatus(
            preferLocal = false,
            autoCloudFallback = false,
            cloudConfigured = false,
            localModel = "local-model",
            cloudModel = "cloud-model",
        )

        assertEquals("cloud-model", status.modelName)
        assertEquals("Cloud valgt · ikke konfigureret", status.modelAuthority)
        assertEquals("Cloud valgt · ikke klar", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun unavailableVramHasNoMeterOrReferenceValue() {
        val presentation = presentVram(KalivVramTelemetry.Unavailable)

        assertFalse(presentation.measured)
        assertNull(presentation.fraction)
        assertEquals("VRAM ikke målt", presentation.label)
    }

    @Test
    fun measuredVramFormatsObservedValues() {
        val presentation = presentVram(KalivVramTelemetry.Measured(usedGb = 6.25, totalGb = 12.0))

        assertTrue(presentation.measured)
        assertEquals(6.25f / 12.0f, presentation.fraction)
        assertEquals("VRAM 6,3 / 12 GB", presentation.label)
    }
}

package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class KalivSidebarStatusPolicyTest {
    @Test
    fun localOnlyPolicyDoesNotClaimCloudCapability() {
        val status = presentSidebarStatus(true, false, true, "local-model", "cloud-model")
        assertEquals("local-model", status.modelName)
        assertEquals("Primær · lokal", status.modelAuthority)
        assertEquals("Chat: kun lokal", status.privacyTitle)
        assertEquals("Ingen automatisk cloud-fallback", status.privacyDetail)
        assertTrue(status.localOnly)
    }

    @Test
    fun localFirstWithConfiguredFallbackMakesCloudPossibilityExplicit() {
        val status = presentSidebarStatus(true, true, true, "local-model", "cloud-model")
        assertEquals("local-model", status.modelName)
        assertEquals("Lokal først · cloud muligt", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun cloudPreferredNamesCloudModelAndPolicy() {
        val status = presentSidebarStatus(false, false, true, "local-model", "cloud-model")
        assertEquals("cloud-model", status.modelName)
        assertEquals("Primær · cloud", status.modelAuthority)
        assertEquals("Cloud foretrukket", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun unavailablePreferredCloudFailsClosedWithVisiblePlaceholder() {
        val status = presentSidebarStatus(false, false, false, "local-model", "")
        assertEquals("Cloud-model ikke valgt", status.modelName)
        assertEquals("Cloud valgt · ikke konfigureret", status.modelAuthority)
        assertEquals("Cloud valgt · ikke klar", status.privacyTitle)
        assertFalse(status.localOnly)
    }

    @Test
    fun enabledButUnconfiguredCloudFallbackDoesNotPretendPolicyIsDisabled() {
        val status = presentSidebarStatus(true, true, false, "local-model", "cloud-model")
        assertEquals("Chat: lokal nu", status.privacyTitle)
        assertTrue(status.privacyDetail.contains("Cloud-fallback er slået til"))
        assertTrue(status.localOnly)
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
        val presentation = presentVram(KalivVramTelemetry.Measured(6.25, 12.0))
        assertTrue(presentation.measured)
        assertEquals(6.25f / 12.0f, presentation.fraction)
        assertEquals("VRAM 6,3 / 12 GB", presentation.label)
    }

    @Test
    fun impossibleVramMeasurementsFailClosed() {
        assertFailsWith<IllegalArgumentException> { KalivVramTelemetry.Measured(-0.1, 12.0) }
        assertFailsWith<IllegalArgumentException> { KalivVramTelemetry.Measured(1.0, 0.0) }
        assertFailsWith<IllegalArgumentException> { KalivVramTelemetry.Measured(13.0, 12.0) }
        assertFailsWith<IllegalArgumentException> { KalivVramTelemetry.Measured(Double.NaN, 12.0) }
    }
}

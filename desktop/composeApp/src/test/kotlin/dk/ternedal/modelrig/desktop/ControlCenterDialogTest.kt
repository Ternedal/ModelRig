package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class ControlCenterDialogTest {
    @Test
    fun overallLabelsNeverTurnUnknownIntoHealthy() {
        assertEquals("Alt ser godt ud", desktopControlCenterOverallLabel("healthy"))
        assertEquals("Kræver opmærksomhed", desktopControlCenterOverallLabel("attention"))
        assertEquals("Utilgængelig", desktopControlCenterOverallLabel("unavailable"))
        assertEquals("Status er ukendt", desktopControlCenterOverallLabel("unknown"))
        assertEquals("Ukendt status", desktopControlCenterOverallLabel("future-state"))
    }

    @Test
    fun stateLabelsKeepStaleUnknownAndDisabledDistinct() {
        assertEquals("Klar", desktopControlCenterStateLabel("healthy"))
        assertEquals("Forældet", desktopControlCenterStateLabel("stale"))
        assertEquals("Ukendt", desktopControlCenterStateLabel("unknown"))
        assertEquals("Slået fra", desktopControlCenterStateLabel("disabled"))
        assertEquals("Fallback", desktopControlCenterStateLabel("fallback"))
        assertEquals("Ukendt", desktopControlCenterStateLabel("synthetic-green"))
    }

    @Test
    fun titlesAndAgeAreHumanReadableWithoutInventingFreshness() {
        assertEquals("Backend", desktopControlCenterTitle("backend"))
        assertEquals("Worker", desktopControlCenterTitle("worker"))
        assertEquals("Modeller", desktopControlCenterTitle("models"))
        assertEquals("Agent 3", desktopControlCenterTitle("agent3"))
        assertEquals("custom", desktopControlCenterTitle("custom"))
        assertEquals("målt nu", desktopControlCenterAge(0.0))
        assertEquals("målt for 12 sek. siden", desktopControlCenterAge(12.0))
        assertEquals("målt for 2 min. siden", desktopControlCenterAge(125.0))
        assertNull(desktopControlCenterAge(null))
        assertNull(desktopControlCenterAge(-1.0))
        assertNull(desktopControlCenterAge(Double.NaN))
        assertNull(desktopControlCenterAge(Double.POSITIVE_INFINITY))
    }

    @Test
    fun knownControlCenterErrorsKeepBoundedHumanCopy() {
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopControlCenterError("Control Center failed (401): token rejected"),
        )
        assertEquals(
            "Riggen kunne ikke levere Control Center-status. Tjek at backend og worker kører.",
            desktopControlCenterError("status unavailable (502)"),
        )
        assertEquals(
            "Statuskaldet fik tidsudløb. Prøv igen.",
            desktopControlCenterError("java.net.http.HttpTimeoutException: request timed out"),
        )
        assertEquals(
            "Kan ikke nå riggen. Tjek URL og at serveren kører.",
            desktopControlCenterError("java.net.ConnectException: Connection refused"),
        )
        assertEquals(
            "Control Center-status kunne ikke hentes.",
            desktopControlCenterError(null),
        )
    }

    @Test
    fun unknownStatusErrorsNeverLeakRawDiagnostics() {
        val raw = "IllegalStateException: C:\\Users\\anders\\secret.txt https://10.0.0.4:8080/internal?token=abc"
        assertEquals(
            "Control Center-status kunne ikke hentes på grund af en ukendt klientfejl.",
            desktopControlCenterError(raw),
        )
    }

    @Test
    fun unknownCapabilityErrorsNeverLeakRawDiagnostics() {
        val raw = "SocketException: /var/lib/modelrig/private.sock bearer=secret-value"
        assertEquals(
            "Capabilities kunne ikke hentes på grund af en ukendt klientfejl.",
            desktopControlCenterCapabilityError(raw),
        )
        assertEquals(
            "Capabilities kunne ikke hentes.",
            desktopControlCenterCapabilityError("   "),
        )
        assertEquals(
            "Capability-kaldet fik tidsudløb. Prøv igen.",
            desktopControlCenterCapabilityError("HttpTimeoutException: timed out"),
        )
    }

    @Test
    fun capabilityLabelsDescribeAuthorityWithoutInventingHealth() {
        assertEquals("læse", desktopControlCenterAccessLabel("read"))
        assertEquals("skrive", desktopControlCenterAccessLabel("write"))
        assertEquals("desktop", desktopControlCenterAccessLabel("desktop"))
        assertEquals("future-access", desktopControlCenterAccessLabel("future-access"))
        assertEquals("ikke direkte afbrydelig", desktopControlCenterTerminationLabel("none"))
        assertEquals("kooperativ stop", desktopControlCenterTerminationLabel("cooperative"))
        assertEquals("runtime-stop", desktopControlCenterTerminationLabel("forceable"))
        assertEquals("future-stop", desktopControlCenterTerminationLabel("future-stop"))
    }
}

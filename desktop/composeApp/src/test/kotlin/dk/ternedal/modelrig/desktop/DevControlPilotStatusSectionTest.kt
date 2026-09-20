package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals

class DevControlPilotStatusSectionTest {
    @Test
    fun knownErrorsStayHumanReadable() {
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopDevControlStatusError("DevControl pilot status failed (401): invalid token"),
        )
        assertEquals(
            "DevControl-status fik tidsudløb. Prøv igen.",
            desktopDevControlStatusError("HttpTimeoutException: timed out"),
        )
        assertEquals(
            "Kan ikke nå riggen for DevControl-status.",
            desktopDevControlStatusError("ConnectException: Connection refused"),
        )
    }

    @Test
    fun unknownErrorsNeverLeakRawDiagnostics() {
        assertEquals(
            "DevControl-status kunne ikke hentes sikkert.",
            desktopDevControlStatusError(
                "IllegalStateException: C:\\Users\\anders\\secret.txt bearer=secret-value",
            ),
        )
    }
}

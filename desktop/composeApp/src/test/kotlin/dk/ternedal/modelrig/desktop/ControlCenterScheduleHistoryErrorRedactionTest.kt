package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse

class ControlCenterScheduleHistoryErrorRedactionTest {
    @Test
    fun knownHistoryErrorsKeepDeterministicOperatorCopy() {
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopControlCenterScheduleHistoryError("request failed (401): unauthorized"),
        )
        assertEquals(
            "Execution-historikken er ikke tilgængelig fra riggen lige nu.",
            desktopControlCenterScheduleHistoryError("request failed (502): upstream unavailable"),
        )
        assertEquals(
            "History-kaldet fik tidsudløb. Prøv igen.",
            desktopControlCenterScheduleHistoryError("HttpTimeoutException: timed out"),
        )
        assertEquals(
            "Kan ikke nå riggen for execution-historik.",
            desktopControlCenterScheduleHistoryError("java.net.ConnectException: Connection refused"),
        )
        assertEquals(
            "Execution-historikken kunne ikke hentes.",
            desktopControlCenterScheduleHistoryError(null),
        )
    }

    @Test
    fun unknownHistoryErrorsNeverEchoTechnicalDetails() {
        val neutral = "Execution-historikken kunne ikke hentes."
        val rawErrors = listOf(
            "java.nio.file.NoSuchFileException: C:\\Users\\anders\\modelrig\\secret.db",
            "GET http://127.0.0.1:8090/api/v1/schedules/history?token=super-secret failed (418)",
            "IllegalStateException: decoder blew up in InternalScheduleHistoryMapper.kt:87",
        )

        rawErrors.forEach { raw ->
            val rendered = desktopControlCenterScheduleHistoryError(raw)
            assertEquals(neutral, rendered)
            assertFalse(rendered.contains(raw))
            assertFalse(rendered.contains("token=", ignoreCase = true))
            assertFalse(rendered.contains("C:\\Users", ignoreCase = true))
            assertFalse(rendered.contains("IllegalStateException", ignoreCase = true))
        }
    }
}

from pathlib import Path

root = Path(__file__).resolve().parents[1]
source = root / "desktop/composeApp/src/main/kotlin/dk/ternedal/modelrig/desktop/ControlCenterScheduleHistorySection.kt"
test = root / "desktop/composeApp/src/test/kotlin/dk/ternedal/modelrig/desktop/ControlCenterScheduleHistorySectionTest.kt"

text = source.read_text(encoding="utf-8")
old = '''        message.isBlank() -> "Execution-historikken kunne ikke hentes."
        else -> message.take(300)
    }
}
'''
new = '''        message.isBlank() -> "Execution-historikken kunne ikke hentes."
        else -> "Execution-historikken kunne ikke hentes på grund af en ukendt klientfejl."
    }
}
'''
if old not in text:
    raise SystemExit("schedule-history error fallback shape not found")
source.write_text(text.replace(old, new, 1), encoding="utf-8")

text = test.read_text(encoding="utf-8")
old_test = '''    @Test
    fun historyErrorsRemainNeutralAndBounded() {
        assertEquals(
            "Execution-historikken er ikke tilgængelig fra riggen lige nu.",
            desktopControlCenterScheduleHistoryError("schedule history failed (502): unavailable"),
        )
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopControlCenterScheduleHistoryError("failed (401)"),
        )
        assertEquals(
            "Execution-historikken kunne ikke hentes.",
            desktopControlCenterScheduleHistoryError(null),
        )
    }
'''
new_test = '''    @Test
    fun historyErrorsRemainNeutralAndBounded() {
        assertEquals(
            "Execution-historikken er ikke tilgængelig fra riggen lige nu.",
            desktopControlCenterScheduleHistoryError("schedule history failed (502): unavailable"),
        )
        assertEquals(
            "Ikke godkendt. Parringen mangler eller er udløbet.",
            desktopControlCenterScheduleHistoryError("failed (401)"),
        )
        assertEquals(
            "History-kaldet fik tidsudløb. Prøv igen.",
            desktopControlCenterScheduleHistoryError("HttpTimeoutException: timed out"),
        )
        assertEquals(
            "Kan ikke nå riggen for execution-historik.",
            desktopControlCenterScheduleHistoryError("ConnectException: Connection refused"),
        )
        assertEquals(
            "Execution-historikken kunne ikke hentes.",
            desktopControlCenterScheduleHistoryError(null),
        )
    }

    @Test
    fun unknownHistoryErrorsNeverLeakRawDiagnostics() {
        val pathLike = "IllegalStateException: C:\\\\Users\\\\anders\\\\private.db"
        val endpointLike = "HTTP 599 https://10.0.0.4:8080/internal?token=abc"
        val socketLike = "SocketException: /var/lib/modelrig/private.sock bearer=secret-value"
        listOf(pathLike, endpointLike, socketLike).forEach { raw ->
            assertEquals(
                "Execution-historikken kunne ikke hentes på grund af en ukendt klientfejl.",
                desktopControlCenterScheduleHistoryError(raw),
                raw,
            )
        }
    }
'''
if old_test not in text:
    raise SystemExit("history error test block not found")
test.write_text(text.replace(old_test, new_test, 1), encoding="utf-8")

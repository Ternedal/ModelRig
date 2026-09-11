package dk.ternedal.modelrig.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class Agent3TaskErrorPresentationTest {
    @Test
    fun `every task operation has deterministic bounded failure copy`() {
        assertEquals(
            "Task-routing kunne ikke hentes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.READINESS, null),
        )
        assertEquals(
            "Plan-preview kunne ikke hentes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.PREVIEW, ""),
        )
        assertEquals(
            "Startstatus kunne ikke bekræftes. Prøv Start igen; samme preview starter ikke en ny task.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.START, "unknown"),
        )
        assertEquals(
            "Opgaven blev ikke accepteret. Prøv samme preview igen.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.START_NOT_ACCEPTED, "503 /secret"),
        )
        assertEquals(
            "Opgaven blev ikke accepteret. Lav et nyt plan-preview.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.START_REFUSED, "409 /secret"),
        )
        assertEquals(
            "Task-status kunne ikke hentes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.STATUS, "unknown"),
        )
        assertEquals(
            "Stop-resultatet kunne ikke bekræftes. Planen kan allerede være stoppet på serveren. Opdatér task-status før du konkluderer eller prøver igen.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.STOP_PLAN, "unknown"),
        )
        assertEquals(
            "Automatisk task-status kunne ikke hentes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.AUTOMATIC_STATUS, "unknown"),
        )
        assertEquals(
            "Task-referencen kunne ikke gemmes lokalt. Hold taskfladen åben.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.LOCAL_REFERENCE, "SQLiteException /private/path"),
        )
        assertEquals(
            "Start blev ikke sendt, fordi recovery-referencen ikke kunne gemmes lokalt.",
            presentAgent3TaskScreenError(
                Agent3TaskFailureOperation.START_RECOVERY_REFERENCE,
                "SharedPreferences /private/path",
            ),
        )
    }

    @Test
    fun `local code owned configuration failures stay actionable`() {
        assertEquals(
            "Ingen rig-URL er gemt.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.PREVIEW, "Ingen rig-URL er gemt"),
        )
        assertEquals(
            "Ingen device-token er gemt.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.START, " Ingen device-token er gemt "),
        )
    }

    @Test
    fun `arbitrary server and exception diagnostics never leak`() {
        val raw = "Read-only task fejlede (502): https://rig.local/internal?token=secret SocketTimeoutException C:/users/private"
        Agent3TaskFailureOperation.values().forEach { operation ->
            val copy = presentAgent3TaskScreenError(operation, raw)
            assertFalse(copy.contains("rig.local"))
            assertFalse(copy.contains("token=secret"))
            assertFalse(copy.contains("SocketTimeoutException"))
            assertFalse(copy.contains("C:/users/private"))
        }
    }
}

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
            "Opgaven kunne ikke startes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.START, "unknown"),
        )
        assertEquals(
            "Task-status kunne ikke hentes.",
            presentAgent3TaskScreenError(Agent3TaskFailureOperation.STATUS, "unknown"),
        )
        assertEquals(
            "Planen kunne ikke stoppes.",
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

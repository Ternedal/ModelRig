package dk.ternedal.modelrig.desktop

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull

class KalivTaskRunPresentationTest {
    @Test
    fun knownRunStatesUseHumanDanishCopy() {
        assertEquals("Kører", presentTaskRunState("running"))
        assertEquals("Blokeret", presentTaskRunState("blocked"))
        assertEquals("Fuldført", presentTaskRunState("completed"))
        assertEquals("Fejlet", presentTaskRunState("failed"))
        assertEquals("Annulleret", presentTaskRunState("cancelled"))
    }

    @Test
    fun unknownRunStateFailsClosedWithoutEchoingIdentifier() {
        assertEquals("Status ukendt", presentTaskRunState("future_internal_state"))
        assertEquals("Status ukendt", presentTaskRunState(""))
        assertEquals("Status ukendt", presentTaskRunState(null))
    }

    @Test
    fun knownRouteUsesHumanCopyAndUnknownRouteFailsClosed() {
        assertEquals("Lokal rig · værktøjer", presentTaskRunRoute("rig_tools_local"))
        assertEquals("Lokal rig · værktøjer", presentTaskRunRoute(" RIG_TOOLS_LOCAL "))
        assertEquals("Rute ukendt", presentTaskRunRoute("future_route"))
        assertEquals("Rute ukendt", presentTaskRunRoute(null))
    }

    @Test
    fun missingRunErrorDoesNotInventProblemCopy() {
        assertNull(presentTaskRunError("failed", null))
        assertNull(presentTaskRunError("failed", ""))
        assertNull(presentTaskRunError("failed", "   "))
    }

    @Test
    fun failedRunErrorUsesBoundedCopyWithoutEchoingPathLikeDetails() {
        val raw = "RuntimeError: C:\\rig\\private\\weights.gguf failed at line 17"
        val presented = presentTaskRunError("failed", raw)
        assertEquals("Kørslen fejlede på riggen.", presented)
        assertFalse(presented.orEmpty().contains(raw))
        assertFalse(presented.orEmpty().contains("weights.gguf"))
    }

    @Test
    fun blockedRunErrorUsesBoundedCopyWithoutEchoingEndpointOrTokenDetails() {
        val raw = "HTTP 403 https://127.0.0.1:8080/internal?token=secret-token"
        val presented = presentTaskRunError("blocked", raw)
        assertEquals("Kørslen blev blokeret på riggen.", presented)
        assertFalse(presented.orEmpty().contains(raw))
        assertFalse(presented.orEmpty().contains("secret-token"))
    }

    @Test
    fun cancelledRunErrorUsesOnlyValidatedStateContext() {
        val raw = "socket.timeout: worker connection closed after cancel"
        val presented = presentTaskRunError("cancelled", raw)
        assertEquals("Kørslen blev annulleret.", presented)
        assertFalse(presented.orEmpty().contains(raw))
        assertFalse(presented.orEmpty().contains("socket.timeout"))
    }

    @Test
    fun otherOrFutureStateWithErrorFailsClosedWithoutEchoingDiagnostics() {
        val raw = "FutureWorkerException: /srv/modelrig/private"
        val states = listOf("running", "waiting_confirmation", "completed", "future_state", null)
        states.forEach { state ->
            val presented = presentTaskRunError(state, raw)
            assertEquals("Riggen rapporterede et problem med kørslen.", presented)
            assertFalse(presented.orEmpty().contains(raw))
            assertFalse(presented.orEmpty().contains("FutureWorkerException"))
        }
    }
}

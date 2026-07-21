package dk.ternedal.modelrig.net

import org.junit.Assert.assertEquals
import org.junit.Test

/** Exact-head guard for the Android side of the T-017 wire contract. */
class ScheduleTimeContractTest {
    @Test
    fun defaultsMatchWorkerAndBackendContract() {
        assertEquals("Europe/Copenhagen", ScheduleClient.DEFAULT_TIMEZONE)
        assertEquals("run_once", ScheduleClient.RUN_ONCE_MISFIRE_POLICY)
    }
}

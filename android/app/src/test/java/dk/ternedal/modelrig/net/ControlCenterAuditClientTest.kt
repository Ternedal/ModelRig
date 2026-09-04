package dk.ternedal.modelrig.net

import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ControlCenterAuditClientTest {
    @Test
    fun snapshotUsesExistingAuthenticatedAuditGetRoute() {
        val server = MockWebServer()
        server.enqueue(
            MockResponse()
                .setResponseCode(200)
                .setHeader("Content-Type", "application/json")
                .setBody(payload().toString()),
        )
        server.start()
        try {
            val snapshot = ControlCenterAuditClient(
                server.url("/").toString(),
                "paired-token",
            ).snapshot()

            assertEquals(1, snapshot.entries.size)
            val request = server.takeRequest()
            assertEquals("GET", request.method)
            assertEquals("/api/v1/tools/audit?limit=100", request.path)
            assertEquals("Bearer paired-token", request.getHeader("Authorization"))
        } finally {
            server.shutdown()
        }
    }

    @Test
    fun rawContentNeverEntersControlCenterModel() {
        val snapshot = client().parse(payload())
        val entry = snapshot.entries.single()

        assertEquals("tool:note_append", entry.capabilityId)
        assertEquals("task-123", entry.taskRef)
        assertEquals("confirm-123", entry.approvalId)
        assertEquals("cloud", entry.origin)
        assertEquals("executed", entry.outcome)
        assertFalse(entry.toString().contains("TOP SECRET ARGUMENT"))
        assertFalse(entry.toString().contains("TOP SECRET RESULT"))
        assertFalse(snapshot.toString().contains("TOP SECRET ARGUMENT"))
        assertFalse(snapshot.toString().contains("TOP SECRET RESULT"))
    }

    @Test
    fun taskCapabilityAndApprovalFiltersUseRecordedEvidence() {
        val snapshot = client().parse(payload())

        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(task = "task-123")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(capability = "tool:note")).size)
        assertEquals(1, snapshot.filtered(ControlCenterAuditFilter(approval = "confirm-123")).size)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(task = "other-task")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(capability = "tool:rig_status")).isEmpty())
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(approval = "other-approval")).isEmpty())
    }

    @Test
    fun connectorFilterFailsClosedBecauseConnectorIsNotRecorded() {
        val snapshot = client().parse(payload())

        assertEquals("unavailable", snapshot.connectorEvidence.state)
        assertEquals("tool_audit_does_not_record_connector_id", snapshot.connectorEvidence.reason)
        assertEquals(null, snapshot.entries.single().connectorId)
        assertTrue(snapshot.filtered(ControlCenterAuditFilter(connector = "gmail")).isEmpty())
    }

    @Test
    fun malformedScalarTypesFailClosed() {
        val fractionalDuration = payload()
        fractionalDuration.getJSONArray("entries").getJSONObject(0).put("duration_ms", 12.5)
        val error = runCatching { client().parse(fractionalDuration) }.exceptionOrNull()
        assertTrue(error is ModelRigException)
        assertTrue(error?.message.orEmpty().contains("duration_ms must be an integer"))

        val stringDuration = payload()
        stringDuration.getJSONArray("entries").getJSONObject(0).put("duration_ms", "12")
        val error2 = runCatching { client().parse(stringDuration) }.exceptionOrNull()
        assertTrue(error2 is ModelRigException)
    }

    @Test
    fun unknownOutcomeStaysUnknownDataInsteadOfSyntheticSuccess() {
        val future = payload()
        future.getJSONArray("entries").getJSONObject(0).put("outcome", "future_outcome")
        val snapshot = client().parse(future)
        assertEquals("future_outcome", snapshot.entries.single().outcome)
    }

    private fun client() = ControlCenterAuditClient("http://127.0.0.1:1", "token")

    private fun payload(): JSONObject = JSONObject()
        .put(
            "entries",
            JSONArray().put(
                JSONObject()
                    .put("ts", "2026-08-11T11:00:00")
                    .put("conversation_id", "task-123")
                    .put("tool", "note_append")
                    .put("args_json", "{\"text\":\"TOP SECRET ARGUMENT\"}")
                    .put("risk", "write")
                    .put("outcome", "executed")
                    .put("confirmation_id", "confirm-123")
                    .put("result_summary", "TOP SECRET RESULT")
                    .put("duration_ms", 12)
                    .put("origin", "cloud"),
            ),
        )
}
